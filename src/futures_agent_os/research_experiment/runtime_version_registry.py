"""Versioned offline runtime combinations for research/autonomous simulation."""

from __future__ import annotations
from dataclasses import dataclass
from futures_agent_os.shared_kernel import canonical_sha256


@dataclass(frozen=True, slots=True)
class RuntimeVersionSet:
    agent_ref: str
    prompt_ref: str
    model_ref: str
    toolset_ref: str
    autonomous_qualified: bool = False
    active: bool = False

    def __post_init__(self):
        if any(
            type(x) is not str or not x.strip()
            for x in (self.agent_ref, self.prompt_ref, self.model_ref, self.toolset_ref)
        ):
            raise ValueError("runtime refs are required")
        if type(self.autonomous_qualified) is not bool or type(self.active) is not bool:
            raise TypeError("runtime states must be bool")
        if self.active and not self.autonomous_qualified:
            raise ValueError("active runtime requires autonomous qualification")

    @property
    def content_sha256(self):
        return canonical_sha256(
            {
                "agent": self.agent_ref,
                "prompt": self.prompt_ref,
                "model": self.model_ref,
                "toolset": self.toolset_ref,
                "qualified": self.autonomous_qualified,
                "active": self.active,
            }
        )


class RuntimeVersionRegistry:
    def __init__(self):
        self._records = {}

    def register(self, runtime: RuntimeVersionSet) -> str:
        if type(runtime) is not RuntimeVersionSet:
            raise TypeError("typed runtime required")
        self._records[runtime.content_sha256] = runtime
        return runtime.content_sha256

    def qualify(self, digest: str) -> RuntimeVersionSet:
        runtime = self._records.get(digest)
        if runtime is None:
            raise ValueError("unknown runtime")
        updated = RuntimeVersionSet(
            runtime.agent_ref, runtime.prompt_ref, runtime.model_ref, runtime.toolset_ref, True, False
        )
        self._records[updated.content_sha256] = updated
        return updated

    def activate(self, digest: str) -> RuntimeVersionSet:
        runtime = self._records.get(digest)
        if runtime is None or not runtime.autonomous_qualified:
            raise ValueError("runtime requires autonomous qualification")
        updated = RuntimeVersionSet(
            runtime.agent_ref, runtime.prompt_ref, runtime.model_ref, runtime.toolset_ref, True, True
        )
        self._records[updated.content_sha256] = updated
        return updated

    def resolve_for_mandate(self, digest: str) -> RuntimeVersionSet:
        runtime = self._records.get(digest)
        if runtime is None or not runtime.active or not runtime.autonomous_qualified:
            raise ValueError("runtime is not active and qualified")
        return runtime


__all__ = ["RuntimeVersionRegistry", "RuntimeVersionSet"]
