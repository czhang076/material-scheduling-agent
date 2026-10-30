"""Real threads synchronize after observation, before competing transactions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import sqlite3
from threading import Barrier

from material_scheduler.adapters.sqlite_store import SQLiteStore
from material_scheduler.application.tools import ToolSession
from material_scheduler.domain.validation import DomainError
from tests.integration.m2_helpers import LedgerTest, call, command, observe, request, save


class SQLiteConcurrencyTests(LedgerTest):
    def test_different_requests_compete_for_same_slot(self):
        sessions = [self.session("REQ-A"), self.session("REQ-B")]
        candidates = [observe(session)[0] for session in sessions]
        barrier = Barrier(2)

        def execute(index):
            barrier.wait(timeout=10)
            return save(sessions[index], candidates[index])

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(execute, range(2)))
        self.assertEqual(sum(result["ok"] for result in results), 1)
        rejected = next(result for result in results if not result["ok"])
        self.assert_error(rejected, "SLOT_CONFLICT")
        self.assertEqual(self.store.counts()["drafts"], 1)
        self.assertEqual(self.store.counts()["reservations"], 1)

    def test_same_request_competing_retries_create_only_one_draft(self):
        sessions = [self.session(), self.session()]
        candidates = [observe(session)[0] for session in sessions]
        barrier = Barrier(2)

        def execute(index):
            barrier.wait(timeout=10)
            return save(sessions[index], candidates[index])

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(execute, range(2)))
        self.assertTrue(all(result["ok"] for result in results), results)
        self.assertEqual({result["data"]["save_status"] for result in results}, {"CREATED", "REUSED"})
        self.assertEqual(len({result["data"]["draft_id"] for result in results}), 1)
        self.assertEqual(self.store.counts()["drafts"], 1)

    def test_two_pending_proposals_compete_when_confirmed(self):
        _, first = self.pending("REQ-A")
        _, second = self.pending("REQ-B")
        self.assertEqual(first["candidate"], second["candidate"])
        self.assertEqual(self.store.counts()["reservations"], 0)
        barrier = Barrier(2)
        commands = [command(first, "C-A"), command(second, "C-B")]

        def execute(index):
            barrier.wait(timeout=10)
            try:
                return self.store.confirm(commands[index]).status
            except DomainError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(execute, range(2)))
        self.assertEqual(sorted(results), ["CONFIRMED", "SLOT_CONFLICT"])
        self.assertEqual(self.store.counts()["reservations"], 1)
        self.assertEqual(self.store.counts()["confirmations"], 1)

    def test_overlap_trigger_is_independent_of_application_precheck(self):
        _, first = self.ready(request_id="REQ-A")
        other = self.session("REQ-B")
        second = save(other, observe(other, mode="alternatives")[0])["data"]
        second = self.store.confirm(command(second)).to_dict()
        with closing(sqlite3.connect(self.path)) as connection:
            # Make draft columns match an attempted reservation, to reach the
            # overlap trigger independently of its READY/payload guard.
            connection.execute(
                "UPDATE drafts SET start_utc=(SELECT start_utc FROM drafts WHERE draft_id=?),"
                "end_utc=(SELECT end_utc FROM drafts WHERE draft_id=?) WHERE draft_id=?",
                (first["draft_id"], first["draft_id"], second["draft_id"]),
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "reservation_overlap"):
                connection.execute(
                    "UPDATE reservations SET start_utc=(SELECT start_utc FROM drafts WHERE draft_id=?),"
                    "end_utc=(SELECT end_utc FROM drafts WHERE draft_id=?) WHERE draft_id=?",
                    (first["draft_id"], first["draft_id"], second["draft_id"]),
                )
            connection.rollback()
        self.assertEqual(self.store.counts()["reservations"], 2)

    def test_new_reservation_changes_availability_on_another_connection(self):
        observer = self.session("REQ-OBSERVER")
        self.assertTrue(call(observer, "query_slots", mode="requested", limit=10)["data"]["requested_available"])
        independent = SQLiteStore(self.path)
        writer = ToolSession(independent, request("REQ-WRITER"))
        self.assertTrue(save(writer, observe(writer)[0])["ok"])
        current = call(observer, "query_slots", mode="requested", limit=10)["data"]
        self.assertFalse(current["requested_available"])
        self.assertEqual(current["candidates"], [])

    def test_rule_change_invalidates_existing_approval(self):
        session, draft = self.pending()
        consent = command(draft)
        self.store.confirm(consent)
        rules = replace(self.dataset.rule_set, version="2.0")
        self.store.import_dataset(replace(self.dataset, rule_set=rules))
        current = session.result()["items"][0]["draft"]
        self.assertEqual(current["draft_state"], "STALE")
        self.assertEqual(self.store.counts()["reservations"], 0)
        with self.assertRaises(DomainError):
            self.store.confirm(consent)

    def test_confirmed_duplicate_save_keeps_valid_approval(self):
        session, draft = self.pending()
        approved = self.store.confirm(command(draft)).to_dict()
        repeated = save(session, observe(session, mode="alternatives")[0])["data"]
        self.assertEqual(repeated["save_status"], "REUSED")
        self.assertEqual(repeated["version"], approved["version"])
        self.assertEqual(repeated["confirmation"], approved["confirmation"])

    def test_stale_record_can_be_read_after_restart(self):
        session, _ = self.ready()
        self.store.import_dataset(replace(self.dataset, slot_offers=()))
        restarted = SQLiteStore(self.path)
        current = restarted.snapshot(session.request.request_id)["items"][0]["draft"]
        self.assertEqual(current["draft_state"], "STALE")
        self.assertEqual(restarted.counts()["reservations"], 0)
