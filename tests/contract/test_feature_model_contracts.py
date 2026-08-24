"""V1-005 contracts for deterministic feature and market-model outputs."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.market_intelligence import (
    FeatureEngine,
    FeatureInputWindow,
    FeatureValue,
    ModelOutputAuthority,
    RegimeCandidate,
    RegimeKind,
    RegimeModelService,
    RegimeModelSpec,
    MarketStateAssessmentComposer,
    MarketStateAssessmentInput,
    MarketStateAssessmentSpec,
    TransitionRisk,
)
from futures_agent_os.agent_orchestration import (
    CATALOG_VERSION,
    AgentRoleId,
    AgentTaskEnvelope,
    ArtifactKind,
    ArtifactRef,
    MarketRegimeAgent,
    MarketRegimeTaskSources,
    TriggerSource,
    definition_for,
)
from futures_agent_os.research_experiment import FeatureAlgorithm, FeatureDefinition, FeatureSpec
from futures_agent_os.research_experiment.signal_model_service import (
    FeatureEvidenceRef,
    SignalDefinition,
    SignalKind,
    SignalModelService,
    SignalModelSpec,
)
from futures_agent_os.reference_market_data import (
    ContractFee,
    ContractRuleRegistry,
    ContractRuleResolver,
    ContractRuleVersion,
    DataQualityLevel,
    DatasetLayer,
    DatasetManifest,
    DatasetRecordRef,
    DeliveryRestrictions,
    Exchange,
    FeeBasis,
    FeeSchedule,
    Instrument,
    LicenseTerms,
    MarginRequirements,
    MarketObservation,
    MarketQualityPolicy,
    MarketSnapshot,
    ObservationKind,
    OffsetRules,
    PositionTradingLimits,
    PriceLimitRange,
    PurposeFreshnessPolicy,
    QualityReport,
    Rate,
    ReferenceProvenance,
    Resolution,
    RevisionInfo,
    RuleEffectiveInterval,
    SessionPhase,
    SnapshotPurpose,
    SourceProvenance,
    SourceTrust,
    TimeCoverage,
    TradingDateService,
    TradingSession,
    Variety,
    contract_rule_registry_content_sha256,
    initial_acceptance_trading_calendar,
)
from futures_agent_os.shared_kernel import (
    EntityId,
    Failure,
    Money,
    Price,
    Quantity,
    RecordedAt,
    SchemaVersion,
    ShanghaiTimestamp,
    TradingDate,
    TraceContext,
    canonical_sha256,
)


def at(hour: int, minute: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 24, hour, minute, tzinfo=UTC))


def instrument() -> Instrument:
    return Instrument(Variety(Exchange.SHFE, "AG", "synthetic silver"), "2606")


def provenance() -> ReferenceProvenance:
    return ReferenceProvenance("dataset://v1-005/synthetic", at(0), at(0), "v1")


_RULE_ID = EntityId.parse("contract_rule_018f9b16-9a00-7abe-8000-000000000019")
_REGISTRY_ID = EntityId.parse("contract_rule_registry_018f9b16-9a00-7abe-8000-000000000020")


def market_snapshot(hour: int, price: str, *, purpose: SnapshotPurpose = SnapshotPurpose.RESEARCH) -> MarketSnapshot:
    target = instrument()
    trading_day = TradingDate(date(2026, 8, 25))
    rule = ContractRuleVersion(
        _RULE_ID,
        target,
        RuleEffectiveInterval(TradingDate.parse("2026-08-01"), TradingDate.parse("2026-09-01")),
        1,
        provenance(),
        Quantity("15", "tonne/lot", 0),
        Price("1.0", "CNY", "CNY/tonne", 1),
        Quantity("1", "lot", 0),
        MarginRequirements(Rate("0.12", 2), Rate("0.10", 2)),
        FeeSchedule(*(ContractFee(FeeBasis.PER_LOT, Money("1.00", "CNY", 2)) for _ in range(3))),
        PriceLimitRange(Price("5000.0", "CNY", "CNY/tonne", 1), Price("7000.0", "CNY", "CNY/tonne", 1)),
        (TradingSession("DAY", time(9), time(15)),),
        TradingDate.parse("2026-08-30"),
        DeliveryRestrictions(TradingDate.parse("2026-08-28"), TradingDate.parse("2026-08-29")),
        PositionTradingLimits(Quantity("100", "lot", 0), Quantity("50", "lot", 0), Quantity("100", "lot", 0)),
        OffsetRules(True, True, True),
    )
    registry = ContractRuleRegistry(_REGISTRY_ID, 1, (rule,), contract_rule_registry_content_sha256((rule,)))
    resolved_rule = ContractRuleResolver(registry).resolve(target, trading_day, at(hour))
    assert not isinstance(resolved_rule, Failure)
    calendar_resolution = TradingDateService(initial_acceptance_trading_calendar()).resolve(
        target.variety, ShanghaiTimestamp.from_iso("2026-08-24T21:10:00+08:00"), at(hour)
    )
    assert not isinstance(calendar_resolution, Failure)
    manifest_id = EntityId.new("dataset")
    observation = MarketObservation(
        EntityId.new("market_observation"),
        target,
        ObservationKind.QUOTE,
        at(hour),
        at(hour),
        at(hour),
        provenance(),
        SourceTrust.PRIMARY,
        SchemaVersion(1, 0),
        hour,
        DatasetRecordRef(manifest_id, f"quote/{hour}", "d" * 64),
        last_price=Price(price, "CNY", "CNY/tonne", 1),
        bid_price=Price(str(Decimal(price) - 1), "CNY", "CNY/tonne", 1),
        ask_price=Price(str(Decimal(price) + 1), "CNY", "CNY/tonne", 1),
        bid_size=Quantity("5", "lot", 0),
        ask_size=Quantity("7", "lot", 0),
        volume=Quantity("10", "lot", 0),
        open_interest=Quantity("100", "lot", 0),
    )
    manifest = DatasetManifest(
        manifest_id,
        DatasetLayer.NORMALIZED_PIT,
        "memory://v1-005",
        "sha256:" + "a" * 64,
        "normalized_quote",
        SchemaVersion(1, 0),
        TimeCoverage(at(hour), at(hour)),
        (target.reference_id,),
        SourceProvenance("synthetic", "memory://v1-005", at(0), at(0), "v1"),
        LicenseTerms("test", "research", "none", "none", "local"),
        at(hour),
        at(hour),
        QualityReport(DataQualityLevel.Q2_RESEARCH, "test", at(hour)),
        RevisionInfo(1, "initial", at(hour)),
    )
    policy = MarketQualityPolicy(
        EntityId.new("market_quality_policy"),
        1,
        tuple(PurposeFreshnessPolicy(item, timedelta(days=7), (SessionPhase.CONTINUOUS,)) for item in SnapshotPurpose),
        timedelta(hours=2),
        Decimal("0.10"),
    )
    return MarketSnapshot.freeze(
        EntityId.new("market_snapshot"),
        at(hour),
        calendar_resolution,
        initial_acceptance_trading_calendar(),
        (observation,),
        (Resolution(target, target.reference_id, EntityId.new("instrument_registry"), 1, "b" * 64, 1, provenance()),),
        registry,
        resolved_rule,
        manifest,
        SchemaVersion(1, 0),
        policy,
        purpose,
    )


def feature_spec(algorithm: FeatureAlgorithm = FeatureAlgorithm.SIMPLE_RETURN) -> FeatureSpec:
    definition = FeatureDefinition(
        EntityId.new("feature_definition"), "return", 1, SchemaVersion(1, 0), algorithm, "market return"
    )
    return FeatureSpec(
        EntityId.new("feature_spec"), definition, 1, SchemaVersion(1, 0), "fao.feature.v1", 2, 8, "REJECT"
    )


def test_feature_snapshot_is_pit_window_bound_decimal_immutable_and_replay_hash_stable() -> None:
    earlier, latest = market_snapshot(13, "6000.0"), market_snapshot(14, "6060.0")
    window = FeatureInputWindow((earlier, latest), latest.as_of)
    spec = feature_spec()
    result = FeatureEngine().compute(spec, window)

    assert result.value == FeatureValue(Decimal("0.01000000"), "ratio", 8)
    assert result.as_of == latest.as_of
    assert result.market_snapshot_refs[-1].content_sha256 == latest.expected_content_sha256
    assert result.content_sha256 == FeatureEngine().compute(spec, window).content_sha256
    with pytest.raises(FrozenInstanceError):
        result.as_of = earlier.as_of  # type: ignore[misc]


def test_feature_engine_rejects_wrong_purpose_short_window_and_as_of_or_reference_mixing() -> None:
    earlier, latest = market_snapshot(13, "6000.0"), market_snapshot(14, "6060.0")
    engine = FeatureEngine()
    with pytest.raises(ValueError, match="fewer snapshots"):
        engine.compute(feature_spec(), FeatureInputWindow((latest,), latest.as_of))
    with pytest.raises(ValueError, match="as_of"):
        FeatureInputWindow((earlier, latest), earlier.as_of)
    with pytest.raises(ValueError, match="RESEARCH or BACKTEST"):
        FeatureInputWindow((market_snapshot(13, "6000.0", purpose=SnapshotPurpose.DISPLAY), latest), latest.as_of)
    with pytest.raises(ValueError, match="cannot mix RESEARCH"):
        FeatureInputWindow((earlier, market_snapshot(14, "6060.0", purpose=SnapshotPurpose.BACKTEST)), latest.as_of)
    same_time = market_snapshot(13, "6001.0")
    with pytest.raises(ValueError, match="strictly increasing"):
        FeatureInputWindow((earlier, same_time), same_time.as_of)


def test_models_preserve_multi_candidates_conflicts_and_are_explicitly_non_authoritative() -> None:
    earlier, latest = market_snapshot(13, "6000.0"), market_snapshot(14, "6060.0")
    return_spec = feature_spec()
    feature = FeatureEngine().compute(return_spec, FeatureInputWindow((earlier, latest), latest.as_of))
    regime = RegimeModelService().evaluate(
        RegimeModelSpec(
            EntityId.new("regime_model_spec"),
            "deterministic-regime",
            1,
            SchemaVersion(1, 0),
            "fao.regime.v1",
            Decimal("0.005"),
            Decimal("0.001"),
            return_feature=feature.feature_spec,
        ),
        (feature,),
    )
    signal = SignalModelService().evaluate(
        SignalModelSpec(
            EntityId.new("signal_model_spec"),
            SignalDefinition(
                EntityId.new("signal_definition"), "return-signals", 1, SchemaVersion(1, 0), "research only"
            ),
            1,
            SchemaVersion(1, 0),
            "fao.signal.v1",
            Decimal("0.005"),
            input_feature=feature.feature_spec,
        ),
        (FeatureEvidenceRef.from_published(feature),),
    )
    assert {item.kind for item in regime.candidates} >= {RegimeKind.TREND, RegimeKind.MEAN_REVERSION}
    assert regime.conflicts
    assert {item.kind for item in signal.signals} >= {SignalKind.MOMENTUM, SignalKind.MEAN_REVERSION}
    assert signal.conflicts
    assert regime.authority is signal.authority is ModelOutputAuthority.NON_TRADING
    assert regime.trading_authorization().reason_code == signal.trading_authorization().reason_code


def test_market_regime_agent_binds_its_task_to_exact_immutable_market_lineage() -> None:
    earlier, latest = market_snapshot(13, "6000.0"), market_snapshot(14, "6060.0")
    return_spec = feature_spec()
    feature = FeatureEngine().compute(return_spec, FeatureInputWindow((earlier, latest), latest.as_of))
    regime = RegimeModelService().evaluate(
        RegimeModelSpec(
            EntityId.new("regime_model_spec"),
            "deterministic-regime",
            1,
            SchemaVersion(1, 0),
            "fao.regime.v1",
            Decimal("0.005"),
            Decimal("0.001"),
            return_feature=feature.feature_spec,
        ),
        (feature,),
    )
    inputs = MarketStateAssessmentInput(regime.terminal_market_snapshot_ref, (feature,), regime)
    agent = MarketRegimeAgent()
    sources = MarketRegimeTaskSources(
        (
            ArtifactRef(
                inputs.market_snapshot.snapshot_id,
                ArtifactKind.MARKET_SNAPSHOT,
                inputs.market_snapshot.schema_version,
                "sha256:" + inputs.market_snapshot.content_sha256,
                inputs.market_snapshot.as_of,
                inputs.market_snapshot.as_of,
            ),
            ArtifactRef(
                feature.observation_id,
                ArtifactKind.FEATURE_OBSERVATION,
                feature.schema_version,
                "sha256:" + feature.content_sha256,
                feature.as_of,
                feature.as_of,
            ),
            ArtifactRef(
                regime.assessment_id,
                ArtifactKind.REGIME_ASSESSMENT,
                regime.model_spec.schema_version,
                "sha256:" + regime.content_sha256,
                regime.as_of,
                regime.as_of,
            ),
        )
    )
    correlation_id = EntityId.new("correlation")
    task = AgentTaskEnvelope(
        EntityId.new("agent_task"),
        EntityId.new("session"),
        correlation_id,
        TraceContext(correlation_id, EntityId.new("trace")),
        AgentRoleId.MARKET_REGIME.value,
        CATALOG_VERSION,
        "assess the current market state",
        "return one non-authoritative market-state assessment",
        (TriggerSource.MARKET,),
        sources.artifacts,
        (),
        ("market_snapshot", "feature_query", "regime_analysis"),
        definition_for(AgentRoleId.MARKET_REGIME.value).budget,
        (ArtifactKind.MARKET_STATE_ASSESSMENT,),
        latest.as_of,
        at(23),
    )
    assessment_spec = MarketStateAssessmentSpec(
        EntityId.new("market_state_assessment_spec"), 1, CATALOG_VERSION, "fao.market-state-assessment.v1"
    )
    assessment = MarketStateAssessmentComposer().compose(assessment_spec, inputs, task.expires_at)
    result = agent.package(
        task,
        sources,
        assessment,
        EntityId.new("agent_run"),
    )

    assert assessment.primary_state is RegimeKind.TREND
    assert assessment.transition_risk is TransitionRisk.HIGH
    assert assessment.conflicts == regime.conflicts
    assert assessment.authority is ModelOutputAuthority.NON_TRADING
    assert assessment.as_of == latest.as_of and assessment.valid_until == task.expires_at
    assert (
        assessment.content_sha256
        == MarketStateAssessmentComposer().compose(assessment_spec, inputs, task.expires_at).content_sha256
    )
    assert assessment.trading_authorization().reason_code.name == "MODEL_OUTPUT_NOT_AUTHORIZATION"
    assert result.ref.artifact_kind is ArtifactKind.MARKET_STATE_ASSESSMENT
    assert result.source_refs == sources.artifacts and result.claims
    assert all(claim.evidence_refs for claim in result.claims)

    duplicated_lineage = (*assessment.feature_lineage, assessment.feature_lineage[0])
    duplicated_payload = {
        **assessment.payload(),
        "feature_lineage": tuple(
            {"content_sha256": item.content_sha256, "schema_version": str(item.schema_version)}
            for item in duplicated_lineage
        ),
    }
    with pytest.raises(ValueError, match="feature artifact lineage"):
        replace(
            assessment,
            feature_lineage=duplicated_lineage,
            content_sha256=canonical_sha256(duplicated_payload),
        )

    class MutableFeatureRef:
        def __init__(self) -> None:
            ref = assessment.feature_observation_refs[0]
            self.observation_id = ref.observation_id
            self.content_sha256 = ref.content_sha256

    with pytest.raises(TypeError, match="FeatureArtifactRef"):
        replace(assessment, feature_observation_refs=(MutableFeatureRef(),))

    class MutableAssessmentPort:
        def __init__(self) -> None:
            self.assessment_id = assessment.assessment_id
            self.schema_version = assessment.schema_version
            self.as_of = assessment.as_of
            self.valid_until = assessment.valid_until
            self.market_snapshot = assessment.market_snapshot
            self.feature_lineage = assessment.feature_lineage
            self.regime_assessment_id = assessment.regime_assessment_id
            self.regime_assessment_content_sha256 = assessment.regime_assessment_content_sha256
            self.regime_assessment_schema_version = assessment.regime_assessment_schema_version
            self.authority = assessment.authority
            self.content_sha256 = assessment.content_sha256
            self.candidates = list(assessment.candidates)
            self.unknowns = assessment.unknowns
            self.alternative_explanations = assessment.alternative_explanations

        def payload(self):  # type: ignore[no-untyped-def]
            return assessment.payload()

    stale_port = MutableAssessmentPort()
    stale_port.candidates[0] = replace(stale_port.candidates[0], unknowns=("forged after hash",))
    with pytest.raises(ValueError, match="payload candidates"):
        agent.package(task, sources, stale_port, EntityId.new("agent_run"))

    with pytest.raises(ValueError, match="exact immutable source artifacts"):
        agent.package(
            replace(task, input_artifacts=task.input_artifacts[:-1]), sources, assessment, EntityId.new("agent_run")
        )
    extra_feature = ArtifactRef(
        EntityId.new("feature_observation"),
        ArtifactKind.FEATURE_OBSERVATION,
        SchemaVersion(1, 0),
        "sha256:" + "e" * 64,
        task.as_of,
        task.as_of,
    )
    extra_sources = MarketRegimeTaskSources((*sources.artifacts, extra_feature))
    with pytest.raises(ValueError, match="exactly match assessment"):
        agent.package(
            replace(task, input_artifacts=extra_sources.artifacts), extra_sources, assessment, EntityId.new("agent_run")
        )
    snapshot_source = next(item for item in sources.artifacts if item.artifact_kind is ArtifactKind.MARKET_SNAPSHOT)
    mismatch_sources = MarketRegimeTaskSources(
        tuple(
            replace(snapshot_source, artifact_id=EntityId.new("market_snapshot")) if item is snapshot_source else item
            for item in sources.artifacts
        )
    )
    with pytest.raises(ValueError, match="exactly match assessment"):
        agent.package(
            replace(task, input_artifacts=mismatch_sources.artifacts),
            mismatch_sources,
            assessment,
            EntityId.new("agent_run"),
        )
    with pytest.raises(ValueError, match="assigned"):
        agent.package(
            replace(task, assigned_role_id=AgentRoleId.RESEARCH.value), sources, assessment, EntityId.new("agent_run")
        )
    with pytest.raises(ValueError, match="required output"):
        agent.package(
            replace(task, required_outputs=(ArtifactKind.RESEARCH_PLAN,)),
            sources,
            assessment,
            EntityId.new("agent_run"),
        )
    assert agent.deferred_result(task, "source artifact conflict").status.name == "DEFERRED"


def test_market_state_preserves_counter_only_and_unknown_candidates_without_fake_support() -> None:
    earlier, latest = market_snapshot(13, "6000.0"), market_snapshot(14, "6060.0")
    returns = FeatureEngine().compute(feature_spec(), FeatureInputWindow((earlier, latest), latest.as_of))
    liquidity = FeatureEngine().compute(
        feature_spec(FeatureAlgorithm.QUOTE_LIQUIDITY), FeatureInputWindow((earlier, latest), latest.as_of)
    )
    spec = MarketStateAssessmentSpec(
        EntityId.new("market_state_assessment_spec"), 1, CATALOG_VERSION, "fao.market-state-assessment.v1"
    )
    high_liquidity_regime = RegimeModelService().evaluate(
        RegimeModelSpec(
            EntityId.new("regime_model_spec"),
            "counter-only-liquidity",
            1,
            SchemaVersion(1, 0),
            "fao.regime.v1",
            Decimal("0.005"),
            Decimal("0.001"),
            return_feature=returns.feature_spec,
            liquidity_feature=liquidity.feature_spec,
            liquidity_stress_below=Decimal("1.00000000"),
        ),
        (returns, liquidity),
    )
    counter_only = MarketStateAssessmentComposer().compose(
        spec,
        MarketStateAssessmentInput(
            high_liquidity_regime.terminal_market_snapshot_ref, (returns, liquidity), high_liquidity_regime
        ),
        at(23),
    )
    liquidity_candidate = next(item for item in counter_only.candidates if item.state is RegimeKind.LIQUIDITY_STRESS)
    assert liquidity_candidate.support == ()
    assert liquidity_candidate.counter_evidence

    counter_only_regime = RegimeModelService().evaluate(
        RegimeModelSpec(
            EntityId.new("regime_model_spec"),
            "liquidity-only",
            1,
            SchemaVersion(1, 0),
            "fao.regime.v1",
            Decimal("0.005"),
            Decimal("0.001"),
            return_feature=returns.feature_spec,
            liquidity_feature=liquidity.feature_spec,
            liquidity_stress_below=Decimal("1.00000000"),
        ),
        (liquidity,),
    )
    counter_only_assessment = MarketStateAssessmentComposer().compose(
        spec,
        MarketStateAssessmentInput(counter_only_regime.terminal_market_snapshot_ref, (liquidity,), counter_only_regime),
        at(23),
    )
    assert counter_only_assessment.primary_state is None
    assert counter_only_assessment.transition_risk is TransitionRisk.UNKNOWN
    assert "no support-backed primary state" in counter_only_assessment.alternative_explanations
    assert "primary state is tied" not in counter_only_assessment.alternative_explanations

    unknown_regime = RegimeModelService().evaluate(
        RegimeModelSpec(
            EntityId.new("regime_model_spec"),
            "unknown-only",
            1,
            SchemaVersion(1, 0),
            "fao.regime.v1",
            Decimal("0.005"),
            Decimal("0.001"),
            return_feature=returns.feature_spec,
        ),
        (liquidity,),
    )
    unknown_inputs = MarketStateAssessmentInput(
        unknown_regime.terminal_market_snapshot_ref, (liquidity,), unknown_regime
    )
    unknown_assessment = MarketStateAssessmentComposer().compose(spec, unknown_inputs, at(23))
    unknown_candidate = next(item for item in unknown_assessment.candidates if item.state is RegimeKind.UNKNOWN)
    assert unknown_candidate.support == unknown_candidate.counter_evidence == ()
    assert unknown_candidate.unknowns
    assert unknown_assessment.primary_state is None
    assert unknown_assessment.transition_risk is TransitionRisk.UNKNOWN
    assert "no support-backed primary state" in unknown_assessment.alternative_explanations
    assert "primary state is tied" not in unknown_assessment.alternative_explanations

    unknown_sources = MarketRegimeTaskSources(
        (
            ArtifactRef(
                unknown_inputs.market_snapshot.snapshot_id,
                ArtifactKind.MARKET_SNAPSHOT,
                unknown_inputs.market_snapshot.schema_version,
                "sha256:" + unknown_inputs.market_snapshot.content_sha256,
                unknown_inputs.market_snapshot.as_of,
                unknown_inputs.market_snapshot.as_of,
            ),
            ArtifactRef(
                liquidity.observation_id,
                ArtifactKind.FEATURE_OBSERVATION,
                liquidity.schema_version,
                "sha256:" + liquidity.content_sha256,
                liquidity.as_of,
                liquidity.as_of,
            ),
            ArtifactRef(
                unknown_regime.assessment_id,
                ArtifactKind.REGIME_ASSESSMENT,
                unknown_regime.model_spec.schema_version,
                "sha256:" + unknown_regime.content_sha256,
                unknown_regime.as_of,
                unknown_regime.as_of,
            ),
        )
    )
    correlation_id = EntityId.new("correlation")
    unknown_task = AgentTaskEnvelope(
        EntityId.new("agent_task"),
        EntityId.new("session"),
        correlation_id,
        TraceContext(correlation_id, EntityId.new("trace")),
        AgentRoleId.MARKET_REGIME.value,
        CATALOG_VERSION,
        "assess unknown state",
        "return non-authoritative unknown",
        (TriggerSource.MARKET,),
        unknown_sources.artifacts,
        (),
        ("market_snapshot",),
        definition_for(AgentRoleId.MARKET_REGIME.value).budget,
        (ArtifactKind.MARKET_STATE_ASSESSMENT,),
        latest.as_of,
        at(23),
    )
    packaged = MarketRegimeAgent().package(unknown_task, unknown_sources, unknown_assessment, EntityId.new("agent_run"))
    assert any("unknown:" in claim.statement for claim in packaged.claims)
    assert "no support-backed primary state" in packaged.warnings


def test_market_regime_agent_has_no_trade_or_risk_authority_dependencies() -> None:
    root = __import__("pathlib").Path(__file__).resolve().parents[2] / "src" / "futures_agent_os"
    source = (root / "agent_orchestration" / "market_regime_agent.py").read_text(encoding="utf-8")
    for forbidden in (
        "futures_agent_os.market_intelligence",
        "futures_agent_os.decision",
        "futures_agent_os.portfolio_risk",
        "futures_agent_os.execution_simulation",
        "futures_agent_os.accounting_settlement",
        "TradePlan",
        "RiskDecision",
        "Order",
    ):
        assert forbidden not in source


def test_deterministic_models_are_order_independent_and_concurrent() -> None:
    earlier, latest = market_snapshot(13, "6000.0"), market_snapshot(14, "6060.0")
    return_spec = feature_spec()
    feature = FeatureEngine().compute(return_spec, FeatureInputWindow((earlier, latest), latest.as_of))
    spec = RegimeModelSpec(
        EntityId.new("regime_model_spec"),
        "deterministic-regime",
        1,
        SchemaVersion(1, 0),
        "fao.regime.v1",
        Decimal("0.005"),
        Decimal("0.001"),
        return_feature=feature.feature_spec,
    )
    service = RegimeModelService()
    one = service.evaluate(spec, (feature,))
    assert one.content_sha256 == service.evaluate(spec, tuple(reversed((feature,)))).content_sha256
    repeated_feature = FeatureEngine().compute(return_spec, FeatureInputWindow((earlier, latest), latest.as_of))
    assert one.content_sha256 == service.evaluate(spec, (repeated_feature,)).content_sha256
    signal_spec = SignalModelSpec(
        EntityId.new("signal_model_spec"),
        SignalDefinition(EntityId.new("signal_definition"), "pipeline", 1, SchemaVersion(1, 0), "test"),
        1,
        SchemaVersion(1, 0),
        "fao.signal.v1",
        Decimal("0.005"),
        input_feature=feature.feature_spec,
    )
    assert (
        SignalModelService().evaluate(signal_spec, (FeatureEvidenceRef.from_published(feature),)).content_sha256
        == SignalModelService()
        .evaluate(signal_spec, (FeatureEvidenceRef.from_published(repeated_feature),))
        .content_sha256
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(executor.map(lambda _: service.evaluate(spec, (feature,)), range(32)))
    assert {item.content_sha256 for item in outcomes} == {one.content_sha256}


def test_v1_005_modules_do_not_depend_on_trade_authority_or_execution_objects() -> None:
    root = __import__("pathlib").Path(__file__).resolve().parents[2] / "src" / "futures_agent_os"
    sources = "\n".join(
        (root / relative).read_text(encoding="utf-8")
        for relative in (
            "market_intelligence/feature_engine.py",
            "market_intelligence/regime_model_service.py",
            "research_experiment/signal_model_service.py",
        )
    )
    for forbidden in (
        "futures_agent_os.decision",
        "futures_agent_os.portfolio_risk",
        "futures_agent_os.execution_simulation",
        "futures_agent_os.accounting_settlement",
    ):
        assert forbidden not in sources


def test_feature_value_rejects_currency_dimension_confusion_and_regime_requires_bound_return_spec() -> None:
    with pytest.raises(ValueError, match="ratio"):
        FeatureValue(Decimal("0.1"), "ratio", 1, "CNY")
    with pytest.raises(ValueError, match="canonical"):
        FeatureValue(Decimal("1.0"), "tonne", 1, "CNY")
    with pytest.raises(ValueError, match="requires a SIMPLE_RETURN"):
        RegimeModelSpec(
            EntityId.new("regime_model_spec"),
            "bad",
            1,
            SchemaVersion(1, 0),
            "fao.regime.v1",
            Decimal("0.1"),
            Decimal("0.1"),
        )


def test_models_reject_ambiguous_bound_feature_evidence_and_invalid_return_window() -> None:
    with pytest.raises(ValueError, match="unsupported feature"):
        FeatureSpec(
            EntityId.new("feature_spec"),
            FeatureDefinition(
                EntityId.new("feature_definition"),
                "bad-version",
                1,
                SchemaVersion(1, 0),
                FeatureAlgorithm.LAST_PRICE,
                "bad",
            ),
            1,
            SchemaVersion(1, 0),
            "unknown-v999",
            1,
            1,
            "REJECT",
        )
    with pytest.raises(ValueError, match="window_size at least two"):
        FeatureSpec(
            EntityId.new("feature_spec"),
            FeatureDefinition(
                EntityId.new("feature_definition"),
                "bad-return",
                1,
                SchemaVersion(1, 0),
                FeatureAlgorithm.SIMPLE_RETURN,
                "bad",
            ),
            1,
            SchemaVersion(1, 0),
            "fao.feature.v1",
            1,
            8,
            "REJECT",
        )
    earlier, latest = market_snapshot(13, "6000.0"), market_snapshot(14, "6060.0")
    bound = feature_spec()
    feature = FeatureEngine().compute(bound, FeatureInputWindow((earlier, latest), latest.as_of))
    regime = RegimeModelSpec(
        EntityId.new("regime_model_spec"),
        "bound",
        1,
        SchemaVersion(1, 0),
        "fao.regime.v1",
        Decimal("0.1"),
        Decimal("0.1"),
        return_feature=feature.feature_spec,
    )
    with pytest.raises(ValueError, match="at most one"):
        RegimeModelService().evaluate(regime, (feature, feature))
    signal = SignalModelSpec(
        EntityId.new("signal_model_spec"),
        SignalDefinition(EntityId.new("signal_definition"), "bound", 1, SchemaVersion(1, 0), "test"),
        1,
        SchemaVersion(1, 0),
        "fao.signal.v1",
        Decimal("0.1"),
        input_feature=feature.feature_spec,
    )
    evidence = FeatureEvidenceRef.from_published(feature)
    with pytest.raises(ValueError, match="exactly one"):
        SignalModelService().evaluate(signal, (evidence, evidence))


def test_regime_collections_detach_caller_lists_and_liquidity_uses_bound_threshold() -> None:
    support = ["support-hash"]
    candidate = RegimeCandidate(RegimeKind.TREND, Decimal("0.5"), support, [], [])
    support.append("mutated")
    assert candidate.support == ("support-hash",)
    earlier, latest = market_snapshot(13, "6000.0"), market_snapshot(14, "6060.0")
    returned = feature_spec()
    liquidity_definition = FeatureDefinition(
        EntityId.new("feature_definition"), "depth", 1, SchemaVersion(1, 0), FeatureAlgorithm.QUOTE_LIQUIDITY, "depth"
    )
    liquidity_spec = FeatureSpec(
        EntityId.new("feature_spec"), liquidity_definition, 1, SchemaVersion(1, 0), "fao.feature.v1", 1, 0, "REJECT"
    )
    returned_value = FeatureEngine().compute(returned, FeatureInputWindow((earlier, latest), latest.as_of))
    liquidity_value = FeatureEngine().compute(liquidity_spec, FeatureInputWindow((latest,), latest.as_of))
    model = RegimeModelSpec(
        EntityId.new("regime_model_spec"),
        "liquidity",
        1,
        SchemaVersion(1, 0),
        "fao.regime.v1",
        Decimal("0.1"),
        Decimal("0.1"),
        return_feature=returned_value.feature_spec,
        liquidity_feature=liquidity_value.feature_spec,
        liquidity_stress_below=Decimal("4"),
    )
    assessment = RegimeModelService().evaluate(model, (returned_value, liquidity_value))
    liquidity = next(item for item in assessment.candidates if item.kind is RegimeKind.LIQUIDITY_STRESS)
    assert liquidity.score == Decimal("0.10") and liquidity.counter_evidence == (liquidity_value.content_sha256,)


def test_feature_evidence_cannot_replace_published_value_independently() -> None:
    earlier, latest = market_snapshot(13, "6000.0"), market_snapshot(14, "6060.0")
    feature = FeatureEngine().compute(feature_spec(), FeatureInputWindow((earlier, latest), latest.as_of))
    evidence = FeatureEvidenceRef.from_published(feature)
    with pytest.raises(TypeError):
        replace(evidence, amount=Decimal("-0.99"))
