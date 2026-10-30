"""Explicit local test faults; not exposed in model/business arguments."""

from __future__ import annotations

from threading import Lock

from material_scheduler.domain.validation import DomainError, integer


class InjectedFailure(DomainError):
    def __init__(self, point: str) -> None:
        super().__init__("TOOL_UNAVAILABLE", "Injected local failure")
        self.point = point


class FaultInjector:
    ALLOWED = frozenset({
        "save.before_write", "save.after_draft_write", "save.after_commit",
        "confirm.before_write", "confirm.after_draft_write", "confirm.after_commit",
        "receipt.read", "read_material", "lookup_metadata", "check_rules", "query_slots",
    })

    def __init__(self, failures: dict[str, int] | None = None) -> None:
        self._failures = dict(failures or {})
        for point, count in self._failures.items():
            if point not in self.ALLOWED:
                raise ValueError("Unknown local fault point")
            integer(count, "fault_count", 1, 100)
        self._lock = Lock()

    def trip(self, point: str) -> None:
        with self._lock:
            count = self._failures.get(point, 0)
            if count:
                self._failures[point] = count - 1
                raise InjectedFailure(point)

    def configuration(self) -> dict[str, int]:
        with self._lock:
            return dict(self._failures)
