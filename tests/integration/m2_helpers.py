"""File-backed, isolated ledgers and actual tool calls for M2 verification."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from material_scheduler.adapters.faults import FaultInjector
from material_scheduler.adapters.sqlite_store import SQLiteStore
from material_scheduler.application.tools import ToolSession
from material_scheduler.domain.drafts import ConfirmationCommand
from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.scheduling import Booking
from tests.unit.helpers import ROOT, fixture_data, request_data


def request(request_id="REQ-TEST", material="M01", *, batch=False):
    raw = request_data()
    raw["request_id"] = request_id
    raw["items"][0]["material_id"] = material
    if batch:
        from copy import deepcopy
        other = deepcopy(raw["items"][0])
        other["item_id"] = "I02"
        raw["items"].append(other)
    return SchedulingRequest.from_dict(raw)


def occupied(dataset, hour=18):
    offer = next(offer for offer in dataset.slot_offers if offer.interval.start.hour == hour)
    return replace(dataset, existing_bookings=dataset.existing_bookings + (
        Booking(f"B{hour}", 1, offer.channel, offer.interval),
    ))


def call(session, tool, item_id="I01", **kwargs):
    arguments = {"rationale": "Verify the current tool result", **kwargs}
    if tool != "finish":
        arguments["item_id"] = item_id
    return session.execute(tool, arguments)


def observe(session, *, mode="requested", item_id="I01"):
    call(session, "check_rules", item_id)
    result = call(session, "query_slots", item_id, mode=mode, limit=10)
    return result["data"]["candidates"]


def save(session, candidate, *, item_id="I01"):
    return call(session, "save_draft", item_id, candidate_start=candidate["start"])


def command(draft, confirmation_id="C01", **changes):
    raw = {
        "confirmation_id": confirmation_id, "draft_id": draft["draft_id"],
        "expected_version": draft["version"],
        "accepted_item_ids": draft["pending_confirmations"], "actor": "local-reviewer",
        **changes,
    }
    return ConfirmationCommand.from_dict(raw)


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.base = (ROOT / "var/m2-tests").resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.temporary = TemporaryDirectory(prefix="ledger-", dir=self.base)
        self.directory = Path(self.temporary.name).resolve()
        self.assertTrue(self.directory.is_relative_to(self.base))
        self.addCleanup(self.temporary.cleanup)
        self.dataset = fixture_data()
        self.path = self.directory / "ledger.sqlite3"
        self.store = SQLiteStore(self.path)
        self.store.import_dataset(self.dataset)

    def session(self, request_id="REQ-TEST", material="M01", **kwargs):
        return ToolSession(self.store, request(request_id, material, **kwargs))

    def ready(self, **kwargs):
        session = self.session(**kwargs)
        observation = save(session, observe(session)[0])
        self.assertTrue(observation["ok"], observation)
        return session, observation["data"]

    def pending(self, request_id="REQ-TEST", material="M01"):
        if not any(booking.booking_id == "B18" for booking in self.dataset.existing_bookings):
            self.dataset = occupied(self.dataset)
        self.store.import_dataset(self.dataset)
        session = self.session(request_id, material)
        observation = save(session, observe(session, mode="alternatives")[0])
        self.assertTrue(observation["ok"], observation)
        return session, observation["data"]

    def assert_error(self, observation, code):
        self.assertFalse(observation["ok"], observation)
        self.assertEqual(observation["error"]["code"], code, observation)

    def fault(self, **points):
        self.store.faults = FaultInjector(points)
