"""Fixed-offset, minute-resolution intervals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from .validation import DomainError, require, text


def valid_time(value: datetime, path: str = "time") -> datetime:
    require(type(value) is datetime, "Expected a datetime", path)
    require(isinstance(value.tzinfo, timezone), "A fixed UTC offset is required", path)
    require(value.second == 0 and value.microsecond == 0, "Minute precision required", path)
    offset = value.utcoffset()
    require(offset is not None and offset.total_seconds() % 60 == 0, "Invalid UTC offset", path)
    try:
        value.astimezone(timezone.utc)
    except OverflowError as exc:
        raise DomainError("INVALID_INPUT", "Absolute UTC time exceeds calendar range", path=path) from exc
    return value


def parse_time(value: str, path: str = "time") -> datetime:
    text(value, path, 40)
    require(
        bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::00)?(?:Z|[+-]\d{2}:\d{2})", value)),
        "Expected an ISO timestamp with a UTC offset and minute precision",
        path,
    )
    # Reject normalized-but-invalid offset minutes such as +08:99.
    if not value.endswith("Z"):
        require(int(value[-5:-3]) < 24 and int(value[-2:]) < 60, "Invalid UTC offset", path)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DomainError("INVALID_INPUT", "Invalid calendar date or time", path=path) from exc
    return valid_time(parsed, path)


def iso(value: datetime, *, canonical: bool = False) -> str:
    valid_time(value)
    if canonical:
        value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class TimeInterval:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        valid_time(self.start, "interval.start")
        valid_time(self.end, "interval.end")
        require(self.end > self.start, "Interval must have positive length", "interval")

    def overlaps(self, other: TimeInterval) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: TimeInterval) -> bool:
        return self.start <= other.start and other.end <= self.end

    def to_dict(self, *, canonical: bool = False) -> dict[str, str]:
        return {
            "start": iso(self.start, canonical=canonical),
            "end": iso(self.end, canonical=canonical),
        }
