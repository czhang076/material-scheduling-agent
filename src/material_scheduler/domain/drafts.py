"""Pure draft transitions, without persistence or user authentication.

M2 must call these rules inside a transaction with current source observations.
Constructing a Draft here does not mean it has been saved.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Iterable

from .requests import RequestItem, TimeMode
from .review import Review, ReviewStatus
from .scheduling import Booking, Candidate, SlotOffer, candidate_for, conflicts_for
from .validation import DomainError, identifier, integer, object_fields, require, text


class DraftState(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    READY = "READY"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class DraftProposal:
    item: RequestItem
    review: Review
    candidate: Candidate
    required_confirmations: tuple[str, ...]

    def __post_init__(self) -> None:
        require(type(self.item) is RequestItem and type(self.review) is Review, "Invalid proposal facts")
        require(type(self.candidate) is Candidate, "Invalid proposal candidate")
        require(
            type(self.required_confirmations) is tuple
            and self.required_confirmations == _confirmation_items(self.item, self.review, self.candidate),
            "Proposal confirmation requirements cannot be overridden",
        )

    @property
    def initial_state(self) -> DraftState:
        return DraftState.PENDING_CONFIRMATION if self.required_confirmations else DraftState.READY


def _confirmation_items(item: RequestItem, review: Review, candidate: Candidate) -> tuple[str, ...]:
    require(review.material_id == item.material_id and review.channel == item.channel, "Review belongs to another request item")
    if review.status == ReviewStatus.BLOCKED:
        raise DomainError("REVIEW_BLOCKED", "Blocking risks prevent a scheduling draft")
    if review.status == ReviewStatus.NEEDS_INPUT:
        raise DomainError("METADATA_MISSING", "Review facts must be completed first")
    require(review.status in {ReviewStatus.PASS, ReviewStatus.NEEDS_REVIEW}, "Review is incomplete")
    require(candidate.channel == item.channel, "Candidate belongs to another channel")
    if not item.time_requirement.allows(candidate.interval):
        raise DomainError("OUTSIDE_WINDOW", "Candidate does not satisfy the scheduling range")
    pending: list[str] = []
    requirement = item.time_requirement
    if candidate.interval.start != requirement.requested_start:
        if requirement.mode == TimeMode.HARD or requirement.alternative_window is None:
            pending.append("TIME_CHANGE")
        if requirement.mode == TimeMode.PREFERRED and requirement.alternative_window is None:
            pending.append("TIME_RANGE_UNSPECIFIED")
    pending.extend(sorted({
        f"RISK:{finding.rule_id}" for finding in review.findings
        if finding.severity == ReviewStatus.NEEDS_REVIEW
    }))
    return tuple(pending)


def propose_draft(item: RequestItem, review: Review, candidate: Candidate) -> DraftProposal:
    return DraftProposal(item, review, candidate, _confirmation_items(item, review, candidate))


@dataclass(frozen=True, slots=True)
class ConfirmationCommand:
    confirmation_id: str
    draft_id: str
    expected_version: int
    accepted_item_ids: tuple[str, ...]
    actor: str
    note: str | None = None

    def __post_init__(self) -> None:
        identifier(self.confirmation_id, "confirmation_id")
        identifier(self.draft_id, "draft_id")
        integer(self.expected_version, "expected_version", 1, 2**31 - 1)
        text(self.actor, "actor", 64)
        require(bool(self.actor.strip()), "Actor label is required")
        require(type(self.accepted_item_ids) is tuple, "Expected immutable accepted items")
        require(all(type(value) is str and 1 <= len(value) <= 128 for value in self.accepted_item_ids), "Invalid accepted item")
        require(len(self.accepted_item_ids) == len(set(self.accepted_item_ids)), "Duplicate acceptance")
        if self.note is not None:
            text(self.note, "confirmation.note", 1000)

    @classmethod
    def from_dict(cls, value: Any) -> ConfirmationCommand:
        data = object_fields(
            value, {"confirmation_id", "draft_id", "expected_version", "accepted_item_ids", "actor"},
            {"note"}, "confirmation",
        )
        require(type(data["accepted_item_ids"]) is list, "Expected accepted item array")
        return cls(
            data["confirmation_id"], data["draft_id"], data["expected_version"],
            tuple(data["accepted_item_ids"]), data["actor"], data.get("note"),
        )


@dataclass(frozen=True, slots=True)
class Draft:
    draft_id: str
    request_id: str
    version: int
    proposal: DraftProposal
    state: DraftState
    confirmation: ConfirmationCommand | None = None

    def __post_init__(self) -> None:
        identifier(self.draft_id, "draft_id")
        identifier(self.request_id, "request_id")
        integer(self.version, "draft.version", 1, 2**31 - 1)
        require(type(self.proposal) is DraftProposal, "Invalid proposal")
        require(type(self.state) is DraftState, "Invalid draft state")
        if self.state == DraftState.PENDING_CONFIRMATION:
            require(bool(self.proposal.required_confirmations) and self.confirmation is None, "Pending draft cannot be preapproved")
        if self.state == DraftState.READY and self.proposal.required_confirmations:
            require(type(self.confirmation) is ConfirmationCommand, "Ready draft requires confirmation")
            require(
                self.confirmation.draft_id == self.draft_id
                and self.confirmation.expected_version == self.version - 1
                and set(self.confirmation.accepted_item_ids) == set(self.proposal.required_confirmations),
                "Confirmation does not authorize this draft version",
            )
        elif self.state == DraftState.READY:
            require(self.confirmation is None, "Unrequired confirmation cannot be attached")

    @property
    def published(self) -> bool:
        return False

    @property
    def pending_confirmations(self) -> tuple[str, ...]:
        return self.proposal.required_confirmations if self.state == DraftState.PENDING_CONFIRMATION else ()


def create_draft(draft_id: str, request_id: str, proposal: DraftProposal) -> Draft:
    return Draft(draft_id, request_id, 1, proposal, proposal.initial_state)


def invalidate_draft(draft: Draft) -> Draft:
    if draft.state == DraftState.STALE:
        return draft
    return replace(draft, version=draft.version + 1, state=DraftState.STALE)


def replan_draft(draft: Draft, proposal: DraftProposal) -> Draft:
    require(
        proposal.item.identity_dict() == draft.proposal.item.identity_dict(),
        "Original request item cannot be replaced",
    )
    if draft.state != DraftState.STALE and draft.proposal == proposal:
        return draft
    return Draft(draft.draft_id, draft.request_id, draft.version + 1, proposal, proposal.initial_state)


def confirm_draft(
    draft: Draft, command: ConfirmationCommand, current_review: Review,
    current_offer: SlotOffer, bookings: Iterable[Booking],
    *, exclude_booking_id: str | None = None,
) -> Draft:
    if command.draft_id != draft.draft_id or command.expected_version != draft.version:
        raise DomainError("DRAFT_VERSION_CONFLICT", "Confirmation targets another draft version")
    if draft.state != DraftState.PENDING_CONFIRMATION:
        raise DomainError("STALE_DRAFT", "Draft is not awaiting confirmation")
    if set(command.accepted_item_ids) != set(draft.proposal.required_confirmations):
        raise DomainError("CONFIRMATION_INCOMPLETE", "All and only current confirmation items must be accepted")
    if current_review.snapshot_id != draft.proposal.review.snapshot_id:
        raise DomainError("STALE_DRAFT", "Review evidence changed")
    current_candidate = candidate_for(draft.proposal.item, current_offer)
    if current_candidate != draft.proposal.candidate:
        raise DomainError("STALE_DRAFT", "Candidate offer changed or was withdrawn")
    if conflicts_for(
        draft.proposal.item.channel, current_candidate.interval, bookings,
        exclude_booking_id=exclude_booking_id,
    ):
        raise DomainError("SLOT_CONFLICT", "Candidate is no longer available")
    return replace(draft, version=draft.version + 1, state=DraftState.READY, confirmation=command)
