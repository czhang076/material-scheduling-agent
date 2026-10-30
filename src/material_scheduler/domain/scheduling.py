"""Candidate availability and same-channel half-open interval conflicts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterable

from .requests import RequestItem
from .time import TimeInterval, parse_time
from .validation import identifier, integer, object_fields, require


class QueryMode(StrEnum):
    REQUESTED = "requested"
    ALTERNATIVES = "alternatives"


@dataclass(frozen=True, slots=True)
class SlotOffer:
    offer_id: str
    revision: int
    channel: str
    interval: TimeInterval

    def __post_init__(self) -> None:
        identifier(self.offer_id, "offer_id")
        integer(self.revision, "offer.revision", 1, 2**31 - 1)
        identifier(self.channel, "channel", 32)
        require(type(self.interval) is TimeInterval, "Invalid offer interval")

    @classmethod
    def from_dict(cls, value: Any) -> SlotOffer:
        data = object_fields(value, {"offer_id", "revision", "channel", "start", "end"}, set(), "offer")
        return cls(data["offer_id"], data["revision"], data["channel"], TimeInterval(parse_time(data["start"]), parse_time(data["end"])))


@dataclass(frozen=True, slots=True)
class Booking:
    booking_id: str
    source_revision: int
    channel: str
    interval: TimeInterval

    def __post_init__(self) -> None:
        identifier(self.booking_id, "booking_id")
        integer(self.source_revision, "booking.source_revision", 1, 2**31 - 1)
        identifier(self.channel, "channel", 32)
        require(type(self.interval) is TimeInterval, "Invalid booking interval")

    @classmethod
    def from_dict(cls, value: Any) -> Booking:
        data = object_fields(value, {"booking_id", "source_revision", "channel", "start", "end"}, set(), "booking")
        return cls(data["booking_id"], data["source_revision"], data["channel"], TimeInterval(parse_time(data["start"]), parse_time(data["end"])))


@dataclass(frozen=True, slots=True)
class Candidate:
    offer_id: str
    offer_revision: int
    channel: str
    interval: TimeInterval

    def __post_init__(self) -> None:
        identifier(self.offer_id, "candidate.offer_id")
        integer(self.offer_revision, "candidate.offer_revision", 1, 2**31 - 1)
        identifier(self.channel, "candidate.channel", 32)
        require(type(self.interval) is TimeInterval, "Invalid candidate interval")


@dataclass(frozen=True, slots=True)
class SlotQuery:
    mode: QueryMode
    requested_available: bool
    candidates: tuple[Candidate, ...]
    requested_conflicts: tuple[Booking, ...]


def conflicts_for(
    channel: str, interval: TimeInterval, bookings: Iterable[Booking],
    *, exclude_booking_id: str | None = None,
) -> tuple[Booking, ...]:
    identifier(channel, "channel", 32)
    return tuple(sorted(
        (booking for booking in bookings
         if booking.channel == channel
         and booking.booking_id != exclude_booking_id
         and booking.interval.overlaps(interval)),
        key=lambda entry: entry.booking_id,
    ))


def candidate_for(item: RequestItem, offer: SlotOffer) -> Candidate | None:
    if offer.channel != item.channel:
        return None
    try:
        interval = TimeInterval(
            offer.interval.start,
            offer.interval.start + timedelta(minutes=item.time_requirement.duration_minutes),
        )
    except OverflowError:
        return None
    if not offer.interval.contains(interval) or not item.time_requirement.allows(interval):
        return None
    return Candidate(offer.offer_id, offer.revision, offer.channel, interval)


def query_slots(
    item: RequestItem, offers: Iterable[SlotOffer], bookings: Iterable[Booking],
    mode: QueryMode, *, limit: int = 10, exclude_booking_id: str | None = None,
) -> SlotQuery:
    require(type(mode) is QueryMode, "Invalid slot query mode")
    integer(limit, "query.limit", 1, 10)
    bookings = tuple(bookings)
    requested = item.time_requirement.requested_interval
    requested_conflicts = conflicts_for(
        item.channel, requested, bookings, exclude_booking_id=exclude_booking_id
    )
    offered: list[Candidate] = []
    for offer in offers:
        candidate = candidate_for(item, offer)
        if candidate is not None and not conflicts_for(
            item.channel, candidate.interval, bookings, exclude_booking_id=exclude_booking_id
        ):
            offered.append(candidate)
    offered.sort(key=lambda candidate: (
        abs((candidate.interval.start - requested.start).total_seconds()),
        candidate.interval.start.astimezone(timezone.utc), candidate.offer_id,
    ))
    # Equivalent offers must not create duplicate time suggestions.
    unique: dict[datetime, Candidate] = {}
    for candidate in offered:
        unique.setdefault(candidate.interval.start.astimezone(timezone.utc), candidate)
    candidates = tuple(unique.values())
    requested_available = any(candidate.interval == requested for candidate in candidates)
    if mode == QueryMode.REQUESTED:
        candidates = tuple(candidate for candidate in candidates if candidate.interval == requested)
    else:
        candidates = tuple(candidate for candidate in candidates if candidate.interval != requested)
    return SlotQuery(mode, requested_available, candidates[:limit], requested_conflicts)
