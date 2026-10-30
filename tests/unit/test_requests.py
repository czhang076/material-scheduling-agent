from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime
import json
import unittest

from material_scheduler.domain.budgets import ExecutionLimits
from material_scheduler.domain.requests import SchedulingRequest, TimeMode, TimeRequirement
from material_scheduler.domain.time import TimeInterval, parse_time
from material_scheduler.domain.validation import DomainError
from .helpers import request_data


class RequestContractTests(unittest.TestCase):
    def test_valid_request_round_trip_preserves_original(self):
        raw = request_data()
        before = deepcopy(raw)
        request = SchedulingRequest.from_dict(raw)
        self.assertEqual(request.to_dict(), raw)
        self.assertEqual(raw, before)
        raw["items"][0]["material_id"] = "CHANGED"
        self.assertEqual(request.items[0].material_id, "M01")
        with self.assertRaises(FrozenInstanceError):
            request.request_id = "CHANGED"

    def test_reject_unknown_fields_at_every_request_level(self):
        for level in ("request", "item", "requirement", "window"):
            with self.subTest(level=level):
                raw = request_data()
                targets = {
                    "request": raw, "item": raw["items"][0],
                    "requirement": raw["items"][0]["time_requirement"],
                    "window": raw["items"][0]["time_requirement"]["alternative_window"],
                }
                targets[level]["approved"] = True
                with self.assertRaises(DomainError):
                    SchedulingRequest.from_dict(raw)

    def test_missing_input_field_is_not_business_metadata_missing(self):
        raw = request_data()
        del raw["items"][0]["material_id"]
        with self.assertRaises(DomainError) as caught:
            SchedulingRequest.from_dict(raw)
        self.assertEqual(caught.exception.code, "INVALID_INPUT")

    def test_strict_duration_and_mode(self):
        for value in (True, False, 0, -1, 181, 30.0, "30", None):
            with self.subTest(duration=value):
                raw = request_data()
                raw["items"][0]["time_requirement"]["duration_minutes"] = value
                with self.assertRaises(DomainError):
                    SchedulingRequest.from_dict(raw)
        for value in ("automatic", None, [], True):
            raw = request_data()
            raw["items"][0]["time_requirement"]["mode"] = value
            with self.assertRaises(DomainError):
                SchedulingRequest.from_dict(raw)

    def test_reject_unsupported_version_ids_and_item_counts(self):
        for field, value in (("request_id", ""), ("request_id", "../request"), ("schema_version", "2.0")):
            raw = request_data()
            raw[field] = value
            with self.assertRaises(DomainError):
                SchedulingRequest.from_dict(raw)
        for count in (0, 21):
            raw = request_data()
            raw["items"] = [
                {**deepcopy(raw["items"][0]), "item_id": f"I{index}"}
                for index in range(count)
            ]
            with self.assertRaises(DomainError):
                SchedulingRequest.from_dict(raw)

    def test_duplicate_item_ids_and_non_array_items(self):
        raw = request_data()
        raw["items"] *= 2
        with self.assertRaises(DomainError):
            SchedulingRequest.from_dict(raw)
        raw["items"] = {}
        with self.assertRaises(DomainError):
            SchedulingRequest.from_dict(raw)

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        for source in (
            '{"request_id":"A","request_id":"B"}',
            '{"items":[{"item_id":"A","item_id":"B"}]}',
            '{"items": NaN}', '{"items": Infinity}', '{"items": -Infinity}', '{bad',
        ):
            with self.subTest(source=source):
                with self.assertRaises(DomainError):
                    SchedulingRequest.from_json(source)

    def test_json_whitespace_and_object_key_order_do_not_change_fingerprint(self):
        raw = request_data()
        first = SchedulingRequest.from_json(json.dumps(raw))
        second = SchedulingRequest.from_json(json.dumps(raw, sort_keys=True, indent=4))
        self.assertEqual(first.payload_hash, second.payload_hash)

    def test_item_order_is_not_part_of_business_identity(self):
        raw = request_data()
        second = deepcopy(raw["items"][0])
        second["item_id"] = "I02"
        second["material_id"] = "M02"
        raw["items"].append(second)
        first_hash = SchedulingRequest.from_dict(raw).payload_hash
        raw["items"].reverse()
        self.assertEqual(first_hash, SchedulingRequest.from_dict(raw).payload_hash)

    def test_explicit_equivalent_offsets_share_fingerprint(self):
        raw = request_data()
        first_hash = SchedulingRequest.from_dict(raw).payload_hash
        requirement = raw["items"][0]["time_requirement"]
        requirement["requested_start"] = "2030-06-01T10:00:00Z"
        requirement["alternative_window"] = {
            "start": "2030-06-01T10:00:00Z", "end": "2030-06-01T13:00:00Z",
        }
        self.assertEqual(first_hash, SchedulingRequest.from_dict(raw).payload_hash)

    def test_default_day_offset_semantics_remain_in_fingerprint(self):
        raw = request_data()
        requirement = raw["items"][0]["time_requirement"]
        requirement.pop("alternative_window")
        first_hash = SchedulingRequest.from_dict(raw).payload_hash
        requirement["requested_start"] = "2030-06-01T10:00:00Z"
        self.assertNotEqual(first_hash, SchedulingRequest.from_dict(raw).payload_hash)

    def test_changed_business_requirement_changes_fingerprint(self):
        raw = request_data()
        first_hash = SchedulingRequest.from_dict(raw).payload_hash
        raw["items"][0]["time_requirement"]["mode"] = "preferred"
        self.assertNotEqual(first_hash, SchedulingRequest.from_dict(raw).payload_hash)

    def test_invalid_windows(self):
        for window in (
            {"start": "2030-06-01T18:00:00+08:00", "end": "2030-06-01T18:00:00+08:00"},
            {"start": "2030-06-01T18:00:00+08:00", "end": "2030-06-01T18:15:00+08:00"},
            {"start": "2030-06-01T18:00:00+08:00", "end": "2030-06-09T18:00:00+08:00"},
        ):
            raw = request_data()
            raw["items"][0]["time_requirement"]["alternative_window"] = window
            with self.assertRaises(DomainError):
                SchedulingRequest.from_dict(raw)


class TimeAndBudgetContractTests(unittest.TestCase):
    def test_timestamp_requires_offset_and_valid_calendar_minute(self):
        for value in (
            "2030-06-01T18:00:00", "2030-02-30T18:00:00Z",
            "2030-06-01T18:00:01Z", "2030-06-01T18:00:00.000Z",
            "2030-06-01T18:00:00+08:99", "tomorrow", True,
        ):
            with self.subTest(value=value):
                with self.assertRaises(DomainError):
                    parse_time(value)

    def test_direct_constructor_cannot_bypass_time_or_integer_validation(self):
        with self.assertRaises(DomainError):
            TimeRequirement(datetime(2030, 6, 1, 18), 30, TimeMode.HARD)
        with self.assertRaises(DomainError):
            TimeRequirement(parse_time("2030-06-01T18:00Z"), True, TimeMode.HARD)

    def test_intervals_are_half_open_and_compare_absolute_instants(self):
        first = TimeInterval(parse_time("2030-06-01T18:00+08:00"), parse_time("2030-06-01T18:30+08:00"))
        adjacent = TimeInterval(first.end, parse_time("2030-06-01T19:00+08:00"))
        equivalent = TimeInterval(parse_time("2030-06-01T10:00Z"), parse_time("2030-06-01T10:30Z"))
        self.assertFalse(first.overlaps(adjacent))
        self.assertTrue(first.overlaps(equivalent))
        self.assertEqual(first, equivalent)

    def test_midnight_requested_interval_is_not_silently_rejected(self):
        requirement = TimeRequirement(parse_time("2030-06-01T23:45+08:00"), 30, TimeMode.HARD)
        self.assertTrue(requirement.allows(requirement.requested_interval))
        next_day = TimeInterval(parse_time("2030-06-02T00:00+08:00"), parse_time("2030-06-02T00:30+08:00"))
        self.assertFalse(requirement.allows(next_day))

    def test_calendar_overflow_is_a_domain_error(self):
        with self.assertRaises(DomainError):
            TimeRequirement(parse_time("9999-12-31T23:45Z"), 30, TimeMode.HARD)

    def test_absolute_utc_time_must_be_representable(self):
        for source in ("0001-01-01T00:00+08:00", "9999-12-31T23:59-08:00"):
            with self.subTest(source=source):
                with self.assertRaises(DomainError):
                    parse_time(source)

    def test_derived_budgets_cover_the_normal_batch_path(self):
        for count in range(1, 21):
            limits = ExecutionLimits.for_items(count)
            self.assertGreaterEqual(limits.max_tool_attempts, 4 * count + 1)
            self.assertLessEqual(limits.max_tool_attempts, 201)
            self.assertLessEqual(limits.max_model_rounds, 205)
            self.assertLessEqual(limits.run_timeout_seconds, 1200)
        self.assertEqual(ExecutionLimits.for_items(1).max_tool_attempts, 11)
        self.assertEqual(ExecutionLimits.for_items(20).run_timeout_seconds, 1200)

    def test_invalid_budget_count_rejected(self):
        for count in (0, 21, True, "1"):
            with self.assertRaises(DomainError):
                ExecutionLimits.for_items(count)
