"""Tool boundaries, live evidence, persistent consent and source changes."""

from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import sqlite3

from material_scheduler.adapters.faults import FaultInjector
from material_scheduler.adapters.fixture_loader import FixtureSet
from material_scheduler.adapters.sqlite_store import SQLiteStore, fixture_to_dict
from material_scheduler.application.tools import ToolSession
from material_scheduler.domain.catalog import MetadataSupplement
from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.validation import DomainError
from tests.integration.m2_helpers import LedgerTest, call, command, observe, occupied, request, save


class SQLiteToolsTests(LedgerTest):
    def test_normal_persists_and_restarts(self):
        session, draft = self.ready()
        self.assertEqual(draft["draft_state"], "READY")
        self.assertFalse(draft["published"])
        self.assertEqual(session.result()["task_status"], "READY_DRAFTS")
        restarted = SQLiteStore(self.path)
        self.assertEqual(restarted.snapshot(session.request.request_id)["items"][0]["draft"]["draft_id"], draft["draft_id"])
        self.assertEqual(restarted.counts()["reservations"], 1)

    def test_missing_material_and_metadata_block_save(self):
        for material, code in [("M02", "METADATA_MISSING"), ("MISSING", "MATERIAL_NOT_FOUND")]:
            with self.subTest(material=material):
                session = self.session("REQ-" + material, material)
                read = call(session, "read_material")
                self.assertTrue(read["ok"])
                candidates = observe(session)
                saved = save(session, candidates[0])
                self.assert_error(saved, code if material == "M02" else "STALE_REVIEW")
                self.assertEqual(self.store.counts()["drafts"], 0)

    def test_blocking_risks_cannot_be_saved(self):
        for material in ("M03", "M05"):
            session = self.session("REQ-" + material, material)
            candidates = observe(session)
            self.assert_error(save(session, candidates[0]), "REVIEW_BLOCKED")
            self.assertEqual(self.store.counts()["reservations"], 0)

    def test_conflict_alternative_requires_explicit_current_consent(self):
        session, draft = self.pending()
        self.assertEqual(draft["draft_state"], "PENDING_CONFIRMATION")
        self.assertEqual(draft["pending_confirmations"], ["TIME_CHANGE"])
        self.assertIn("18:00", draft["requested_start"])
        self.assertIn("19:00", draft["candidate"]["start"])
        self.assertEqual(self.store.counts()["reservations"], 0)
        with self.assertRaises(DomainError) as error:
            self.store.confirm(command(draft, accepted_item_ids=[]))
        self.assertEqual(error.exception.code, "CONFIRMATION_INCOMPLETE")
        result = self.store.confirm(command(draft))
        self.assertEqual(result.draft.state.value, "READY")
        self.assertEqual(result.draft.version, draft["version"] + 1)
        self.assertEqual(self.store.counts()["reservations"], 1)
        self.assertEqual(session.result()["task_status"], "READY_DRAFTS")

    def test_manual_risk_persists_after_consent(self):
        session = self.session(material="M04")
        draft = save(session, observe(session)[0])["data"]
        self.assertEqual(draft["draft_state"], "PENDING_CONFIRMATION")
        self.assertEqual(draft["pending_confirmations"], ["RISK:R-MEDICAL-001"])
        confirmed = self.store.confirm(command(draft)).to_dict()
        self.assertEqual(confirmed["review_status"], "NEEDS_REVIEW")
        self.assertEqual(confirmed["draft_state"], "READY")

    def test_duplicate_save_reuses_one_draft_across_sessions(self):
        session, first = self.ready()
        again = self.session()
        second = save(again, observe(again)[0])["data"]
        self.assertEqual(second["save_status"], "REUSED")
        self.assertEqual((second["draft_id"], second["version"]), (first["draft_id"], first["version"]))
        self.assertEqual(self.store.counts()["drafts"], 1)
        self.assertEqual(self.store.counts()["reservations"], 1)

    def test_changed_payload_same_identity_is_rejected(self):
        self.session()
        with self.assertRaises(DomainError) as error:
            self.session(material="M02")
        self.assertEqual(error.exception.code, "REQUEST_ID_CONFLICT")
        self.assertEqual(self.store.counts()["requests"], 1)

    def test_model_cannot_forge_tool_authority_or_consent(self):
        session = self.session()
        target = {"start": "2030-06-01T18:00:00+08:00"}
        self.assert_error(save(session, target), "STALE_REVIEW")
        call(session, "check_rules")
        self.assert_error(save(session, target), "CANDIDATE_NOT_OBSERVED")
        candidate = observe(session)[0]
        forged = call(session, "save_draft", candidate_start=candidate["start"], approved=True)
        self.assert_error(forged, "INVALID_ARGUMENTS")
        self.assert_error(call(session, "confirm"), "INVALID_ACTION")
        self.assert_error(call(session, "publish"), "INVALID_ACTION")
        self.assert_error(call(session, "read_material", "OUTSIDE"), "ACTION_NOT_ALLOWED")
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_changed_source_invalidates_observed_review(self):
        session = self.session()
        candidate = observe(session)[0]
        material = replace(self.dataset.materials[0], copy_text="已更新的文案", revision=2)
        self.store.import_dataset(replace(self.dataset, materials=(material,) + self.dataset.materials[1:]))
        self.assert_error(save(session, candidate), "STALE_REVIEW")
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_changed_offer_invalidates_observed_candidate(self):
        session = self.session()
        candidate = observe(session)[0]
        offers = tuple(replace(offer, revision=2) if offer.offer_id == candidate["offer_id"] else offer for offer in self.dataset.slot_offers)
        self.store.import_dataset(replace(self.dataset, slot_offers=offers))
        self.assert_error(save(session, candidate), "CANDIDATE_NOT_OBSERVED")

    def test_new_occupancy_rechecked_at_save(self):
        session = self.session()
        candidate = observe(session)[0]
        self.store.import_dataset(occupied(self.dataset))
        self.assert_error(save(session, candidate), "SLOT_CONFLICT")
        self.assertEqual(self.store.counts()["reservations"], 0)

    def test_source_change_invalidates_ready_and_releases_capacity(self):
        session, draft = self.ready()
        updated = replace(self.dataset.materials[0], revision=2)
        imported = self.store.import_dataset(replace(self.dataset, materials=(updated,) + self.dataset.materials[1:]))
        self.assertEqual(imported["invalidated"], [draft["draft_id"]])
        current = session.result()["items"][0]["draft"]
        self.assertEqual(current["draft_state"], "STALE")
        self.assertGreater(current["version"], draft["version"])
        self.assertEqual(self.store.counts()["reservations"], 0)
        self.assertIn("DRAFT_INVALIDATED", [event["event_type"] for event in self.store.audit_events()])
        self.assertFalse(session.result()["items"][0]["review_observed_in_session"])

    def test_unrelated_occupancy_does_not_invalidate(self):
        session, draft = self.ready()
        self.store.import_dataset(occupied(self.dataset, 20))
        self.assertEqual(session.result()["items"][0]["draft"]["version"], draft["version"])

    def test_replan_reuses_id_but_discards_historical_consent(self):
        session, draft = self.pending()
        old_command = command(draft)
        confirmed = self.store.confirm(old_command).to_dict()
        self.dataset = occupied(self.dataset, 19)
        self.store.import_dataset(self.dataset)
        updated = save(session, observe(session, mode="alternatives")[0])["data"]
        self.assertEqual(updated["draft_id"], draft["draft_id"])
        self.assertGreater(updated["version"], confirmed["version"])
        self.assertEqual(updated["draft_state"], "PENDING_CONFIRMATION")
        self.assertIsNone(updated["confirmation"])
        with self.assertRaises(DomainError) as error:
            self.store.confirm(old_command)
        self.assertEqual(error.exception.code, "STALE_DRAFT")

    def test_confirmation_identity_duplicate_and_conflict(self):
        _, draft = self.pending()
        consent = command(draft)
        first = self.store.confirm(consent)
        duplicate = self.store.confirm(consent)
        self.assertEqual(duplicate.status, "REUSED")
        self.assertEqual(duplicate.draft.version, first.draft.version)
        with self.assertRaises(DomainError) as error:
            self.store.confirm(replace(consent, actor="other-reviewer"))
        self.assertEqual(error.exception.code, "REQUEST_ID_CONFLICT")
        self.assertEqual(self.store.counts()["confirmations"], 1)

    def test_wrong_version_cannot_confirm(self):
        _, draft = self.pending()
        with self.assertRaises(DomainError) as error:
            self.store.confirm(command(draft, expected_version=draft["version"] + 1))
        self.assertEqual(error.exception.code, "DRAFT_VERSION_CONFLICT")
        self.assertEqual(self.store.counts()["reservations"], 0)

    def test_changed_occupancy_blocks_confirmation_and_commits_invalidation(self):
        session, draft = self.pending()
        self.dataset = occupied(self.dataset, 19)
        self.store.import_dataset(self.dataset)
        with self.assertRaises(DomainError) as error:
            self.store.confirm(command(draft))
        self.assertEqual(error.exception.code, "SLOT_CONFLICT")
        self.assertEqual(session.result()["items"][0]["draft"]["draft_state"], "STALE")
        self.assertEqual(self.store.counts()["reservations"], 0)

    def test_supplement_fills_missing_only_and_preserves_provenance(self):
        supplement = MetadataSupplement("S02", "M02", 1, (("rights_status", "licensed"),), "synthetic rights register")
        self.dataset = replace(self.dataset, supplements=(supplement,))
        self.store.import_dataset(self.dataset)
        session = self.session(material="M02")
        old_candidate = observe(session)[0]
        result = call(session, "lookup_metadata")["data"]
        self.assertEqual(result["applied_fields"], ["rights_status"])
        self.assertEqual(result["revision"], 2)
        self.assertEqual(result["field_sources"]["rights_status"][0]["source_id"], "S02")
        self.assert_error(save(session, old_candidate), "STALE_REVIEW")
        self.assertEqual(call(session, "lookup_metadata")["data"]["revision"], 2)
        self.assertTrue(save(session, observe(session)[0])["ok"])
        self.assertEqual(self.store.counts()["drafts"], 1)

    def test_source_conflict_blocks_even_when_lookup_skipped(self):
        supplement = MetadataSupplement("S01", "M01", 1, (("rights_status", "disputed"),), "synthetic dispute source")
        self.store.import_dataset(replace(self.dataset, supplements=(supplement,)))
        session = self.session()
        self.assert_error(call(session, "check_rules"), "SOURCE_CONFLICT")
        read = call(session, "read_material")["data"]
        self.assertTrue(read["source_conflicts"])
        original = read["material"]["rights_status"]
        self.assertEqual(call(session, "lookup_metadata")["data"]["applied_fields"], [])
        self.assertEqual(call(session, "read_material")["data"]["material"]["rights_status"], original)
        self.assertEqual(session.result()["task_status"], "NEEDS_INPUT")
        self.store.import_dataset(self.dataset)
        self.assertTrue(save(session, observe(session)[0])["ok"])

    def test_conflicting_supplements_leave_missing_field_unresolved(self):
        supplements = tuple(MetadataSupplement(sid, "M02", 1, (("rights_status", value),), "synthetic") for sid, value in [("S-A", "licensed"), ("S-B", "disputed")])
        self.store.import_dataset(replace(self.dataset, supplements=supplements))
        session = self.session(material="M02")
        lookup = call(session, "lookup_metadata")["data"]
        self.assertEqual(lookup["applied_fields"], [])
        self.assertIn("rights_status", lookup["remaining_missing"])
        self.assert_error(call(session, "check_rules"), "SOURCE_CONFLICT")

    def test_invalid_import_preserves_current_ledger(self):
        before = self.store.counts()
        raw = fixture_to_dict(self.dataset)
        raw["materials"].append(deepcopy(raw["materials"][0]))
        with self.assertRaises(DomainError):
            self.store.import_dataset(FixtureSet.from_dict(raw))
        self.assertEqual(self.store.counts(), before)

    def test_pending_same_batch_avoids_collision(self):
        self.store.import_dataset(occupied(self.dataset))
        session = self.session(batch=True)
        first = save(session, observe(session, mode="alternatives")[0])["data"]
        second = save(session, observe(session, mode="alternatives", item_id="I02")[0], item_id="I02")["data"]
        self.assertNotEqual(first["candidate"]["start"], second["candidate"]["start"])
        self.assertEqual(self.store.counts()["drafts"], 2)
        self.assertEqual(self.store.counts()["reservations"], 0)

    def test_schedule_fingerprint_includes_other_local_reservations(self):
        observer = self.session("REQ-OBSERVER")
        before = call(observer, "query_slots", mode="requested", limit=10)["data"]["schedule_revision"]
        self.ready(request_id="REQ-SAVER")
        after = call(observer, "query_slots", mode="requested", limit=10)["data"]["schedule_revision"]
        self.assertNotEqual(before, after)

    def test_end_result_revalidates_without_claiming_tool_observation(self):
        session = self.session()
        result = session.result()
        self.assertEqual(result["task_status"], "INCOMPLETE")
        self.assertFalse(result["items"][0]["review_observed_in_session"])
        self.assertEqual(result["items"][0]["save_attempt"]["save_status"], "NOT_ATTEMPTED")
        self.assertEqual(session.records, [])
        call(session, "finish")
        self.assert_error(call(session, "read_material"), "ACTION_NOT_ALLOWED")

    def test_failed_current_attempt_not_masked_by_old_ready_draft(self):
        session, _ = self.ready()
        self.assert_error(call(session, "save_draft", candidate_start="invalid"), "INVALID_ARGUMENTS")
        result = session.result()
        self.assertEqual(result["items"][0]["draft"]["draft_state"], "READY")
        self.assertEqual(result["items"][0]["save_attempt"]["save_status"], "FAILED")
        self.assertNotEqual(result["task_status"], "READY_DRAFTS")

    def test_corrupt_draft_fails_closed(self):
        session, _ = self.ready()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE drafts SET payload_json='{}'")
            connection.commit()
        self.assertEqual(session.result()["error"]["code"], "STORE_UNAVAILABLE")


class SQLiteFailureTests(LedgerTest):
    def test_save_precommit_faults_roll_back_all_effects(self):
        session = self.session()
        candidate = observe(session)[0]
        before = self.store.counts()
        for point in ("save.before_write", "save.after_draft_write"):
            with self.subTest(point=point):
                self.store.faults = FaultInjector({point: 1})
                self.assert_error(save(session, candidate), "SAVE_FAILED")
                self.assertEqual(self.store.counts(), before)
                self.assertEqual(session.result()["task_status"], "FAILED")
        self.assertTrue(save(session, candidate)["ok"])

    def test_save_acknowledgement_loss_reconciles_exact_receipt(self):
        session = self.session()
        candidate = observe(session)[0]
        self.store.faults = FaultInjector({"save.after_commit": 1})
        result = save(session, candidate)["data"]
        self.assertTrue(result["reconciled"])
        self.assertEqual(result["save_status"], "CREATED")
        self.assertEqual(self.store.counts()["drafts"], 1)
        self.assertEqual(self.store.counts()["operation_receipts"], 1)

    def test_unknown_commit_is_not_false_success_and_retry_is_idempotent(self):
        session = self.session()
        candidate = observe(session)[0]
        self.store.faults = FaultInjector({"save.after_commit": 1, "receipt.read": 1})
        self.assert_error(save(session, candidate), "SAVE_OUTCOME_UNKNOWN")
        result = session.result()
        self.assertEqual(result["items"][0]["save_attempt"]["save_status"], "UNKNOWN")
        self.assertNotEqual(result["task_status"], "READY_DRAFTS")
        self.assertEqual(self.store.counts()["drafts"], 1)
        self.assertEqual(save(session, candidate)["data"]["save_status"], "REUSED")
        self.assertEqual(self.store.counts()["drafts"], 1)

    def test_failed_repeat_write_preserves_old_draft(self):
        session, first = self.ready()
        self.store.faults = FaultInjector({"save.after_draft_write": 1})
        self.assert_error(save(session, observe(session)[0]), "SAVE_FAILED")
        current = session.result()["items"][0]["draft"]
        self.assertEqual((current["draft_id"], current["version"]), (first["draft_id"], first["version"]))
        self.assertEqual(self.store.counts()["reservations"], 1)

    def test_confirmation_fault_rolls_back_and_retry_succeeds(self):
        session, draft = self.pending()
        before = self.store.counts()
        self.store.faults = FaultInjector({"confirm.after_draft_write": 1})
        with self.assertRaises(DomainError) as error:
            self.store.confirm(command(draft))
        self.assertEqual(error.exception.code, "SAVE_FAILED")
        self.assertEqual(self.store.counts(), before)
        self.assertEqual(session.result()["items"][0]["draft"]["version"], draft["version"])
        self.assertEqual(self.store.confirm(command(draft)).status, "CONFIRMED")

    def test_confirmation_acknowledgement_loss_reconciles(self):
        _, draft = self.pending()
        self.store.faults = FaultInjector({"confirm.after_commit": 1})
        result = self.store.confirm(command(draft))
        self.assertTrue(result.reconciled)
        self.assertEqual(self.store.counts()["confirmations"], 1)

    def test_tool_failures_are_actual_error_observations(self):
        session = self.session()
        for tool in ("read_material", "lookup_metadata", "check_rules", "query_slots"):
            with self.subTest(tool=tool):
                self.store.faults = FaultInjector({tool: 1})
                kwargs = {"mode": "requested", "limit": 10} if tool == "query_slots" else {}
                self.assert_error(call(session, tool, **kwargs), "TOOL_UNAVAILABLE")
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_busy_database_returns_failure_without_partial_write(self):
        session = self.session()
        candidate = observe(session)[0]
        self.store.busy_timeout_ms = 25
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.assert_error(save(session, candidate), "SAVE_FAILED")
            connection.rollback()
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_database_trigger_rejects_pending_reservation(self):
        _, draft = self.pending()
        with closing(sqlite3.connect(self.path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO reservations VALUES(?,?,?,?)", (draft["draft_id"], "douyin", "2030-06-01T11:00:00+00:00", "2030-06-01T11:30:00+00:00"))
            connection.rollback()
        self.assertEqual(self.store.counts()["reservations"], 0)
