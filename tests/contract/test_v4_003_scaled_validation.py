from decimal import Decimal

import pytest

from futures_agent_os.research_experiment import (
    ALL_VALIDATIONS,
    ArtifactStatus,
    CompatibleEvidence,
    CompatibleSource,
    FrozenValidationDataset,
    PinnedRef,
    ScaleValidationConfig,
    ScaleValidationRunner,
    ScenarioDefinition,
    StrategyDefinition,
    StrategyDirection,
    ValidationKind,
    assemble_promotion_evidence,
)
from futures_agent_os.shared_kernel import canonical_sha256


def _ref(name: str, digest: str) -> PinnedRef:
    return PinnedRef(name, "1", digest * 64)


def _dataset(count: int = 40, *, zero_features: bool = False) -> FrozenValidationDataset:
    features = tuple(
        Decimal("0") if zero_features else Decimal("0.02") if index % 2 == 0 else Decimal("-0.02")
        for index in range(count)
    )
    returns = tuple(Decimal("0.01") if index % 2 == 0 else Decimal("-0.008") for index in range(count))
    times = tuple(f"2026-01-{index + 1:02d}T00:00:00Z" for index in range(count))
    return FrozenValidationDataset(_ref("dataset", "a"), features, returns, times)


def _strategy(name: str = "primary", *, invert: bool = False) -> StrategyDefinition:
    direction = StrategyDirection.INVERT if invert else StrategyDirection.FOLLOW
    digest = "b" if not invert else "c"
    return StrategyDefinition(_ref(name, digest), Decimal("0.005"), direction)


def _config(seed: int = 7) -> ScaleValidationConfig:
    return ScaleValidationConfig(
        20,
        5,
        5,
        1,
        Decimal("0.001"),
        (Decimal("1"), Decimal("2")),
        (Decimal("0"), Decimal("0.001")),
        100,
        seed,
        (Decimal("0"), Decimal("0.005"), Decimal("0.03")),
        (
            ScenarioDefinition("early", 0, 10),
            ScenarioDefinition("adverse", 10, 20, Decimal("-1"), Decimal("0.001")),
        ),
        (_strategy(), _strategy("inverse", invert=True)),
    )


def test_all_validations_are_independent_reproducible_artifacts() -> None:
    runner = ScaleValidationRunner()
    artifacts = runner.run(_dataset(), _strategy(), _config())
    replay = runner.run(_dataset(), _strategy(), _config())
    assert tuple(item.kind for item in artifacts) == ALL_VALIDATIONS
    assert all(item.status is ArtifactStatus.COMPLETE for item in artifacts)
    assert len({item.config_sha256 for item in artifacts}) == len(ALL_VALIDATIONS)
    assert tuple(item.content_sha256 for item in replay) == tuple(item.content_sha256 for item in artifacts)
    assert all(item.source_refs and isinstance(item.warnings, tuple) for item in artifacts)

    package = assemble_promotion_evidence(artifacts)
    assert package.artifacts == artifacts
    assert package.content_sha256 == assemble_promotion_evidence(replay).content_sha256


def test_only_monte_carlo_artifact_changes_when_seed_changes() -> None:
    runner = ScaleValidationRunner()
    base = runner.run(_dataset(), _strategy(), _config(7))
    changed = runner.run(_dataset(), _strategy(), _config(8))
    changed_kinds = tuple(
        left.kind for left, right in zip(base, changed, strict=True) if left.content_sha256 != right.content_sha256
    )
    assert changed_kinds == (ValidationKind.MONTE_CARLO,)


def test_stress_scenario_sweep_and_compare_use_frozen_assumptions() -> None:
    artifacts = ScaleValidationRunner().run(_dataset(), _strategy(), _config())
    by_kind = {item.kind: item for item in artifacts}
    stress = by_kind[ValidationKind.COST_SLIPPAGE_STRESS]
    rows = stress.result["scenarios"]
    assert isinstance(rows, tuple) and len(rows) == 4
    assert rows[0]["net_return"] > rows[-1]["net_return"]

    scenario = by_kind[ValidationKind.SCENARIO_REPLAY]
    assert len(scenario.result["scenarios"]) == 2
    sweep = by_kind[ValidationKind.PARAMETER_SWEEP]
    assert tuple(item["threshold"] for item in sweep.result["parameters"]) == ("0", "0.005", "0.03")
    compare = by_kind[ValidationKind.STRATEGY_COMPARE]
    assert len(compare.result["strategies"]) == 2


def test_incomplete_run_cannot_enter_promotion_evidence() -> None:
    artifacts = ScaleValidationRunner().run(_dataset(10, zero_features=True), _strategy(), _config())
    assert any(item.status is ArtifactStatus.INCOMPLETE and item.warnings for item in artifacts)
    with pytest.raises(ValueError, match="incomplete validation"):
        assemble_promotion_evidence(artifacts)


def test_batch_runs_multiple_frozen_requests_without_cross_contamination() -> None:
    runner = ScaleValidationRunner()
    results = runner.run_batch(
        (
            (_dataset(), _strategy(), _config(7)),
            (_dataset(), _strategy("inverse", invert=True), _config(9)),
        )
    )
    assert len(results) == 2
    assert results[0][0].strategy_sha256 != results[1][0].strategy_sha256


@pytest.mark.parametrize("source", tuple(CompatibleSource))
def test_v1_v2_evidence_replays_through_compatible_contract(source: CompatibleSource) -> None:
    evidence = CompatibleEvidence(
        source,
        PinnedRef("legacy-result", "1", canonical_sha256({"fold_manifest_sha256": "e" * 64})),
        ValidationKind.WALK_FORWARD,
        {"split": "chronological-v1"},
        {"fold_manifest_sha256": "e" * 64},
        ("legacy limitations retained",),
        True,
    )
    digest = evidence.content_sha256
    assert evidence.replay(digest) is evidence
    artifact = evidence.to_artifact(_dataset(), _strategy())
    assert artifact.status is ArtifactStatus.COMPLETE
    assert artifact.source_refs[0] == evidence.source_ref
    with pytest.raises(ValueError, match="digest mismatch"):
        evidence.replay("0" * 64)


def test_compatibility_evidence_detaches_mutable_input() -> None:
    payload = {"nested": {"value": 1}}
    evidence = CompatibleEvidence(
        CompatibleSource.V1,
        PinnedRef("legacy-result", "1", canonical_sha256({"net_return": "0.1"})),
        ValidationKind.COUNTERFACTUAL,
        payload,
        {"net_return": "0.1"},
        (),
        True,
    )
    before = evidence.content_sha256
    payload["nested"]["value"] = 99
    assert evidence.content_sha256 == before
