"""One bounded background web run; business behavior is the existing CLI use case."""

from threading import Event, Lock, Thread
from uuid import uuid4

from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.validation import DomainError, identifier, object_fields, require


class Workbench:
    def __init__(self, store, journal, model_factory, run_use_case, *, real_model_name=None):
        self.store, self.journal = store, journal
        self.model_factory, self.run_use_case = model_factory, run_use_case
        self.real_model_name = real_model_name
        self._gate = Lock()
        self._stopping = Event()
        self._thread = None
        self._terminal_lock = Lock()
        self._pending_terminal = {}

    def submit(self, payload):
        data = object_fields(payload, {"request", "mode", "submission_id"}, set(), "run")
        require(type(data["mode"]) is str and data["mode"] in {"mock", "real"}, "Invalid run mode")
        identifier(data["submission_id"], "submission_id")
        request = SchedulingRequest.from_json(data["request"]) if type(data["request"]) is str else SchedulingRequest.from_dict(data["request"])
        with self._gate:
            if self._stopping.is_set():
                raise DomainError("SERVER_STOPPING", "Workbench is stopping")
            # Only an explicit write operation retries journal persistence.
            # Reads expose the degraded state without changing the ledger.
            self._recover_terminal()
            previous = self.journal.for_submission(data["submission_id"])
            if previous:
                self._match(previous, request, data["mode"])
                return {"run": previous, "reused": True}
            active = self.journal.active()
            if active:
                if active["request_id"] != request.request_id:
                    raise DomainError("RUN_BUSY", "Another request is running; wait for its result")
                self._match(active, request, data["mode"])
                self.journal.alias_submission(data["submission_id"], active["run_id"])
                return {"run": active, "reused": True}
            model = self.model_factory(data["mode"])
            self.store.register_request(request)
            run_id = "RUN-" + uuid4().hex
            self.journal.create(run_id, data["submission_id"], request, data["mode"])
            self._thread = Thread(target=self._run, args=(run_id, request, model), daemon=True)
            try:
                self._thread.start()
            except RuntimeError:
                self._thread = None
                self._finish(run_id, "FAILED", error={"code": "RUN_START_FAILED", "message": "Could not start the run"})
                raise DomainError("RUN_START_FAILED", "Could not start the run") from None
            return {"run": self._project(self.journal.get(run_id)), "reused": False}

    @staticmethod
    def _match(prior, request, mode):
        if prior["request_id"] != request.request_id or prior["payload_hash"] != request.payload_hash:
            raise DomainError("REQUEST_ID_CONFLICT", "This operation already refers to different requirements")
        if prior["mode"] != mode:
            raise DomainError("RUN_MODE_CONFLICT", "This operation already refers to another model mode")

    def _run(self, run_id, request, model):
        try:
            self.journal.update(run_id, "RUNNING")
            result = self.run_use_case(self.store, request, model, self.journal.directory / "runs" / run_id,
                                       run_id=run_id, on_event=self.journal.append, cancelled=self._stopping.is_set,
                                       invocation={"entrypoint": "local_workbench", "mode": model.mode})
            self._finish(run_id, "FINISHED", result=result)
        except DomainError as exc:
            self._finish(run_id, "FAILED", error=exc.to_dict())
        except Exception:
            self._finish(run_id, "FAILED", error={"code": "RUN_INTERRUPTED", "message": "Run interrupted; inspect current drafts before retrying"})

    def _finish(self, run_id, status, *, result=None, error=None):
        outcome = {"status": status, "result": result, "error": error}
        with self._terminal_lock:
            self._pending_terminal[run_id] = outcome
        try:
            self._persist_terminal(run_id, outcome)
        except DomainError:
            # Keep the actual outcome while this process lives. After a crash,
            # the existing journal startup recovery marks active rows interrupted.
            with self._terminal_lock:
                if self._pending_terminal.get(run_id) is outcome:
                    outcome["degraded"] = True

    def _persist_terminal(self, run_id, outcome):
        self.journal.update(run_id, outcome["status"], result=outcome["result"], error=outcome["error"])
        with self._terminal_lock:
            if self._pending_terminal.get(run_id) is outcome:
                del self._pending_terminal[run_id]

    def _recover_terminal(self):
        with self._terminal_lock:
            pending = [(run_id, outcome) for run_id, outcome in self._pending_terminal.items() if outcome.get("degraded")]
        for run_id, outcome in pending:
            self._persist_terminal(run_id, outcome)

    def _project(self, value):
        with self._terminal_lock:
            outcome = self._pending_terminal.get(value["run_id"])
        if outcome is not None and outcome.get("degraded"):
            value = {**value, "status": "INTERRUPTED", "state_persisted": False,
                     "error": {"code": "RUN_STATE_UNPERSISTED", "message": "Worker ended but its terminal state is not durably acknowledged; retry the original submission to reconcile"}}
            if "result" in value:
                value["result"] = outcome["result"]
        return value

    def list_runs(self):
        return [self._project(value) for value in self.journal.list()]

    def submission(self, submission_id):
        value = self.journal.for_submission(submission_id)
        return self._project(value) if value else None

    def get(self, run_id):
        identifier(run_id, "run_id")
        value = self._project(self.journal.get(run_id))
        value["current"] = self.store.read_request(value["request_id"])
        return value

    def trace_path(self, run_id):
        self.journal.get(run_id)
        base = (self.journal.directory / "runs").resolve()
        path = (base / run_id / "trace.jsonl").resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise DomainError("TRACE_NOT_FOUND", "Trace is not available yet")
        return path

    def close(self, timeout=35):
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise DomainError("SERVER_STOPPING", "Wait for the bounded provider call to finish")
        self.journal.close()
