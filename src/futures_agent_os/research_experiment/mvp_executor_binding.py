"""Bind owner-verified V1-010 results to one frozen MVP-R episode."""

from __future__ import annotations

from futures_agent_os.research_experiment.mvp_validation import (
    EpisodeDefinition,
    FrozenToolResultExecutor,
    ResearchToolResult,
    V1010ResultOwnerAuthority,
)


class V1010ExecutorBinding:
    """The only composition step from V1-010 facts to the MVP tool executor."""

    def __init__(self, owner_authority: V1010ResultOwnerAuthority) -> None:
        if type(owner_authority) is not V1010ResultOwnerAuthority:
            raise TypeError("executor binding requires the V1-010 result owner authority")
        self._owner_authority = owner_authority

    def bind(
        self,
        *,
        episode: EpisodeDefinition,
        request_sha256: str,
        snapshot_sha256: str,
        owner_verified_results: tuple[ResearchToolResult, ...],
    ) -> FrozenToolResultExecutor:
        if type(episode) is not EpisodeDefinition:
            raise TypeError("executor binding requires an exact EpisodeDefinition")
        if snapshot_sha256 not in episode.input_artifact_sha256s:
            raise PermissionError("V1-010 snapshot is absent from the frozen episode inputs")
        allowed_sources = set(episode.input_artifact_sha256s)
        if any(
            not {source.content_sha256 for source in result.source_refs} <= allowed_sources
            for result in owner_verified_results
        ):
            raise PermissionError("V1-010 result sources are outside the frozen episode inputs")
        executor = self._owner_authority.issue(
            episode_id=episode.episode_id,
            request_sha256=request_sha256,
            owner_verified_results=owner_verified_results,
        )
        self._owner_authority.verify(executor)
        return executor
