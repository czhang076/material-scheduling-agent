"""Versioned deterministic review, including exact source evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .catalog import Material, REVIEW_FIELDS
from .validation import fingerprint, identifier, object_fields, require, string_list, text


class ReviewStatus(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    PASS = "PASS"
    NEEDS_INPUT = "NEEDS_INPUT"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"


class RuleType(StrEnum):
    REQUIRED = "required_fields"
    FORBIDDEN_VALUES = "forbidden_values"
    CHANNEL = "channel_supported"
    PHRASES = "forbidden_phrases"
    TAGS = "manual_tags"


SEVERITIES = {
    RuleType.REQUIRED: ReviewStatus.NEEDS_INPUT,
    RuleType.FORBIDDEN_VALUES: ReviewStatus.BLOCKED,
    RuleType.CHANNEL: ReviewStatus.BLOCKED,
    RuleType.PHRASES: ReviewStatus.BLOCKED,
    RuleType.TAGS: ReviewStatus.NEEDS_REVIEW,
}


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    kind: RuleType
    severity: ReviewStatus
    message: str
    fields: tuple[str, ...]
    values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identifier(self.rule_id, "rule_id")
        require(type(self.kind) is RuleType, "Unknown rule type")
        require(type(self.severity) is ReviewStatus and self.severity == SEVERITIES[self.kind], "Invalid severity for rule type")
        text(self.message, "rule.message", 1000)
        require(bool(self.message.strip()), "Rule message is required")
        require(type(self.fields) is tuple and bool(self.fields), "Rule fields must be nonempty")
        require(all(type(field) is str for field in self.fields), "Invalid rule field")
        require(len(self.fields) == len(set(self.fields)), "Duplicate rule field")
        require(type(self.values) is tuple and all(type(value) is str for value in self.values), "Invalid rule values")
        require(len(self.values) == len(set(self.values)), "Duplicate rule value")
        if self.kind == RuleType.REQUIRED:
            require(set(self.fields) <= REVIEW_FIELDS and not self.values, "Invalid required-fields rule")
        elif self.kind == RuleType.FORBIDDEN_VALUES:
            require(self.fields == ("rights_status",), "Invalid rights rule field")
            require(bool(self.values) and set(self.values) <= {"disputed", "unlicensed"}, "Invalid forbidden rights values")
        elif self.kind == RuleType.CHANNEL:
            require(self.fields == ("supported_channels",) and not self.values, "Invalid channel rule")
        elif self.kind == RuleType.PHRASES:
            require(set(self.fields) <= {"title", "copy_text"}, "Invalid phrase field")
            require(bool(self.values), "Rule phrases must be nonempty")
            for phrase in self.values:
                text(phrase, "rule.phrase", 8000)
                require(bool(phrase.strip()), "Empty phrase is not allowed")
        elif self.kind == RuleType.TAGS:
            require(self.fields == ("tags",) and bool(self.values), "Invalid tag rule")
            for tag in self.values:
                identifier(tag, "rule.tag")

    @classmethod
    def from_dict(cls, value: Any) -> Rule:
        require(type(value) is dict, "Expected rule object")
        kind = value.get("type")
        require(type(kind) is str and kind in {entry.value for entry in RuleType}, "Unknown rule type")
        kind = RuleType(kind)
        specific = {
            RuleType.REQUIRED: {"fields"},
            RuleType.FORBIDDEN_VALUES: {"field", "values"},
            RuleType.CHANNEL: {"field"},
            RuleType.PHRASES: {"fields", "phrases"},
            RuleType.TAGS: {"field", "values"},
        }[kind]
        data = object_fields(
            value, {"rule_id", "type", "severity", "message"} | specific, set(), "rule"
        )
        require(type(data["severity"]) is str and data["severity"] == SEVERITIES[kind].value, "Invalid rule severity")
        fields = (
            string_list(data["fields"], "rule.fields")
            if "fields" in data else (text(data["field"], "rule.field", 64),)
        )
        if kind == RuleType.PHRASES:
            require(type(data["phrases"]) is list, "Expected phrases array")
            values = tuple(data["phrases"])
        elif "values" in data:
            values = string_list(data["values"], "rule.values")
        else:
            values = ()
        return cls(data["rule_id"], kind, ReviewStatus(data["severity"]), data["message"], fields, values)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "rule_id": self.rule_id, "type": self.kind.value,
            "severity": self.severity.value, "message": self.message,
        }
        if self.kind in {RuleType.REQUIRED, RuleType.PHRASES}:
            result["fields"] = list(self.fields)
        else:
            result["field"] = self.fields[0]
        if self.kind == RuleType.PHRASES:
            result["phrases"] = list(self.values)
        elif self.values:
            result["values"] = list(self.values)
        return result


@dataclass(frozen=True, slots=True)
class RuleSet:
    rule_set_id: str
    version: str
    rules: tuple[Rule, ...]

    def __post_init__(self) -> None:
        identifier(self.rule_set_id, "rule_set_id")
        text(self.version, "rule_set.version", 64)
        require(bool(self.version.strip()), "Rule set version is required")
        require(type(self.rules) is tuple and bool(self.rules), "Expected nonempty rules")
        require(all(type(rule) is Rule for rule in self.rules), "Invalid rule")
        require(len({rule.rule_id for rule in self.rules}) == len(self.rules), "Duplicate rule_id")
        # Essential review protections cannot disappear through an incomplete rule set.
        required = {field for rule in self.rules if rule.kind == RuleType.REQUIRED for field in rule.fields}
        forbidden = {value for rule in self.rules if rule.kind == RuleType.FORBIDDEN_VALUES for value in rule.values}
        require(REVIEW_FIELDS <= required, "Rule set must cover all essential review fields")
        require({"disputed", "unlicensed"} <= forbidden, "Rule set must block disputed and unlicensed rights")
        require(any(rule.kind == RuleType.CHANNEL for rule in self.rules), "Rule set must check channel support")

    @classmethod
    def from_dict(cls, value: Any) -> RuleSet:
        data = object_fields(value, {"rule_set_id", "version", "rules"}, set(), "rule_set")
        require(type(data["rules"]) is list, "Expected rules array")
        return cls(data["rule_set_id"], data["version"], tuple(Rule.from_dict(rule) for rule in data["rules"]))

    def to_dict(self) -> dict[str, Any]:
        return {"rule_set_id": self.rule_set_id, "version": self.version, "rules": [rule.to_dict() for rule in self.rules]}

    @property
    def content_hash(self) -> str:
        return fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    severity: ReviewStatus
    message: str
    source_id: str
    material_revision: int
    content_hash: str
    field: str
    value: str | tuple[str, ...] | None
    quote: str | None = None
    start: int | None = None
    end: int | None = None

    def __post_init__(self) -> None:
        if self.start is not None or self.end is not None:
            require(type(self.value) is str and type(self.start) is int and type(self.end) is int, "Invalid evidence span")
            require(0 <= self.start < self.end <= len(self.value), "Evidence span outside source")
            require(self.quote == self.value[self.start:self.end], "Evidence quote does not match source")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id, "severity": self.severity.value, "message": self.message,
            "source_id": self.source_id, "material_revision": self.material_revision,
            "content_hash": self.content_hash, "field": self.field,
            "value": list(self.value) if type(self.value) is tuple else self.value,
            "quote": self.quote, "start": self.start, "end": self.end,
        }


@dataclass(frozen=True, slots=True)
class Review:
    material_id: str
    material_revision: int
    material_hash: str
    rule_set_hash: str
    rule_set_id: str
    rule_set_version: str
    channel: str
    status: ReviewStatus
    findings: tuple[Finding, ...]
    missing_fields: tuple[str, ...]

    @property
    def snapshot_id(self) -> str:
        return fingerprint({"material": self.material_hash, "rules": self.rule_set_hash, "channel": self.channel})

    @property
    def review_coverage(self) -> tuple[str, ...]:
        return ("metadata", "copy_text")


def evaluate_review(material: Material, rules: RuleSet, channel: str) -> Review:
    identifier(channel, "channel", 32)
    findings: list[Finding] = []
    missing: set[str] = set()
    material_hash = material.content_hash

    def add(rule: Rule, field: str, start: int | None = None, end: int | None = None) -> None:
        value = material.value(field)
        quote = value[start:end] if start is not None and type(value) is str else None
        findings.append(Finding(
            rule.rule_id, rule.severity, rule.message, material.source_id,
            material.revision, material_hash, field, value, quote, start, end,
        ))

    for rule in rules.rules:
        if rule.kind == RuleType.REQUIRED:
            for field in rule.fields:
                if material.is_missing(field):
                    missing.add(field)
                    add(rule, field)
        elif rule.kind == RuleType.FORBIDDEN_VALUES:
            if material.rights_status in rule.values:
                add(rule, "rights_status")
        elif rule.kind == RuleType.CHANNEL:
            if not material.is_missing("supported_channels") and channel not in material.supported_channels:
                add(rule, "supported_channels")
        elif rule.kind == RuleType.PHRASES:
            for field in rule.fields:
                value = material.value(field)
                if type(value) is not str:
                    continue
                for phrase in rule.values:
                    offset = 0
                    while (start := value.find(phrase, offset)) >= 0:
                        add(rule, field, start, start + len(phrase))
                        offset = start + 1
        elif rule.kind == RuleType.TAGS:
            if material.tags is not None and set(material.tags) & set(rule.values):
                add(rule, "tags")

    statuses = {finding.severity for finding in findings}
    status = next(
        (candidate for candidate in (ReviewStatus.BLOCKED, ReviewStatus.NEEDS_INPUT, ReviewStatus.NEEDS_REVIEW) if candidate in statuses),
        ReviewStatus.PASS,
    )
    return Review(
        material.material_id, material.revision, material_hash, rules.content_hash,
        rules.rule_set_id, rules.version, channel, status, tuple(findings), tuple(sorted(missing)),
    )
