"""Derived limits only; enforcement belongs to the later Agent runtime."""

from dataclasses import dataclass

from .validation import integer


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    per_item_tool_limit: int
    max_tool_attempts: int
    max_model_rounds: int
    run_timeout_seconds: int
    model_timeout_seconds: int
    protocol_error_limit: int

    def __post_init__(self) -> None:
        integer(self.per_item_tool_limit, "per_item_tool_limit", 1, 10)
        integer(self.max_tool_attempts, "max_tool_attempts", 1, 201)
        integer(self.max_model_rounds, "max_model_rounds", self.max_tool_attempts, 205)
        integer(self.run_timeout_seconds, "run_timeout_seconds", 1, 1200)
        integer(self.model_timeout_seconds, "model_timeout_seconds", 1, min(30, self.run_timeout_seconds))
        integer(self.protocol_error_limit, "protocol_error_limit", 1, 4)

    @classmethod
    def for_items(cls, count: int) -> "ExecutionLimits":
        integer(count, "item_count", 1, 20)
        tool_limit = min(10 * count + 1, 201)
        return cls(10, tool_limit, tool_limit + 4, min(180 * count, 1200), 30, 4)
