from decimal import Decimal
import pytest
from futures_agent_os.research_experiment import (
    PinnedRef,
    FrozenValidationDataset,
    StrategyDefinition,
    AttributionSource,
    AttributionAnalyzer,
    ValidationArtifact,
    ValidationKind,
    ArtifactStatus,
)
from futures_agent_os.shared_kernel import canonical_sha256, EntityId


def ref(n):
    return PinnedRef(n, "1", canonical_sha256({n: 1}))


def test_attribution_reconciles_and_warns():
    d = FrozenValidationDataset(
        ref("d"),
        (Decimal(".1"), Decimal("-.1"), Decimal(".1")),
        (Decimal(".1"), Decimal(".2"), Decimal(".05")),
        ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", "2026-02-02T00:00:00Z"),
    )
    s = StrategyDefinition(ref("s"), Decimal(".01"))
    src = AttributionSource.from_validation(
        d, s, base_cost=Decimal(".01"), instruments=("A", "A", "B"), regimes=("TREND", "TREND", "RANGE")
    )
    r = AttributionAnalyzer().analyze(
        src, expected_net=src.trades[0].net_return + src.trades[1].net_return + src.trades[2].net_return
    )
    assert r.total.net == sum((x.net_return for x in src.trades), Decimal(0))
    assert r.tables
    assert r.drawdowns
    assert r.to_json()
    assert "SAMPLE_SHORTAGE" in {x.code for x in r.warnings}


def test_bad_parameter_binding_rejected():
    d = FrozenValidationDataset(ref("d"), (Decimal(".1"),), (Decimal(".1"),), ("2026-01-01T00:00:00Z",))
    s = StrategyDefinition(ref("s"), Decimal(".01"))
    src = AttributionSource.from_validation(d, s, base_cost=Decimal(".01"), instruments=("A",), regimes=("R",))
    a = ValidationArtifact(
        EntityId.deterministic("validation_artifact", "x"),
        ValidationKind.PARAMETER_SWEEP,
        ArtifactStatus.COMPLETE,
        "0" * 64,
        s.strategy_ref.content_sha256,
        {},
        {"parameters": ({"threshold": ".1", "net_return": ".1"},)},
        (),
        (ref("x"),),
    )
    with pytest.raises(ValueError):
        AttributionAnalyzer().analyze(src, parameter_sweep=a)


def test_exact_drawdown_recovery_costs_and_replay():
    from futures_agent_os.research_experiment import AttributionTrade
    from dataclasses import replace

    trades = tuple(
        AttributionTrade(
            str(i), f"2026-01-0{i + 1}T00:00:00Z", "A", "R", "LONG", Decimal(n), (("fee", Decimal(".01")),), True
        )
        for i, n in enumerate((".11", "-.19", ".31", "-.09"))
    )
    source = AttributionSource(trades, "facts", "a" * 64, "b" * 64)
    report = AttributionAnalyzer().analyze(source, expected_net=Decimal(".10"), expected_cost=Decimal(".04"))
    assert report.drawdowns[0].depth == Decimal("-.20")
    assert report.drawdowns[0].recovered_at is not None
    assert report.drawdowns[1].depth == Decimal("-.10")
    assert report.drawdowns[1].recovered_at is None
    assert report.worst_trades[0].source_id == "1"
    assert dict(report.cost_components) == {"fee": Decimal(".04")}
    for _, rows in report.tables:
        assert sum((x.net for x in rows), Decimal(0)) == Decimal(".10")
    assert report.to_json() == AttributionAnalyzer().analyze(source).to_json()
    assert "ROLLOVER_CONCENTRATION" in {x.code for x in report.warnings}
    assert not AttributionAnalyzer().analyze(replace(source, data_gaps=("missing session",))).complete
    with pytest.raises(ValueError, match="reconcile"):
        AttributionAnalyzer().analyze(source, expected_cost=Decimal(".05"))


def test_real_sweep_instability_and_cost_warning():
    from futures_agent_os.research_experiment import (
        ScaleValidationConfig,
        ScaleValidationRunner,
        ScenarioDefinition,
        StrategyDirection,
    )

    d = FrozenValidationDataset(
        ref("dataset"),
        (Decimal(".02"),) * 10,
        (Decimal(".01"),) * 10,
        tuple(f"2026-01-{i + 1:02d}T00:00:00Z" for i in range(10)),
    )
    s = StrategyDefinition(ref("strategy"), Decimal(".005"))
    config = ScaleValidationConfig(
        2,
        2,
        2,
        0,
        Decimal(".006"),
        (Decimal(1),),
        (Decimal(0),),
        10,
        1,
        (Decimal(".005"), Decimal(".03")),
        (ScenarioDefinition("all", 0, 10),),
        (s, StrategyDefinition(ref("inverse"), s.threshold, StrategyDirection.INVERT)),
    )
    sweep = next(x for x in ScaleValidationRunner().run(d, s, config) if x.kind is ValidationKind.PARAMETER_SWEEP)
    source = AttributionSource.from_validation(
        d, s, base_cost=config.base_cost, instruments=("A",) * 10, regimes=("R",) * 10
    )
    report = AttributionAnalyzer().analyze(source, parameter_sweep=sweep)
    assert report.parameter_results == ((Decimal(".005"), Decimal(".040")), (Decimal(".03"), Decimal(0)))
    assert {"PARAMETER_INSTABILITY", "COST_SENSITIVITY"} <= {x.code for x in report.warnings}
    assert report.total.net == Decimal(".040")


def test_simultaneous_closes_have_no_artificial_drawdown():
    from futures_agent_os.research_experiment import AttributionTrade

    trades = tuple(
        AttributionTrade(str(i), "2026-01-01T00:00:00Z", "A", "R", "LONG", Decimal(n), ())
        for i, n in enumerate(("-.1", ".2"))
    )
    assert not AttributionAnalyzer().analyze(AttributionSource(trades, "facts", "a" * 64, "b" * 64)).drawdowns
