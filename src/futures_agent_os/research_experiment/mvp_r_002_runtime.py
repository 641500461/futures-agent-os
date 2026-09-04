"""Frozen qualification-only runtime wires for MVP-R-002 Phase 0."""

from __future__ import annotations

import json
import re
from dataclasses import InitVar, dataclass, replace
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from threading import Lock
from typing import Any, Callable, Mapping, cast

from futures_agent_os.research_experiment.model_routing import (
    MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
    MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
    MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
    ModelCostAccountingMode,
    ModelProfileRevision,
    FrozenQualificationCaseRoster,
    ModelQualificationState,
    MvpR002QualificationWorkloads,
    ProfileQualificationAuthority,
    ProfileQualificationReport,
    ProfileQualificationReceiptRegistry,
    ResolvedQualificationRunConfig,
)
from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .mvp_r_002 import (
    AgentCriticOutcome,
    AgentRunOutcome,
    CriticDecision,
    EvidenceKind,
    ExperimentBinding,
    ExperimentReadiness,
    FrozenProfileQualification,
    GroundedTextClaim,
    IndependentCriticInvocation,
    IndependentCritic,
    NarrativeCategory,
    OwnerEvidenceIssuer,
    OwnerEvidenceRegistry,
    PhaseZeroAuthority,
    ProposalIntent,
    ResearchAction,
    ResearchCandidatePacket,
    ResearchInvocationAuthorization,
    ResearchProposal,
    ResearchRunner,
    RuntimeInputKind,
    RuntimeInputRef,
    RuntimeAssetRef,
    RuntimeOwnerBinding,
    RuntimeReceiptPayload,
    SourceReference,
    build_next_experiment,
)

RuntimeObservation = tuple[
    str | None,
    str | None,
    str | None,
    str | None,
    tuple[int, int, int, int, int, int] | None,
    int | None,
    tuple[str, ...],
    tuple[str, ...],
]

_FROZEN_RUNTIME_ASSETS_PROOF = object()
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class MvpR002RuntimeFailureCode(StrEnum):
    CONFIG_NOT_QUALIFIED = "CONFIG_NOT_QUALIFIED"
    INPUT_REJECTED = "INPUT_REJECTED"
    PROVIDER_CALL_FAILED = "PROVIDER_CALL_FAILED"
    LOCAL_WIRE_SERIALIZATION_FAILURE = "LOCAL_WIRE_SERIALIZATION_FAILURE"
    PROVIDER_MISMATCH = "PROVIDER_MISMATCH"
    MODEL_DRIFT = "MODEL_DRIFT"
    EFFORT_DRIFT = "EFFORT_DRIFT"
    REROUTE_REJECTED = "REROUTE_REJECTED"
    ACTIVITY_REJECTED = "ACTIVITY_REJECTED"
    TURN_INCOMPLETE = "TURN_INCOMPLETE"
    TURN_START_UNPROVEN = "TURN_START_UNPROVEN"
    RESPONSE_UNPROVEN = "RESPONSE_UNPROVEN"
    USAGE_INCOMPLETE = "USAGE_INCOMPLETE"
    FINAL_COUNT_INVALID = "FINAL_COUNT_INVALID"
    RESPONSE_INVALID_JSON = "RESPONSE_INVALID_JSON"
    RESPONSE_SCHEMA_INVALID = "RESPONSE_SCHEMA_INVALID"
    EFFORT_METADATA_CONFLICT = "EFFORT_METADATA_CONFLICT"
    COST_MISSING = "COST_MISSING"
    COST_INCONSISTENT = "COST_INCONSISTENT"
    COST_AMOUNT_REJECTED = "COST_AMOUNT_REJECTED"
    DETERMINISTIC_DEFER = "DETERMINISTIC_DEFER"


class MvpR002FailureStage(StrEnum):
    PRE_FLIGHT = "PRE_FLIGHT"
    PROVIDER = "PROVIDER"
    OBSERVATION = "OBSERVATION"
    RESPONSE = "RESPONSE"
    DETERMINISTIC = "DETERMINISTIC"


def _execution_config_sha256(payload: Mapping[str, object]) -> str:
    return canonical_sha256(
        _freeze(
            {
                key: payload[key]
                for key in ("workload", "model", "effort", "prompt", "schema", "tools", "runtime_identity")
            }
        )
    )


def _bytes_digest(value: bytes) -> str:
    return sha256(value).hexdigest()


def _runtime_digest(value: str) -> str:
    return canonical_sha256({"runtime_identity": value})


def _freeze(value: object) -> JsonValue:
    if value is None or type(value) in (str, int, bool):
        return cast(JsonValue, value)
    if type(value) in (list, tuple):
        return tuple(_freeze(item) for item in cast(list[object] | tuple[object, ...], value))
    if isinstance(value, Mapping) and all(type(key) is str for key in value):
        return MappingProxyType({cast(str, key): _freeze(item) for key, item in value.items()})
    raise TypeError("runtime JSON must be recursively immutable and finite")


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a canonical SHA-256 digest")
    return value


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise TypeError(f"{label} must be text")
    return value


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError(f"{label} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if type(value) not in (tuple, list):
        raise TypeError(f"{label} must be an array")
    return tuple(cast(tuple[object, ...] | list[object], value))


@dataclass(frozen=True, slots=True)
class MvpR002RuntimeWorkloadAsset:
    workload_id: str
    config: ResolvedQualificationRunConfig
    qualification_report: ProfileQualificationReport
    prompt_bytes: bytes
    schema: JsonValue
    runtime_identity: str

    def __post_init__(self) -> None:
        if (
            type(self.config) is not ResolvedQualificationRunConfig
            or type(self.qualification_report) is not ProfileQualificationReport
        ):
            raise TypeError("runtime assets require factory-issued config and signed report")
        if self.workload_id != str(self.config.workload_id) or self.workload_id != str(
            self.qualification_report.workload_id
        ):
            raise PermissionError("runtime asset crossed workload identities")
        if self.config.qualification_report_sha256 != self.qualification_report.content_sha256:
            raise PermissionError("runtime asset does not bind its exact qualification report")
        if (
            type(self.prompt_bytes) is not bytes
            or not self.prompt_bytes
            or type(self.runtime_identity) is not str
            or not self.runtime_identity
        ):
            raise ValueError("runtime asset needs prompt bytes and identity")
        frozen = _freeze(self.schema)
        object.__setattr__(self, "schema", frozen)
        if (
            self.qualification_report.prompt_sha256 != self.prompt_sha256
            or self.qualification_report.schema_sha256 != self.schema_sha256
            or self.qualification_report.toolset_sha256 != canonical_sha256(())
            or self.qualification_report.runtime_sha256 != self.runtime_sha256
            or self.config.capabilities.cost_accounting_mode is not ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE
        ):
            raise PermissionError("runtime asset does not match qualification evidence")

    @property
    def prompt_sha256(self) -> str:
        return _bytes_digest(self.prompt_bytes)

    @property
    def schema_sha256(self) -> str:
        return canonical_sha256(self.schema)

    @property
    def runtime_sha256(self) -> str:
        return _runtime_digest(self.runtime_identity)

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "workload_id": self.workload_id,
                "config_sha256": self.config.content_sha256,
                "qualification_report_sha256": self.qualification_report.content_sha256,
                "prompt_sha256": self.prompt_sha256,
                "schema_sha256": self.schema_sha256,
                "toolset_sha256": canonical_sha256(()),
                "runtime_sha256": self.runtime_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class MvpR002RuntimeAssets:
    workloads: MvpR002QualificationWorkloads
    research_synthesis: MvpR002RuntimeWorkloadAsset
    experiment_design: MvpR002RuntimeWorkloadAsset
    independent_critic: MvpR002RuntimeWorkloadAsset

    def __post_init__(self) -> None:
        if type(self.workloads) is not MvpR002QualificationWorkloads:
            raise TypeError("runtime requires complete qualification workloads")
        expected = (
            (
                self.research_synthesis,
                MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
                self.workloads.research.hypothesis_synthesis,
            ),
            (
                self.experiment_design,
                MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
                self.workloads.research.preregistration_design,
            ),
            (self.independent_critic, MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD, self.workloads.adversarial_critique),
        )
        if any(
            type(asset) is not MvpR002RuntimeWorkloadAsset or asset.workload_id != workload or asset.config != config
            for asset, workload, config in expected
        ):
            raise PermissionError("runtime assets do not match the three qualified workload configs")
        if (
            len({asset.prompt_sha256 for asset, _, _ in expected}) != 3
            or len({asset.schema_sha256 for asset, _, _ in expected}) != 3
        ):
            raise PermissionError("the three prompts and schemas must remain distinct")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "research_synthesis": self.research_synthesis.content_sha256,
                "experiment_design": self.experiment_design.content_sha256,
                "independent_critic": self.independent_critic.content_sha256,
            }
        )

    def for_workload(self, workload_id: str) -> MvpR002RuntimeWorkloadAsset:
        return {
            MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD: self.research_synthesis,
            MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD: self.experiment_design,
            MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD: self.independent_critic,
        }[workload_id]


@dataclass(frozen=True, slots=True)
class FrozenRuntimeAssets:
    """Owner-signed, repository-root-bound runtime assets.

    ``MvpR002RuntimeAssets`` is an internal assembly type only.  Production
    runners receive this wrapper and re-verify it before every construction.
    """

    assets: MvpR002RuntimeAssets
    repository_root: str
    content_sha256: str
    signature_sha256: str
    _proof: InitVar[object]

    def __post_init__(self, _proof: object) -> None:
        if _proof is not _FROZEN_RUNTIME_ASSETS_PROOF:
            raise PermissionError("frozen runtime assets must be factory-issued")
        if type(self.assets) is not MvpR002RuntimeAssets:
            raise TypeError("frozen runtime assets require exact assembled assets")
        if type(self.repository_root) is not str or not self.repository_root:
            raise ValueError("frozen runtime assets require a repository root")
        if Path(self.repository_root).resolve() != _REPOSITORY_ROOT:
            raise PermissionError("frozen runtime assets must remain bound to the fixed repository root")
        _digest(self.content_sha256, "frozen runtime assets content")
        _digest(self.signature_sha256, "frozen runtime assets signature")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("frozen runtime assets digest is invalid")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {"repository_root": self.repository_root, "assets_sha256": self.assets.content_sha256}

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @property
    def asset_ref(self) -> RuntimeAssetRef:
        return RuntimeAssetRef(self.assets.content_sha256, self.content_sha256)

    @classmethod
    def issue_from_repository(
        cls,
        authority: PhaseZeroAuthority,
        workloads: MvpR002QualificationWorkloads,
        reports: tuple[ProfileQualificationReport, ProfileQualificationReport, ProfileQualificationReport],
        qualification_registries: tuple[
            ProfileQualificationReceiptRegistry,
            ProfileQualificationReceiptRegistry,
            ProfileQualificationReceiptRegistry,
        ],
        qualification_rosters: tuple[
            FrozenQualificationCaseRoster,
            FrozenQualificationCaseRoster,
            FrozenQualificationCaseRoster,
        ],
        *,
        repository_root: Path | None = None,
    ) -> "FrozenRuntimeAssets":
        if type(authority) is not PhaseZeroAuthority or type(workloads) is not MvpR002QualificationWorkloads:
            raise TypeError("runtime asset factory requires exact owner authority and qualification workloads")
        qualification_authority = ProfileQualificationAuthority(authority)
        root = _REPOSITORY_ROOT if repository_root is None else repository_root.resolve()
        if root != _REPOSITORY_ROOT:
            raise PermissionError("runtime assets must load from the fixed repository root")
        configs = (
            workloads.research.hypothesis_synthesis,
            workloads.research.preregistration_design,
            workloads.adversarial_critique,
        )
        for config, report, receipt_registry, case_roster in zip(
            configs, reports, qualification_registries, qualification_rosters, strict=True
        ):
            # The report signs the EVALUATING revision.  Recreate only that
            # state from the factory-issued qualified config before verifying.
            profile = ModelProfileRevision(
                config.profile_id,
                config.profile_revision,
                config.workload_id,
                config.protocol_family,
                config.provider,
                config.runner_kind,
                config.authentication_mode,
                config.model_id,
                config.reasoning_effort,
                config.prompt_binding,
                config.output_schema_binding,
                config.toolset_binding,
                config.capabilities,
                ModelQualificationState.EVALUATING,
                config.credential_ref,
            )
            qualification_authority.verify(report, profile, receipt_registry, case_roster)
        from futures_agent_os.adapters.research_model_payload import (
            R002_EXPERIMENT_DESIGN_SCHEMA,
            R002_INDEPENDENT_CRITIC_SCHEMA,
            R002_RESEARCH_SYNTHESIS_SCHEMA,
        )

        specifications: tuple[
            tuple[str, ResolvedQualificationRunConfig, ProfileQualificationReport, str, JsonValue], ...
        ] = (
            (
                MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
                workloads.research.hypothesis_synthesis,
                reports[0],
                "r002-research-synthesis-v1.md",
                _freeze(R002_RESEARCH_SYNTHESIS_SCHEMA),
            ),
            (
                MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
                workloads.research.preregistration_design,
                reports[1],
                "r002-experiment-design-v1.md",
                _freeze(R002_EXPERIMENT_DESIGN_SCHEMA),
            ),
            (
                MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
                workloads.adversarial_critique,
                reports[2],
                "r002-independent-critic-v1.md",
                _freeze(R002_INDEPENDENT_CRITIC_SCHEMA),
            ),
        )
        built: list[MvpR002RuntimeWorkloadAsset] = []
        for workload, config, report, filename, schema in specifications:
            path = root / "prompts" / "mvp-r" / filename
            if path.resolve().parent != (root / "prompts" / "mvp-r").resolve() or not path.is_file():
                raise PermissionError("runtime prompt path is not an exact approved asset")
            built.append(
                MvpR002RuntimeWorkloadAsset(
                    workload, config, report, path.read_bytes(), schema, f"mvp-r-002.runtime.{workload}.v1"
                )
            )
        assembled = MvpR002RuntimeAssets(workloads, built[0], built[1], built[2])
        payload: dict[str, JsonValue] = {"repository_root": str(root), "assets_sha256": assembled.content_sha256}
        return cls(
            assembled,
            str(root),
            canonical_sha256(payload),
            authority.sign(payload),
            _FROZEN_RUNTIME_ASSETS_PROOF,
        )

    @classmethod
    def hydrate(
        cls, value: Mapping[str, object], authority: PhaseZeroAuthority, assets: MvpR002RuntimeAssets
    ) -> "FrozenRuntimeAssets":
        if set(value) != {"repository_root", "assets_sha256", "content_sha256", "signature_sha256"}:
            raise ValueError("frozen runtime asset fields are not exact")
        payload: dict[str, JsonValue] = {
            "repository_root": _text(value["repository_root"], "repository root"),
            "assets_sha256": _digest(value["assets_sha256"], "assets"),
        }
        if payload["assets_sha256"] != assets.content_sha256:
            raise PermissionError("frozen runtime assets do not bind the assembled asset bytes")
        frozen = cls(
            assets,
            cast(str, payload["repository_root"]),
            _text(value["content_sha256"], "content"),
            _text(value["signature_sha256"], "signature"),
            _FROZEN_RUNTIME_ASSETS_PROOF,
        )
        if not authority.verify(frozen.unsigned_payload(), frozen.signature_sha256):
            raise PermissionError("frozen runtime assets signature is invalid")
        frozen._verify_repository_bytes()
        return frozen

    def verify(self, authority: PhaseZeroAuthority) -> "FrozenRuntimeAssets":
        return FrozenRuntimeAssets.hydrate(self.to_dict(), authority, self.assets)

    def bind_owner(
        self,
        registry: OwnerEvidenceRegistry,
        *,
        workload_id: str,
        profile_sha256: str,
        prompt_sha256: str,
        schema_sha256: str,
        toolset_sha256: str,
        runtime_sha256: str,
    ) -> RuntimeOwnerBinding:
        """Create one verified inner/outer asset identity for an invocation."""

        asset = self.assets.for_workload(workload_id)
        expected = (
            asset.config.profile_sha256,
            asset.prompt_sha256,
            asset.schema_sha256,
            canonical_sha256(()),
            asset.runtime_sha256,
        )
        references: list[RuntimeAssetRef] = []
        for (digest, kind), inner_sha256 in zip(
            (
                (profile_sha256, EvidenceKind.PROFILE),
                (prompt_sha256, EvidenceKind.PROMPT),
                (schema_sha256, EvidenceKind.SCHEMA),
                (toolset_sha256, EvidenceKind.TOOLSET),
                (runtime_sha256, EvidenceKind.RUNTIME),
            ),
            expected,
            strict=True,
        ):
            evidence = registry.require(digest, kind)
            payload = evidence.payload()
            if payload.get("workload_id") != workload_id or payload.get("asset_sha256") != inner_sha256:
                raise PermissionError("owner evidence does not map the exact workload asset bytes")
            references.append(RuntimeAssetRef(inner_sha256, evidence.content_sha256))
        binding = RuntimeOwnerBinding.hydrate(
            {
                "workload_id": workload_id,
                "asset_ref": self.asset_ref.to_dict(),
                "profile_ref": references[0].to_dict(),
                "prompt_ref": references[1].to_dict(),
                "schema_ref": references[2].to_dict(),
                "toolset_ref": references[3].to_dict(),
                "runtime_ref": references[4].to_dict(),
            }
        )
        return self.verify_owner_binding(registry, binding, workload_id=workload_id)

    def verify_owner_binding(
        self,
        registry: OwnerEvidenceRegistry,
        binding: RuntimeOwnerBinding,
        *,
        workload_id: str,
    ) -> RuntimeOwnerBinding:
        """Re-derive one cross-proof from frozen bytes and owner payloads."""

        if type(binding) is not RuntimeOwnerBinding or binding.workload_id != workload_id:
            raise PermissionError("runtime owner binding workload is not exact")
        asset = self.assets.for_workload(workload_id)
        expected_inner = (
            asset.config.profile_sha256,
            asset.prompt_sha256,
            asset.schema_sha256,
            canonical_sha256(()),
            asset.runtime_sha256,
        )
        if binding.asset_ref != self.asset_ref or binding.inner_digests != expected_inner:
            raise PermissionError("runtime owner binding does not bind exact frozen inner bytes")
        for reference, kind, expected_sha256 in zip(
            (
                binding.profile_ref,
                binding.prompt_ref,
                binding.schema_ref,
                binding.toolset_ref,
                binding.runtime_ref,
            ),
            (
                EvidenceKind.PROFILE,
                EvidenceKind.PROMPT,
                EvidenceKind.SCHEMA,
                EvidenceKind.TOOLSET,
                EvidenceKind.RUNTIME,
            ),
            expected_inner,
            strict=True,
        ):
            evidence = registry.require(reference.owner_evidence_sha256, kind)
            payload = evidence.payload()
            if (
                evidence.content_sha256 != reference.owner_evidence_sha256
                or payload.get("workload_id") != workload_id
                or payload.get("asset_sha256") != expected_sha256
            ):
                raise PermissionError("runtime owner binding outer evidence does not map exact inner bytes")
        return binding

    def _verify_repository_bytes(self) -> None:
        from futures_agent_os.adapters.research_model_payload import (
            R002_EXPERIMENT_DESIGN_SCHEMA,
            R002_INDEPENDENT_CRITIC_SCHEMA,
            R002_RESEARCH_SYNTHESIS_SCHEMA,
        )

        expected = (
            (self.assets.research_synthesis, "r002-research-synthesis-v1.md", R002_RESEARCH_SYNTHESIS_SCHEMA),
            (self.assets.experiment_design, "r002-experiment-design-v1.md", R002_EXPERIMENT_DESIGN_SCHEMA),
            (self.assets.independent_critic, "r002-independent-critic-v1.md", R002_INDEPENDENT_CRITIC_SCHEMA),
        )
        for asset, filename, schema in expected:
            path = _REPOSITORY_ROOT / "prompts" / "mvp-r" / filename
            if (
                path.resolve().parent != (_REPOSITORY_ROOT / "prompts" / "mvp-r").resolve()
                or not path.is_file()
                or asset.prompt_bytes != path.read_bytes()
                or asset.schema != _freeze(schema)
            ):
                raise PermissionError("frozen runtime assets drifted from fixed repository bytes")


MvpR002RunReceipt = RuntimeReceiptPayload


@dataclass(frozen=True, slots=True)
class MvpR002CriticWireDecision:
    decision: CriticDecision
    reason: NarrativeCategory


@dataclass(frozen=True, slots=True)
class MvpR002RuntimeResult:
    value: object | None
    receipt: MvpR002RunReceipt
    receipt_evidence_sha256: str


@dataclass(frozen=True, slots=True)
class MvpR002CapabilityProbeSpec:
    """One deliberately non-qualifying, empty-tool Phase-0 probe profile."""

    workload_id: str
    requested_model_id: str
    requested_reasoning_effort: str
    prompt_sha256: str
    schema_sha256: str
    toolset_sha256: str
    runtime_sha256: str
    cost_mode: ModelCostAccountingMode = ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE
    cost_available: bool = False
    cost_amount: None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "workload_id": self.workload_id,
            "requested_model_id": self.requested_model_id,
            "requested_reasoning_effort": self.requested_reasoning_effort,
            "prompt_sha256": self.prompt_sha256,
            "schema_sha256": self.schema_sha256,
            "toolset_sha256": self.toolset_sha256,
            "runtime_sha256": self.runtime_sha256,
            "cost_mode": self.cost_mode.value,
            "cost_available": self.cost_available,
            "cost_amount": self.cost_amount,
        }


@dataclass(frozen=True, slots=True)
class MvpR002CapabilityProbeReceipt:
    """Sanitized observation from one provider attempt.

    This is intentionally *not* a ``ProfileQualificationReceipt``: it has no
    critical/fault case assertion and cannot be fed into the qualification
    authority.  It keeps only hashes of prompt, request, and response bytes.
    """

    spec: MvpR002CapabilityProbeSpec
    status: str
    actual_provider: str | None
    actual_model_id: str | None
    actual_reasoning_effort: str | None
    response_id: str | None
    usage: tuple[int, int, int, int, int, int] | None
    latency_ms: int | None
    provider_turn_started: bool
    provider_response_observed: bool
    reroute_sha256s: tuple[str, ...]
    activity_sha256s: tuple[str, ...]
    request_sha256: str
    response_sha256: str | None
    failure_code: str | None
    failure_stage: str | None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "record_type": "MVP_R_002_MINIMAL_CAPABILITY_RECEIPT",
            "qualification_status": "NOT_A_QUALIFICATION_RECEIPT",
            "profile": self.spec.to_dict(),
            "status": self.status,
            "actual_provider": self.actual_provider,
            "actual_model_id": self.actual_model_id,
            "actual_reasoning_effort": self.actual_reasoning_effort,
            "response_id_sha256": canonical_sha256({"response_id": self.response_id}) if self.response_id else None,
            "usage": (
                {
                    "input_tokens": self.usage[0],
                    "cached_input_tokens": self.usage[1],
                    "output_tokens": self.usage[2],
                    "reasoning_tokens": self.usage[3],
                    "cache_write_input_tokens": self.usage[4],
                    "total_tokens": self.usage[5],
                }
                if self.usage is not None
                else None
            ),
            "latency_ms": self.latency_ms,
            "provider_turn_started": self.provider_turn_started,
            "provider_response_observed": self.provider_response_observed,
            "reroute_sha256s": self.reroute_sha256s,
            "activity_sha256s": self.activity_sha256s,
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "failure_code": self.failure_code,
            "failure_stage": self.failure_stage,
            "cost_mode": self.spec.cost_mode.value,
            "cost_available": self.spec.cost_available,
            "cost_amount": self.spec.cost_amount,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())


class _MvpR002RuntimeExecutor:
    """Private execution closure owned by one factory-issued orchestrator."""

    def __init__(
        self,
        execute: Callable[[Mapping[str, object]], Mapping[str, object]],
        authority: PhaseZeroAuthority,
        registry: OwnerEvidenceRegistry,
        assets: FrozenRuntimeAssets,
        critic_authority: PhaseZeroAuthority | None = None,
    ) -> None:
        if (
            not callable(execute)
            or type(authority) is not PhaseZeroAuthority
            or type(registry) is not OwnerEvidenceRegistry
            or type(assets) is not FrozenRuntimeAssets
        ):
            raise TypeError("runtime runner needs authority, owner registry, and complete frozen assets")
        self._execute, self._authority, self._registry, self._assets = execute, authority, registry, assets
        if critic_authority is not None and type(critic_authority) is not PhaseZeroAuthority:
            raise TypeError("critic request authority must be Phase-0 authority")
        if critic_authority is None or critic_authority == authority:
            raise PermissionError("critic authority must be explicit and independent from research authority")
        self._critic_authority = critic_authority
        self._assets.verify(authority)
        self._issuer = OwnerEvidenceIssuer(authority, "mvp-r-002.runtime")

    def _research_proposal(
        self,
        candidate: ResearchCandidatePacket,
        *,
        invocation_id: str,
        owner_binding: RuntimeOwnerBinding | None = None,
    ) -> MvpR002RuntimeResult:
        self._assets.verify(self._authority)
        try:
            if type(candidate) is not ResearchCandidatePacket:
                raise TypeError
            checked = ResearchCandidatePacket.hydrate(candidate.to_dict(), self._authority, self._registry)
        except TypeError, ValueError, PermissionError:
            return self._preflight(
                MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, invocation_id, canonical_sha256({"invalid": "candidate"})
            )
        value, receipt, evidence = self._invoke(
            MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
            invocation_id,
            checked.content_sha256,
            {"candidate": checked.to_dict()},
            (RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, checked.content_sha256),),
        )
        if value is None:
            return MvpR002RuntimeResult(None, receipt, evidence)
        try:
            proposal = _proposal_from_wire(_mapping(value, "research wire"), checked)
            if owner_binding is not None:
                receipt = self._rebind_receipt(receipt, owner_binding)
            return MvpR002RuntimeResult(proposal, receipt, "")
        except TypeError, ValueError, PermissionError:
            failed, failure_evidence = self._failure_from(
                receipt, MvpR002RuntimeFailureCode.RESPONSE_SCHEMA_INVALID, MvpR002FailureStage.RESPONSE
            )
            return MvpR002RuntimeResult(None, failed, failure_evidence)

    def _experiment_request(
        self,
        candidate: ResearchCandidatePacket,
        binding: ExperimentBinding,
        *,
        invocation_id: str,
        owner_binding: RuntimeOwnerBinding | None = None,
    ) -> MvpR002RuntimeResult:
        self._assets.verify(self._authority)
        try:
            if type(candidate) is not ResearchCandidatePacket or type(binding) is not ExperimentBinding:
                raise TypeError
            checked = ResearchCandidatePacket.hydrate(candidate.to_dict(), self._authority, self._registry)
        except TypeError, ValueError, PermissionError:
            return self._preflight(
                MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, invocation_id, canonical_sha256({"invalid": "experiment"})
            )
        value, receipt, evidence = self._invoke(
            MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
            invocation_id,
            checked.content_sha256,
            {"candidate_sha256": checked.content_sha256, "binding": binding.to_dict()},
            (
                RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, checked.content_sha256),
                RuntimeInputRef(RuntimeInputKind.EXPERIMENT_BINDING, canonical_sha256(binding.to_dict())),
            ),
        )
        if value is None:
            return MvpR002RuntimeResult(None, receipt, evidence)
        try:
            if _mapping(value, "experiment wire") != {"design_category": "USE_FROZEN_BINDING"}:
                raise ValueError
            experiment = build_next_experiment(
                checked, ExperimentReadiness.READY, binding, self._authority, self._registry
            )
            if owner_binding is not None:
                receipt = self._rebind_receipt(receipt, owner_binding)
            return MvpR002RuntimeResult(experiment.instantiate_request(self._authority), receipt, "")
        except TypeError, ValueError, PermissionError:
            failed, failure_evidence = self._failure_from(
                receipt, MvpR002RuntimeFailureCode.RESPONSE_SCHEMA_INVALID, MvpR002FailureStage.RESPONSE
            )
            return MvpR002RuntimeResult(None, failed, failure_evidence)

    def _critic_decision(
        self,
        request: IndependentCriticInvocation,
        owner_binding: RuntimeOwnerBinding,
    ) -> MvpR002RuntimeResult:
        self._assets.verify(self._authority)
        try:
            if type(request) is not IndependentCriticInvocation:
                raise TypeError
            checked = IndependentCriticInvocation.hydrate(request.to_dict(), self._critic_authority)
            owner_binding = self._assets.verify_owner_binding(
                self._registry, owner_binding, workload_id=MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD
            )
            if (
                checked.profile_sha256,
                checked.prompt_sha256,
                checked.schema_sha256,
                checked.toolset_sha256,
                checked.runtime_sha256,
            ) != owner_binding.owner_digests:
                raise PermissionError
        except TypeError, ValueError, PermissionError:
            return self._preflight(
                MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
                getattr(request, "run_id", "invalid"),
                canonical_sha256({"invalid": "critic"}),
            )
        value, receipt, evidence = self._invoke(
            MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
            checked.run_id,
            checked.content_sha256,
            checked.to_dict(),
            (
                RuntimeInputRef(RuntimeInputKind.CRITIC_INVOCATION, checked.content_sha256),
                RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, checked.candidate_sha256),
                RuntimeInputRef(RuntimeInputKind.AGENT_OUTCOME, checked.agent_outcome_sha256),
                RuntimeInputRef(RuntimeInputKind.RESEARCH_RUN, checked.research_run_sha256),
                RuntimeInputRef(RuntimeInputKind.RESEARCH_BRIEF, checked.brief_sha256),
            ),
        )
        if value is None:
            return MvpR002RuntimeResult(None, receipt, evidence)
        try:
            wire = _mapping(value, "critic wire")
            if set(wire) != {"decision", "reason_category"}:
                raise ValueError
            decision = MvpR002CriticWireDecision(
                CriticDecision(_text(wire["decision"], "decision")),
                NarrativeCategory(_text(wire["reason_category"], "reason")),
            )
            receipt = self._rebind_receipt(receipt, owner_binding)
            return MvpR002RuntimeResult(decision, receipt, "")
        except TypeError, ValueError:
            failed, failure_evidence = self._failure_from(
                receipt, MvpR002RuntimeFailureCode.RESPONSE_SCHEMA_INVALID, MvpR002FailureStage.RESPONSE
            )
            return MvpR002RuntimeResult(None, failed, failure_evidence)

    def deterministic_defer(self, workload_id: str, invocation_id: str, subject_sha256: str) -> None:
        """Validate the no-model branch without minting a model receipt.

        The signed EvidenceKind.FAILURE -> ResearchRunner.defer_for_failure path
        owns deterministic DEFER.  A runtime receipt would falsely imply that a
        provider invocation occurred.
        """

        self._assets.verify(self._authority).assets.for_workload(workload_id)
        _text(invocation_id, "invocation")
        _digest(subject_sha256, "subject")

    def _preflight(self, workload: str, invocation: str, subject: str) -> MvpR002RuntimeResult:
        input_kind = (
            RuntimeInputKind.CRITIC_INVOCATION
            if workload == MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD
            else RuntimeInputKind.RESEARCH_CANDIDATE
        )
        receipt = self._receipt(
            self._assets.assets.for_workload(workload),
            invocation,
            subject,
            canonical_sha256({"preflight": subject}),
            (RuntimeInputRef(input_kind, subject),),
            None,
            None,
            "FAILED",
            MvpR002RuntimeFailureCode.INPUT_REJECTED,
            MvpR002FailureStage.PRE_FLIGHT,
        )
        issued, evidence = self._issue(receipt)
        return MvpR002RuntimeResult(None, issued, evidence)

    def _invoke(
        self,
        workload: str,
        invocation: str,
        subject: str,
        request: Mapping[str, JsonValue],
        input_lineage: tuple[RuntimeInputRef, ...],
    ) -> tuple[object | None, MvpR002RunReceipt, str]:
        asset = self._assets.assets.for_workload(workload)
        request_json = canonical_json_text(_freeze(request))
        request_sha = _bytes_digest(request_json.encode())
        frozen_payload: dict[str, object] = {
            "workload": workload,
            "model": asset.config.model_id,
            "effort": asset.config.reasoning_effort,
            "prompt": asset.prompt_bytes.decode("utf-8"),
            "schema": asset.schema,
            "input": request_json,
            "tools": (),
            "runtime_identity": asset.runtime_identity,
        }
        try:
            response = self._execute(frozen_payload)
        except Exception:
            receipt = self._receipt(
                asset,
                invocation,
                subject,
                request_sha,
                input_lineage,
                None,
                None,
                "FAILED",
                MvpR002RuntimeFailureCode.PROVIDER_CALL_FAILED,
                MvpR002FailureStage.PROVIDER,
            )
            issued, evidence = self._issue(receipt)
            return None, issued, evidence
        return self._parse(asset, invocation, subject, request_sha, input_lineage, response)

    def _parse(
        self,
        asset: MvpR002RuntimeWorkloadAsset,
        invocation: str,
        subject: str,
        request_sha: str,
        input_lineage: tuple[RuntimeInputRef, ...],
        response: object,
    ) -> tuple[object | None, MvpR002RunReceipt, str]:
        raw_response: str | None = None
        provider = model = effort = response_id = None
        usage: tuple[int, int, int, int, int, int] | None = None
        latency: int | None = None
        reroutes: tuple[str, ...] = ()
        activities: tuple[str, ...] = ()
        provider, model, effort, response_id, usage, latency = _extract_observed_scalars(response)
        try:
            frozen_response = _freeze(response)
            raw_response = canonical_json_text(frozen_response)
            response_map = _mapping(frozen_response, "response")
            provider = _text(response_map["model_provider"], "provider")
            model = _text(response_map["model"], "model")
            effort = _text(response_map["reasoning_effort"], "effort")
            response_id = _text(response_map["response_id"], "response id")
            usage = _usage(_mapping(response_map["usage"], "usage"))
            latency = _integer(response_map["latencyMs"], "latency")
            reroutes = _hashes(response_map.get("reroutes", ()))
            dynamic_calls = _sequence(response_map.get("dynamic_calls", ()), "dynamic")
            server_requests = _sequence(response_map.get("server_requests", ()), "server")
            item_types = tuple(_text(item, "item") for item in _sequence(response_map.get("item_types", ()), "items"))
            disallowed_item_types = tuple(
                item for item in item_types if item not in {"agentMessage", "reasoning", "userMessage"}
            )
            activities = (
                _hashes(
                    {
                        "dynamic_calls": dynamic_calls,
                        "server_requests": server_requests,
                        "disallowed_item_types": disallowed_item_types,
                    }
                )
                if dynamic_calls or server_requests or disallowed_item_types
                else ()
            )
            code: MvpR002RuntimeFailureCode | None = None
            if provider != "openai":
                code = MvpR002RuntimeFailureCode.PROVIDER_MISMATCH
            elif model != asset.config.model_id:
                code = MvpR002RuntimeFailureCode.MODEL_DRIFT
            elif effort != asset.config.reasoning_effort:
                code = MvpR002RuntimeFailureCode.EFFORT_DRIFT
            elif reroutes:
                code = MvpR002RuntimeFailureCode.REROUTE_REJECTED
            elif activities:
                code = MvpR002RuntimeFailureCode.ACTIVITY_REJECTED
            elif response_map.get("status") != "completed" or response_map.get("timed_out") is True:
                code = MvpR002RuntimeFailureCode.TURN_INCOMPLETE
            finals = _sequence(response_map.get("final_texts", ()), "finals")
            if code is None and len(finals) != 1:
                code = MvpR002RuntimeFailureCode.FINAL_COUNT_INVALID
            observation = (provider, model, effort, response_id, usage, latency, reroutes, activities)
            if code is not None:
                receipt = self._receipt(
                    asset,
                    invocation,
                    subject,
                    request_sha,
                    input_lineage,
                    raw_response,
                    observation,
                    "FAILED",
                    code,
                    MvpR002FailureStage.OBSERVATION,
                )
                issued, evidence = self._issue(receipt)
                return None, issued, evidence
            parsed = _freeze(json.loads(_text(finals[0], "final")))
            receipt = self._receipt(
                asset,
                invocation,
                subject,
                request_sha,
                input_lineage,
                raw_response,
                observation,
                "COMPLETED",
                None,
                None,
                canonical_response=canonical_sha256(parsed),
            )
            # Closed workload decoding happens before a successful receipt can
            # enter the append-only owner registry.
            return parsed, receipt, ""
        except json.JSONDecodeError:
            receipt = self._receipt(
                asset,
                invocation,
                subject,
                request_sha,
                input_lineage,
                raw_response,
                (provider, model, effort, response_id, usage, latency, reroutes, activities),
                "FAILED",
                MvpR002RuntimeFailureCode.RESPONSE_INVALID_JSON,
                MvpR002FailureStage.RESPONSE,
            )
        except KeyError, TypeError, ValueError:
            receipt = self._receipt(
                asset,
                invocation,
                subject,
                request_sha,
                input_lineage,
                raw_response,
                (provider, model, effort, response_id, usage, latency, reroutes, activities),
                "FAILED",
                MvpR002RuntimeFailureCode.USAGE_INCOMPLETE,
                MvpR002FailureStage.OBSERVATION,
            )
        issued, evidence = self._issue(receipt)
        return None, issued, evidence

    def _failure_from(
        self, receipt: MvpR002RunReceipt, code: MvpR002RuntimeFailureCode, stage: MvpR002FailureStage
    ) -> tuple[MvpR002RunReceipt, str]:
        # Do not erase observed provider facts when a closed output fails parsing.
        payload = {
            **receipt.unsigned_payload(),
            "status": "FAILED",
            "failure_code": code.value,
            "failure_stage": stage.value,
        }
        replacement = replace(
            receipt,
            status="FAILED",
            failure_code=code,
            failure_stage=stage,
            content_sha256=canonical_sha256(payload),
            signature_sha256=self._authority.sign(payload),
        )
        return self._issue(replacement)

    def _rebind_receipt(
        self,
        receipt: MvpR002RunReceipt,
        owner_binding: RuntimeOwnerBinding,
    ) -> MvpR002RunReceipt:
        """Bind qualified inner runtime bytes to their owner-evidence identities.

        The frozen asset envelope proves the exact bytes.  Downstream domain
        artifacts use append-only owner-evidence digests, so the completed
        receipt must carry those outer identities before it is signed or
        registered.  This one-way rewrite happens only while the receipt is
        still unissued.
        """

        owner_binding = self._assets.verify_owner_binding(
            self._registry, owner_binding, workload_id=receipt.workload_id
        )
        profile, prompt, schema, toolset, runtime = owner_binding.owner_digests
        for digest, kind in (
            (profile, EvidenceKind.PROFILE),
            (prompt, EvidenceKind.PROMPT),
            (schema, EvidenceKind.SCHEMA),
            (toolset, EvidenceKind.TOOLSET),
            (runtime, EvidenceKind.RUNTIME),
        ):
            self._registry.require(digest, kind)
        payload = {
            **receipt.unsigned_payload(),
            "profile_sha256": profile,
            "prompt_sha256": prompt,
            "schema_sha256": schema,
            "toolset_sha256": toolset,
            "runtime_sha256": runtime,
        }
        return replace(
            receipt,
            profile_sha256=profile,
            prompt_sha256=prompt,
            schema_sha256=schema,
            toolset_sha256=toolset,
            runtime_sha256=runtime,
            content_sha256=canonical_sha256(payload),
            signature_sha256=self._authority.sign(payload),
        )

    def _receipt(
        self,
        asset: MvpR002RuntimeWorkloadAsset,
        invocation: str,
        subject: str,
        request_sha: str,
        input_lineage: tuple[RuntimeInputRef, ...],
        raw_response: str | None,
        observation: RuntimeObservation | None,
        status: str,
        code: MvpR002RuntimeFailureCode | None,
        stage: MvpR002FailureStage | None,
        *,
        canonical_response: str | None = None,
    ) -> MvpR002RunReceipt:
        provider = model = effort = response_id = None
        usage: tuple[int, int, int, int, int, int] | None = None
        latency = None
        reroutes: tuple[str, ...] = ()
        activities: tuple[str, ...] = ()
        if observation is not None:
            provider, model, effort, response_id, usage, latency, reroutes, activities = observation
        payload: dict[str, JsonValue] = {
            "workload_id": asset.workload_id,
            "invocation_id": _text(invocation, "invocation"),
            "run_id": _text(invocation, "invocation"),
            "subject_sha256": _digest(subject, "subject"),
            "input_lineage": tuple(item.to_dict() for item in input_lineage),
            "qualification_report_sha256": asset.qualification_report.content_sha256,
            "config_sha256": asset.config.content_sha256,
            "asset_ref": self._assets.asset_ref.to_dict(),
            "profile_sha256": asset.config.profile_sha256,
            "prompt_sha256": asset.prompt_sha256,
            "schema_sha256": asset.schema_sha256,
            "toolset_sha256": canonical_sha256(()),
            "runtime_sha256": asset.runtime_sha256,
            "raw_request_sha256": _digest(request_sha, "request"),
            "canonical_request_sha256": _digest(request_sha, "request"),
            "raw_response_sha256": _bytes_digest(raw_response.encode()) if raw_response else None,
            "canonical_response_sha256": canonical_response,
            "response_id": cast(JsonValue, response_id),
            "requested_model_id": asset.config.model_id,
            "requested_reasoning_effort": asset.config.reasoning_effort,
            "actual_provider": cast(JsonValue, provider),
            "actual_model_id": cast(JsonValue, model),
            "actual_reasoning_effort": cast(JsonValue, effort),
            "input_tokens": cast(JsonValue, usage[0] if usage else None),
            "cached_input_tokens": cast(JsonValue, usage[1] if usage else None),
            "output_tokens": cast(JsonValue, usage[2] if usage else None),
            "reasoning_tokens": cast(JsonValue, usage[3] if usage else None),
            "cache_write_input_tokens": cast(JsonValue, usage[4] if usage else None),
            "total_tokens": cast(JsonValue, usage[5] if usage else None),
            "latency_ms": cast(JsonValue, latency),
            "reroute_sha256s": reroutes,
            "activity_sha256s": activities,
            "status": status,
            "failure_code": code.value if code else None,
            "failure_stage": stage.value if stage else None,
            "cost_mode": ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE.value,
            "cost_available": False,
            "cost_amount": None,
        }
        values: dict[str, object] = {
            **payload,
            "content_sha256": canonical_sha256(payload),
            "signature_sha256": self._authority.sign(payload),
        }
        values["failure_code"] = code
        values["failure_stage"] = stage
        values["cost_mode"] = ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE
        values["input_lineage"] = input_lineage
        values["asset_ref"] = self._assets.asset_ref
        return MvpR002RunReceipt(**values)  # type: ignore[arg-type]

    def _issue(self, receipt: MvpR002RunReceipt) -> tuple[MvpR002RunReceipt, str]:
        if receipt.status == "COMPLETED":
            raise PermissionError("completed runtime receipts can be committed only with output and run evidence")
        artifact = self._issuer.issue(EvidenceKind.RUNTIME_RECEIPT, receipt.to_dict())
        self._registry.add(artifact)
        return receipt, artifact.content_sha256


def _capability_probe_specs() -> tuple[MvpR002CapabilityProbeSpec, ...]:
    """Load the accepted local bytes without creating qualification evidence."""

    from futures_agent_os.adapters.research_model_payload import (
        R002_EXPERIMENT_DESIGN_SCHEMA,
        R002_INDEPENDENT_CRITIC_SCHEMA,
        R002_RESEARCH_SYNTHESIS_SCHEMA,
    )

    definitions: tuple[tuple[str, str, str, JsonValue], ...] = (
        (
            MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
            "medium",
            "r002-research-synthesis-v1.md",
            _freeze(R002_RESEARCH_SYNTHESIS_SCHEMA),
        ),
        (
            MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
            "medium",
            "r002-experiment-design-v1.md",
            _freeze(R002_EXPERIMENT_DESIGN_SCHEMA),
        ),
        (
            MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
            "high",
            "r002-independent-critic-v1.md",
            _freeze(R002_INDEPENDENT_CRITIC_SCHEMA),
        ),
    )
    specs: list[MvpR002CapabilityProbeSpec] = []
    prompt_root = (_REPOSITORY_ROOT / "prompts" / "mvp-r").resolve()
    for workload, effort, filename, schema in definitions:
        path = (_REPOSITORY_ROOT / "prompts" / "mvp-r" / filename).resolve()
        if path.parent != prompt_root or not path.is_file():
            raise PermissionError("capability probe requires an exact approved prompt asset")
        runtime_identity = f"mvp-r-002.runtime.{workload}.v1"
        specs.append(
            MvpR002CapabilityProbeSpec(
                workload,
                "gpt-5.6-terra",
                effort,
                _bytes_digest(path.read_bytes()),
                canonical_sha256(schema),
                canonical_sha256(()),
                _runtime_digest(runtime_identity),
            )
        )
    return tuple(specs)


def mvp_r_002_capability_probe_plan() -> tuple[MvpR002CapabilityProbeSpec, ...]:
    """Return the fixed at-most-three-attempt plan; this function has no provider effects."""

    return _capability_probe_specs()


def _schema_matches(value: object, schema: Mapping[str, object]) -> bool:
    """Small closed-schema verifier for the three local R-002 response shapes."""

    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
            return False
        properties = _mapping(schema.get("properties"), "probe schema properties")
        required = _sequence(schema.get("required"), "probe schema required")
        if any(type(item) is not str or item not in value for item in required):
            return False
        if schema.get("additionalProperties") is False and set(value) != set(properties):
            return False
        return all(
            key not in value or _schema_matches(value[key], _mapping(child, "probe schema child"))
            for key, child in properties.items()
        )
    if expected_type == "array":
        if type(value) not in (list, tuple):
            return False
        values = cast(list[object] | tuple[object, ...], value)
        minimum = schema.get("minItems", 0)
        return (
            type(minimum) is int
            and len(values) >= minimum
            and all(_schema_matches(item, _mapping(schema.get("items"), "probe schema items")) for item in values)
        )
    if expected_type == "string":
        if type(value) is not str:
            return False
        minimum = schema.get("minLength")
        if type(minimum) is int and len(value) < minimum:
            return False
        choices = schema.get("enum")
        choice_values = cast(tuple[object, ...] | list[object], choices) if type(choices) in (list, tuple) else ()
        return (not choice_values or value in choice_values) and (
            type(schema.get("pattern")) is not str or re.fullmatch(cast(str, schema["pattern"]), value) is not None
        )
    if expected_type == "null":
        return value is None
    if type(expected_type) is list:
        return any(_schema_matches(value, {**schema, "type": candidate}) for candidate in expected_type)
    return False


def _observe_capability_probe(
    spec: MvpR002CapabilityProbeSpec,
    response: object | None,
    *,
    provider_failed: bool,
    provider_failure_code: MvpR002RuntimeFailureCode = MvpR002RuntimeFailureCode.PROVIDER_CALL_FAILED,
) -> MvpR002CapabilityProbeReceipt:
    request_sha256 = canonical_sha256(
        {
            "protocol": "mvp-r-002.phase0.capability-probe.v1",
            "workload_id": spec.workload_id,
            "prompt_sha256": spec.prompt_sha256,
            "schema_sha256": spec.schema_sha256,
            "toolset_sha256": spec.toolset_sha256,
            "runtime_sha256": spec.runtime_sha256,
        }
    )
    if provider_failed:
        return MvpR002CapabilityProbeReceipt(
            spec,
            "FAILED",
            None,
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            (),
            (),
            request_sha256,
            None,
            provider_failure_code.value,
            MvpR002FailureStage.PROVIDER.value,
        )
    provider, model, effort, response_id, usage, latency = _extract_observed_scalars(response)
    response_sha256: str | None = None
    reroutes: tuple[str, ...] = ()
    activities: tuple[str, ...] = ()
    provider_turn_started = False
    provider_response_observed = False

    def receipt(
        status: str,
        code: MvpR002RuntimeFailureCode | None,
        stage: MvpR002FailureStage | None,
    ) -> MvpR002CapabilityProbeReceipt:
        return MvpR002CapabilityProbeReceipt(
            spec,
            status,
            provider,
            model,
            effort,
            response_id,
            usage,
            latency,
            provider_turn_started,
            provider_response_observed,
            reroutes,
            activities,
            request_sha256,
            response_sha256,
            code.value if code is not None else None,
            stage.value if stage is not None else None,
        )

    try:
        frozen_response = _freeze(response)
        response_sha256 = canonical_sha256(frozen_response)
        response_map = _mapping(frozen_response, "capability probe response")
        provider_turn_started = response_map.get("provider_turn_started") is True
        provider_response_observed = response_map.get("provider_response_observed") is True
        effort_conflict = response_map.get("reasoning_effort_error") == "EFFORT_METADATA_CONFLICT"
        provider = _text(response_map["model_provider"], "provider")
        model = _text(response_map["model"], "model")
        if effort_conflict:
            observed_effort = response_map.get("reasoning_effort")
            effort = observed_effort if type(observed_effort) is str and observed_effort else None
        else:
            effort = _text(response_map["reasoning_effort"], "effort")
        response_id = _text(response_map["response_id"], "response id")
        usage = _usage(_mapping(response_map["usage"], "usage"))
        latency = _integer(response_map["latencyMs"], "latency")
        reroutes = _hashes(response_map.get("reroutes", ()))
        dynamic_calls = _sequence(response_map.get("dynamic_calls", ()), "dynamic calls")
        server_requests = _sequence(response_map.get("server_requests", ()), "server requests")
        item_types = tuple(_text(item, "item type") for item in _sequence(response_map.get("item_types", ()), "items"))
        disallowed_item_types = tuple(
            item for item in item_types if item not in {"agentMessage", "reasoning", "userMessage"}
        )
        activities = (
            _hashes(
                {
                    "dynamic_calls": dynamic_calls,
                    "server_requests": server_requests,
                    "disallowed_item_types": disallowed_item_types,
                }
            )
            if dynamic_calls or server_requests or disallowed_item_types
            else ()
        )
        code: MvpR002RuntimeFailureCode | None = None
        stage: MvpR002FailureStage | None = None
        if effort_conflict:
            code = MvpR002RuntimeFailureCode.EFFORT_METADATA_CONFLICT
        elif provider != "openai":
            code = MvpR002RuntimeFailureCode.PROVIDER_MISMATCH
        elif model != spec.requested_model_id:
            code = MvpR002RuntimeFailureCode.MODEL_DRIFT
        elif effort != spec.requested_reasoning_effort:
            code = MvpR002RuntimeFailureCode.EFFORT_DRIFT
        elif reroutes:
            code = MvpR002RuntimeFailureCode.REROUTE_REJECTED
        elif activities:
            code = MvpR002RuntimeFailureCode.ACTIVITY_REJECTED
        elif response_map.get("status") != "completed" or response_map.get("timed_out") is True:
            code = MvpR002RuntimeFailureCode.TURN_INCOMPLETE
        elif not provider_turn_started:
            code = MvpR002RuntimeFailureCode.TURN_START_UNPROVEN
        elif not provider_response_observed:
            code = MvpR002RuntimeFailureCode.RESPONSE_UNPROVEN
        elif (
            "cost_mode" not in response_map or "cost_available" not in response_map or "cost_amount" not in response_map
        ):
            code = MvpR002RuntimeFailureCode.COST_MISSING
        elif (
            response_map["cost_mode"] != spec.cost_mode.value
            or response_map["cost_available"] is not spec.cost_available
        ):
            code = MvpR002RuntimeFailureCode.COST_INCONSISTENT
        elif response_map["cost_amount"] is not None:
            code = MvpR002RuntimeFailureCode.COST_AMOUNT_REJECTED
        finals = _sequence(response_map.get("final_texts", ()), "final texts")
        if code is None and len(finals) != 1:
            code = MvpR002RuntimeFailureCode.FINAL_COUNT_INVALID
        if code is None:
            parsed = json.loads(_text(finals[0], "final text"))
            schema = next(item[3] for item in _capability_probe_schema_definitions() if item[0] == spec.workload_id)
            if not _schema_matches(parsed, cast(Mapping[str, object], schema)):
                code = MvpR002RuntimeFailureCode.RESPONSE_SCHEMA_INVALID
                stage = MvpR002FailureStage.RESPONSE
        if code is not None:
            return receipt("FAILED", code, stage or MvpR002FailureStage.OBSERVATION)
        return receipt("COMPLETED", None, None)
    except json.JSONDecodeError:
        return receipt("FAILED", MvpR002RuntimeFailureCode.RESPONSE_INVALID_JSON, MvpR002FailureStage.RESPONSE)
    except KeyError, TypeError, ValueError, PermissionError:
        return receipt("FAILED", MvpR002RuntimeFailureCode.USAGE_INCOMPLETE, MvpR002FailureStage.OBSERVATION)


def _capability_probe_schema_definitions() -> tuple[tuple[str, str, str, JsonValue], ...]:
    from futures_agent_os.adapters.research_model_payload import (
        R002_EXPERIMENT_DESIGN_SCHEMA,
        R002_INDEPENDENT_CRITIC_SCHEMA,
        R002_RESEARCH_SYNTHESIS_SCHEMA,
    )

    return (
        (
            MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
            "medium",
            "r002-research-synthesis-v1.md",
            _freeze(R002_RESEARCH_SYNTHESIS_SCHEMA),
        ),
        (
            MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
            "medium",
            "r002-experiment-design-v1.md",
            _freeze(R002_EXPERIMENT_DESIGN_SCHEMA),
        ),
        (
            MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
            "high",
            "r002-independent-critic-v1.md",
            _freeze(R002_INDEPENDENT_CRITIC_SCHEMA),
        ),
    )


def _capability_probe_payload(spec: MvpR002CapabilityProbeSpec) -> Mapping[str, object]:
    """Freeze one approved prompt/schema into the closure-owned request shape."""

    filenames = {
        MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD: "r002-research-synthesis-v1.md",
        MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD: "r002-experiment-design-v1.md",
        MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD: "r002-independent-critic-v1.md",
    }
    filename = filenames.get(spec.workload_id)
    if filename is None:
        raise PermissionError("capability probe workload is not fixed")
    path = (_REPOSITORY_ROOT / "prompts" / "mvp-r" / filename).resolve()
    if path.parent != (_REPOSITORY_ROOT / "prompts" / "mvp-r").resolve() or not path.is_file():
        raise PermissionError("capability probe prompt escaped the fixed repository root")
    prompt = path.read_text(encoding="utf-8")
    schema = next(item[3] for item in _capability_probe_schema_definitions() if item[0] == spec.workload_id)
    runtime_identity = f"mvp-r-002.runtime.{spec.workload_id}.v1"
    if (
        _bytes_digest(prompt.encode()) != spec.prompt_sha256
        or canonical_sha256(schema) != spec.schema_sha256
        or canonical_sha256(()) != spec.toolset_sha256
        or _runtime_digest(runtime_identity) != spec.runtime_sha256
    ):
        raise PermissionError("capability probe assets drifted from the accepted fixed bytes")
    return cast(
        Mapping[str, object],
        _freeze(
            {
                "workload": spec.workload_id,
                "model": spec.requested_model_id,
                "effort": spec.requested_reasoning_effort,
                "prompt": prompt,
                "schema": schema,
                "input": canonical_json_text(
                    {
                        "protocol": "mvp-r-002.phase0.capability-probe.v1",
                        "purpose": "minimal_provider_capability_only",
                    }
                ),
                "tools": (),
                "runtime_identity": runtime_identity,
            }
        ),
    )


def _build_orchestrator_type() -> type:
    """Build the public façade around closure-only runtime capabilities."""

    executor_type = _MvpR002RuntimeExecutor
    states: dict[object, object] = {}

    @dataclass(frozen=True, slots=True)
    class RuntimeState:
        research_authority: PhaseZeroAuthority
        registry: OwnerEvidenceRegistry
        assets: FrozenRuntimeAssets
        binding: ExperimentBinding
        synthesis_binding: RuntimeOwnerBinding
        experiment_design_binding: RuntimeOwnerBinding
        critic_binding: RuntimeOwnerBinding
        executor: object
        research: ResearchRunner
        critic: IndependentCritic
        issuer: OwnerEvidenceIssuer

    @dataclass(slots=True)
    class CapabilityProbeState:
        transport: Callable[[Mapping[str, object]], Mapping[str, object]]
        specs: tuple[MvpR002CapabilityProbeSpec, ...]
        payloads: Mapping[str, Mapping[str, object]]
        lock: Lock
        consumed: bool = False

    class Orchestrator:
        """Opaque façade; executable state exists only in the factory closure."""

        __slots__ = ("__opaque_id",)

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise PermissionError("Phase-0 runtime orchestrators must be factory-issued")

        def __setattr__(self, _name: str, _value: object) -> None:
            raise AttributeError("Phase-0 orchestrator identity is immutable")

        def __delattr__(self, _name: str) -> None:
            raise AttributeError("Phase-0 orchestrator identity is immutable")

        @classmethod
        def create_capability_probe(
            cls,
            transport: Callable[[Mapping[str, object]], Mapping[str, object]],
        ) -> Orchestrator:
            """Issue at most three fixed-order minimal provider attempts.

            This composition root deliberately owns no candidate packet,
            qualification registry, suite, roster, or activation capability.
            Its receipts are evidence for later qualification planning only.
            """

            if not callable(transport):
                raise TypeError("capability probe requires a callable generic transport")
            opaque_id = object()
            specs = _capability_probe_specs()
            instance = object.__new__(cls)
            object.__setattr__(instance, "_Orchestrator__opaque_id", opaque_id)
            states[opaque_id] = CapabilityProbeState(
                transport,
                specs,
                MappingProxyType({spec.workload_id: _capability_probe_payload(spec) for spec in specs}),
                Lock(),
            )
            return instance

        @classmethod
        def create(
            cls,
            transport: Callable[[Mapping[str, object]], Mapping[str, object]],
            research_authority: PhaseZeroAuthority,
            critic_authority: PhaseZeroAuthority,
            registry: OwnerEvidenceRegistry,
            assets: FrozenRuntimeAssets,
            experiment_binding: ExperimentBinding,
            synthesis_binding: RuntimeOwnerBinding,
            experiment_design_binding: RuntimeOwnerBinding,
            critic_binding: RuntimeOwnerBinding,
        ) -> Orchestrator:
            if not callable(transport):
                raise TypeError("Phase-0 orchestrator requires a callable generic transport")
            if type(experiment_binding) is not ExperimentBinding or any(
                type(binding) is not RuntimeOwnerBinding
                for binding in (synthesis_binding, experiment_design_binding, critic_binding)
            ):
                raise TypeError("Phase-0 orchestrator requires exact domain and runtime owner bindings")
            if (
                type(research_authority) is not PhaseZeroAuthority
                or type(critic_authority) is not PhaseZeroAuthority
                or critic_authority == research_authority
                or type(registry) is not OwnerEvidenceRegistry
                or type(assets) is not FrozenRuntimeAssets
            ):
                raise PermissionError("Phase-0 orchestrator requires exact independent owner authorities")
            verified_assets = assets.verify(research_authority)
            bindings = tuple(
                verified_assets.verify_owner_binding(registry, binding, workload_id=workload)
                for binding, workload in zip(
                    (synthesis_binding, experiment_design_binding, critic_binding),
                    (
                        MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
                        MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
                        MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
                    ),
                    strict=True,
                )
            )
            if (
                len({binding.inner_digests for binding in bindings}) != 3
                or len({binding.owner_digests for binding in bindings}) != 3
            ):
                raise PermissionError("the three runtime workloads require independent cross-proofs")

            opaque_id = object()
            pending_leases: dict[object, tuple[object, str, str, str]] = {}

            def execute(payload: Mapping[str, object]) -> Mapping[str, object]:
                required = {
                    "model",
                    "effort",
                    "prompt",
                    "schema",
                    "input",
                    "tools",
                    "runtime_identity",
                    "workload",
                }
                if set(payload) != required or payload.get("tools") != ():
                    raise PermissionError("R-002 requires one empty-tool frozen structured turn")
                workload = _text(payload.get("workload"), "workload")
                if workload not in {
                    MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
                    MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
                    MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
                }:
                    raise PermissionError("R-002 workload is not frozen")
                frozen_payload = _freeze(payload)
                config_sha256 = _execution_config_sha256(payload)
                request_sha256 = canonical_sha256(frozen_payload)
                lease = object()
                pending_leases[lease] = (opaque_id, workload, config_sha256, request_sha256)
                expected = pending_leases.pop(lease, None)
                observed = (
                    opaque_id,
                    workload,
                    _execution_config_sha256(payload),
                    canonical_sha256(_freeze(payload)),
                )
                if expected != observed:
                    raise PermissionError("R-002 execution lease is reused or crossed request/config/owner")
                return transport(payload)

            executor = executor_type(
                execute,
                research_authority,
                registry,
                verified_assets,
                critic_authority,
            )
            state = RuntimeState(
                research_authority,
                registry,
                verified_assets,
                experiment_binding,
                bindings[0],
                bindings[1],
                bindings[2],
                executor,
                ResearchRunner(research_authority, registry, experiment_binding),
                IndependentCritic(research_authority, critic_authority, registry),
                OwnerEvidenceIssuer(research_authority, "mvp-r-002.phase0-orchestrator"),
            )
            instance = object.__new__(cls)
            object.__setattr__(instance, "_Orchestrator__opaque_id", opaque_id)
            states[opaque_id] = state
            return instance

        def run_plan_once(self) -> tuple[MvpR002CapabilityProbeReceipt, ...]:
            """Consume the fixed plan once; no public per-workload replay exists."""

            opaque_id = object.__getattribute__(self, "_Orchestrator__opaque_id")
            state = states.get(opaque_id)
            if type(state) is not CapabilityProbeState:
                raise PermissionError("capability probe requires its dedicated factory-issued composition root")
            with state.lock:
                if state.consumed:
                    raise PermissionError("capability probe plan is already consumed")
                state.consumed = True
            receipts: list[MvpR002CapabilityProbeReceipt] = []
            for spec in state.specs:
                frozen = state.payloads[spec.workload_id]
                official_payload: Mapping[str, object] = MappingProxyType(
                    {
                        "model": frozen["model"],
                        "effort": frozen["effort"],
                        "instructions": frozen["prompt"],
                        "input": frozen["input"],
                        "tools": frozen["tools"],
                        "output_schema": frozen["schema"],
                        "timeout_seconds": 120,
                    }
                )
                try:
                    response = state.transport(official_payload)
                except Exception as error:
                    from futures_agent_os.adapters.codex_app_server import LocalWireSerializationError

                    failure_code = (
                        MvpR002RuntimeFailureCode.LOCAL_WIRE_SERIALIZATION_FAILURE
                        if isinstance(error, LocalWireSerializationError)
                        else MvpR002RuntimeFailureCode.PROVIDER_CALL_FAILED
                    )
                    observed = _observe_capability_probe(
                        spec,
                        None,
                        provider_failed=True,
                        provider_failure_code=failure_code,
                    )
                else:
                    observed = _observe_capability_probe(spec, response, provider_failed=False)
                receipts.append(observed)
                if observed.status != "COMPLETED":
                    break
            return tuple(receipts)

        def run_research(
            self,
            candidate: ResearchCandidatePacket,
            *,
            synthesis_invocation_id: str,
            experiment_invocation_id: str,
        ) -> AgentRunOutcome:
            opaque_id = object.__getattribute__(self, "_Orchestrator__opaque_id")
            state = states.get(opaque_id)
            if type(state) is not RuntimeState:
                raise PermissionError("Phase-0 orchestrator capability is not factory-issued")
            research_binding = state.assets.verify_owner_binding(
                state.registry,
                state.synthesis_binding,
                workload_id=MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
            )
            experiment_binding = state.assets.verify_owner_binding(
                state.registry,
                state.experiment_design_binding,
                workload_id=MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
            )
            if research_binding.owner_digests != (
                state.binding.profile_sha256,
                state.binding.prompt_sha256,
                state.binding.schema_sha256,
                candidate.evidence.toolset_sha256,
                candidate.evidence.runtime_sha256,
            ):
                raise PermissionError("synthesis owner binding does not match the domain experiment input")
            executor = cast(Any, state.executor)
            synthesis = executor._research_proposal(
                candidate,
                invocation_id=synthesis_invocation_id,
                owner_binding=research_binding,
            )
            if type(synthesis.value) is not ResearchProposal or synthesis.receipt.status != "COMPLETED":
                raise PermissionError("research orchestration requires a completed typed synthesis output")
            proposal = synthesis.value
            experiment = executor._experiment_request(
                candidate,
                state.binding,
                invocation_id=experiment_invocation_id,
                owner_binding=experiment_binding,
            )
            if experiment.value is None or experiment.receipt.status != "COMPLETED":
                raise PermissionError("research orchestration requires a completed typed experiment output")
            brief = state.research.preview_agent_brief(candidate, proposal)
            synthesis_receipt = state.issuer.issue(EvidenceKind.RUNTIME_RECEIPT, synthesis.receipt.to_dict())
            experiment_receipt = state.issuer.issue(EvidenceKind.RUNTIME_RECEIPT, experiment.receipt.to_dict())
            authorization = ResearchInvocationAuthorization.issue(
                state.research_authority,
                candidate_sha256=candidate.content_sha256,
                request_sha256=proposal.content_sha256,
                profile_sha256=synthesis.receipt.profile_sha256,
                prompt_sha256=synthesis.receipt.prompt_sha256,
                schema_sha256=synthesis.receipt.schema_sha256,
                toolset_sha256=synthesis.receipt.toolset_sha256,
                runtime_sha256=synthesis.receipt.runtime_sha256,
                invocation_id=synthesis.receipt.invocation_id,
            )
            authorization_artifact = state.issuer.issue_research_invocation(authorization)
            synthesis_output = state.issuer.issue(
                EvidenceKind.MODEL_OUTPUT,
                {
                    "workload_id": synthesis.receipt.workload_id,
                    "receipt_sha256": synthesis_receipt.content_sha256,
                    "wire": _proposal_wire(proposal),
                },
            )
            experiment_output = state.issuer.issue(
                EvidenceKind.MODEL_OUTPUT,
                {
                    "workload_id": experiment.receipt.workload_id,
                    "receipt_sha256": experiment_receipt.content_sha256,
                    "wire": {"design_category": "USE_FROZEN_BINDING"},
                },
            )
            qualification = FrozenProfileQualification.hydrate(
                state.registry.require(synthesis.receipt.profile_sha256, EvidenceKind.PROFILE).payload()
            )
            run = state.issuer.issue(
                EvidenceKind.RESEARCH_RUN,
                {
                    "candidate_sha256": candidate.content_sha256,
                    "proposal_sha256": proposal.content_sha256,
                    "agent_brief_sha256": brief.content_sha256,
                    "invocation_authorization_sha256": authorization_artifact.content_sha256,
                    "invocation_id": synthesis.receipt.invocation_id,
                    "synthesis_receipt_sha256": synthesis_receipt.content_sha256,
                    "experiment_design_receipt_sha256": experiment_receipt.content_sha256,
                    "synthesis_output_sha256": synthesis_output.content_sha256,
                    "experiment_design_output_sha256": experiment_output.content_sha256,
                    "synthesis_owner_binding": state.synthesis_binding.to_dict(),
                    "experiment_design_owner_binding": state.experiment_design_binding.to_dict(),
                    "experiment_binding_sha256": canonical_sha256(state.binding.to_dict()),
                    "response_sha256": brief.content_sha256,
                    "response_id": cast(str, synthesis.receipt.response_id),
                    "workload_id": synthesis.receipt.workload_id,
                    "profile_sha256": synthesis.receipt.profile_sha256,
                    "prompt_sha256": synthesis.receipt.prompt_sha256,
                    "schema_sha256": synthesis.receipt.schema_sha256,
                    "toolset_sha256": synthesis.receipt.toolset_sha256,
                    "runtime_sha256": synthesis.receipt.runtime_sha256,
                    "actual_provider": cast(str, synthesis.receipt.actual_provider),
                    "actual_model_id": cast(str, synthesis.receipt.actual_model_id),
                    "actual_reasoning_effort": cast(str, synthesis.receipt.actual_reasoning_effort),
                    "actual_profile_id": qualification.profile_id,
                    "input_tokens": cast(int, synthesis.receipt.input_tokens),
                    "output_tokens": cast(int, synthesis.receipt.output_tokens),
                    "reasoning_tokens": cast(int, synthesis.receipt.reasoning_tokens),
                    "cache_tokens": cast(int, synthesis.receipt.cached_input_tokens)
                    + cast(int, synthesis.receipt.cache_write_input_tokens),
                    "latency_ms": cast(int, synthesis.receipt.latency_ms),
                    "reroutes": synthesis.receipt.reroute_sha256s,
                },
            )
            state.registry.add_many_atomic(
                (
                    synthesis_receipt,
                    experiment_receipt,
                    authorization_artifact,
                    synthesis_output,
                    experiment_output,
                    run,
                )
            )
            return state.research.agent_without_critic(candidate, proposal, run.content_sha256)

        def run_critic(
            self,
            candidate: ResearchCandidatePacket,
            agent_outcome: AgentRunOutcome,
            *,
            run_id: str,
        ) -> AgentCriticOutcome:
            opaque_id = object.__getattribute__(self, "_Orchestrator__opaque_id")
            state = states.get(opaque_id)
            if type(state) is not RuntimeState:
                raise PermissionError("Phase-0 orchestrator capability is not factory-issued")
            critic_binding = state.assets.verify_owner_binding(
                state.registry,
                state.critic_binding,
                workload_id=MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
            )
            invocation = state.critic.prepare_request(
                candidate,
                agent_outcome,
                run_id=run_id,
                profile_sha256=critic_binding.profile_sha256,
                prompt_sha256=critic_binding.prompt_sha256,
                schema_sha256=critic_binding.schema_sha256,
                toolset_sha256=critic_binding.toolset_sha256,
                runtime_sha256=critic_binding.runtime_sha256,
            )
            result = cast(Any, state.executor)._critic_decision(invocation, critic_binding)
            if type(result.value) is not MvpR002CriticWireDecision or result.receipt.status != "COMPLETED":
                raise PermissionError("critic orchestration requires a completed typed critic output")
            wire = {
                "decision": result.value.decision.value,
                "reason_category": result.value.reason.value,
            }
            receipt_artifact = state.issuer.issue(EvidenceKind.RUNTIME_RECEIPT, result.receipt.to_dict())
            output = state.issuer.issue(
                EvidenceKind.MODEL_OUTPUT,
                {
                    "workload_id": result.receipt.workload_id,
                    "receipt_sha256": receipt_artifact.content_sha256,
                    "wire": wire,
                },
            )
            request = state.critic._bind_unregistered_receipt(
                invocation,
                result.receipt,
                receipt_artifact.content_sha256,
            )
            qualification = FrozenProfileQualification.hydrate(
                state.registry.require(result.receipt.profile_sha256, EvidenceKind.PROFILE).payload()
            )
            run = state.issuer.issue(
                EvidenceKind.CRITIC_RUN,
                {
                    "request_sha256": request.content_sha256,
                    "workload_id": request.workload_id,
                    "candidate_sha256": request.candidate_sha256,
                    "brief_sha256": request.brief_sha256,
                    "profile_sha256": request.profile_sha256,
                    "prompt_sha256": request.prompt_sha256,
                    "schema_sha256": request.schema_sha256,
                    "toolset_sha256": request.toolset_sha256,
                    "runtime_sha256": request.runtime_sha256,
                    "critic_receipt_sha256": receipt_artifact.content_sha256,
                    "critic_output_sha256": output.content_sha256,
                    "critic_owner_binding": state.critic_binding.to_dict(),
                    "decision": result.value.decision.value,
                    "reason_category": result.value.reason.value,
                    "reason": _reason_text(result.value.reason),
                    "actual_provider": cast(str, result.receipt.actual_provider),
                    "actual_model_id": cast(str, result.receipt.actual_model_id),
                    "actual_reasoning_effort": cast(str, result.receipt.actual_reasoning_effort),
                    "actual_profile_id": qualification.profile_id,
                    "input_tokens": cast(int, result.receipt.input_tokens),
                    "output_tokens": cast(int, result.receipt.output_tokens),
                    "reasoning_tokens": cast(int, result.receipt.reasoning_tokens),
                    "cache_tokens": cast(int, result.receipt.cached_input_tokens)
                    + cast(int, result.receipt.cache_write_input_tokens),
                    "latency_ms": cast(int, result.receipt.latency_ms),
                    "reroutes": result.receipt.reroute_sha256s,
                },
            )
            state.registry.add_many_atomic((receipt_artifact, output, run))
            review = state.critic.review(request, run.content_sha256)
            return state.research.agent_with_critic(candidate, agent_outcome, request, review, state.critic)

    Orchestrator.__name__ = "MvpR002PhaseZeroOrchestrator"
    Orchestrator.__qualname__ = "MvpR002PhaseZeroOrchestrator"
    return Orchestrator


MvpR002PhaseZeroOrchestrator = _build_orchestrator_type()
globals().pop("_MvpR002RuntimeExecutor", None)


def _integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be non-negative exact integer")
    return value


def _usage(value: Mapping[str, object]) -> tuple[int, int, int, int, int, int]:
    required = {
        "inputTokens",
        "cachedInputTokens",
        "outputTokens",
        "reasoningOutputTokens",
        "cacheWriteInputTokens",
        "totalTokens",
    }
    if set(value) != required:
        raise ValueError("usage fields are incomplete")
    result = tuple(
        _integer(value[key], key)
        for key in (
            "inputTokens",
            "cachedInputTokens",
            "outputTokens",
            "reasoningOutputTokens",
            "cacheWriteInputTokens",
            "totalTokens",
        )
    )
    if (
        result[1] > result[0]
        or result[3] > result[2]
        or result[4] > result[0]
        or result[1] + result[4] > result[0]
        or result[5] != result[0] + result[2]
    ):
        raise ValueError("usage relationships are incongruent")
    return cast(tuple[int, int, int, int, int, int], result)


def _extract_observed_scalars(
    value: object,
) -> tuple[str | None, str | None, str | None, str | None, tuple[int, int, int, int, int, int] | None, int | None]:
    """Preserve trustworthy scalar observations even when raw freezing fails."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        return None, None, None, None, None, None

    def text_value(name: str) -> str | None:
        candidate = value.get(name)
        return candidate if type(candidate) is str and candidate else None

    observed_usage: tuple[int, int, int, int, int, int] | None = None
    candidate_usage = value.get("usage")
    if isinstance(candidate_usage, Mapping) and all(type(key) is str for key in candidate_usage):
        try:
            observed_usage = _usage(cast(Mapping[str, object], candidate_usage))
        except KeyError, TypeError, ValueError:
            pass
    candidate_latency = value.get("latencyMs")
    observed_latency = candidate_latency if type(candidate_latency) is int and candidate_latency >= 0 else None
    return (
        text_value("model_provider"),
        text_value("model"),
        text_value("reasoning_effort"),
        text_value("response_id"),
        observed_usage,
        observed_latency,
    )


def _hashes(value: object) -> tuple[str, ...]:
    frozen = _freeze(value)
    items = frozen if type(frozen) is tuple else (frozen,)
    return tuple(canonical_sha256(item) for item in items)


def _proposal_wire(proposal: ResearchProposal) -> dict[str, JsonValue]:
    return {
        "intent": proposal.intent.value,
        "action": proposal.action.value,
        "why_now": proposal.why_now.value,
        "supporting_claims": tuple(item.to_dict() for item in proposal.supporting_claims),
        "strongest_counter_claim": proposal.strongest_counter_claim.to_dict(),
        "additional_unknowns": tuple(item.value for item in proposal.additional_unknowns),
        "falsifiable_hypothesis": proposal.falsifiable_hypothesis.value,
        "source_refs": tuple(item.to_dict() for item in proposal.source_refs),
    }


def _reason_text(category: NarrativeCategory) -> str:
    return {
        NarrativeCategory.SCREENING_SUPPORTS_RESEARCH: "冻结来源支持继续研究",
        NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN: "独立窗口结果仍未知",
        NarrativeCategory.FROZEN_THRESHOLD_RATIONALE: "按冻结门槛映射研究处置",
        NarrativeCategory.FROZEN_HYPOTHESIS: "若独立窗口未通过冻结门槛则命题不成立",
        NarrativeCategory.DETERMINISTIC_INPUT_UNAVAILABLE: "确定性输入不可用",
        NarrativeCategory.INPUT_RECOVERY_REEVALUATION: "输入恢复后可重新评估",
        NarrativeCategory.FIXED_ABLATION: "固定消融处置",
        NarrativeCategory.ABLATION_COUNTERFACTUAL: "该基线不使用候选差异",
    }[category]


def _proposal_from_wire(value: Mapping[str, object], candidate: ResearchCandidatePacket) -> ResearchProposal:
    expected = {
        "intent",
        "action",
        "why_now",
        "supporting_claims",
        "strongest_counter_claim",
        "additional_unknowns",
        "falsifiable_hypothesis",
        "source_refs",
    }
    if set(value) != expected:
        raise ValueError("research wire fields are not closed")
    proposal = ResearchProposal(
        candidate.content_sha256,
        ProposalIntent(_text(value["intent"], "intent")),
        ResearchAction(_text(value["action"], "action")),
        NarrativeCategory(_text(value["why_now"], "why-now")),
        tuple(
            GroundedTextClaim.hydrate(_mapping(item, "claim"))
            for item in _sequence(value["supporting_claims"], "claims")
        ),
        GroundedTextClaim.hydrate(_mapping(value["strongest_counter_claim"], "counter")),
        tuple(
            NarrativeCategory(_text(item, "unknown")) for item in _sequence(value["additional_unknowns"], "unknowns")
        ),
        NarrativeCategory(_text(value["falsifiable_hypothesis"], "hypothesis")),
        tuple(SourceReference.hydrate(_mapping(item, "source")) for item in _sequence(value["source_refs"], "sources")),
    )
    if tuple(item.to_dict() for item in proposal.source_refs) != tuple(item.to_dict() for item in candidate.sources):
        raise PermissionError("research wire must preserve exact candidate sources")
    allowed = {
        "ELIGIBLE": {ResearchAction.TEST_NEXT, ResearchAction.WATCH_FOR_DATA, ResearchAction.REJECT_AS_UNSUPPORTED},
        "INSUFFICIENT_EVIDENCE": {ResearchAction.WATCH_FOR_DATA, ResearchAction.REJECT_AS_UNSUPPORTED},
        "REJECTED": {ResearchAction.REJECT_AS_UNSUPPORTED},
    }[candidate.eligibility.value]
    if proposal.action not in allowed:
        raise PermissionError("research action violates deterministic eligibility")
    return proposal


__all__ = [
    "FrozenRuntimeAssets",
    "MvpR002CriticWireDecision",
    "MvpR002FailureStage",
    "MvpR002PhaseZeroOrchestrator",
    "MvpR002RunReceipt",
    "MvpR002RuntimeAssets",
    "MvpR002RuntimeFailureCode",
    "MvpR002RuntimeResult",
    "MvpR002RuntimeWorkloadAsset",
]
