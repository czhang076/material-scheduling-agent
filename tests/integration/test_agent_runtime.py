"""Actual bounded loop, history feedback, timeouts and Trace failures."""

from dataclasses import replace
import json
from unittest.mock import patch

from material_scheduler.adapters.faults import FaultInjector
from material_scheduler.adapters.mock_model import ObservationMock
from material_scheduler.agent.decisions import Action
from material_scheduler.agent.runner import AgentRunner
from material_scheduler.domain.budgets import ExecutionLimits
from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.validation import DomainError
from tests.integration.m2_helpers import LedgerTest, occupied
from tests.integration.m3_helpers import FakeClock, FaultTrace, ScriptedModel, action


class AgentRuntimeTests(LedgerTest):
    def run_mock(self, session=None, **kwargs):
        return AgentRunner(session or self.session(), ObservationMock(), **kwargs).run()

    def test_normal_mock_uses_actual_observation_history(self):
        class CapturingMock(ObservationMock):
            def __init__(self):
                self.inputs = []
            def choose(self, context, **kwargs):
                self.inputs.append(context)
                return super().choose(context, **kwargs)
        model = CapturingMock()
        runner = AgentRunner(self.session(), model)
        result = runner.run()
        self.assertEqual(result["task_status"], "READY_DRAFTS")
        self.assertEqual(result["stats"]["tool_attempts"], 5)
        self.assertEqual([entry["action"]["tool"] for entry in runner.history], ["read_material", "check_rules", "query_slots", "save_draft", "finish"])
        self.assertEqual(model.inputs[1].history[-1]["observation"]["data"]["material"]["material_id"], "M01")
        self.assertFalse(result["react_verified_with_real_model"])

    def test_conflict_changes_the_next_selected_action(self):
        self.store.import_dataset(occupied(self.dataset))
        runner = AgentRunner(self.session(), ObservationMock())
        result = runner.run()
        queries = [entry for entry in runner.history if entry["action"]["tool"] == "query_slots"]
        self.assertEqual([entry["action"]["arguments"]["mode"] for entry in queries], ["requested", "alternatives"])
        self.assertFalse(queries[0]["observation"]["data"]["requested_available"])
        self.assertEqual(result["task_status"], "NEEDS_CONFIRMATION")
        self.assertIn("19:00", result["items"][0]["draft"]["candidate"]["start"])

    def test_save_race_is_observed_then_replanned(self):
        store, dataset = self.store, self.dataset
        class RacingMock(ObservationMock):
            injected = False
            def choose(self, context, **kwargs):
                response = super().choose(context, **kwargs)
                if json.loads(response)["tool"] == "save_draft" and not self.injected:
                    self.injected = True
                    store.import_dataset(occupied(dataset))
                return response
        runner = AgentRunner(self.session(), RacingMock())
        result = runner.run()
        failures = [entry["observation"]["error"]["code"] for entry in runner.history if not entry["observation"]["ok"]]
        self.assertIn("SLOT_CONFLICT", failures)
        self.assertEqual(result["task_status"], "NEEDS_CONFIRMATION")
        self.assertEqual(self.store.counts()["drafts"], 1)

    def test_missing_metadata_supplement_attempt_preserves_gap(self):
        result = self.run_mock(self.session(material="M02"))
        self.assertEqual(result["task_status"], "NEEDS_INPUT")
        self.assertEqual(self.store.counts()["drafts"], 0)
        self.assertIn("rights_status", result["items"][0]["review"]["missing_fields"])

    def test_blocking_risk_stops_without_save(self):
        result = self.run_mock(self.session(material="M03"))
        self.assertEqual(result["task_status"], "BLOCKED")
        self.assertEqual(result["stats"]["tool_attempts"], 3)
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_one_transient_failure_is_seen_and_retried_once(self):
        self.store.faults = FaultInjector({"read_material": 1})
        runner = AgentRunner(self.session(), ObservationMock())
        result = runner.run()
        self.assertEqual(result["task_status"], "READY_DRAFTS")
        self.assertFalse(runner.history[0]["observation"]["ok"])
        self.assertTrue(runner.history[1]["observation"]["ok"])
        self.assertEqual(result["stats"]["tool_attempts"], 6)

    def test_persistent_save_failure_is_never_success(self):
        self.store.faults = FaultInjector({"save.after_draft_write": 2})
        result = self.run_mock()
        self.assertEqual(result["task_status"], "FAILED")
        self.assertEqual(result["items"][0]["save_attempt"]["save_status"], "FAILED")
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_total_tool_budget_stops_before_dispatch(self):
        limits = replace(ExecutionLimits.for_items(1), max_tool_attempts=3, max_model_rounds=7)
        result = self.run_mock(limits=limits)
        self.assertEqual((result["stop_reason"], result["limit_kind"]), ("LIMIT_REACHED", "TOOL_ATTEMPTS"))
        self.assertEqual(result["stats"]["tool_attempts"], 3)
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_per_item_exhaustion_still_allows_other_items(self):
        session = self.session(batch=True)
        actions = [action("read_material")] * 5 + [action("read_material", "I02"), action("check_rules", "I02"),
            action("query_slots", "I02", mode="requested", limit=10),
            action("save_draft", "I02", candidate_start="2030-06-01T18:00:00+08:00"), action("finish")]
        limits = replace(ExecutionLimits.for_items(2), per_item_tool_limit=4)
        result = AgentRunner(session, ScriptedModel(actions), limits=limits).run()
        self.assertEqual(result["stats"]["per_item_attempts"], {"I01": 4, "I02": 4})
        self.assertEqual(result["items"][1]["draft"]["draft_state"], "READY")
        self.assertIn("ITEM_LIMIT_REACHED", result["items"][0]["incomplete_reasons"])
        self.assertEqual(result["task_status"], "INCOMPLETE")

    def test_mock_finishing_at_item_limit_marks_unfinished(self):
        limits = replace(ExecutionLimits.for_items(1), per_item_tool_limit=2)
        result = self.run_mock(limits=limits)
        self.assertIn("ITEM_LIMIT_REACHED", result["items"][0]["incomplete_reasons"])
        self.assertEqual(result["execution_status"], "INCOMPLETE")

    def test_model_protocol_errors_are_bounded_and_repairable(self):
        model = ScriptedModel(["not JSON", action("finish")])
        result = AgentRunner(self.session(), model).run()
        self.assertEqual(result["stats"]["protocol_errors"], 1)
        self.assertEqual(model.contexts[1].history[-1]["error"]["code"], "MODEL_PROTOCOL_ERROR")
        self.assertEqual(result["task_status"], "INCOMPLETE")

    def test_four_protocol_errors_stop_without_any_tool(self):
        result = AgentRunner(self.session(), ScriptedModel(["bad"] * 4)).run()
        self.assertEqual(result["stop_reason"], "MODEL_PROTOCOL_ERROR")
        self.assertEqual(result["stats"]["model_rounds"], 4)
        self.assertEqual(result["stats"]["tool_attempts"], 0)

    def test_model_round_budget_covers_parse_failures(self):
        limits = replace(ExecutionLimits.for_items(1), max_tool_attempts=1, max_model_rounds=2)
        result = AgentRunner(self.session(), ScriptedModel(["bad"] * 3), limits=limits).run()
        self.assertEqual(result["limit_kind"], "MODEL_ROUNDS")
        self.assertEqual(result["stats"]["model_rounds"], 2)

    def test_provider_failure_has_one_retry_and_no_silent_mock(self):
        model = ScriptedModel([OSError("private provider details")] * 2)
        runner = AgentRunner(self.session(), model)
        result = runner.run()
        self.assertEqual(result["stop_reason"], "MODEL_UNAVAILABLE")
        self.assertEqual(result["stats"]["model_rounds"], 2)
        self.assertNotIn("private provider", json.dumps(runner.history))
        self.assertEqual(result["model"]["mode"], "test")

    def test_late_model_response_is_discarded(self):
        clock = FakeClock()
        def late(context):
            clock.advance(31)
            return action("read_material")
        model = ScriptedModel([late])
        result = AgentRunner(self.session(), model, clock=clock).run()
        self.assertEqual(result["stop_reason"], "MODEL_TIMEOUT")
        self.assertEqual(result["stats"]["tool_dispatches"], 0)
        self.assertEqual(model.timeouts, [30])

    def test_total_deadline_is_checked_after_model_before_tool(self):
        clock = FakeClock()
        def late(context):
            clock.advance(2)
            return action("read_material")
        limits = replace(ExecutionLimits.for_items(1), run_timeout_seconds=1, model_timeout_seconds=1)
        result = AgentRunner(self.session(), ScriptedModel([late]), clock=clock, limits=limits).run()
        self.assertEqual((result["stop_reason"], result["limit_kind"]), ("LIMIT_REACHED", "RUN_TIMEOUT"))
        self.assertEqual(result["stats"]["tool_dispatches"], 0)

    def test_cancellation_preserves_existing_saved_draft(self):
        session, _ = self.ready()
        result = AgentRunner(session, ObservationMock(), cancelled=lambda: True).run()
        self.assertEqual(result["stop_reason"], "CANCELLED")
        self.assertEqual(result["items"][0]["draft"]["draft_state"], "READY")
        self.assertEqual(result["stats"]["model_rounds"], 0)

    def test_trace_failure_before_save_prevents_write(self):
        session = self.session()
        trace = FaultTrace(session.run_id, "tool_attempt", "save_draft")
        result = AgentRunner(session, ObservationMock(), trace=trace).run()
        self.assertEqual(result["stop_reason"], "TRACE_UNAVAILABLE")
        self.assertFalse(result["trace_complete"])
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_trace_failure_after_save_preserves_actual_commit(self):
        session = self.session()
        trace = FaultTrace(session.run_id, "tool_observation", "save_draft")
        result = AgentRunner(session, ObservationMock(), trace=trace).run()
        self.assertEqual(result["stop_reason"], "TRACE_UNAVAILABLE")
        self.assertEqual(result["business_task_status"], "READY_DRAFTS")
        self.assertEqual(result["items"][0]["save_attempt"]["save_status"], "CREATED")
        self.assertEqual(self.store.counts()["drafts"], 1)
        self.assertFalse(result["trace_complete"])

    def test_trace_start_failure_dispatches_no_model_or_tool(self):
        session = self.session()
        result = AgentRunner(session, ObservationMock(), trace=FaultTrace(session.run_id, "run_started")).run()
        self.assertEqual(result["stats"]["model_rounds"], 0)
        self.assertEqual(result["stats"]["tool_dispatches"], 0)

    def test_runner_is_single_use_and_cannot_increase_limits(self):
        runner = AgentRunner(self.session(), ObservationMock())
        runner.run()
        with self.assertRaises(DomainError):
            runner.run()
        with self.assertRaises(DomainError):
            AgentRunner(self.session("OTHER"), ObservationMock(), limits=ExecutionLimits.for_items(2))

    def test_protocol_rejects_multiple_actions_and_nonfinite_or_surrogate_data(self):
        responses = ['[{"tool":"finish","arguments":{}}]', '{"tool":"finish","tool":"save_draft","arguments":{}}',
                     '{"tool":"finish","arguments":{"rationale":1e999}}',
                     '{"tool":"finish","arguments":{"rationale":' + '9' * 5000 + '}}',
                     '{"tool":"finish","arguments":{"rationale":"\\ud800"}}']
        for response in responses:
            with self.subTest(response=repr(response)):
                with self.assertRaises(DomainError) as error:
                    Action.parse(response)
                self.assertEqual(error.exception.code, "MODEL_PROTOCOL_ERROR")

    def test_twenty_items_complete_with_derived_budget(self):
        from material_scheduler.application.tools import ToolSession
        from tests.unit.helpers import request_data
        raw = request_data()
        base = raw["items"][0]
        channels = tuple(f"channel-{index}" for index in range(20))
        raw["items"] = [{**base, "item_id": f"I{index:02}", "channel": channel} for index, channel in enumerate(channels)]
        material = replace(self.dataset.materials[0], supported_channels=channels)
        offer = next(entry for entry in self.dataset.slot_offers if entry.interval.start.hour == 18)
        offers = tuple(replace(offer, offer_id=f"O{index:02}", channel=channel) for index, channel in enumerate(channels))
        self.store.import_dataset(replace(self.dataset, materials=(material,) + self.dataset.materials[1:], slot_offers=offers))
        session = ToolSession(self.store, SchedulingRequest.from_dict(raw))
        result = AgentRunner(session, ObservationMock()).run()
        self.assertEqual(result["task_status"], "READY_DRAFTS")
        self.assertEqual(result["stats"]["tool_attempts"], 81)
        self.assertEqual(result["limits"]["max_tool_attempts"], 201)
        self.assertEqual(self.store.counts()["reservations"], 20)

    def test_tool_finishing_after_deadline_retains_commit_as_unfinished_run(self):
        clock = FakeClock()
        actual_save = self.store.save_draft
        def late_save(*args, **kwargs):
            result = actual_save(*args, **kwargs)
            clock.advance(2)
            return result
        limits = replace(ExecutionLimits.for_items(1), run_timeout_seconds=1, model_timeout_seconds=1)
        with patch.object(self.store, "save_draft", side_effect=late_save):
            result = self.run_mock(clock=clock, limits=limits)
        self.assertEqual(result["stop_reason"], "LIMIT_REACHED")
        self.assertEqual(result["business_task_status"], "READY_DRAFTS")
        self.assertEqual(result["task_status"], "INCOMPLETE")
        self.assertEqual(result["items"][0]["save_attempt"]["save_status"], "CREATED")

    def test_unknown_commit_stops_without_fabricating_success(self):
        self.store.faults = FaultInjector({"save.after_commit": 1, "receipt.read": 1})
        result = self.run_mock()
        self.assertEqual(result["items"][0]["save_attempt"]["save_status"], "UNKNOWN")
        self.assertNotEqual(result["task_status"], "READY_DRAFTS")
        self.assertEqual(self.store.counts()["drafts"], 1)

    def test_final_state_read_failure_preserves_acknowledgement_and_is_failure(self):
        from material_scheduler.interfaces.artifacts import result_exit_code
        with patch.object(self.store, "snapshot", side_effect=DomainError("STORE_UNAVAILABLE", "test unavailable ledger")):
            result = self.run_mock()
        self.assertEqual(result["stop_reason"], "RESULT_UNAVAILABLE")
        self.assertEqual(result["execution_status"], "FAILED")
        self.assertEqual(result_exit_code(result), 4)
        self.assertEqual(result["last_known_save_attempts"]["I01"]["save_status"], "CREATED")
        self.assertEqual(self.store.counts()["drafts"], 1)
