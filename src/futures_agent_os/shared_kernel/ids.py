"""Immutable, opaque identifiers shared across bounded contexts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from uuid import UUID, uuid7


_NAMESPACE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class EntityId:
    """A UUIDv7 identifier with a context-neutral, stable namespace."""

    namespace: str
    value: UUID

    def __post_init__(self) -> None:
        if not _NAMESPACE.fullmatch(self.namespace):
            raise ValueError("identifier namespace must be lower_snake_case")
        if self.value.version != 7:
            raise ValueError("identifier value must be UUIDv7")

    @classmethod
    def new(cls, namespace: str) -> EntityId:
        return cls(namespace=namespace, value=uuid7())

    @classmethod
    def deterministic(cls, namespace: str, seed: str) -> EntityId:
        """Create a stable UUIDv7-shaped identifier for replay fixtures."""
        if not isinstance(seed, str) or not seed:
            raise ValueError("deterministic identifier seed must be non-empty")
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        # Deterministic IDs carry no event-time claim; keep the UUIDv7
        # timestamp at the epoch and derive all identity entropy from seed.
        timestamp = 0
        random_a = int.from_bytes(digest[:2], "big") & 0x0FFF
        random_b = int.from_bytes(digest[2:10], "big") & ((1 << 62) - 1)
        value = (timestamp << 80) | (0x7 << 76) | (random_a << 64) | (0x2 << 62) | random_b
        return cls(namespace=namespace, value=UUID(int=value))

    @classmethod
    def parse(cls, text: str) -> EntityId:
        namespace, separator, uuid_text = text.rpartition("_")
        if not separator:
            raise ValueError("identifier must contain a namespace and UUIDv7")
        value = UUID(uuid_text)
        identifier = cls(namespace=namespace, value=value)
        if str(identifier) != text:
            raise ValueError("identifier must use canonical lowercase form")
        return identifier

    def __str__(self) -> str:
        return f"{self.namespace}_{self.value}"

    def to_dict(self) -> dict[str, str]:
        return {"id": str(self)}
