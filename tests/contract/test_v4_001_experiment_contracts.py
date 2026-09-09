from datetime import UTC, datetime

import pytest

from futures_agent_os.research_experiment.v4_001 import (
    BacktestRun,
    ArtifactEntry,
    ArtifactManifest,
    CostRef,
    DatasetRef,
    current_engine_ref,
    StrategyRef,
    ModelRef,
    PromptRef,
    RuleRef,
    SeedBundle,
    ExperimentPlan,
    execute_backtest,
    replay_backtest,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256


_AT = RecordedAt(datetime(2026, 1, 1, tzinfo=UTC))
_D = "a" * 64


def _plan(*, config: dict[str, object] | None = None) -> ExperimentPlan:
    return ExperimentPlan(
        experiment_id=EntityId.deterministic("experiment", "v4-001"),
        schema_version=SchemaVersion(4, 0),
        dataset_ref=DatasetRef("bars", "2026-01", _D),
        rule_ref=RuleRef("contract-rules", "2026-01", "b" * 64),
        cost_ref=CostRef("fees", "v1", "c" * 64),
        engine_ref=current_engine_ref(),
        model_ref=ModelRef("research-model", "m1", "e" * 64),
        prompt_ref=PromptRef("backtest-prompt", "p1", "f" * 64),
        seeds=SeedBundle({"bootstrap": 7, "simulation": 11}),
        config=config or {"bars": 2, "mode": "base"},
        created_at=_AT,
        strategy_ref=StrategyRef("fixed-direction", "1", "1" * 64),
        environment={
            "code_commit": "test-fixture-revision",
            "runtime_image": "test-python-runtime-v1",
            "resource_spec": {"worker_count": 1},
        },
    )


def test_frozen_plan_and_artifact_manifest_have_stable_identity() -> None:
    plan = _plan()
    assert plan.content_sha256 == _plan().content_sha256
    assert plan.seeds.to_dict() == {"bootstrap": 7, "simulation": 11}
    with pytest.raises(TypeError):
        plan.config["bars"] = 9  # type: ignore[index]

    manifest = ArtifactManifest((ArtifactEntry("result", _D, "artifact://result"),))
    assert manifest.content_sha256 == canonical_sha256(manifest.to_dict())


def test_execution_requires_real_v1_typed_inputs() -> None:
    plan = _plan()
    with pytest.raises(TypeError, match="MarketSnapshot"):
        execute_backtest(plan, ({"close": 100},))


def test_changed_frozen_plan_inputs_change_identity() -> None:
    base = _plan()
    changed = _plan(config={"bars": 3, "mode": "base"})
    assert base.content_sha256 != changed.content_sha256


def test_replay_requires_real_v1_typed_inputs() -> None:
    plan = _plan()
    with pytest.raises(TypeError, match="BacktestRun"):
        replay_backtest(plan, object(), ({"close": 100},))  # type: ignore[arg-type]


def test_real_v1_metrics_replay():
    from datetime import timedelta
    from decimal import Decimal
    from test_market_snapshot_contracts import snapshot, _final_bar, at, SnapshotPurpose
    from futures_agent_os.research_experiment.validation_tools import (
        ValidationConfig,
        ResearchArtifactRef,
        ResearchQueryScope,
        ValidationRunRequest,
        TrustedFeatureEvidencePort,
        TrustedMemorySearchPort,
        TrustedExperimentSearchPort,
        TrustedResearchToolsPort,
        DeterministicResearchTools,
    )

    bars = tuple(_final_bar(i, f"{6000 + i}.0", f"{6000 + i}.0") for i in range(1, 38))
    frozen = snapshot(observations=bars, as_of=at(14), purpose=SnapshotPurpose.RESEARCH)
    config = ValidationConfig(
        EntityId.new("research_validation_config"),
        1,
        20,
        5,
        5,
        20,
        Decimal("0.0001"),
        Decimal("0"),
        Decimal("0"),
        (Decimal("1"), Decimal("2")),
        2,
    )
    ref = ResearchArtifactRef(
        frozen.snapshot_id,
        "market_snapshot",
        frozen.schema_version,
        frozen.expected_content_sha256,
        frozen.as_of,
        RecordedAt(frozen.as_of.value + timedelta(hours=1)),
    )
    scope = ResearchQueryScope(
        frozen.rule_resolution.rule.instrument.reference_id,
        frozen.rule_resolution.rule.instrument.variety.code,
        config.signal_rule,
        config.content_sha256,
        "a" * 64,
        ("AG",),
    )
    feature = TrustedFeatureEvidencePort(b"v4-test-feature-owner-01234567890123")
    memory = TrustedMemorySearchPort(b"v4-test-memory-owner-012345678901234")
    experiment = TrustedExperimentSearchPort(b"v4-test-experiment-owner-0123456789")
    result = TrustedResearchToolsPort(b"v4-test-result-owner-01234567890123")
    request = ValidationRunRequest(
        EntityId.new("research_validation_request"),
        EntityId.new("research_validation_run"),
        ref,
        config,
        scope,
        (),
        memory.issue(()),
        experiment.issue(()),
    )
    tools = DeterministicResearchTools(feature, memory, experiment, result)
    from dataclasses import replace

    plan = replace(
        _plan(config=config.payload()),
        dataset_ref=DatasetRef(str(frozen.snapshot_id), "1", frozen.expected_content_sha256),
        rule_ref=RuleRef("rule", "1", frozen.rule_resolution.rule_content_sha256),
        cost_ref=CostRef(
            "cost",
            "1",
            canonical_sha256(
                {key: config.payload()[key] for key in ("round_trip_cost_bps", "slippage_bps", "stress_multipliers")}
            ),
        ),
    )
    for field in ("dataset_ref", "rule_ref", "cost_ref", "engine_ref"):
        invalid = replace(plan, **{field: replace(getattr(plan, field), content_sha256="0" * 64)})
        with pytest.raises(ValueError, match="reference"):
            execute_backtest(invalid, (frozen, request, tools))
    with pytest.raises(ValueError, match="config"):
        execute_backtest(replace(plan, config={"ignored": True}), (frozen, request, tools))
    run = execute_backtest(plan, (frozen, request, tools))
    replay = replay_backtest(plan, run, (frozen, ValidationRunRequest.hydrate(request.to_dict()), tools))
    assert replay.result == run.result
    assert replay.run_id == run.run_id
    assert run.result["results"] == tuple(item.to_dict() for item in tools.run_snapshot_suite(frozen, request))
    assert any(item["metrics"] for item in run.result["results"])

    assert run.result["reproducibility"] == "REPRODUCIBLE"
    incomplete = execute_backtest(replace(plan, environment={}), (frozen, request, tools))
    assert incomplete.result["reproducibility"] == "NON_REPRODUCIBLE"
    for field in ("model_ref", "prompt_ref", "strategy_ref"):
        changed_plan = replace(plan, **{field: replace(getattr(plan, field), revision="next")})
        changed_run = execute_backtest(changed_plan, (frozen, request, tools))
        assert changed_run.run_id != run.run_id
        assert changed_run.content_sha256 != run.content_sha256
        with pytest.raises(ValueError, match="plan"):
            replay_backtest(changed_plan, run, (frozen, request, tools))
    with pytest.raises(ValueError, match="config"):
        execute_backtest(replace(plan, config={"round_trip_cost_bps": "0.25"}), (frozen, request, tools))
    changed_seed = execute_backtest(replace(plan, seeds=SeedBundle({"simulation": 12})), (frozen, request, tools))
    assert changed_seed.run_id != run.run_id
    assert changed_seed.result["results"] == run.result["results"]  # V1 has no random computation.

    expensive = replace(config, round_trip_cost_bps=Decimal("0.25"))
    expensive_request = replace(
        request, config=expensive, query_scope=replace(scope, config_sha256=expensive.content_sha256)
    )
    expensive_plan = replace(
        plan,
        config=expensive.payload(),
        cost_ref=CostRef(
            "cost",
            "2",
            canonical_sha256(
                {key: expensive.payload()[key] for key in ("round_trip_cost_bps", "slippage_bps", "stress_multipliers")}
            ),
        ),
    )
    expensive_run = execute_backtest(expensive_plan, (frozen, expensive_request, tools))
    assert expensive_run.run_id != run.run_id

    def net_mean(value):
        return next(
            Decimal(dict(item["metrics"])["net_directional_mean"])
            for item in value.result["results"]
            if "net_directional_mean" in dict(item["metrics"])
        )

    assert net_mean(run) - net_mean(expensive_run) == Decimal("0.00002500")

    import json
    from futures_agent_os.shared_kernel import canonical_json_text

    restored_plan = ExperimentPlan.hydrate(json.loads(canonical_json_text(plan.to_dict())))
    restored_run = BacktestRun.hydrate(json.loads(canonical_json_text(run.to_dict())))
    assert restored_plan.content_sha256 == plan.content_sha256
    assert restored_run.content_sha256 == run.content_sha256
    assert replay_backtest(restored_plan, restored_run, (frozen, request, tools)).content_sha256 == run.content_sha256


@pytest.mark.parametrize("name", ["hypothesis_ref", "universe_ref", "feature_graph_ref", "split_ref"])
def test_explicit_research_refs_survive_json_roundtrip(name):
    import json
    from dataclasses import replace
    from futures_agent_os.research_experiment.v4_001 import PinnedRef
    from futures_agent_os.shared_kernel import canonical_json_text

    plan = replace(_plan(), **{name: PinnedRef(name, "1", "9" * 64)})
    restored = ExperimentPlan.hydrate(json.loads(canonical_json_text(plan.to_dict())))
    assert getattr(restored, name) == getattr(plan, name)
    assert restored.content_sha256 == plan.content_sha256
