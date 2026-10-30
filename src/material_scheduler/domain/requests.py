"""Immutable request identity and explicit scheduling authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from .time import TimeInterval, iso, parse_time, valid_time
from .validation import DomainError, fingerprint, identifier, integer, object_fields, parse_json, require


class TimeMode(StrEnum):
    HARD = "hard"
    PREFERRED = "preferred"


@dataclass(frozen=True, slots=True)
class TimeRequirement:
    requested_start: datetime
    duration_minutes: int
    mode: TimeMode
    alternative_window: TimeInterval | None = None

    def __post_init__(self) -> None:
        valid_time(self.requested_start, "time_requirement.requested_start")
        integer(self.duration_minutes, "time_requirement.duration_minutes", 1, 180)
        require(type(self.mode) is TimeMode, "Invalid time mode", "time_requirement.mode")
        # Validate representability even for boundary dates.
        try:
            requested = self.requested_interval
            _ = self.default_day
        except OverflowError as exc:
            raise DomainError("INVALID_INPUT", "Time interval exceeds calendar range") from exc
        if self.alternative_window is not None:
            require(type(self.alternative_window) is TimeInterval, "Invalid alternative window")
            require(
                self.alternative_window.end - self.alternative_window.start <= timedelta(days=7),
                "Alternative window exceeds seven days",
            )
            require(self.alternative_window.contains(requested), "Requested interval is outside window")

    @property
    def requested_interval(self) -> TimeInterval:
        return TimeInterval(
            self.requested_start,
            self.requested_start + timedelta(minutes=self.duration_minutes),
        )

    @property
    def default_day(self) -> TimeInterval:
        start = self.requested_start.replace(hour=0, minute=0)
        return TimeInterval(start, start + timedelta(days=1))

    def allows(self, candidate: TimeInterval) -> bool:
        if candidate.end - candidate.start != timedelta(minutes=self.duration_minutes):
            return False
        if self.alternative_window is not None:
            return self.alternative_window.contains(candidate)
        # No cross-day candidate starts. The requested interval itself may end after midnight.
        day = self.default_day
        return day.start <= candidate.start < day.end

    @classmethod
    def from_dict(cls, value: Any) -> TimeRequirement:
        data = object_fields(
            value,
            {"requested_start", "duration_minutes", "mode"},
            {"alternative_window"},
            "time_requirement",
        )
        require(type(data["mode"]) is str and data["mode"] in {"hard", "preferred"}, "Invalid time mode")
        window = data.get("alternative_window")
        if window is not None:
            window = object_fields(window, {"start", "end"}, set(), "alternative_window")
            window = TimeInterval(
                parse_time(window["start"], "alternative_window.start"),
                parse_time(window["end"], "alternative_window.end"),
            )
        return cls(
            parse_time(data["requested_start"], "requested_start"),
            data["duration_minutes"],
            TimeMode(data["mode"]),
            window,
        )

    def to_dict(self, *, canonical: bool = False) -> dict[str, Any]:
        return {
            "requested_start": iso(self.requested_start, canonical=canonical),
            "duration_minutes": self.duration_minutes,
            "mode": self.mode.value,
            "alternative_window": (
                self.alternative_window.to_dict(canonical=canonical)
                if self.alternative_window is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class RequestItem:
    item_id: str
    material_id: str
    channel: str
    time_requirement: TimeRequirement

    def __post_init__(self) -> None:
        identifier(self.item_id, "item_id")
        identifier(self.material_id, "material_id")
        identifier(self.channel, "channel", 32)
        require(type(self.time_requirement) is TimeRequirement, "Invalid time requirement")

    @classmethod
    def from_dict(cls, value: Any) -> RequestItem:
        data = object_fields(
            value, {"item_id", "material_id", "channel", "time_requirement"}, set(), "item"
        )
        return cls(
            data["item_id"], data["material_id"], data["channel"],
            TimeRequirement.from_dict(data["time_requirement"]),
        )

    def to_dict(self, *, canonical: bool = False) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "material_id": self.material_id,
            "channel": self.channel,
            "time_requirement": self.time_requirement.to_dict(canonical=canonical),
        }

    def identity_dict(self) -> dict[str, Any]:
        value = self.to_dict(canonical=True)
        if self.time_requirement.alternative_window is None:
            value["time_requirement"]["effective_default_day"] = (
                self.time_requirement.default_day.to_dict(canonical=True)
            )
        return value


@dataclass(frozen=True, slots=True)
class SchedulingRequest:
    request_id: str
    items: tuple[RequestItem, ...]
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        identifier(self.request_id, "request_id")
        require(self.schema_version == "1.0", "Unsupported schema version")
        require(type(self.items) is tuple and 1 <= len(self.items) <= 20, "Expected 1 to 20 items")
        require(all(type(item) is RequestItem for item in self.items), "Invalid request item")
        require(len({item.item_id for item in self.items}) == len(self.items), "Duplicate item_id")

    @classmethod
    def from_dict(cls, value: Any) -> SchedulingRequest:
        data = object_fields(value, {"schema_version", "request_id", "items"}, set(), "request")
        require(type(data["items"]) is list, "Expected items array", "request.items")
        require(1 <= len(data["items"]) <= 20, "Expected 1 to 20 items", "request.items")
        return cls(
            data["request_id"], tuple(RequestItem.from_dict(item) for item in data["items"]),
            data["schema_version"],
        )

    @classmethod
    def from_json(cls, value: str) -> SchedulingRequest:
        return cls.from_dict(parse_json(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "items": [item.to_dict() for item in self.items],
        }

    @property
    def payload_hash(self) -> str:
        canonical_items = []
        for item in sorted(self.items, key=lambda entry: entry.item_id):
            canonical_items.append(item.identity_dict())
        return fingerprint({"schema_version": self.schema_version, "items": canonical_items})
