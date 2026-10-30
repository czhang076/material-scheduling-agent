"""Pure JSON and result representations shared by application and storage."""

from __future__ import annotations

from typing import Any

from material_scheduler.domain.drafts import (
    ConfirmationCommand, Draft, DraftProposal, DraftState,
)
from material_scheduler.domain.requests import RequestItem
from material_scheduler.domain.review import Finding, Review, ReviewStatus
from material_scheduler.domain.scheduling import Candidate
from material_scheduler.domain.time import TimeInterval, iso, parse_time


def candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "offer_id": candidate.offer_id, "offer_revision": candidate.offer_revision,
        "channel": candidate.channel, **candidate.interval.to_dict(),
    }


def candidate_from_dict(value: dict[str, Any]) -> Candidate:
    return Candidate(
        value["offer_id"], value["offer_revision"], value["channel"],
        TimeInterval(parse_time(value["start"]), parse_time(value["end"])),
    )


def review_to_dict(review: Review) -> dict[str, Any]:
    return {
        "material_id": review.material_id, "material_revision": review.material_revision,
        "material_hash": review.material_hash, "rule_set_hash": review.rule_set_hash,
        "rule_set_id": review.rule_set_id, "rule_set_version": review.rule_set_version,
        "channel": review.channel, "status": review.status.value,
        "findings": [finding.to_dict() for finding in review.findings],
        "missing_fields": list(review.missing_fields),
    }


def review_from_dict(value: dict[str, Any]) -> Review:
    findings = []
    for raw in value["findings"]:
        raw = dict(raw)
        raw["severity"] = ReviewStatus(raw["severity"])
        if type(raw["value"]) is list:
            raw["value"] = tuple(raw["value"])
        findings.append(Finding(**raw))
    return Review(
        value["material_id"], value["material_revision"], value["material_hash"],
        value["rule_set_hash"], value["rule_set_id"], value["rule_set_version"],
        value["channel"], ReviewStatus(value["status"]), tuple(findings),
        tuple(value["missing_fields"]),
    )


def confirmation_to_dict(command: ConfirmationCommand) -> dict[str, Any]:
    return {
        "confirmation_id": command.confirmation_id, "draft_id": command.draft_id,
        "expected_version": command.expected_version,
        "accepted_item_ids": sorted(command.accepted_item_ids),
        "actor": command.actor, "note": command.note,
    }


def draft_to_dict(draft: Draft) -> dict[str, Any]:
    return {
        "draft_id": draft.draft_id, "request_id": draft.request_id,
        "version": draft.version, "state": draft.state.value,
        "proposal": {
            "item": draft.proposal.item.to_dict(),
            "review": review_to_dict(draft.proposal.review),
            "candidate": candidate_to_dict(draft.proposal.candidate),
            "required_confirmations": list(draft.proposal.required_confirmations),
        },
        "confirmation": confirmation_to_dict(draft.confirmation) if draft.confirmation else None,
    }


def draft_from_dict(value: dict[str, Any]) -> Draft:
    proposal = value["proposal"]
    return Draft(
        value["draft_id"], value["request_id"], value["version"],
        DraftProposal(
            RequestItem.from_dict(proposal["item"]),
            review_from_dict(proposal["review"]),
            candidate_from_dict(proposal["candidate"]),
            tuple(proposal["required_confirmations"]),
        ),
        DraftState(value["state"]),
        ConfirmationCommand.from_dict(value["confirmation"]) if value["confirmation"] else None,
    )


def draft_view(draft: Draft, *, stale_reason: str | None = None) -> dict[str, Any]:
    return {
        "draft_id": draft.draft_id, "request_id": draft.request_id,
        "item_id": draft.proposal.item.item_id, "version": draft.version,
        "draft_state": draft.state.value,
        "requested_start": iso(draft.proposal.item.time_requirement.requested_start),
        "candidate": candidate_to_dict(draft.proposal.candidate),
        "pending_confirmations": list(draft.pending_confirmations),
        "required_confirmations": list(draft.proposal.required_confirmations),
        "review_status": draft.proposal.review.status.value,
        "review_snapshot_id": draft.proposal.review.snapshot_id,
        "confirmation": confirmation_to_dict(draft.confirmation) if draft.confirmation else None,
        "stale_reason": stale_reason, "published": False,
    }
