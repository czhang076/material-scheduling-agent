"""Validated, immutable source metadata. Missing review facts remain missing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .validation import (
    fingerprint, identifier, integer, object_fields, require, string_list, text,
)

RIGHTS_STATES = frozenset({"owned", "licensed", "disputed", "unlicensed", "unknown"})
REVIEW_FIELDS = frozenset({"title", "copy_text", "rights_status", "supported_channels"})
METADATA_FIELDS = REVIEW_FIELDS | {"description", "tags"}


@dataclass(frozen=True, slots=True)
class Material:
    material_id: str
    revision: int
    source_id: str
    title: str | None = None
    copy_text: str | None = None
    rights_status: str | None = None
    supported_channels: tuple[str, ...] | None = None
    description: str | None = None
    tags: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        identifier(self.material_id, "material_id")
        identifier(self.source_id, "source_id")
        integer(self.revision, "revision", 1, 2**31 - 1)
        for field, maximum in (("title", 200), ("copy_text", 8000), ("description", None)):
            value = getattr(self, field)
            if value is not None:
                text(value, field, maximum)
        if self.rights_status is not None:
            text(self.rights_status, "rights_status", 32)
            require(
                self.rights_status.strip() == "" or self.rights_status in RIGHTS_STATES,
                "Unknown rights enum", "rights_status",
            )
        for field, maximum in (("supported_channels", 32), ("tags", 64)):
            value = getattr(self, field)
            if value is not None:
                require(type(value) is tuple, "Expected an immutable string tuple", field)
                for entry in value:
                    identifier(entry, field, maximum)
                require(len(value) == len(set(value)), "Duplicate array entries", field)

    @classmethod
    def from_dict(cls, value: Any) -> Material:
        data = object_fields(
            value, {"material_id", "revision", "source_id"}, set(METADATA_FIELDS), "material"
        ).copy()
        for field, maximum in (("supported_channels", 32), ("tags", 64)):
            if data.get(field) is not None:
                data[field] = string_list(data[field], field, maximum_length=maximum)
        return cls(**data)

    def value(self, field: str) -> str | tuple[str, ...] | None:
        require(field in METADATA_FIELDS, "Unknown metadata field")
        return getattr(self, field)

    def is_missing(self, field: str) -> bool:
        value = self.value(field)
        if value is None or value == () or (type(value) is str and not value.strip()):
            return True
        return field == "rights_status" and value == "unknown"

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "material_id": self.material_id,
            "revision": self.revision,
            "source_id": self.source_id,
        }
        for field in sorted(METADATA_FIELDS):
            value = self.value(field)
            result[field] = list(value) if type(value) is tuple else value
        return result

    @property
    def content_hash(self) -> str:
        return fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class MetadataSupplement:
    source_id: str
    material_id: str
    revision: int
    fields: tuple[tuple[str, Any], ...]
    provenance: str

    def __post_init__(self) -> None:
        identifier(self.source_id, "supplement.source_id")
        identifier(self.material_id, "supplement.material_id")
        integer(self.revision, "supplement.revision", 1, 2**31 - 1)
        text(self.provenance, "supplement.provenance", 1000)
        require(bool(self.provenance.strip()), "Supplement provenance is required")
        require(type(self.fields) is tuple and bool(self.fields), "Supplement fields must be nonempty")
        require(all(type(pair) is tuple and len(pair) == 2 for pair in self.fields), "Invalid supplement fields")
        for key, value in self.fields:
            require(type(key) is str and key in METADATA_FIELDS, "Unknown supplement field")
            require(type(value) in {str, tuple, type(None)}, "Mutable or invalid supplement value")
        require(len({pair[0] for pair in self.fields}) == len(self.fields), "Duplicate supplement field")
        Material(
            material_id=self.material_id, revision=self.revision, source_id=self.source_id,
            **dict(self.fields),
        )

    @classmethod
    def from_dict(cls, value: Any) -> MetadataSupplement:
        data = object_fields(
            value, {"source_id", "material_id", "revision", "fields", "provenance"},
            set(), "supplement",
        )
        raw = object_fields(data["fields"], set(), set(METADATA_FIELDS), "supplement.fields")
        material = Material.from_dict({
            "material_id": data["material_id"], "revision": data["revision"],
            "source_id": data["source_id"], **raw,
        })
        return cls(
            data["source_id"], data["material_id"], data["revision"],
            tuple((key, material.value(key)) for key in sorted(raw)), data["provenance"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id, "material_id": self.material_id,
            "revision": self.revision, "provenance": self.provenance,
            "fields": {key: list(value) if type(value) is tuple else value for key, value in self.fields},
        }
