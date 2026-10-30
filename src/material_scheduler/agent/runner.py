"""Bounded orchestration; business decisions belong to the supplied model."""

from copy import deepcopy
from dataclasses import asdict
from time import monotonic

from material_scheduler.application.tools import ToolSession, tool_definitions
from material_scheduler.domain.budgets import ExecutionLimits
from material_scheduler.domain.validation import DomainError, fingerprint, require
from .decisions import Action, DecisionModel, ModelContext
from .prompt import PROMPT_VERSION, SYSTEM_PROMPT
from .trace import MemoryTrace


class _Stop(Exception):
    def __init__(self, reason, detail=None):
        self.reason, self.detail = reason, detail


class AgentRunner:
    def __init__(self, session: ToolSession, model: DecisionModel, *, trace=None,
                 limits=None, clock=monotonic, cancelled=lambda: False, source_identity=None):
        self.session, self.model = session, model
        self.trace = trace if trace is not None else MemoryTrace(session.run_id)
        self.limits = limits or ExecutionLimits.for_items(len(session.request.items))
        defaults = asdict(ExecutionLimits.for_items(len(session.request.items)))
        require(all(value <= defaults[key] for key, value in asdict(self.limits).items()), "Run configuration may only tighten limits")
        require(model.mode in {"mock", "test", "real"}, "Model must declare its mode")
        self.model_identity = {"mode": model.mode, "name": model.name, "version": model.version}
        require(all(type(value) is str and 0 < len(value) <= 128 for value in self.model_identity.values()), "Invalid model identity")
        self.clock, self.cancelled = clock, cancelled
        self.source_identity = deepcopy(source_identity or {})
        self.history = []
        self._used = False
        self._trace_complete = True
        self._protocol_errors = 0
        self._model_failures = 0
        self._rounds = self._attempts = self._dispatches = self._executions = 0
        self._items = {item.item_id: 0 for item in session.request.items}
        self._blocked = set()
        self._transient_failures = {}
        self._last_observation = None

    def _emit(self, event):
        try:
            self.trace.append(event)
        except DomainError:
            self._trace_complete = False
            raise _Stop("TRACE_UNAVAILABLE")

    def _guard(self):
        if self.cancelled():
            raise _Stop("CANCELLED")
        if self.clock() >= self._deadline:
            raise _Stop("LIMIT_REACHED", "RUN_TIMEOUT")

    def _budget(self):
        return {"limits": asdict(self.limits), "tool_attempts": self._attempts,
                "model_rounds": self._rounds,
                "tools_remaining": self.limits.max_tool_attempts - self._attempts,
                "model_rounds_remaining": self.limits.max_model_rounds - self._rounds,
                "seconds_remaining": max(0, self._deadline - self.clock()),
                "per_item_remaining": {key: self.limits.per_item_tool_limit - used for key, used in self._items.items()},
                "blocked_items": sorted(self._blocked)}

    def _after_model(self, started, timeout):
        self._guard()
        if self.clock() - started >= timeout:
            raise _Stop("MODEL_TIMEOUT")

    def _feedback(self, action, observation, call_id, *, dispatched):
        self._last_observation = deepcopy(observation)
        entry = {"kind": "tool", "call_id": call_id, "action": action.to_dict(),
                 "observation": observation, "dispatched": dispatched}
        self.history.append(deepcopy(entry))
        self._emit({"type": "tool_observation", **entry, "budget": self._budget()})

    @staticmethod
    def _signature(action):
        return fingerprint({"tool": action.tool, "arguments": {
            key: value for key, value in action.arguments.items() if key != "rationale"
        }})

    def _protocol_failure(self):
        self._protocol_errors += 1
        observation = {"kind": "model_error", "error": {
            "code": "MODEL_PROTOCOL_ERROR", "message": "Return one tool/arguments JSON object",
            "retryable": self._protocol_errors < self.limits.protocol_error_limit}}
        self.history.append(observation)
        self._emit({"type": "model_error", **observation})
        if self._protocol_errors >= self.limits.protocol_error_limit:
            raise _Stop("MODEL_PROTOCOL_ERROR")

    def _loop(self):
        while True:
            self._guard()
            if self._attempts >= self.limits.max_tool_attempts:
                raise _Stop("LIMIT_REACHED", "TOOL_ATTEMPTS")
            if self._rounds >= self.limits.max_model_rounds:
                raise _Stop("LIMIT_REACHED", "MODEL_ROUNDS")
            context = ModelContext(SYSTEM_PROMPT, self.session.request.to_dict(),
                                   deepcopy(self.source_identity), tool_definitions(),
                                   tuple(deepcopy(self.history)), deepcopy(self._budget()), self.session.run_id)
            self._emit({"type": "model_requested", "round": self._rounds + 1,
                        "context_sha256": fingerprint(asdict(context)), "history_entries": len(self.history),
                        "budget": self._budget()})
            self._guard()
            started = self.clock()
            timeout = min(self.limits.model_timeout_seconds, self._deadline - started)
            self._rounds += 1
            try:
                response = self.model.choose(context, timeout_seconds=timeout)
            except DomainError as exc:
                self._after_model(started, timeout)
                if exc.code == "MODEL_PROTOCOL_ERROR":
                    self._protocol_failure()
                    continue
                if exc.code == "MODEL_TIMEOUT":
                    self._guard()
                    raise _Stop("MODEL_TIMEOUT") from exc
                self._model_error()
                continue
            except TimeoutError as exc:
                self._guard()
                raise _Stop("MODEL_TIMEOUT") from exc
            except Exception:
                # Provider details/free text can contain secrets or private reasoning.
                self._after_model(started, timeout)
                self._model_error()
                continue
            self._after_model(started, timeout)
            try:
                action = Action.parse(response)
            except DomainError:
                self._protocol_failure()
                continue
            self._emit({"type": "action_selected", "round": self._rounds, "action": action.to_dict()})
            self._guard()
            self._attempts += 1
            call_id = f"CALL-{self._attempts}"
            raw_item = action.arguments.get("item_id")
            item_id = raw_item if type(raw_item) is str and raw_item in self._items else None
            rejection = None
            if item_id is not None:
                if self._items[item_id] >= self.limits.per_item_tool_limit:
                    self._blocked.add(item_id)
                    rejection = "ITEM_LIMIT_REACHED"
                else:
                    self._items[item_id] += 1
            signature = self._signature(action)
            if self._transient_failures.get(signature, 0) >= 2:
                rejection = rejection or "RETRY_LIMIT_REACHED"
            if rejection:
                observation = {"ok": False, "tool": action.tool, "item_id": item_id,
                               "error": {"code": rejection, "message": "Choose another supported action/item or finish", "retryable": False}}
                self._feedback(action, observation, call_id, dispatched=False)
                continue
            # Persist intent BEFORE the tool can produce a business side effect.
            self._emit({"type": "tool_attempt", "call_id": call_id, "action": action.to_dict(),
                        "dispatch_planned": True, "budget": self._budget()})
            self._guard()
            self._dispatches += 1
            observation = self.session.execute(action.tool, action.arguments)
            if observation.get("error", {}).get("code") not in {"INVALID_ARGUMENTS", "INVALID_ACTION", "ACTION_NOT_ALLOWED"}:
                self._executions += 1
            if observation.get("error", {}).get("retryable"):
                self._transient_failures[signature] = self._transient_failures.get(signature, 0) + 1
            self._feedback(action, observation, call_id, dispatched=True)
            self._guard()
            if action.tool == "finish" and observation["ok"]:
                raise _Stop("MODEL_FINISHED")

    def _model_error(self):
        self._model_failures += 1
        event = {"kind": "model_error", "error": {"code": "MODEL_UNAVAILABLE",
                 "message": "Decision provider failed", "retryable": self._model_failures < 2}}
        self.history.append(deepcopy(event))
        self._emit({"type": "model_error", **event})
        self._guard()
        if self._model_failures >= 2:
            raise _Stop("MODEL_UNAVAILABLE")

    def run(self):
        require(not self._used, "A runner cannot be reused")
        self._used = True
        self._started = self.clock()
        self._deadline = self._started + self.limits.run_timeout_seconds
        try:
            self._emit({"type": "run_started", "request": self.session.request.to_dict(),
                        "request_sha256": self.session.request.payload_hash, "model": self.model_identity,
                        "source_identity": self.source_identity, "prompt_version": PROMPT_VERSION,
                        "prompt_sha256": fingerprint(SYSTEM_PROMPT), "tools_sha256": fingerprint(tool_definitions()),
                        "budget": self._budget()})
            self._loop()
        except _Stop as stop:
            reason, detail = stop.reason, stop.detail
        except KeyboardInterrupt:
            reason, detail = "CANCELLED", None
        except Exception:
            reason, detail = "TOOL_RUNTIME_ERROR", None
        result = self.session.result()
        if "error" in result:
            reason, detail = "RESULT_UNAVAILABLE", None
        result["business_task_status"] = result["task_status"]
        for item in result["items"]:
            last = next((entry["observation"] for entry in reversed(self.history)
                         if entry["kind"] == "tool" and entry["observation"].get("item_id") == item["item_id"]), None)
            gaps = []
            if (self._items[item["item_id"]] >= self.limits.per_item_tool_limit
                    and item["status"] not in {"READY", "NEEDS_CONFIRMATION", "BLOCKED", "NEEDS_INPUT"}):
                self._blocked.add(item["item_id"])
            if item["item_id"] in self._blocked:
                gaps.append("ITEM_LIMIT_REACHED")
            if item["status"] not in {"READY", "NEEDS_CONFIRMATION"}:
                if last and not last["ok"]:
                    gaps.append(last["error"]["code"])
                elif last and last["tool"] == "query_slots" and not last["data"]["candidates"]:
                    gaps.append("NO_AVAILABLE_SLOT")
                elif item.get("review_error"):
                    gaps.append(item["review_error"]["code"])
                elif item.get("review", {}).get("review_status") in {"NEEDS_INPUT", "BLOCKED"}:
                    gaps.append(item["review"]["review_status"])
                else:
                    gaps.append("NO_DRAFT_SAVED")
            item["incomplete_reasons"] = gaps
        stats = {"model_rounds": self._rounds, "protocol_errors": self._protocol_errors,
                 "tool_attempts": self._attempts, "tool_dispatches": self._dispatches,
                 "tool_executions": self._executions, "per_item_attempts": dict(self._items),
                 "elapsed_seconds": max(0, self.clock() - self._started),
                 "final_revalidations": 1}
        if self._trace_complete:
            try:
                self._emit({"type": "run_stopped", "stop_reason": reason, "limit_kind": detail,
                            "business_task_status": result["business_task_status"], "stats": stats})
            except _Stop:
                reason, detail = "TRACE_UNAVAILABLE", None
        execution = "FINISHED" if reason == "MODEL_FINISHED" and not self._blocked else "INCOMPLETE"
        if reason in {"TRACE_UNAVAILABLE", "MODEL_PROTOCOL_ERROR", "MODEL_UNAVAILABLE", "MODEL_TIMEOUT", "TOOL_RUNTIME_ERROR", "RESULT_UNAVAILABLE"}:
            execution = "FAILED"
        if execution != "FINISHED":
            result["task_status"] = "FAILED" if execution == "FAILED" else "INCOMPLETE"
        return {**result, "model": self.model_identity, "stop_reason": reason, "limit_kind": detail,
                "execution_status": execution, "stats": stats, "limits": asdict(self.limits),
                "trace_complete": self._trace_complete, "last_tool_observation": self._last_observation,
                "prompt_sha256": fingerprint(SYSTEM_PROMPT), "tools_sha256": fingerprint(tool_definitions()),
                "react_verified_with_real_model": False}
