"""Synthetic source helpers; no models, database writes, or expected traces."""

import json
from pathlib import Path

from material_scheduler.adapters.fixture_loader import load_fixture_set
from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.scheduling import candidate_for

ROOT = Path(__file__).resolve().parents[2]


def request_data():
    return json.loads((ROOT / "data/requests/normal.json").read_text(encoding="utf-8"))


def fixture_data():
    return load_fixture_set(ROOT / "data")


def item(material_id="M01", *, mode="hard", explicit_window=True):
    raw = request_data()
    raw["items"][0]["material_id"] = material_id
    raw["items"][0]["time_requirement"]["mode"] = mode
    if not explicit_window:
        raw["items"][0]["time_requirement"].pop("alternative_window")
    return SchedulingRequest.from_dict(raw).items[0]


def candidate(request_item, hour=18):
    dataset = fixture_data()
    offer = next(entry for entry in dataset.slot_offers if entry.interval.start.hour == hour)
    return candidate_for(request_item, offer), offer
