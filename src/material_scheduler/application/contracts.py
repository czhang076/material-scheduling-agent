"""Application data passed across the ledger interface."""

from dataclasses import dataclass

from material_scheduler.domain.drafts import Draft
from material_scheduler.domain.scheduling import Candidate
from material_scheduler.domain.validation import identifier, require
from .serialization import draft_view


@dataclass(frozen=True, slots=True)
class SaveEvidence:
    request_id: str
    item_id: str
    review_snapshot_id: str
    candidate: Candidate

    def __post_init__(self) -> None:
        identifier(self.request_id, "evidence.request_id")
        identifier(self.item_id, "evidence.item_id")
        require(type(self.review_snapshot_id) is str and len(self.review_snapshot_id) == 64, "Invalid review snapshot")
        require(type(self.candidate) is Candidate, "Invalid observed candidate")


@dataclass(frozen=True, slots=True)
class MutationResult:
    kind: str
    status: str
    draft: Draft
    operation_id: str
    operation_version: int
    reconciled: bool = False
    stale_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            **draft_view(self.draft, stale_reason=self.stale_reason),
            "save_status" if self.kind == "SAVE" else "confirmation_status": self.status,
            "persisted": True, "operation_id": self.operation_id,
            "operation_version": self.operation_version, "reconciled": self.reconciled,
        }
