from copy import deepcopy
import json
from pathlib import Path
import unittest

from material_scheduler.adapters.fixture_loader import FixtureSet, load_fixture_set
from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.review import ReviewStatus, evaluate_review
from material_scheduler.domain.validation import DomainError

ROOT = Path(__file__).resolve().parents[2]


def dataset_dict():
    def read(name):
        return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
    return {
        "schema_version": "1.0",
        **{key: value for name in (
            "catalog/materials.json", "catalog/supplements.json",
            "rules/review-rules.json", "schedules/slot-offers.json",
            "schedules/existing-bookings.json",
        ) for key, value in read(name).items() if key != "schema_version"},
    }


class SyntheticInputIntegrationTests(unittest.TestCase):
    def test_actual_files_parse_and_cover_review_states(self):
        data = load_fixture_set(ROOT / "data")
        self.assertEqual(len(data.materials), 5)
        self.assertEqual(len(data.rule_set.rules), 5)
        self.assertEqual(len(data.slot_offers), 3)
        expected = {
            "M01": ReviewStatus.PASS, "M02": ReviewStatus.NEEDS_INPUT,
            "M03": ReviewStatus.BLOCKED, "M04": ReviewStatus.NEEDS_REVIEW,
            "M05": ReviewStatus.BLOCKED,
        }
        for material in data.materials:
            self.assertEqual(evaluate_review(material, data.rule_set, "douyin").status, expected[material.material_id])

    def test_request_file_is_valid_and_catalog_resolvable(self):
        source = (ROOT / "data/requests/normal.json").read_text(encoding="utf-8")
        request = SchedulingRequest.from_json(source)
        data = load_fixture_set(ROOT / "data")
        self.assertEqual(data.material(request.items[0].material_id).source_id, "SYN-M01")

    def test_duplicate_and_unknown_source_identities_rejected(self):
        for field in ("materials", "slot_offers"):
            raw = dataset_dict()
            raw[field].append(deepcopy(raw[field][0]))
            with self.assertRaises(DomainError):
                FixtureSet.from_dict(raw)
        raw = dataset_dict()
        raw["supplements"].append({
            "source_id": "SUP01", "material_id": "UNKNOWN", "revision": 1,
            "fields": {"rights_status": "licensed"}, "provenance": "合成",
        })
        with self.assertRaises(DomainError):
            FixtureSet.from_dict(raw)

    def test_incomplete_material_is_loaded_not_silently_discarded(self):
        data = load_fixture_set(ROOT / "data")
        self.assertIsNone(data.material("M02").rights_status)
        self.assertEqual(len(data.materials), 5)

    def test_missing_file_returns_safe_structured_error(self):
        with self.assertRaises(DomainError) as caught:
            load_fixture_set(ROOT / "definitely-not-a-dataset")
        self.assertEqual(caught.exception.code, "INVALID_INPUT")
        self.assertEqual(caught.exception.path, "catalog/materials.json")

    def test_unknown_material_returns_explicit_gap(self):
        with self.assertRaises(DomainError) as caught:
            load_fixture_set(ROOT / "data").material("DOES-NOT-EXIST")
        self.assertEqual(caught.exception.code, "MATERIAL_NOT_FOUND")

    def test_fixture_objects_do_not_share_mutable_input_lists(self):
        raw = dataset_dict()
        data = FixtureSet.from_dict(raw)
        raw["materials"][0]["supported_channels"].append("bilibili")
        self.assertEqual(data.materials[0].supported_channels, ("douyin",))
