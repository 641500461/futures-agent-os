"""Version and failure contracts that cross bounded-context boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


_SCHEMA_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


@dataclass(frozen=True, slots=True, order=True)
class SchemaVersion:
    """A canonical major.minor schema version for artifacts, events, and APIs."""

    major: int
    minor: int

    def __post_init__(self) -> None:
        if any(isinstance(part, bool) or not isinstance(part, int) or part < 0 for part in (self.major, self.minor)):
            raise ValueError("schema version parts must be non-negative integers")

    @classmethod
    def parse(cls, text: str) -> SchemaVersion:
        match = _SCHEMA_VERSION.fullmatch(text)
        if not match:
            raise ValueError("schema version must use canonical major.minor form")
        return cls(major=int(match.group(1)), minor=int(match.group(2)))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"

    def to_dict(self) -> dict[str, str]:
        return {"schema_version": str(self)}


class ReasonCode(StrEnum):
    """Stable, machine-readable failures shared by deterministic boundaries."""

    DATA_MISSING = "DATA_MISSING"
    DATA_STALE = "DATA_STALE"
    DATA_CONFLICT = "DATA_CONFLICT"
    DATA_OUT_OF_ORDER = "DATA_OUT_OF_ORDER"
    DATA_GAP = "DATA_GAP"
    DATA_INCOMPLETE = "DATA_INCOMPLETE"
    DATA_FUTURE = "DATA_FUTURE"
    DATA_TIMESTAMP_UNTRUSTED = "DATA_TIMESTAMP_UNTRUSTED"
    DATA_SOURCE_FALLBACK = "DATA_SOURCE_FALLBACK"
    DATA_PURPOSE_DENIED = "DATA_PURPOSE_DENIED"
    RULE_MISSING = "RULE_MISSING"
    RULE_CONFLICT = "RULE_CONFLICT"
    INVALID_IDENTIFIER = "INVALID_IDENTIFIER"
    INVALID_VALUE = "INVALID_VALUE"
    INVALID_SCHEMA_VERSION = "INVALID_SCHEMA_VERSION"
    INVALID_TIMEZONE = "INVALID_TIMEZONE"
    UNAUTHORIZED = "UNAUTHORIZED"
    TOOL_AUTHORIZED = "TOOL_AUTHORIZED"
    TOOL_NOT_REGISTERED = "TOOL_NOT_REGISTERED"
    TOOL_VERSION_MISMATCH = "TOOL_VERSION_MISMATCH"
    TOOL_REGISTRY_VERSION_MISMATCH = "TOOL_REGISTRY_VERSION_MISMATCH"
    TOOL_ROLE_MISMATCH = "TOOL_ROLE_MISMATCH"
    TOOL_CATALOG_VERSION_MISMATCH = "TOOL_CATALOG_VERSION_MISMATCH"
    TOOL_NOT_DECLARED_FOR_ROLE = "TOOL_NOT_DECLARED_FOR_ROLE"
    TOOL_GRANT_MISSING = "TOOL_GRANT_MISSING"
    TOOL_GRANT_INACTIVE = "TOOL_GRANT_INACTIVE"
    TOOL_GRANT_EXPIRED = "TOOL_GRANT_EXPIRED"
    TOOL_NODE_SCOPE_MISMATCH = "TOOL_NODE_SCOPE_MISMATCH"
    TOOL_PERMISSION_TIER_DENIED = "TOOL_PERMISSION_TIER_DENIED"
    TOOL_SCOPE_MISMATCH = "TOOL_SCOPE_MISMATCH"
    PROMPT_UNTRUSTED_CONTENT = "PROMPT_UNTRUSTED_CONTENT"
    SANDBOX_POLICY_PERMITTED = "SANDBOX_POLICY_PERMITTED"
    SANDBOX_RESOURCE_LIMIT_EXCEEDED = "SANDBOX_RESOURCE_LIMIT_EXCEEDED"
    SANDBOX_FILE_SCOPE_DENIED = "SANDBOX_FILE_SCOPE_DENIED"
    SANDBOX_EGRESS_DENIED = "SANDBOX_EGRESS_DENIED"
    STALE_REFERENCE = "STALE_REFERENCE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INSTRUMENT_UNKNOWN = "INSTRUMENT_UNKNOWN"
    INSTRUMENT_AMBIGUOUS = "INSTRUMENT_AMBIGUOUS"
    INSTRUMENT_MALFORMED = "INSTRUMENT_MALFORMED"
    REFERENCE_MAPPING_EXPIRED = "REFERENCE_MAPPING_EXPIRED"
    CONTINUOUS_SERIES_NOT_TRADABLE = "CONTINUOUS_SERIES_NOT_TRADABLE"
    INSTRUMENT_NOT_TRADEABLE = "INSTRUMENT_NOT_TRADEABLE"
    REFERENCE_NOT_YET_VISIBLE = "REFERENCE_NOT_YET_VISIBLE"
    CALENDAR_MISSING = "CALENDAR_MISSING"
    CALENDAR_CONFLICT = "CALENDAR_CONFLICT"
    CALENDAR_CLOSED = "CALENDAR_CLOSED"
    MODEL_OUTPUT_NOT_AUTHORIZATION = "MODEL_OUTPUT_NOT_AUTHORIZATION"


class ModelOutputAuthority(StrEnum):
    """A model/derived result is evidence, never a permission capability."""

    NON_TRADING = "NON_TRADING"


@dataclass(frozen=True, slots=True)
class Failure:
    """A serializable failure whose stable code is separate from human wording."""

    reason_code: ReasonCode
    message: str | None = None

    def to_dict(self) -> dict[str, str]:
        result = {"reason_code": self.reason_code.value}
        if self.message is not None:
            result["message"] = self.message
        return result
