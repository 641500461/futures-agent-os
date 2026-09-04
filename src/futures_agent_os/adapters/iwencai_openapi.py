"""Bounded Iwencai OpenAPI adapter for auxiliary research lookups.

It intentionally does not load an installed SkillHub directory.  Credentials
are supplied by the composition root and never persisted in request evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol, cast

from futures_agent_os.shared_kernel import RecordedAt


_TRACE_ID = re.compile(r"^[0-9a-f]{64}$")
_ENDPOINT = "https://openapi.iwencai.com/v1/query2data"


class IwencaiSkill(StrEnum):
    FUTURES_QUERY = "hithink-futures-query"
    BASICINFO_QUERY = "hithink-basicinfo-query"


@dataclass(frozen=True, slots=True)
class IwencaiRequest:
    skill: IwencaiSkill
    query: str
    page: int = 1
    limit: int = 10

    def __post_init__(self) -> None:
        if not self.query.strip() or len(self.query) > 500:
            raise ValueError("Iwencai query must contain 1-500 non-blank characters")
        if isinstance(self.page, bool) or not isinstance(self.page, int) or self.page < 1:
            raise ValueError("Iwencai page must be a positive integer")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or not 1 <= self.limit <= 100:
            raise ValueError("Iwencai limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class IwencaiHttpResult:
    status_code: int
    content: bytes
    final_url: str = _ENDPOINT


class IwencaiTransport(Protocol):
    def post(
        self, url: str, *, headers: Mapping[str, str], content: bytes, timeout_seconds: float
    ) -> IwencaiHttpResult: ...


class UrlLibIwencaiTransport:
    """POST-only transport with a fixed maximum response size."""

    def __init__(self, *, maximum_bytes: int = 5_000_000) -> None:
        if maximum_bytes < 1:
            raise ValueError("Iwencai maximum_bytes must be positive")
        self._maximum_bytes = maximum_bytes

    def post(
        self, url: str, *, headers: Mapping[str, str], content: bytes, timeout_seconds: float
    ) -> IwencaiHttpResult:
        request = urllib.request.Request(url, data=content, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed endpoint
                body = response.read(self._maximum_bytes + 1)
                if len(body) > self._maximum_bytes:
                    raise ValueError("Iwencai response exceeds maximum_bytes")
                return IwencaiHttpResult(response.status, body, response.geturl())
        except urllib.error.HTTPError as error:
            body = error.read(self._maximum_bytes + 1)
            if len(body) > self._maximum_bytes:
                raise ValueError("Iwencai error response exceeds maximum_bytes") from error
            return IwencaiHttpResult(error.code, body, error.geturl())


@dataclass(frozen=True, slots=True)
class IwencaiEvidence:
    skill: IwencaiSkill
    skill_version: str
    endpoint: str
    trace_id: str
    acquired_at: RecordedAt
    request_hash: str
    response_hash: str
    response: Mapping[str, object]

    def __post_init__(self) -> None:
        if not _TRACE_ID.fullmatch(self.trace_id):
            raise ValueError("Iwencai trace_id must be 64 lowercase hex characters")
        object.__setattr__(self, "response", _freeze_mapping(self.response))


class IwencaiOpenApiClient:
    """Execute one typed auxiliary lookup with fixed endpoint and skill version."""

    SKILL_VERSION = "1.0.0"

    def __init__(self, transport: IwencaiTransport, *, api_key: str, timeout_seconds: float = 30.0) -> None:
        if not api_key.strip():
            raise ValueError("Iwencai client requires a credential supplied by the composition root")
        if timeout_seconds <= 0:
            raise ValueError("Iwencai timeout must be positive")
        self._transport = transport
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def query(self, request: IwencaiRequest, *, acquired_at: RecordedAt) -> IwencaiEvidence:
        trace_id = secrets.token_hex(32)
        payload = json.dumps(
            {
                "expand_index": "true",
                "is_cache": "1",
                "limit": str(request.limit),
                "page": str(request.page),
                "query": request.query,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Claw-Call-Type": "normal",
            "X-Claw-Plugin-Id": "none",
            "X-Claw-Plugin-Version": "none",
            "X-Claw-Skill-Id": request.skill.value,
            "X-Claw-Skill-Version": self.SKILL_VERSION,
            "X-Claw-Trace-Id": trace_id,
        }
        result = self._transport.post(
            _ENDPOINT,
            headers=headers,
            content=payload,
            timeout_seconds=self._timeout_seconds,
        )
        if result.final_url != _ENDPOINT:
            raise ValueError("Iwencai redirect left the fixed endpoint boundary")
        if result.status_code != 200:
            raise RuntimeError(f"Iwencai request failed with HTTP {result.status_code}")
        try:
            parsed = json.loads(result.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Iwencai response must be valid UTF-8 JSON") from error
        if not isinstance(parsed, dict):
            raise ValueError("Iwencai response must be a JSON object")
        return IwencaiEvidence(
            skill=request.skill,
            skill_version=self.SKILL_VERSION,
            endpoint=_ENDPOINT,
            trace_id=trace_id,
            acquired_at=acquired_at,
            request_hash=_digest(payload),
            response_hash=_digest(result.content),
            response=parsed,
        )


def _digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _freeze(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return tuple(_freeze(item) for item in cast(list[object], value))
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        if any(not isinstance(key, str) for key in mapping):
            raise ValueError("Iwencai response object keys must be strings")
        return MappingProxyType({cast(str, key): _freeze(item) for key, item in mapping.items()})
    raise ValueError("Iwencai response contains a non-JSON value")


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    frozen = _freeze(dict(value))
    assert isinstance(frozen, Mapping)
    return frozen
