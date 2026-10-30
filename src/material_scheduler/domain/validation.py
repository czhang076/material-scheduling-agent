"""Small strict validators shared by the domain contracts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


class DomainError(ValueError):
    """A public error code and location, without echoing untrusted values."""

    def __init__(self, code: str, message: str, *, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.path = path

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self), "path": self.path}


def require(condition: bool, message: str, path: str = "") -> None:
    if not condition:
        raise DomainError("INVALID_INPUT", message, path=path)


def object_fields(
    value: Any, required: set[str], optional: set[str], path: str
) -> dict[str, Any]:
    require(type(value) is dict, "Expected an object", path)
    require(not set(value) - required - optional, "Unknown field", path)
    require(not required - set(value), "Required field is absent", path)
    return value


def text(value: Any, path: str, maximum: int | None = None) -> str:
    require(type(value) is str, "Expected a string", path)
    if maximum is not None:
        require(len(value) <= maximum, "String exceeds length limit", path)
    require(
        not any(0xD800 <= ord(character) <= 0xDFFF for character in value),
        "Unpaired Unicode surrogate is not allowed",
        path,
    )
    return value


def identifier(value: Any, path: str, maximum: int = 64) -> str:
    value = text(value, path, maximum)
    require(bool(re.fullmatch(r"[A-Za-z0-9_-]+", value)), "Invalid identifier", path)
    return value


def integer(value: Any, path: str, minimum: int, maximum: int) -> int:
    require(type(value) is int, "Expected an integer, not a boolean", path)
    require(minimum <= value <= maximum, "Integer outside allowed range", path)
    return value


def string_list(
    value: Any, path: str, *, maximum_length: int = 64
) -> tuple[str, ...]:
    require(type(value) is list, "Expected an array", path)
    result = tuple(identifier(item, path, maximum_length) for item in value)
    require(len(result) == len(set(result)), "Duplicate array entries", path)
    return result


def parse_json(value: str) -> Any:
    text(value, "json", 1_048_576)

    def pairs(entries: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, entry in entries:
            require(key not in result, "Duplicate JSON key", "json")
            result[key] = entry
        return result

    def invalid_constant(_: str) -> None:
        raise DomainError("INVALID_INPUT", "Non-finite JSON number", path="json")

    try:
        return json.loads(
            value, object_pairs_hook=pairs, parse_constant=invalid_constant
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise DomainError("INVALID_INPUT", "Malformed JSON", path="json") from exc


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
