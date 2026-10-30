"""Append-only hash-linked actual events; durable intent precedes dispatch."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from material_scheduler.domain.validation import DomainError, fingerprint


class MemoryTrace:
    def __init__(self, run_id):
        self.run_id = run_id
        self.events = []
        self._previous = None

    def _write(self, event):
        self.events.append(deepcopy(event))

    def append(self, event):
        body = {"sequence": len(self.events) + 1, "run_id": self.run_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "previous_hash": self._previous, "event": deepcopy(event)}
        envelope = {**body, "event_hash": fingerprint(body)}
        try:
            self._write(envelope)
        except (OSError, UnicodeError, ValueError) as exc:
            raise DomainError("TRACE_UNAVAILABLE", "Cannot persist the actual run event") from exc
        self._previous = envelope["event_hash"]

    def close(self):
        pass


class FileTrace(MemoryTrace):
    def __init__(self, path: Path, run_id: str):
        super().__init__(run_id)
        try:
            self._file = Path(path).open("x", encoding="utf-8", newline="\n")
        except OSError as exc:
            raise DomainError("TRACE_UNAVAILABLE", "Cannot create a new trace file") from exc

    def _write(self, event):
        self._file.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())
        super()._write(event)

    def close(self):
        try:
            self._file.close()
        except OSError as exc:
            raise DomainError("TRACE_UNAVAILABLE", "Cannot close the trace file") from exc


def verify_trace(path: Path):
    previous = None
    events = []
    try:
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            event = json.loads(line)
            digest = event.pop("event_hash")
            if event["sequence"] != index or event["previous_hash"] != previous or fingerprint(event) != digest:
                raise ValueError("Trace sequence or hash does not match")
            event["event_hash"] = digest
            if events and event["run_id"] != events[0]["run_id"]:
                raise ValueError("Trace contains another run")
            previous = digest
            events.append(event)
        if not events or events[0]["event"]["type"] != "run_started" or events[-1]["event"]["type"] != "run_stopped":
            raise ValueError("Trace has no complete run boundary")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise DomainError("TRACE_INVALID", "Trace is incomplete or its sequence/hash does not match") from exc
    return events
