"""Read validated synthetic inputs; never interpret them as instructions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from material_scheduler.domain.catalog import Material, MetadataSupplement
from material_scheduler.domain.review import RuleSet
from material_scheduler.domain.scheduling import Booking, SlotOffer
from material_scheduler.domain.validation import (
    DomainError, integer, object_fields, parse_json, require,
)


@dataclass(frozen=True, slots=True)
class FixtureSet:
    data_revision: int
    materials: tuple[Material, ...]
    supplements: tuple[MetadataSupplement, ...]
    rule_set: RuleSet
    slot_offers: tuple[SlotOffer, ...]
    existing_bookings: tuple[Booking, ...]

    @classmethod
    def from_dict(cls, value: Any) -> FixtureSet:
        data = object_fields(
            value,
            {"schema_version", "data_revision", "materials", "supplements", "rule_set", "slot_offers", "existing_bookings"},
            set(), "dataset",
        )
        require(data["schema_version"] == "1.0", "Unsupported dataset version")
        integer(data["data_revision"], "data_revision", 1, 2**31 - 1)
        for field in ("materials", "supplements", "slot_offers", "existing_bookings"):
            require(type(data[field]) is list, "Expected dataset array", field)
        materials = tuple(Material.from_dict(entry) for entry in data["materials"])
        supplements = tuple(MetadataSupplement.from_dict(entry) for entry in data["supplements"])
        offers = tuple(SlotOffer.from_dict(entry) for entry in data["slot_offers"])
        bookings = tuple(Booking.from_dict(entry) for entry in data["existing_bookings"])
        for values in (
            [entry.material_id for entry in materials],
            [entry.source_id for entry in materials],
            [entry.source_id for entry in supplements],
            [entry.offer_id for entry in offers],
            [entry.booking_id for entry in bookings],
        ):
            require(len(values) == len(set(values)), "Duplicate dataset identity")
        material_ids = {entry.material_id for entry in materials}
        require(all(entry.material_id in material_ids for entry in supplements), "Supplement references unknown material")
        source_ids = [entry.source_id for entry in materials] + [entry.source_id for entry in supplements]
        require(len(source_ids) == len(set(source_ids)), "Source IDs must be unique")
        return cls(
            data["data_revision"], materials, supplements,
            RuleSet.from_dict(data["rule_set"]), offers, bookings,
        )

    def material(self, material_id: str) -> Material:
        for material in self.materials:
            if material.material_id == material_id:
                return material
        raise DomainError("MATERIAL_NOT_FOUND", "Material is absent from synthetic catalog")


def load_fixture_set(root: Path | str) -> FixtureSet:
    root = Path(root)

    def read(relative: str, fields: set[str]) -> dict[str, Any]:
        try:
            content = (root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise DomainError("INVALID_INPUT", "Cannot read synthetic data file", path=relative) from exc
        data = object_fields(parse_json(content), {"schema_version"} | fields, set(), relative)
        require(data["schema_version"] == "1.0", "Unsupported data file version", relative)
        return data

    material_data = read("catalog/materials.json", {"materials"})
    supplement_data = read("catalog/supplements.json", {"supplements"})
    rule_data = read("rules/review-rules.json", {"rule_set"})
    offer_data = read("schedules/slot-offers.json", {"slot_offers"})
    booking_data = read("schedules/existing-bookings.json", {"data_revision", "existing_bookings"})
    return FixtureSet.from_dict({
        "schema_version": "1.0",
        "data_revision": booking_data["data_revision"],
        "materials": material_data["materials"],
        "supplements": supplement_data["supplements"],
        "rule_set": rule_data["rule_set"],
        "slot_offers": offer_data["slot_offers"],
        "existing_bookings": booking_data["existing_bookings"],
    })
