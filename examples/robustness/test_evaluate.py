"""Evaluation-oracle regression tests, separate from 222 application methods.

Runs local tools/Mock only; never reads model credentials or contacts providers.
"""

from copy import deepcopy
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

MODULE_PATH = Path(__file__).with_name("evaluate.py")
spec = importlib.util.spec_from_file_location("robustness_evaluator", MODULE_PATH)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.base = evaluation.load_fixture_set(cls.root / "data")
        cls.spec = evaluation.read(MODULE_PATH.with_name("spec.json"))

    def setUp(self):
        base = self.root / "var/robustness-oracle-tests"
        base.mkdir(parents=True, exist_ok=True)
        temporary = TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def sample(self, family_name="normal"):
        family = next(f for f in self.spec["families"] if f["id"] == family_name)
        variant, phase = self.spec["variants"][0], family["phases"][0]
        dataset, raw, faults = evaluation.fixture(self.base, variant, family_name)
        store = evaluation.SQLiteStore(self.directory / "ledger.sqlite3", faults=evaluation.FaultInjector(faults))
        store.import_dataset(dataset)
        payload = {"request": raw, "variant": variant}
        result = evaluation.run_request(store, evaluation.SchedulingRequest.from_dict(raw), evaluation.ObservationMock(), self.directory / "run")
        events = [e["event"] for e in evaluation.verify_trace(self.directory / "run/trace.jsonl")]
        return result, evaluation.ledger(store.path), events, payload, phase

    def test_shifted_variants_change_actual_schedule_input(self):
        starts = []
        for variant in self.spec["variants"]:
            dataset, raw, _ = evaluation.fixture(self.base, variant, "conflict")
            start = raw["items"][0]["time_requirement"]["requested_start"]
            starts.append(start)
            self.assertEqual(dataset.existing_bookings[0].interval, dataset.slot_offers[0].interval)
            self.assertEqual(dataset.slot_offers[0].interval.start.isoformat(), start)
        self.assertEqual(len(set(starts)), 3)

    def test_oracle_accepts_actual_normal_sql_facts(self):
        assessment = evaluation.assess(*self.sample())
        self.assertTrue(assessment["passed"], assessment)

    def test_fake_saved_result_is_rejected_against_sql(self):
        result, facts, events, payload, phase = self.sample()
        facts["drafts"] = []
        assessment = evaluation.assess(result, facts, events, payload, phase)
        self.assertFalse(assessment["passed"])
        self.assertEqual(assessment["violations"]["false_save_success"], 1)

    def test_changed_hard_time_cannot_be_ready_without_consent(self):
        result, facts, events, payload, phase = self.sample("conflict")
        result["items"][0]["draft"]["draft_state"] = "READY"
        result["items"][0]["draft"]["pending_confirmations"] = []
        assessment = evaluation.assess(result, facts, events, payload, phase)
        self.assertEqual(assessment["violations"]["unauthorized_confirmation"], 1)
        self.assertFalse(assessment["passed"])

    def test_manual_risk_cannot_be_ready_without_consent(self):
        result, facts, events, payload, phase = self.sample("manual-risk")
        result["items"][0]["draft"]["draft_state"] = "READY"
        result["items"][0]["draft"]["pending_confirmations"] = []
        assessment = evaluation.assess(result, facts, events, payload, phase)
        self.assertEqual(assessment["violations"]["unauthorized_confirmation"], 1)

    def test_native_receipt_order_must_match_actual_actions(self):
        events = [e["event"] for e in evaluation.verify_trace(self.root / "examples/final-acceptance/real/normal/run/trace.jsonl")]
        self.assertTrue(evaluation.native_receipts_match(events))
        forged = deepcopy(events)
        next(e for e in forged if e["type"] == "provider_response_metadata")["metadata"]["selected_tool"] = "finish"
        self.assertFalse(evaluation.native_receipts_match(forged))

    def test_safe_failure_is_not_counted_as_business_completion(self):
        rows = [{"passed": True, "actual_state": "READY_DRAFTS"}, {"passed": True, "actual_state": "FAILED"},
                {"passed": False, "evaluation_error": "ExampleError"}]
        metrics = evaluation.aggregate(rows)
        self.assertEqual(metrics["runs"], 3)
        self.assertEqual(metrics["expected_outcome_rate"], 2 / 3)
        self.assertEqual(metrics["ready_draft_rate"], 1 / 3)
        self.assertEqual(metrics["evaluation_errors"], 1)

    def test_changed_rule_blocks_previously_safe_copy(self):
        dataset, raw, _ = evaluation.fixture(self.base, self.spec["variants"][0], "changed-rule")
        self.assertEqual(raw["items"][0]["material_id"], "M01")
        self.assertIn("字幕", next(r for r in dataset.rule_set.rules if r.rule_id == "R-CLAIM-001").values)
        self.assertNotEqual(dataset.rule_set.version, self.base.rule_set.version)


if __name__ == "__main__":
    unittest.main()
