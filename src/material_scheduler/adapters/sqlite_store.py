"""Atomic local draft ledger, reusing the deterministic domain rules."""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from material_scheduler.domain.catalog import Material, MetadataSupplement, METADATA_FIELDS
from material_scheduler.domain.drafts import (
    ConfirmationCommand, Draft, DraftState, confirm_draft, create_draft,
    invalidate_draft, propose_draft, replan_draft,
)
from material_scheduler.domain.requests import RequestItem, SchedulingRequest
from material_scheduler.domain.review import Review, ReviewStatus, evaluate_review
from material_scheduler.domain.scheduling import (
    Booking, Candidate, QueryMode, candidate_for, conflicts_for, query_slots,
)
from material_scheduler.domain.time import TimeInterval, iso, parse_time
from material_scheduler.domain.validation import (
    DomainError, fingerprint, identifier, integer, require,
)
from material_scheduler.application.contracts import MutationResult, SaveEvidence
from material_scheduler.application.serialization import (
    candidate_to_dict, confirmation_to_dict, draft_from_dict, draft_to_dict, draft_view,
)
from .faults import FaultInjector, InjectedFailure
from .fixture_loader import FixtureSet


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def fixture_to_dict(dataset: FixtureSet) -> dict[str, Any]:
    return {
        "schema_version": "1.0", "data_revision": dataset.data_revision,
        "materials": [entry.to_dict() for entry in dataset.materials],
        "supplements": [entry.to_dict() for entry in dataset.supplements],
        "rule_set": dataset.rule_set.to_dict(),
        "slot_offers": [
            {"offer_id": entry.offer_id, "revision": entry.revision, "channel": entry.channel, **entry.interval.to_dict()}
            for entry in dataset.slot_offers
        ],
        "existing_bookings": [
            {"booking_id": entry.booking_id, "source_revision": entry.source_revision, "channel": entry.channel, **entry.interval.to_dict()}
            for entry in dataset.existing_bookings
        ],
    }


class _CommitUncertain(Exception):
    """The commit acknowledgement was not trustworthy; reconcile an exact receipt."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    payload_json TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation>0),
    provenance_json TEXT NOT NULL, conflicts_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES requests(request_id),
    item_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
    state TEXT NOT NULL CHECK(state IN ('READY','PENDING_CONFIRMATION','STALE')),
    channel TEXT NOT NULL, start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL, stale_reason TEXT,
    UNIQUE(request_id,item_id), CHECK(start_utc<end_utc)
);
CREATE TABLE IF NOT EXISTS reservations (
    draft_id TEXT PRIMARY KEY REFERENCES drafts(draft_id),
    channel TEXT NOT NULL, start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
    CHECK(start_utc<end_utc)
);
CREATE INDEX IF NOT EXISTS reservation_intervals ON reservations(channel,start_utc,end_utc);
CREATE TRIGGER IF NOT EXISTS reservation_insert_guard BEFORE INSERT ON reservations
BEGIN
    SELECT RAISE(ABORT,'invalid_reservation')
    WHERE NOT EXISTS (
        SELECT 1 FROM drafts WHERE draft_id=NEW.draft_id AND state='READY'
          AND channel=NEW.channel AND start_utc=NEW.start_utc AND end_utc=NEW.end_utc
    );
    SELECT RAISE(ABORT,'reservation_overlap')
    WHERE EXISTS (
        SELECT 1 FROM reservations WHERE channel=NEW.channel
          AND start_utc<NEW.end_utc AND NEW.start_utc<end_utc
    );
END;
CREATE TRIGGER IF NOT EXISTS reservation_update_guard BEFORE UPDATE ON reservations
BEGIN
    SELECT RAISE(ABORT,'invalid_reservation')
    WHERE NOT EXISTS (
        SELECT 1 FROM drafts WHERE draft_id=NEW.draft_id AND state='READY'
          AND channel=NEW.channel AND start_utc=NEW.start_utc AND end_utc=NEW.end_utc
    );
    SELECT RAISE(ABORT,'reservation_overlap')
    WHERE EXISTS (
        SELECT 1 FROM reservations WHERE draft_id<>OLD.draft_id AND channel=NEW.channel
          AND start_utc<NEW.end_utc AND NEW.start_utc<end_utc
    );
END;
CREATE TABLE IF NOT EXISTS confirmations (
    confirmation_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL, draft_id TEXT NOT NULL REFERENCES drafts(draft_id),
    result_version INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
    request_id TEXT, item_id TEXT, draft_id TEXT, version INTEGER,
    run_id TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operation_receipts (
    operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
    draft_id TEXT NOT NULL REFERENCES drafts(draft_id),
    result_version INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


class SQLiteStore:
    """Small public operations; every connection is owned by one operation/thread."""

    def __init__(
        self, path: str | Path, *, busy_timeout_ms: int = 3000,
        faults: FaultInjector | None = None,
    ) -> None:
        require(str(path) != ":memory:", "A file-backed ledger is required")
        self.path = Path(path).resolve()
        integer(busy_timeout_ms, "busy_timeout_ms", 1, 30_000)
        self.busy_timeout_ms = busy_timeout_ms
        self.faults = faults if faults is not None else FaultInjector()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with closing(self._connect()) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise DomainError("STORE_UNAVAILABLE", "Unsupported ledger schema version")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA + "\nPRAGMA user_version=1;\nCOMMIT;")
        except sqlite3.Error as exc:
            raise DomainError("STORE_UNAVAILABLE", "Cannot initialize local ledger") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path, timeout=self.busy_timeout_ms / 1000, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            try:
                connection.commit()
            except sqlite3.Error as exc:
                if connection.in_transaction:
                    connection.rollback()
                raise _CommitUncertain() from exc
        finally:
            connection.close()

    def _catalog(self, connection: sqlite3.Connection) -> tuple[FixtureSet, int, dict, dict]:
        row = connection.execute("SELECT * FROM catalog WHERE singleton=1").fetchone()
        if row is None:
            raise DomainError("STORE_UNAVAILABLE", "Synthetic data has not been imported")
        try:
            return (
                FixtureSet.from_dict(json.loads(row["payload_json"])), row["generation"],
                json.loads(row["provenance_json"]), json.loads(row["conflicts_json"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Stored source snapshot failed validation") from exc

    def _put_catalog(self, connection, dataset, generation, provenance, conflicts) -> None:
        connection.execute(
            "INSERT INTO catalog VALUES(1,?,?,?,?) "
            "ON CONFLICT(singleton) DO UPDATE SET payload_json=excluded.payload_json,"
            "generation=excluded.generation,provenance_json=excluded.provenance_json,conflicts_json=excluded.conflicts_json",
            (_json(fixture_to_dict(dataset)), generation, _json(provenance), _json(conflicts)),
        )

    def _audit(self, connection, event, *, draft=None, request_id=None, item_id=None, run_id=None, data=None) -> None:
        connection.execute(
            "INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?,?)",
            (
                _id("AUD"), event, draft.request_id if draft else request_id,
                draft.proposal.item.item_id if draft else item_id,
                draft.draft_id if draft else None, draft.version if draft else None,
                run_id, _json(data or {}), _now(),
            ),
        )

    @staticmethod
    def _source_conflicts(dataset: FixtureSet) -> dict[str, list[dict[str, Any]]]:
        conflicts: dict[str, list[dict[str, Any]]] = {}
        for material in dataset.materials:
            related = [source for source in dataset.supplements if source.material_id == material.material_id]
            for field in sorted(METADATA_FIELDS):
                entries: list[dict[str, Any]] = []
                if not material.is_missing(field):
                    value = material.value(field)
                    entries.append({"source_id": material.source_id, "revision": material.revision, "value": value})
                for source in related:
                    values = dict(source.fields)
                    if field not in values:
                        continue
                    probe = replace(material, **{field: values[field]})
                    if not probe.is_missing(field):
                        entries.append({"source_id": source.source_id, "revision": source.revision, "value": values[field]})
                keys = {
                    _json(sorted(entry["value"]) if type(entry["value"]) is tuple else entry["value"])
                    for entry in entries
                }
                if len(keys) > 1:
                    conflicts.setdefault(material.material_id, []).append({"field": field, "sources": entries})
        return conflicts

    def import_dataset(self, dataset: FixtureSet) -> dict[str, Any]:
        dataset = FixtureSet.from_dict(fixture_to_dict(dataset))
        try:
            with self._transaction() as connection:
                existing = connection.execute("SELECT 1 FROM catalog").fetchone()
                if existing:
                    old, generation, _, conflicts = self._catalog(connection)
                    if fingerprint(fixture_to_dict(old)) == fingerprint(fixture_to_dict(dataset)):
                        self._refresh(connection)
                        return {"changed": False, "generation": generation}
                else:
                    generation = 0
                conflicts = self._source_conflicts(dataset)
                self._put_catalog(connection, dataset, generation + 1, {}, conflicts)
                self._audit(connection, "DATA_IMPORTED", data={
                    "generation": generation + 1,
                    "dataset_sha256": fingerprint(fixture_to_dict(dataset)),
                    "source_conflicts": conflicts,
                })
                invalidated = self._refresh(connection)
                return {"changed": True, "generation": generation + 1, "invalidated": invalidated}
        except (sqlite3.Error, _CommitUncertain) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Dataset import could not be acknowledged") from exc

    def _request(self, connection, request_id) -> SchedulingRequest:
        row = connection.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            raise DomainError("INVALID_INPUT", "Request is not registered")
        return SchedulingRequest.from_dict(json.loads(row["payload_json"]))

    def register_request(self, request: SchedulingRequest) -> SchedulingRequest:
        try:
            with self._transaction() as connection:
                row = connection.execute("SELECT * FROM requests WHERE request_id=?", (request.request_id,)).fetchone()
                if row:
                    if row["payload_hash"] != request.payload_hash:
                        raise DomainError("REQUEST_ID_CONFLICT", "Request ID already has different business content")
                    return self._request(connection, request.request_id)
                connection.execute(
                    "INSERT INTO requests VALUES(?,?,?,?)",
                    (request.request_id, request.payload_hash, _json(request.to_dict()), _now()),
                )
                return request
        except (sqlite3.Error, _CommitUncertain) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Cannot register request identity") from exc

    def _item(self, connection, request_id, item_id) -> RequestItem:
        for item in self._request(connection, request_id).items:
            if item.item_id == item_id:
                return item
        raise DomainError("ACTION_NOT_ALLOWED", "Item is outside the current request")

    def _review(self, connection, item: RequestItem) -> Review:
        dataset, _, _, conflicts = self._catalog(connection)
        if conflicts.get(item.material_id):
            raise DomainError("SOURCE_CONFLICT", "Source facts conflict; user clarification is required")
        return evaluate_review(dataset.material(item.material_id), dataset.rule_set, item.channel)

    def _load_draft(self, row) -> Draft:
        try:
            draft = draft_from_dict(json.loads(row["payload_json"]))
            require(
                draft.draft_id == row["draft_id"] and draft.request_id == row["request_id"]
                and draft.proposal.item.item_id == row["item_id"]
                and draft.version == row["version"] and draft.state.value == row["state"],
                "Stored draft columns do not match payload",
            )
            require(
                draft.proposal.candidate.channel == row["channel"]
                and iso(draft.proposal.candidate.interval.start, canonical=True) == row["start_utc"]
                and iso(draft.proposal.candidate.interval.end, canonical=True) == row["end_utc"],
                "Stored draft interval does not match payload",
            )
            return draft
        except (ValueError, KeyError, TypeError) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Stored draft failed validation") from exc

    def _draft_row(self, connection, request_id, item_id):
        return connection.execute("SELECT * FROM drafts WHERE request_id=? AND item_id=?", (request_id, item_id)).fetchone()

    def _bookings(self, connection, request_id, *, exclude_draft_id=None) -> tuple[Booking, ...]:
        dataset, _, _, _ = self._catalog(connection)
        bookings = list(dataset.existing_bookings)
        for row in connection.execute(
            "SELECT * FROM reservations WHERE draft_id<>?", (exclude_draft_id or "",)
        ):
            bookings.append(Booking(
                "RES-" + row["draft_id"], 1, row["channel"],
                TimeInterval(parse_time(row["start_utc"]), parse_time(row["end_utc"])),
            ))
        for row in connection.execute(
            "SELECT * FROM drafts WHERE request_id=? AND state='PENDING_CONFIRMATION' AND draft_id<>?",
            (request_id, exclude_draft_id or ""),
        ):
            draft = self._load_draft(row)
            bookings.append(Booking(
                "PEN-" + draft.draft_id, draft.version, draft.proposal.item.channel,
                draft.proposal.candidate.interval,
            ))
        return tuple(bookings)

    def _put_draft(self, connection, draft: Draft, *, stale_reason=None) -> None:
        candidate = draft.proposal.candidate
        start, end = iso(candidate.interval.start, canonical=True), iso(candidate.interval.end, canonical=True)
        connection.execute("DELETE FROM reservations WHERE draft_id=?", (draft.draft_id,))
        connection.execute(
            "INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(draft_id) DO UPDATE SET version=excluded.version,state=excluded.state,"
            "channel=excluded.channel,start_utc=excluded.start_utc,end_utc=excluded.end_utc,"
            "payload_json=excluded.payload_json,stale_reason=excluded.stale_reason",
            (
                draft.draft_id, draft.request_id, draft.proposal.item.item_id,
                draft.version, draft.state.value, candidate.channel, start, end,
                _json(draft_to_dict(draft)), stale_reason,
            ),
        )
        if draft.state == DraftState.READY:
            connection.execute("INSERT INTO reservations VALUES(?,?,?,?)", (draft.draft_id, candidate.channel, start, end))

    def _refresh(self, connection) -> list[str]:
        rows = connection.execute("SELECT * FROM drafts WHERE state<>'STALE' ORDER BY draft_id").fetchall()
        if not rows:
            return []
        dataset, _, _, _ = self._catalog(connection)
        offers = {offer.offer_id: offer for offer in dataset.slot_offers}
        invalidated = []
        for row in rows:
            draft = self._load_draft(row)
            reason = None
            try:
                review = self._review(connection, draft.proposal.item)
                if review.status == ReviewStatus.BLOCKED:
                    reason = "REVIEW_BLOCKED"
                elif review.status == ReviewStatus.NEEDS_INPUT:
                    reason = "METADATA_MISSING"
                elif review.snapshot_id != draft.proposal.review.snapshot_id:
                    reason = "STALE_REVIEW"
                offer = offers.get(draft.proposal.candidate.offer_id)
                if reason is None and (offer is None or candidate_for(draft.proposal.item, offer) != draft.proposal.candidate):
                    reason = "STALE_DRAFT"
                if reason is None and conflicts_for(
                    draft.proposal.item.channel, draft.proposal.candidate.interval,
                    self._bookings(connection, draft.request_id, exclude_draft_id=draft.draft_id),
                ):
                    reason = "SLOT_CONFLICT"
            except DomainError as exc:
                if exc.code == "STORE_UNAVAILABLE":
                    raise
                reason = exc.code
            if reason:
                stale = invalidate_draft(draft)
                self._put_draft(connection, stale, stale_reason=reason)
                self._audit(connection, "DRAFT_INVALIDATED", draft=stale, data={"reason": reason, "previous": draft_to_dict(draft)})
                invalidated.append(draft.draft_id)
        return invalidated

    def read_material(self, request_id: str, item_id: str) -> dict[str, Any]:
        self.faults.trip("read_material")
        try:
            with self._transaction() as connection:
                item = self._item(connection, request_id, item_id)
                dataset, generation, provenance, conflicts = self._catalog(connection)
                try:
                    material = dataset.material(item.material_id)
                except DomainError as exc:
                    if exc.code != "MATERIAL_NOT_FOUND":
                        raise
                    return {
                        "material": None, "source_id": None, "revision": None,
                        "missing_fields": ["material"], "supplement_available": False,
                        "source_conflicts": [], "generation": generation,
                    }
                return {
                    "material": material.to_dict(), "source_id": material.source_id,
                    "revision": material.revision,
                    "missing_fields": [field for field in sorted(("title", "copy_text", "rights_status", "supported_channels")) if material.is_missing(field)],
                    "supplement_available": any(source.material_id == material.material_id for source in dataset.supplements),
                    "field_sources": provenance.get(material.material_id, {}),
                    "source_conflicts": conflicts.get(material.material_id, []), "generation": generation,
                }
        except (sqlite3.Error, _CommitUncertain) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Cannot read local source") from exc

    def check_rules(self, request_id: str, item_id: str) -> Review:
        self.faults.trip("check_rules")
        try:
            with self._transaction() as connection:
                return self._review(connection, self._item(connection, request_id, item_id))
        except (sqlite3.Error, _CommitUncertain) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Cannot check current source") from exc

    def query_slots(self, request_id: str, item_id: str, mode: QueryMode, *, limit=10):
        self.faults.trip("query_slots")
        try:
            with self._transaction() as connection:
                self._refresh(connection)
                item = self._item(connection, request_id, item_id)
                dataset, generation, _, _ = self._catalog(connection)
                existing = self._draft_row(connection, request_id, item_id)
                result = query_slots(
                    item, dataset.slot_offers,
                    self._bookings(connection, request_id, exclude_draft_id=existing["draft_id"] if existing else None),
                    mode, limit=limit,
                )
                # Include local reservations and same-batch pending proposals, not
                # just imported catalog changes, in the availability fingerprint.
                revision = fingerprint({
                    "catalog_generation": generation,
                    "bookings": sorted([
                        {"id": booking.booking_id, "revision": booking.source_revision,
                         "channel": booking.channel, **booking.interval.to_dict()}
                        for booking in self._bookings(
                            connection, request_id,
                            exclude_draft_id=existing["draft_id"] if existing else None,
                        )
                    ], key=lambda entry: entry["id"]),
                })
                return result, revision
        except (sqlite3.Error, _CommitUncertain) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Cannot query current schedule") from exc

    def lookup_metadata(self, request_id: str, item_id: str, *, run_id=None) -> dict[str, Any]:
        self.faults.trip("lookup_metadata")
        try:
            with self._transaction() as connection:
                item = self._item(connection, request_id, item_id)
                dataset, generation, provenance, _ = self._catalog(connection)
                material = dataset.material(item.material_id)
                related = sorted(
                    (source for source in dataset.supplements if source.material_id == material.material_id),
                    key=lambda source: source.source_id,
                )
                conflicts = self._source_conflicts(dataset)
                conflicting_fields = {entry["field"] for entry in conflicts.get(material.material_id, [])}
                changes = {}
                applied_sources = {}
                for field in sorted(METADATA_FIELDS):
                    if not material.is_missing(field) or field in conflicting_fields:
                        continue
                    for source in related:
                        values = dict(source.fields)
                        if field not in values or replace(material, **{field: values[field]}).is_missing(field):
                            continue
                        changes.setdefault(field, values[field])
                        applied_sources.setdefault(field, []).append({
                            "source_id": source.source_id, "revision": source.revision,
                            "provenance": source.provenance,
                        })
                if changes:
                    material = replace(material, revision=material.revision + 1, **changes)
                    dataset = replace(dataset, materials=tuple(
                        material if entry.material_id == material.material_id else entry
                        for entry in dataset.materials
                    ))
                    provenance.setdefault(material.material_id, {}).update(applied_sources)
                    generation += 1
                conflicts = self._source_conflicts(dataset)
                self._put_catalog(connection, dataset, generation, provenance, conflicts)
                if changes:
                    self._audit(
                        connection, "METADATA_ENRICHED", request_id=request_id,
                        item_id=item_id, run_id=run_id,
                        data={"fields": sorted(changes), "field_sources": applied_sources, "revision": material.revision},
                    )
                self._refresh(connection)
                return {
                    "applied_fields": sorted(changes),
                    "source_ids": [source.source_id for source in related],
                    "remaining_missing": [field for field in sorted(("title", "copy_text", "rights_status", "supported_channels")) if material.is_missing(field)],
                    "source_conflicts": conflicts.get(material.material_id, []),
                    "revision": material.revision,
                    "field_sources": provenance.get(material.material_id, {}),
                }
        except (sqlite3.Error, _CommitUncertain) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Cannot acknowledge metadata merge") from exc

    def _validate_save(self, connection, evidence: SaveEvidence) -> tuple[Draft, str]:
        item = self._item(connection, evidence.request_id, evidence.item_id)
        review = self._review(connection, item)
        if review.snapshot_id != evidence.review_snapshot_id:
            raise DomainError("STALE_REVIEW", "Review evidence changed; check rules again")
        dataset, _, _, _ = self._catalog(connection)
        offer = next((entry for entry in dataset.slot_offers if entry.offer_id == evidence.candidate.offer_id), None)
        if offer is None or candidate_for(item, offer) != evidence.candidate:
            raise DomainError("CANDIDATE_NOT_OBSERVED", "Candidate offer is no longer the observed offer")
        existing_row = self._draft_row(connection, evidence.request_id, evidence.item_id)
        existing = self._load_draft(existing_row) if existing_row else None
        if conflicts_for(
            item.channel, evidence.candidate.interval,
            self._bookings(connection, evidence.request_id, exclude_draft_id=existing.draft_id if existing else None),
        ):
            raise DomainError("SLOT_CONFLICT", "Candidate became occupied; query again")
        proposal = propose_draft(item, review, evidence.candidate)
        if existing is None:
            return create_draft(_id("D"), evidence.request_id, proposal), "CREATED"
        updated = replan_draft(existing, proposal)
        return updated, "REUSED" if updated is existing else "UPDATED"

    def _receipt(self, connection, result: MutationResult) -> None:
        connection.execute(
            "INSERT INTO operation_receipts VALUES(?,?,?,?,?,?)",
            (result.operation_id, result.kind, result.draft.draft_id, result.operation_version, result.status, _now()),
        )

    def _reconcile(self, operation_id: str) -> MutationResult:
        try:
            self.faults.trip("receipt.read")
            with self._transaction() as connection:
                self._refresh(connection)
                row = connection.execute(
                    "SELECT * FROM operation_receipts WHERE operation_id=?", (operation_id,)
                ).fetchone()
                if row is None:
                    raise DomainError("SAVE_OUTCOME_UNKNOWN", "Exact commit receipt cannot be verified")
                current = connection.execute("SELECT * FROM drafts WHERE draft_id=?", (row["draft_id"],)).fetchone()
                if current is None:
                    raise DomainError("SAVE_OUTCOME_UNKNOWN", "Committed draft cannot be read")
                return MutationResult(
                    row["kind"], row["status"], self._load_draft(current),
                    operation_id, row["result_version"], True, current["stale_reason"],
                )
        except (sqlite3.Error, _CommitUncertain, InjectedFailure) as exc:
            raise DomainError("SAVE_OUTCOME_UNKNOWN", "Commit result requires later verification") from exc

    def save_draft(self, evidence: SaveEvidence, *, run_id=None) -> MutationResult:
        operation_id = _id("OP")
        result = None
        rejection = None
        try:
            with self._transaction() as connection:
                self._refresh(connection)
                try:
                    draft, status = self._validate_save(connection, evidence)
                except DomainError as exc:
                    rejection = exc
                if rejection is None:
                    self.faults.trip("save.before_write")
                    self._put_draft(connection, draft)
                    self.faults.trip("save.after_draft_write")
                    self._audit(
                        connection, "DRAFT_" + status, draft=draft,
                        run_id=run_id, data={"draft": draft_to_dict(draft), "operation_id": operation_id},
                    )
                    result = MutationResult("SAVE", status, draft, operation_id, draft.version)
                    self._receipt(connection, result)
                    self._refresh(connection)
        except _CommitUncertain:
            return self._reconcile(operation_id)
        except (sqlite3.Error, InjectedFailure) as exc:
            raise DomainError("SAVE_FAILED", "Save failed before acknowledged commit; transaction rolled back") from exc
        if rejection is not None:
            # Revalidation invalidations commit, but the rejected save creates no draft.
            raise rejection
        try:
            self.faults.trip("save.after_commit")
        except InjectedFailure:
            return self._reconcile(operation_id)
        return result

    def _validate_confirmation(self, connection, command: ConfirmationCommand):
        current = connection.execute("SELECT * FROM drafts WHERE draft_id=?", (command.draft_id,)).fetchone()
        if current is None:
            raise DomainError("STALE_DRAFT", "Draft does not exist")
        draft = self._load_draft(current)
        old = connection.execute(
            "SELECT * FROM confirmations WHERE confirmation_id=?", (command.confirmation_id,)
        ).fetchone()
        command_json = confirmation_to_dict(command)
        if old is not None:
            if old["payload_hash"] != fingerprint(command_json):
                raise DomainError("REQUEST_ID_CONFLICT", "Confirmation ID already has different content")
            if draft.state == DraftState.STALE:
                raise DomainError(current["stale_reason"] or "STALE_DRAFT", "Previously confirmed draft is no longer current")
            if (
                draft.version != old["result_version"] or draft.confirmation is None
                or draft.confirmation.confirmation_id != command.confirmation_id
            ):
                raise DomainError("STALE_DRAFT", "Historical confirmation does not authorize the current version")
            return draft, "REUSED"
        if draft.state == DraftState.STALE:
            raise DomainError(current["stale_reason"] or "STALE_DRAFT", "Draft must be replanned")
        dataset, _, _, _ = self._catalog(connection)
        offer = next((entry for entry in dataset.slot_offers if entry.offer_id == draft.proposal.candidate.offer_id), None)
        if offer is None:
            raise DomainError("STALE_DRAFT", "Candidate was withdrawn")
        confirmed = confirm_draft(
            draft, command, self._review(connection, draft.proposal.item), offer,
            self._bookings(connection, draft.request_id, exclude_draft_id=draft.draft_id),
        )
        return confirmed, "CONFIRMED"

    def confirm(self, command: ConfirmationCommand, *, run_id=None) -> MutationResult:
        operation_id = _id("OP")
        result = None
        rejection = None
        try:
            with self._transaction() as connection:
                self._refresh(connection)
                try:
                    draft, status = self._validate_confirmation(connection, command)
                except DomainError as exc:
                    rejection = exc
                if rejection is None:
                    self.faults.trip("confirm.before_write")
                    self._put_draft(connection, draft)
                    self.faults.trip("confirm.after_draft_write")
                    if status == "CONFIRMED":
                        command_json = confirmation_to_dict(command)
                        connection.execute(
                            "INSERT INTO confirmations VALUES(?,?,?,?,?,?)",
                            (
                                command.confirmation_id, fingerprint(command_json), _json(command_json),
                                draft.draft_id, draft.version, _now(),
                            ),
                        )
                    self._audit(connection, "CONFIRMATION_" + status, draft=draft, run_id=run_id, data={"confirmation": confirmation_to_dict(command)})
                    result = MutationResult("CONFIRM", status, draft, operation_id, draft.version)
                    self._receipt(connection, result)
                    self._refresh(connection)
        except _CommitUncertain:
            return self._reconcile(operation_id)
        except (sqlite3.Error, InjectedFailure) as exc:
            raise DomainError("SAVE_FAILED", "Confirmation transaction failed and rolled back") from exc
        if rejection is not None:
            raise rejection
        try:
            self.faults.trip("confirm.after_commit")
        except InjectedFailure:
            return self._reconcile(operation_id)
        return result

    def snapshot(self, request_id: str) -> dict[str, Any]:
        try:
            with self._transaction() as connection:
                self._refresh(connection)
                request = self._request(connection, request_id)
                items = []
                for item in request.items:
                    row = self._draft_row(connection, request_id, item.item_id)
                    entry = {
                        "item_id": item.item_id, "material_id": item.material_id,
                        "channel": item.channel, "time_requirement": item.time_requirement.to_dict(),
                        "draft": draft_view(self._load_draft(row), stale_reason=row["stale_reason"]) if row else None,
                    }
                    try:
                        review = self._review(connection, item)
                        entry["review"] = {
                            "review_status": review.status.value,
                            "review_snapshot_id": review.snapshot_id,
                            "review_coverage": list(review.review_coverage),
                            "findings": [finding.to_dict() for finding in review.findings],
                            "missing_fields": list(review.missing_fields),
                        }
                    except DomainError as exc:
                        if exc.code == "STORE_UNAVAILABLE":
                            raise
                        entry["review_error"] = exc.to_dict()
                    items.append(entry)
                return {"request_id": request_id, "items": items, "observed_at": _now(), "published": False}
        except (sqlite3.Error, _CommitUncertain) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Cannot inspect current ledger") from exc

    def audit_events(self, *, request_id: str | None = None) -> list[dict[str, Any]]:
        try:
            with self._transaction() as connection:
                if request_id is None:
                    rows = connection.execute("SELECT * FROM audit_events ORDER BY rowid").fetchall()
                else:
                    rows = connection.execute("SELECT * FROM audit_events WHERE request_id=? ORDER BY rowid", (request_id,)).fetchall()
                return [{**dict(row), "payload_json": json.loads(row["payload_json"])} for row in rows]
        except (sqlite3.Error, _CommitUncertain) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Cannot inspect audit") from exc

    def counts(self) -> dict[str, int]:
        try:
            with self._transaction() as connection:
                return {
                    table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                    for table in ("requests", "drafts", "reservations", "confirmations", "operation_receipts", "audit_events")
                }
        except (sqlite3.Error, _CommitUncertain) as exc:
            raise DomainError("STORE_UNAVAILABLE", "Cannot inspect ledger counts") from exc
