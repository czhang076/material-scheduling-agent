"""One strict action per decision and an explicit provider interface."""

from dataclasses import dataclass
from typing import Protocol

from material_scheduler.domain.validation import DomainError, fingerprint, object_fields, parse_json, text


@dataclass(frozen=True, slots=True)
class Action:
    tool: str
    arguments: dict

    @classmethod
    def parse(cls, response: str):
        try:
            data = object_fields(parse_json(response), {"tool", "arguments"}, set(), "decision")
            text(data["tool"], "tool", 64)
            if not data["tool"] or type(data["arguments"]) is not dict:
                raise DomainError("INVALID_INPUT", "Expected one tool and argument object")
            fingerprint(data)  # Also rejects nested surrogates and numeric overflow.
            return cls(data["tool"], data["arguments"])
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise DomainError("MODEL_PROTOCOL_ERROR", "Return exactly one JSON tool/arguments object") from exc

    def to_dict(self):
        return {"tool": self.tool, "arguments": self.arguments}


@dataclass(frozen=True, slots=True)
class ModelContext:
    system_prompt: str
    request: dict
    source_identity: dict
    tools: list[dict]
    history: tuple[dict, ...]
    budget: dict
    run_id: str


class DecisionModel(Protocol):
    mode: str
    name: str
    version: str

    def choose(self, context: ModelContext, *, timeout_seconds: float) -> str:
        """Use actual past observations; honor the supplied timeout; return JSON."""
