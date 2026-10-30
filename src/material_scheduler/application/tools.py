"""Strict model-facing tools with run-local observations and truthful results."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.scheduling import QueryMode
from material_scheduler.domain.time import iso, parse_time
from material_scheduler.domain.validation import (
    DomainError, identifier, integer, object_fields, require, text,
)
from .contracts import SaveEvidence
from .serialization import candidate_to_dict


_ARGUMENTS = {
    "read_material": {"item_id", "rationale"},
    "lookup_metadata": {"item_id", "rationale"},
    "check_rules": {"item_id", "rationale"},
    "query_slots": {"item_id", "mode", "limit", "rationale"},
    "save_draft": {"item_id", "candidate_start", "rationale"},
    "finish": {"rationale"},
}


def tool_definitions() -> list[dict]:
    """The executable directory and JSON schemas share the same field sets."""
    descriptions = {
        "read_material": "读取本请求项素材、来源和缺失字段。",
        "lookup_metadata": "从带来源补充资料填补缺失字段，保留矛盾与缺口。",
        "check_rules": "审核元数据与文案，返回风险证据及审核快照。",
        "query_slots": "查询目标或替代时段，不预留容量。",
        "save_draft": "保存已观察候选；事务复核，自动计算待确认事项。",
        "finish": "结束选择；业务状态由真实工具与账本生成。",
    }
    properties = {
        "item_id": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[A-Za-z0-9_-]+$"},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 240},
        "mode": {"type": "string", "enum": ["requested", "alternatives"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
        "candidate_start": {"type": "string", "minLength": 20, "maxLength": 40},
    }
    return [{"type": "function", "function": {
        "name": name, "description": descriptions[name], "parameters": {
            "type": "object", "properties": {field: deepcopy(properties[field]) for field in sorted(fields)},
            "required": sorted(fields), "additionalProperties": False,
        },
    }} for name, fields in _ARGUMENTS.items()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ToolSession:
    """One run's tool observations. No model is called and no policy is selected."""

    def __init__(self, store, request: SchedulingRequest, *, run_id: str | None = None) -> None:
        self.store = store
        self.request = store.register_request(request)
        self.run_id = run_id or "RUN-" + uuid4().hex
        identifier(self.run_id, "run_id")
        self._items = {item.item_id: item for item in self.request.items}
        self._reviews: dict[str, str] = {}
        self._candidates: dict[str, dict] = {}
        self._last_saves: dict[str, dict] = {}
        self._finished = False
        self._records: list[dict] = []

    @property
    def records(self) -> list[dict]:
        return deepcopy(self._records)

    def _arguments(self, action: str, arguments: dict) -> dict:
        if type(action) is not str or action not in _ARGUMENTS:
            raise DomainError("INVALID_ACTION", "Tool is not in the allowed directory")
        try:
            data = object_fields(arguments, _ARGUMENTS[action], set(), "tool.arguments")
            text(data["rationale"], "rationale", 240)
            require(bool(data["rationale"].strip()), "A short public rationale is required")
            if action != "finish":
                identifier(data["item_id"], "item_id")
                if data["item_id"] not in self._items:
                    raise DomainError("ACTION_NOT_ALLOWED", "Item is outside this request")
            if action == "query_slots":
                require(type(data["mode"]) is str and data["mode"] in {"requested", "alternatives"}, "Invalid query mode")
                integer(data["limit"], "limit", 1, 10)
            if action == "save_draft":
                text(data["candidate_start"], "candidate_start", 40)
                require(len(data["candidate_start"]) >= 20, "Timestamp must include seconds and offset")
                parse_time(data["candidate_start"])
            return data
        except DomainError as exc:
            if exc.code == "ACTION_NOT_ALLOWED":
                raise
            raise DomainError("INVALID_ARGUMENTS", str(exc), path=exc.path) from exc

    def execute(self, action: str, arguments: dict) -> dict:
        raw_item = arguments.get("item_id") if type(arguments) is dict else None
        item_id = raw_item if type(raw_item) is str and raw_item in self._items else None
        try:
            data = self._arguments(action, arguments)
            item_id = data.get("item_id")
            if self._finished:
                raise DomainError("ACTION_NOT_ALLOWED", "Tool session has already finished")
            result = self._execute_valid(action, data)
            observation = {
                "ok": True, "tool": action, "item_id": item_id,
                "data": result, "observed_at": _now(),
            }
        except DomainError as exc:
            if action == "save_draft" and item_id in self._items:
                self._last_saves[item_id] = {
                    "save_status": "UNKNOWN" if exc.code == "SAVE_OUTCOME_UNKNOWN" else "FAILED",
                    "error_code": exc.code,
                }
            observation = {
                "ok": False, "tool": action, "item_id": item_id,
                "error": {
                    **exc.to_dict(),
                    "retryable": exc.code in {"TOOL_UNAVAILABLE", "STORE_UNAVAILABLE", "SAVE_FAILED"},
                    "next_step": self._next_step(exc.code),
                },
                "observed_at": _now(),
            }
        self._records.append({
            "step": len(self._records) + 1, "run_id": self.run_id,
            "tool": action, "parameters": deepcopy(arguments),
            "observation": deepcopy(observation),
        })
        return observation

    @staticmethod
    def _next_step(code: str) -> str | None:
        if code in {"STALE_REVIEW"}:
            return "check_rules"
        if code in {"SLOT_CONFLICT", "CANDIDATE_NOT_OBSERVED", "OUTSIDE_WINDOW"}:
            return "query_slots"
        if code in {"METADATA_MISSING", "SOURCE_CONFLICT", "MATERIAL_NOT_FOUND"}:
            return "request_user_input"
        if code == "SAVE_OUTCOME_UNKNOWN":
            return "retry_same_request"
        return None

    def _execute_valid(self, action, data) -> dict:
        item_id = data.get("item_id")
        request_id = self.request.request_id
        if action == "read_material":
            return self.store.read_material(request_id, item_id)
        if action == "lookup_metadata":
            # Any source change invalidates local observation authority for that material.
            material_id = self._items[item_id].material_id
            for related in self._items.values():
                if related.material_id == material_id:
                    self._reviews.pop(related.item_id, None)
                    self._candidates.pop(related.item_id, None)
            return self.store.lookup_metadata(request_id, item_id, run_id=self.run_id)
        if action == "check_rules":
            self._reviews.pop(item_id, None)
            self._candidates.pop(item_id, None)
            review = self.store.check_rules(request_id, item_id)
            self._reviews[item_id] = review.snapshot_id
            return {
                "review_status": review.status.value,
                "findings": [finding.to_dict() for finding in review.findings],
                "missing_fields": list(review.missing_fields),
                "review_coverage": list(review.review_coverage),
                "review_snapshot_id": review.snapshot_id,
            }
        if action == "query_slots":
            result, generation = self.store.query_slots(
                request_id, item_id, QueryMode(data["mode"]), limit=data["limit"]
            )
            self._candidates[item_id] = {
                iso(candidate.interval.start, canonical=True): candidate
                for candidate in result.candidates
            }
            return {
                "mode": result.mode.value, "requested_available": result.requested_available,
                "candidates": [candidate_to_dict(candidate) for candidate in result.candidates],
                "conflicts": [
                    {"booking_id": booking.booking_id, "channel": booking.channel, **booking.interval.to_dict()}
                    for booking in result.requested_conflicts
                ],
                "schedule_revision": generation, "available_as_of": _now(),
            }
        if action == "save_draft":
            if item_id not in self._reviews:
                raise DomainError("STALE_REVIEW", "Check current rules before saving")
            key = iso(parse_time(data["candidate_start"]), canonical=True)
            candidate = self._candidates.get(item_id, {}).get(key)
            if candidate is None:
                raise DomainError("CANDIDATE_NOT_OBSERVED", "Query and use a returned candidate before saving")
            result = self.store.save_draft(
                SaveEvidence(request_id, item_id, self._reviews[item_id], candidate),
                run_id=self.run_id,
            ).to_dict()
            self._last_saves[item_id] = {
                "save_status": result["save_status"], "error_code": None,
                "operation_id": result["operation_id"], "operation_version": result["operation_version"],
            }
            return result
        self._finished = True
        return {"stop_reason": "TOOL_SESSION_FINISHED"}

    def result(self) -> dict:
        try:
            result = self.store.snapshot(self.request.request_id)
        except DomainError as exc:
            return {
                "request_id": self.request.request_id, "run_id": self.run_id,
                "task_status": "FAILED", "error": exc.to_dict(),
                "items": [], "last_known_save_attempts": deepcopy(self._last_saves),
                "published": False,
            }
        statuses = []
        for item in result["items"]:
            attempt = deepcopy(self._last_saves.get(item["item_id"], {"save_status": "NOT_ATTEMPTED", "error_code": None}))
            item["save_attempt"] = attempt
            observed_review = self._reviews.get(item["item_id"])
            item["review_observed_in_session"] = (
                observed_review is not None
                and observed_review == item.get("review", {}).get("review_snapshot_id")
            )
            draft = item["draft"]
            if attempt["save_status"] in {"FAILED", "UNKNOWN"}:
                status = "FAILED"
            elif "review_error" in item:
                status = "NEEDS_INPUT"
            elif item["review"]["review_status"] in {"BLOCKED", "NEEDS_INPUT"}:
                status = item["review"]["review_status"]
            elif draft and draft["draft_state"] == "READY":
                status = "READY"
            elif draft and draft["draft_state"] == "PENDING_CONFIRMATION":
                status = "NEEDS_CONFIRMATION"
            else:
                status = "INCOMPLETE"
            item["status"] = status
            statuses.append(status)
        if all(status == "READY" for status in statuses):
            task_status = "READY_DRAFTS"
        elif set(statuses) <= {"READY", "NEEDS_CONFIRMATION"}:
            task_status = "NEEDS_CONFIRMATION"
        elif any(item["draft"] is not None for item in result["items"]):
            task_status = "PARTIAL"
        elif all(status == "BLOCKED" for status in statuses):
            task_status = "BLOCKED"
        elif "FAILED" in statuses:
            task_status = "FAILED"
        elif "NEEDS_INPUT" in statuses:
            task_status = "NEEDS_INPUT"
        else:
            task_status = "INCOMPLETE"
        return {**result, "run_id": self.run_id, "task_status": task_status}
