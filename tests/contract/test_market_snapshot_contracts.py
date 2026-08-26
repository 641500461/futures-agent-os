"""Contracts for immutable point-in-time market snapshots and quality gates."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from futures_agent_os.market_intelligence import FeatureObservation
from futures_agent_os.agent_orchestration import (
    AgentRoleId,
    AgentTaskEnvelope,
    ArtifactKind,
    ResultStatus,
    TriggerSource,
    V1_010CriticTaskSources,
    V1_010ResearchCriticAgent,
    definition_for,
)

from futures_agent_os.reference_market_data import (
    BarInterval,
    BarStatus,
    ContinuousAdjustment,
    ContinuousSeries,
    ContractFee,
    ContractRuleVersion,
    ContractRuleRegistry,
    ContractRuleResolver,
    DatasetManifest,
    DatasetRecordRef,
    DataQualityLevel,
    DatasetLayer,
    LicenseTerms,
    QualityReport,
    RevisionInfo,
    SourceProvenance,
    TimeCoverage,
    contract_rule_registry_content_sha256,
    DeliveryRestrictions,
    Exchange,
    FeeBasis,
    FeeSchedule,
    Instrument,
    MarginRequirements,
    MarketObservation,
    MarketQualityCode,
    MarketQualityPolicy,
    MarketSnapshot,
    ObservationKind,
    OffsetRules,
    PositionTradingLimits,
    PriceLimitRange,
    PurposeFreshnessPolicy,
    Rate,
    ReferenceProvenance,
    Resolution,
    RuleEffectiveInterval,
    SessionPhase,
    SnapshotPurpose,
    SourceTrust,
    TradingSession,
    TradingDateResolution,
    TradingDateService,
    TradingCalendarRef,
    Variety,
    assess_market_quality,
    initial_acceptance_trading_calendar,
    select_active_observations,
)
from futures_agent_os.shared_kernel import (
    EntityId,
    Failure,
    Money,
    Price,
    Quantity,
    ReasonCode,
    RecordedAt,
    SchemaVersion,
    ShanghaiTimestamp,
    TraceContext,
    TradingDate,
    canonical_sha256,
)
from futures_agent_os.research_experiment import (
    CritiqueStatus,
    DeterministicResearchTools,
    DiagnosticEvidenceV1_010,
    EvidenceGap,
    ExperimentOutcome,
    ExperimentRequestSpec,
    ExperimentSearchRecord,
    FalsifiableHypothesisSpec,
    HypothesisProposalSource,
    MarketStateAssessmentRef,
    MemorySearchRecord,
    PRIOR_CLOSE_RETURN_FEATURE_SPEC_ID,
    PRIOR_CLOSE_RETURN_FEATURE_SPEC_SHA256,
    ResearchQueryScope,
    ResearchArtifactRef,
    ResearchSynthesisComposer,
    ResearchSynthesisInput,
    ToolFailureCode,
    TrustedExperimentSearchPort,
    TrustedFeatureEvidencePort,
    TrustedMemorySearchPort,
    TrustedResearchToolsPort,
    V1_010CritiqueComposer,
    V1_010CriticWorker,
    V1_010DiagnosticProducer,
    ValidationConfig,
    ValidationRunRequest,
)


def at(hour: int, minute: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 24, hour, minute, tzinfo=UTC))


_MANIFEST_ID = EntityId.parse("dataset_018f9b16-9a00-7abe-8000-000000000019")


def day() -> TradingDate:
    return TradingDate(date(2026, 8, 25))


def provenance() -> ReferenceProvenance:
    return ReferenceProvenance("dataset://v1-004/synthetic", at(8), at(8), "v1")


def instrument():
    return Instrument(Variety(Exchange.SHFE, "AG", "synthetic silver"), "2606")


def rule() -> ContractRuleVersion:
    target = instrument()
    return ContractRuleVersion(
        EntityId.new("contract_rule"),
        target,
        RuleEffectiveInterval(TradingDate.parse("2026-08-01"), TradingDate.parse("2026-09-01")),
        1,
        provenance(),
        Quantity("15", "tonne/lot", 0),
        Price("1.0", "CNY", "CNY/tonne", 1),
        Quantity("1", "lot", 0),
        MarginRequirements(Rate("0.12", 2), Rate("0.10", 2)),
        FeeSchedule(
            ContractFee(FeeBasis.PER_LOT, Money("1.00", "CNY", 2)),
            ContractFee(FeeBasis.PER_LOT, Money("1.00", "CNY", 2)),
            ContractFee(FeeBasis.PER_LOT, Money("1.00", "CNY", 2)),
        ),
        PriceLimitRange(Price("5000.0", "CNY", "CNY/tonne", 1), Price("7000.0", "CNY", "CNY/tonne", 1)),
        (TradingSession("DAY", time(9), time(15)),),
        TradingDate.parse("2026-08-30"),
        DeliveryRestrictions(TradingDate.parse("2026-08-28"), TradingDate.parse("2026-08-29")),
        PositionTradingLimits(Quantity("100", "lot", 0), Quantity("50", "lot", 0), Quantity("100", "lot", 0)),
        OffsetRules(True, True, True),
    )


def policy() -> MarketQualityPolicy:
    return MarketQualityPolicy(
        EntityId.new("market_quality_policy"),
        1,
        tuple(
            PurposeFreshnessPolicy(purpose, timedelta(days=7), (SessionPhase.CONTINUOUS,))
            for purpose in SnapshotPurpose
        ),
        timedelta(hours=2),
        Decimal("0.10"),
    )


def resolution(target=None) -> Resolution:
    target = target or instrument()
    return Resolution(target, target.reference_id, EntityId.new("instrument_registry"), 1, "b" * 64, 1, provenance())


def quote(
    *,
    event: RecordedAt = at(13),
    available: RecordedAt = at(14),
    ingested: RecordedAt = at(14),
    trust: SourceTrust = SourceTrust.PRIMARY,
    source_sequence: int = 1,
):
    return MarketObservation(
        EntityId.new("market_observation"),
        instrument(),
        ObservationKind.QUOTE,
        event,
        available,
        ingested,
        provenance(),
        trust,
        SchemaVersion(1, 0),
        source_sequence,
        DatasetRecordRef(_MANIFEST_ID, f"quote/{source_sequence}", "d" * 64),
        last_price=Price("6000.0", "CNY", "CNY/tonne", 1),
        bid_price=Price("5999.0", "CNY", "CNY/tonne", 1),
        ask_price=Price("6001.0", "CNY", "CNY/tonne", 1),
        bid_size=Quantity("1", "lot", 0),
        ask_size=Quantity("1", "lot", 0),
    )


def calendar_resolution(as_of: RecordedAt = at(14)) -> TradingDateResolution:
    outcome = TradingDateService(initial_acceptance_trading_calendar()).resolve(
        instrument().variety, ShanghaiTimestamp.from_iso("2026-08-24T21:10:00+08:00"), as_of
    )
    assert not isinstance(outcome, Failure)
    return outcome


def snapshot(
    *,
    observations=None,
    resolutions=None,
    as_of: RecordedAt = at(14),
    calendar: TradingDateResolution | None = None,
    purpose: SnapshotPurpose = SnapshotPurpose.EXECUTION,
) -> MarketSnapshot:
    contract_rule = rule()
    registry = ContractRuleRegistry(
        EntityId.new("contract_rule_registry"),
        1,
        (contract_rule,),
        contract_rule_registry_content_sha256((contract_rule,)),
    )
    rule_outcome = ContractRuleResolver(registry).resolve(contract_rule.instrument, day(), as_of)
    assert not isinstance(rule_outcome, Failure)
    observations = tuple(observations or (quote(),))
    return MarketSnapshot.freeze(
        EntityId.new("market_snapshot"),
        as_of,
        calendar or calendar_resolution(as_of),
        initial_acceptance_trading_calendar(),
        observations,
        tuple(resolutions or (resolution(observations[0].reference),)),
        registry,
        rule_outcome,
        manifest(observations, as_of),
        SchemaVersion(1, 0),
        policy(),
        purpose,
    )


def manifest(observations: tuple[MarketObservation, ...], as_of: RecordedAt):
    event_times = tuple(item.event_time for item in observations)
    return DatasetManifest(
        _MANIFEST_ID,
        DatasetLayer.NORMALIZED_PIT,
        "memory://v1-004",
        "sha256:" + "c" * 64,
        "normalized_quote",
        SchemaVersion(1, 0),
        TimeCoverage(min(event_times, key=lambda item: item.value), max(event_times, key=lambda item: item.value)),
        tuple(sorted({item.reference_id for item in observations})),
        SourceProvenance("synthetic", "memory://v1-004", at(8), at(8), "v1"),
        LicenseTerms("test", "research", "none", "none", "local"),
        as_of,
        as_of,
        QualityReport(DataQualityLevel.Q2_RESEARCH, "test", as_of),
        RevisionInfo(1, "initial", as_of),
    )


def test_snapshot_freezes_complete_pit_refs_and_permits_a_primary_two_sided_quote_for_execution() -> None:
    frozen = snapshot()

    assert frozen.eligible_for(SnapshotPurpose.EXECUTION) is None
    assert frozen.eligible_for(SnapshotPurpose.RESEARCH) == Failure(
        ReasonCode.DATA_PURPOSE_DENIED, "snapshot was frozen for a different purpose"
    )
    assert frozen.quality.issues == ()
    with pytest.raises(FrozenInstanceError):
        frozen.as_of = at(11)  # type: ignore[misc]


def test_future_availability_never_leaks_into_any_snapshot_purpose() -> None:
    future = quote(available=at(15), ingested=at(15))
    quality = assess_market_quality((future,), at(14), policy())

    assert quality.has(MarketQualityCode.FUTURE_AVAILABILITY)
    with pytest.raises(ValueError, match="unavailable at as_of"):
        snapshot(observations=(future,))


def test_quality_issues_are_structured_and_backtest_does_not_inherit_research_eligibility() -> None:
    first = quote()
    duplicate = replace(first, observation_id=EntityId.new("market_observation"))
    conflicting = replace(
        first, observation_id=EntityId.new("market_observation"), last_price=Price("6600.0", "CNY", "CNY/tonne", 1)
    )
    frozen = snapshot(observations=(first, duplicate, conflicting), purpose=SnapshotPurpose.RESEARCH)

    assert frozen.quality.has(
        MarketQualityCode.DUPLICATE_OBSERVATION,
        MarketQualityCode.CONFLICTING_OBSERVATION,
    )
    assert all(issue.observation_ids for issue in frozen.quality.issues)
    assert frozen.eligible_for(SnapshotPurpose.RESEARCH) == Failure(
        ReasonCode.DATA_CONFLICT, "snapshot contains conflicting observations"
    )
    assert frozen.eligible_for(SnapshotPurpose.BACKTEST) == Failure(
        ReasonCode.DATA_PURPOSE_DENIED, "snapshot was frozen for a different purpose"
    )


def test_incomplete_bar_and_continuous_series_remain_research_evidence_not_execution_inputs() -> None:
    continuous = ContinuousSeries(instrument().variety, "C8888", ContinuousAdjustment.UNADJUSTED, "roll://v1")
    bar = MarketObservation(
        EntityId.new("market_observation"),
        continuous,
        ObservationKind.BAR,
        at(13),
        at(14),
        at(14),
        provenance(),
        SourceTrust.PRIMARY,
        SchemaVersion(1, 0),
        1,
        DatasetRecordRef(_MANIFEST_ID, "bar/1", "d" * 64),
        open_price=Price("6000.0", "CNY", "CNY/tonne", 1),
        high_price=Price("6002.0", "CNY", "CNY/tonne", 1),
        low_price=Price("5998.0", "CNY", "CNY/tonne", 1),
        close_price=Price("6001.0", "CNY", "CNY/tonne", 1),
        volume=Quantity("10", "lot", 0),
        bar_interval=BarInterval("5m", timedelta(minutes=5)),
        bar_status=BarStatus.IN_PROGRESS,
        component_instrument=instrument(),
    )
    frozen = snapshot(
        observations=(bar,),
        resolutions=(resolution(continuous), resolution(instrument())),
        purpose=SnapshotPurpose.RESEARCH,
    )

    assert frozen.quality.has(MarketQualityCode.INCOMPLETE_BAR)
    assert frozen.eligible_for(SnapshotPurpose.RESEARCH) is None
    execution = snapshot(
        observations=(bar,),
        resolutions=(resolution(continuous), resolution(instrument())),
        purpose=SnapshotPurpose.EXECUTION,
    )
    assert execution.eligible_for(SnapshotPurpose.EXECUTION) == Failure(
        ReasonCode.CONTINUOUS_SERIES_NOT_TRADABLE, "continuous series cannot be an execution input"
    )


def test_manifest_metadata_and_observation_order_are_hashed_not_silently_normalized() -> None:
    original = snapshot()
    different_manifest = replace(
        original.dataset_manifest,
        schema_name="normalized_quote_v2",
    )
    changed = MarketSnapshot.freeze(
        EntityId.new("market_snapshot"),
        original.as_of,
        original.trading_date_resolution,
        original.trading_calendar,
        original.observations,
        original.reference_resolutions,
        original.contract_rule_registry,
        original.rule_resolution,
        different_manifest,
        original.schema_version,
        original.quality_policy,
        original.intended_purpose,
    )
    assert original.expected_content_sha256 != changed.expected_content_sha256
    with pytest.raises(ValueError, match="supersede"):
        replace(quote(), revision=2)


def test_execution_rejects_source_fallback_and_rule_unit_mismatch_without_downgrading_research() -> None:
    fallback = snapshot(observations=(quote(trust=SourceTrust.FALLBACK),))
    assert fallback.quality.has(MarketQualityCode.SOURCE_FALLBACK)
    assert fallback.eligible_for(SnapshotPurpose.EXECUTION) == Failure(
        ReasonCode.DATA_SOURCE_FALLBACK, "snapshot uses a fallback source"
    )

    original = quote()
    wrong_unit = replace(
        original,
        last_price=Price("6000.00", "CNY", "CNY/kg", 2),
        bid_price=Price("5999.00", "CNY", "CNY/kg", 2),
        ask_price=Price("6001.00", "CNY", "CNY/kg", 2),
    )
    with pytest.raises(ValueError, match="contract rule quote unit"):
        snapshot(observations=(wrong_unit,))
    zero_size = replace(quote(), bid_size=Quantity("0", "lot", 0))
    assert snapshot(observations=(zero_size,)).eligible_for(SnapshotPurpose.EXECUTION) == Failure(
        ReasonCode.DATA_MISSING, "execution requires a primary positive-size two-sided quote"
    )


def test_snapshot_rejects_same_variety_but_wrong_contract_and_rule_effective_date() -> None:
    wrong_contract = Instrument(Variety(Exchange.SHFE, "AG", "synthetic silver"), "2607")
    wrong_observation = replace(quote(), reference=wrong_contract)
    with pytest.raises(ValueError, match="exactly match"):
        snapshot(observations=(wrong_observation,), resolutions=(resolution(wrong_contract),))


def test_snapshot_cannot_be_bound_to_a_forged_registry_resolution() -> None:
    target = instrument()
    valid_mapping_alias = Resolution(
        target, "AG2606", EntityId.new("instrument_registry"), 1, "b" * 64, 1, provenance()
    )
    assert valid_mapping_alias.alias == "AG2606"
    with pytest.raises(ValueError, match="instrument_registry namespace"):
        Resolution(target, "AG2606", EntityId.new("evil_registry"), 1, "b" * 64, 1, provenance())
    with pytest.raises(ValueError, match="positive"):
        Resolution(target, "AG2606", EntityId.new("instrument_registry"), 0, "b" * 64, 1, provenance())
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        Resolution(target, "AG2606", EntityId.new("instrument_registry"), 1, "B" * 64, 1, provenance())


def test_hash_relevant_quality_and_bar_durations_reject_microsecond_truncation() -> None:
    with pytest.raises(ValueError, match="whole seconds"):
        BarInterval("1m", timedelta(minutes=1, microseconds=1))
    with pytest.raises(ValueError, match="whole seconds"):
        PurposeFreshnessPolicy(
            SnapshotPurpose.RESEARCH, timedelta(seconds=1, microseconds=1), (SessionPhase.CONTINUOUS,)
        )
    base = policy()
    with pytest.raises(ValueError, match="whole seconds"):
        MarketQualityPolicy(
            base.policy_id,
            base.version,
            base.freshness_by_purpose,
            timedelta(minutes=1, microseconds=1),
            base.max_price_jump_ratio,
        )


def test_observation_input_order_does_not_change_hash_but_explicit_late_arrival_is_out_of_order() -> None:
    early_event = quote(event=at(13, 5), available=at(13, 6), ingested=at(13, 6), source_sequence=1)
    late_event = quote(event=at(13, 4), available=at(13, 7), ingested=at(13, 7), source_sequence=2)
    forward = snapshot(observations=(early_event, late_event), purpose=SnapshotPurpose.BACKTEST)
    reversed_input = MarketSnapshot.freeze(
        EntityId.new("market_snapshot"),
        forward.as_of,
        forward.trading_date_resolution,
        forward.trading_calendar,
        (late_event, early_event),
        forward.reference_resolutions,
        forward.contract_rule_registry,
        forward.rule_resolution,
        forward.dataset_manifest,
        forward.schema_version,
        forward.quality_policy,
        forward.intended_purpose,
    )

    assert forward.expected_content_sha256 == reversed_input.expected_content_sha256
    assert forward.quality == reversed_input.quality
    assert forward.quality.has(MarketQualityCode.OUT_OF_ORDER_OBSERVATION)
    assert forward.eligible_for(SnapshotPurpose.BACKTEST) == Failure(
        ReasonCode.DATA_CONFLICT, "snapshot is not reliable enough for deterministic replay"
    )


def test_revision_history_replays_old_then_new_active_leaf_without_tuple_order() -> None:
    original = quote(event=at(13), available=at(13, 5), ingested=at(13, 5), source_sequence=1)
    correction = replace(
        original,
        observation_id=EntityId.new("market_observation"),
        available_time=at(13, 10),
        ingested_at=at(13, 10),
        last_price=Price("6100.0", "CNY", "CNY/tonne", 1),
        revision=2,
        supersedes_observation_id=original.observation_id,
    )

    old = snapshot(observations=(original,), as_of=at(13, 5), purpose=SnapshotPurpose.BACKTEST)
    new = snapshot(observations=(correction, original), as_of=at(14), purpose=SnapshotPurpose.BACKTEST)
    reversed_history = MarketSnapshot.freeze(
        EntityId.new("market_snapshot"),
        new.as_of,
        new.trading_date_resolution,
        new.trading_calendar,
        (original, correction),
        new.reference_resolutions,
        new.contract_rule_registry,
        new.rule_resolution,
        new.dataset_manifest,
        new.schema_version,
        new.quality_policy,
        new.intended_purpose,
    )

    assert old.active_observations == (original,)
    assert new.active_observations == (correction,)
    assert select_active_observations((original, correction), at(13, 5)) == (original,)
    assert select_active_observations((correction, original), at(14)) == (correction,)
    assert new.expected_content_sha256 == reversed_history.expected_content_sha256
    changed_superseded_fact = replace(original, last_price=Price("5900.0", "CNY", "CNY/tonne", 1))
    changed_history = snapshot(
        observations=(changed_superseded_fact, correction), as_of=at(14), purpose=SnapshotPurpose.BACKTEST
    )
    assert changed_history.active_observations == (correction,)
    assert changed_history.expected_content_sha256 != new.expected_content_sha256
    assert new.quality.issues == ()
    assert new.eligible_for(SnapshotPurpose.BACKTEST) is None


def test_revision_history_rejects_missing_predecessor_non_increment_lineage_change_and_fork() -> None:
    original = quote(event=at(13), available=at(13, 5), ingested=at(13, 5), source_sequence=1)
    correction = replace(
        original,
        observation_id=EntityId.new("market_observation"),
        available_time=at(13, 10),
        ingested_at=at(13, 10),
        revision=2,
        supersedes_observation_id=original.observation_id,
    )
    with pytest.raises(ValueError, match="predecessor is absent"):
        snapshot(observations=(correction,), as_of=at(14))
    with pytest.raises(ValueError, match="increment"):
        snapshot(observations=(original, replace(correction, revision=3)), as_of=at(14))
    with pytest.raises(ValueError, match="natural key and source lineage"):
        snapshot(
            observations=(
                original,
                replace(correction, source=ReferenceProvenance("dataset://different", at(8), at(8), "v2")),
            ),
            as_of=at(14),
        )
    fork = replace(
        correction,
        observation_id=EntityId.new("market_observation"),
        available_time=at(13, 11),
        ingested_at=at(13, 11),
    )
    with pytest.raises(ValueError, match="DATA_CONFLICT: market observation revision history forks"):
        snapshot(observations=(original, correction, fork), as_of=at(14))
    left_id, right_id = EntityId.new("market_observation"), EntityId.new("market_observation")
    cyclic_left = replace(original, observation_id=left_id, revision=2, supersedes_observation_id=right_id)
    cyclic_right = replace(
        correction,
        observation_id=right_id,
        revision=3,
        supersedes_observation_id=left_id,
    )
    with pytest.raises(ValueError, match="DATA_CONFLICT: market observation revision history contains a cycle"):
        snapshot(observations=(cyclic_left, cyclic_right), as_of=at(14))


def test_exact_contract_price_limit_confirms_jump_but_unqualified_jump_blocks_backtest() -> None:
    previous = quote(event=at(13), available=at(13), ingested=at(13), source_sequence=1)
    limit_hit = replace(
        quote(event=at(13, 30), available=at(13, 30), ingested=at(13, 30), source_sequence=2),
        last_price=Price("7000.0", "CNY", "CNY/tonne", 1),
        bid_price=Price("7000.0", "CNY", "CNY/tonne", 1),
        ask_price=Price("7000.0", "CNY", "CNY/tonne", 1),
    )
    confirmed = snapshot(observations=(previous, limit_hit), purpose=SnapshotPurpose.BACKTEST)
    assert confirmed.quality.has(MarketQualityCode.PRICE_LIMIT_CONFIRMED)
    assert not confirmed.quality.has(MarketQualityCode.PRICE_JUMP)
    assert confirmed.eligible_for(SnapshotPurpose.BACKTEST) is None

    unexplained = replace(
        limit_hit,
        observation_id=EntityId.new("market_observation"),
        last_price=Price("6800.0", "CNY", "CNY/tonne", 1),
        bid_price=Price("6800.0", "CNY", "CNY/tonne", 1),
        ask_price=Price("6800.0", "CNY", "CNY/tonne", 1),
    )
    blocked = snapshot(observations=(previous, unexplained), purpose=SnapshotPurpose.BACKTEST)
    assert blocked.quality.has(MarketQualityCode.PRICE_JUMP)
    assert blocked.eligible_for(SnapshotPurpose.BACKTEST) == Failure(
        ReasonCode.DATA_CONFLICT, "snapshot is not reliable enough for deterministic replay"
    )


def test_snapshot_rejects_forged_calendar_phase_ref_and_later_as_of_evidence() -> None:
    accepted = calendar_resolution()
    with pytest.raises(ValueError, match="schedule phase"):
        replace(accepted, phase=SessionPhase.BREAK)
    with pytest.raises(ValueError, match="agree with its schedule"):
        replace(accepted, trading_date=TradingDate.parse("2026-08-26"))

    forged_ref = replace(
        accepted,
        calendar_ref=TradingCalendarRef(EntityId.new("trading_calendar"), 1, "f" * 64),
    )
    with pytest.raises(ValueError, match="backed by its immutable TradingCalendar"):
        snapshot(calendar=forged_ref)
    with pytest.raises(ValueError, match="as_of must exactly match"):
        snapshot(calendar=replace(accepted, as_of=at(15)), as_of=at(14))


def _final_bar(sequence: int, opening: str, closing: str) -> MarketObservation:
    event = at(13, sequence)
    return MarketObservation(
        EntityId.new("market_observation"),
        instrument(),
        ObservationKind.BAR,
        event,
        event,
        event,
        provenance(),
        SourceTrust.PRIMARY,
        SchemaVersion(1, 0),
        sequence,
        DatasetRecordRef(_MANIFEST_ID, f"bar/{sequence}", format(sequence, "064x")),
        open_price=Price(opening, "CNY", "CNY/tonne", 1),
        high_price=Price(str(max(Decimal(opening), Decimal(closing)) + Decimal("1.0")), "CNY", "CNY/tonne", 1),
        low_price=Price(str(min(Decimal(opening), Decimal(closing)) - Decimal("1.0")), "CNY", "CNY/tonne", 1),
        close_price=Price(closing, "CNY", "CNY/tonne", 1),
        volume=Quantity("10", "lot", 0),
        bar_interval=BarInterval("1m", timedelta(minutes=1)),
        bar_status=BarStatus.FINAL,
    )


def _v1_010_research(as_of: RecordedAt):
    valid_until = RecordedAt(as_of.value + timedelta(hours=1))
    market = MarketStateAssessmentRef(
        EntityId.new("market_state_assessment"), SchemaVersion(1, 5), as_of, valid_until, "a" * 64
    )
    values = ResearchSynthesisInput(
        "A fixed signal differs from its prespecified control.",
        ("AG",),
        "Held-out return differs from control.",
        "Held-out return includes zero.",
        ("historical_data",),
        HypothesisProposalSource.MARKET_STATE_ASSESSMENT,
        ("Frozen PIT bars are available.",),
        (),
        (),
        ("Run the fixed suite.",),
        (EvidenceGap("validation", "Requires deterministic diagnostics."),),
        "Zero-return control.",
        "Fixed chronological windows.",
        "Synchronous deterministic proxy.",
        ("mean_return",),
        ("all eight critic diagnostics",),
        "Stop after fixed folds.",
        ("selection_bias",),
    )
    return ResearchSynthesisComposer().compose(
        FalsifiableHypothesisSpec(EntityId.new("hypothesis_spec"), 1, SchemaVersion(1, 5)),
        ExperimentRequestSpec(EntityId.new("experiment_request_spec"), 1, SchemaVersion(1, 5)),
        market,
        values,
        valid_until,
    )


def test_v1_010_snapshot_validation_diagnostics_and_critic_are_replayable_and_fail_closed() -> None:
    bars = tuple(_final_bar(index, f"{6000 + index}.0", f"{6000 + index}.0") for index in range(1, 38))
    frozen = snapshot(observations=bars, as_of=at(14), purpose=SnapshotPurpose.RESEARCH)
    config = ValidationConfig(
        EntityId.new("research_validation_config"),
        1,
        20,
        5,
        5,
        20,
        Decimal("0.00010000"),
        Decimal("0.00000000"),
        Decimal("0.00000000"),
        (Decimal("1.00000000"), Decimal("2.00000000")),
        2,
    )
    valid_until = RecordedAt(frozen.as_of.value + timedelta(hours=1))
    research = _v1_010_research(frozen.as_of)
    scope = ResearchQueryScope(
        frozen.rule_resolution.rule.instrument.reference_id,
        frozen.rule_resolution.rule.instrument.variety.code,
        config.signal_rule,
        config.content_sha256,
        research.hypothesis.content_sha256,
        ("AG",),
    )
    snapshot_ref = ResearchArtifactRef(
        frozen.snapshot_id,
        "market_snapshot",
        frozen.schema_version,
        frozen.expected_content_sha256,
        frozen.as_of,
        valid_until,
    )
    feature_definition_ref = {
        "definition_id": str(EntityId.new("feature_definition")),
        "version": 1,
        "schema_version": "1.0",
        "content_sha256": "8" * 64,
        "algorithm": "SIMPLE_RETURN",
    }
    feature_payload = {
        "feature_spec_id": str(PRIOR_CLOSE_RETURN_FEATURE_SPEC_ID),
        "feature_spec_content_sha256": PRIOR_CLOSE_RETURN_FEATURE_SPEC_SHA256,
        "feature_spec": {
            "spec_id": str(PRIOR_CLOSE_RETURN_FEATURE_SPEC_ID),
            "version": 1,
            "schema_version": "1.0",
            "content_sha256": PRIOR_CLOSE_RETURN_FEATURE_SPEC_SHA256,
            "definition": feature_definition_ref,
        },
        "feature_definition": feature_definition_ref,
        "feature_algorithm": "SIMPLE_RETURN",
        "target_reference_id": frozen.rule_resolution.rule.instrument.reference_id,
        "as_of": frozen.as_of.to_dict()["recorded_at"],
        "input_window_size": 2,
        "market_snapshot_refs": (
            {
                "snapshot_id": str(EntityId.new("market_snapshot")),
                "content_sha256": "7" * 64,
                "as_of": at(13).to_dict()["recorded_at"],
                "schema_version": str(frozen.schema_version),
                "purpose": frozen.intended_purpose.value,
            },
            {
                "snapshot_id": str(frozen.snapshot_id),
                "content_sha256": frozen.expected_content_sha256,
                "as_of": frozen.as_of.to_dict()["recorded_at"],
                "schema_version": str(frozen.schema_version),
                "purpose": frozen.intended_purpose.value,
            },
        ),
        "observation_ids": (str(bars[-2].observation_id), str(bars[-1].observation_id)),
        "input_observation_refs": (
            {
                "observation_id": str(bars[-2].observation_id),
                "content_sha256": bars[-2].dataset_record_ref.record_sha256,
            },
            {
                "observation_id": str(bars[-1].observation_id),
                "content_sha256": bars[-1].dataset_record_ref.record_sha256,
            },
        ),
        "value": {"amount": "0.00010000", "unit": "ratio", "scale": 8},
        "schema_version": "1.0",
    }
    attacker_feature_authority = TrustedFeatureEvidencePort(b"attacker-feature-secret-v1-010-test")
    attacker_memory_authority = TrustedMemorySearchPort(b"attacker-memory-secret-v1-010-tests-")
    attacker_experiment_authority = TrustedExperimentSearchPort(b"attacker-experiment-secret-v1-tests")
    feature_authority = TrustedFeatureEvidencePort(b"feature-owner-secret-for-v1-010-tests")
    memory_authority = TrustedMemorySearchPort(b"memory-owner-secret-for-v1-010-tests-")
    experiment_authority = TrustedExperimentSearchPort(b"experiment-owner-secret-v1-010-tests")
    result_authority = TrustedResearchToolsPort(b"result-owner-secret-for-v1-010-tests-")
    feature_observation = FeatureObservation.hydrate(EntityId.new("feature_observation"), feature_payload)
    feature = feature_authority.issue(
        feature_observation,
        snapshot_ref,
        valid_until,
        scope,
    )
    lesson = MemorySearchRecord(
        ResearchArtifactRef(
            EntityId.new("artifact"), "validated_lesson", SchemaVersion(1, 5), "f" * 64, at(12), valid_until
        ),
        ("AG",),
        scope_sha256=scope.content_sha256,
    )
    provenance_ref = ResearchArtifactRef(
        EntityId.new("artifact"), "dataset", SchemaVersion(1, 5), "d" * 64, at(11), valid_until
    )
    failed_experiment = ExperimentSearchRecord(
        ResearchArtifactRef(
            EntityId.new("artifact"), "experiment_result", SchemaVersion(1, 5), "c" * 64, at(12), valid_until
        ),
        ("AG",),
        ExperimentOutcome.SUCCESS,
        at(13),
        (provenance_ref,),
        scope.content_sha256,
    )
    request = ValidationRunRequest(
        EntityId.new("research_validation_request"),
        EntityId.new("research_validation_run"),
        snapshot_ref,
        config,
        scope,
        (feature,),
        memory_authority.issue((lesson,)),
        experiment_authority.issue((failed_experiment,)),
    )
    hydrated_request = ValidationRunRequest.hydrate(request.to_dict())
    tools = DeterministicResearchTools(feature_authority, memory_authority, experiment_authority, result_authority)
    attacker_feature = attacker_feature_authority.issue(feature_observation, snapshot_ref, valid_until, scope)
    with pytest.raises(ValueError, match="authority proof"):
        tools.run_snapshot_suite(frozen, replace(request, feature_evidence=(attacker_feature,)))
    with pytest.raises(ValueError, match="authority proof"):
        tools.run_snapshot_suite(frozen, replace(request, memory_batch=attacker_memory_authority.issue((lesson,))))
    forged_provenance = replace(provenance_ref, content_sha256="9" * 64)
    forged_experiment = replace(failed_experiment, provenance_refs=(forged_provenance,))
    with pytest.raises(ValueError, match="authority proof"):
        tools.run_snapshot_suite(
            frozen,
            replace(
                request,
                experiment_batch=attacker_experiment_authority.issue((forged_experiment,)),
            ),
        )
    results = tools.run_snapshot_suite(frozen, request)
    replayed_results = DeterministicResearchTools(
        feature_authority, memory_authority, experiment_authority, result_authority
    ).run_snapshot_suite(frozen, hydrated_request)
    evaluated_at = RecordedAt(frozen.as_of.value + timedelta(minutes=10))
    expires_at = RecordedAt(frozen.as_of.value + timedelta(minutes=30))
    diagnostics = V1_010DiagnosticProducer(tools).produce(
        frozen,
        request,
        results,
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        evaluated_at,
    )
    diagnostics = tuple(
        type(item)(
            DiagnosticEvidenceV1_010.hydrate(
                json.loads(json.dumps(item.evidence.to_dict())),
                item.evidence.research_sources,
                item.evidence.tool_results,
            )
        )
        for item in diagnostics
    )
    critique = V1_010CriticWorker().run(
        frozen,
        request,
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        diagnostics,
        evaluated_at,
        expires_at,
    )

    assert len(results) == 11
    assert all(result.failure_code is ToolFailureCode.NONE for result in results)
    assert tuple(result.content_sha256 for result in results) == tuple(
        result.content_sha256 for result in replayed_results
    )
    assert results == replayed_results
    assert all(result.artifact_refs[0].content_sha256 == result.content_sha256 for result in results)
    assert type(results[0]).hydrate(results[0].to_dict()).content_sha256 == results[0].content_sha256
    assert len(critique.diagnostics) == 8
    assert all(item.evidence.evaluated_at == evaluated_at for item in critique.diagnostics)
    assert critique.status is CritiqueStatus.PASS
    hydrated_critique = type(critique).hydrate(
        critique.to_dict(),
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        results,
    )
    assert hydrated_critique == critique
    assert (
        critique.content_sha256
        == V1_010CritiqueComposer()
        .compose(
            frozen,
            hydrated_request,
            research.hypothesis,
            research.evidence_synthesis,
            research.experiment_request,
            diagnostics,
            evaluated_at,
            expires_at,
        )
        .content_sha256
    )

    different_request = replace(
        request,
        request_id=EntityId.new("research_validation_request"),
        run_id=EntityId.new("research_validation_run"),
    )
    different_run = tools.run_snapshot_suite(frozen, different_request)
    with pytest.raises(ValueError, match="untrusted or non-deterministic"):
        V1_010DiagnosticProducer(tools).produce(
            frozen,
            request,
            (*results[:-1], different_run[-1]),
            research.hypothesis,
            research.evidence_synthesis,
            research.experiment_request,
            evaluated_at,
        )

    insufficient = replace(config, train_bars=30)
    insufficient_scope = replace(scope, config_sha256=insufficient.content_sha256)
    insufficient_scope_sha = insufficient_scope.content_sha256
    deferred_request = replace(
        request,
        config=insufficient,
        query_scope=insufficient_scope,
        feature_evidence=(feature_authority.issue(feature_observation, snapshot_ref, valid_until, insufficient_scope),),
        memory_batch=memory_authority.issue((replace(lesson, scope_sha256=insufficient_scope_sha),)),
        experiment_batch=experiment_authority.issue((replace(failed_experiment, scope_sha256=insufficient_scope_sha),)),
    )
    deferred_results = tools.run_snapshot_suite(frozen, deferred_request)
    deferred_diagnostics = V1_010DiagnosticProducer(tools).produce(
        frozen,
        deferred_request,
        deferred_results,
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        evaluated_at,
    )
    deferred = V1_010CritiqueComposer().compose(
        frozen,
        deferred_request,
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        deferred_diagnostics,
        evaluated_at,
        expires_at,
    )
    assert deferred.status is CritiqueStatus.DEFER
    assert deferred.required_validations

    failed_record = replace(failed_experiment, outcome=ExperimentOutcome.FAILED)
    failed_request = replace(request, experiment_batch=experiment_authority.issue((failed_record,)))
    failed_results = tools.run_snapshot_suite(frozen, failed_request)
    experiment_result = next(item for item in failed_results if item.tool.value == "experiment_search")
    forged_metrics = tuple(
        sorted(
            (key, "0" if key == "failed_count" else "1" if key == "success_count" else value)
            for key, value in experiment_result.metrics
        )
    )
    forged_payload = {**experiment_result.payload(), "metrics": forged_metrics}
    forged_result = replace(
        experiment_result,
        metrics=forged_metrics,
        content_sha256=canonical_sha256(forged_payload),
    )
    forged_results = tuple(forged_result if item.tool is experiment_result.tool else item for item in failed_results)
    assert forged_result.result_id == experiment_result.result_id
    with pytest.raises(ValueError, match="authority proof|non-deterministic"):
        V1_010DiagnosticProducer(tools).produce(
            frozen,
            failed_request,
            forged_results,
            research.hypothesis,
            research.evidence_synthesis,
            research.experiment_request,
            evaluated_at,
        )
    unknown_metrics = tuple(sorted((*experiment_result.metrics, ("caller_metric", "999"))))
    unknown_payload = {**experiment_result.payload(), "metrics": unknown_metrics}
    unknown_result = replace(
        experiment_result,
        metrics=unknown_metrics,
        content_sha256=canonical_sha256(unknown_payload),
    )
    with pytest.raises(ValueError, match="authority proof|non-deterministic"):
        V1_010DiagnosticProducer(tools).produce(
            frozen,
            failed_request,
            tuple(unknown_result if item.tool is experiment_result.tool else item for item in failed_results),
            research.hypothesis,
            research.evidence_synthesis,
            research.experiment_request,
            evaluated_at,
        )
    failed_diagnostics = V1_010DiagnosticProducer(tools).produce(
        frozen,
        failed_request,
        failed_results,
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        evaluated_at,
    )
    failed_critique = V1_010CritiqueComposer().compose(
        frozen,
        failed_request,
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        failed_diagnostics,
        evaluated_at,
        expires_at,
    )
    assert failed_critique.status is CritiqueStatus.DEFER
    assert any("HISTORICAL_FAILURE" in item for item in failed_critique.required_validations)

    no_memory_request = replace(request, memory_batch=memory_authority.issue(()))
    no_memory_results = tools.run_snapshot_suite(frozen, no_memory_request)
    no_memory_diagnostics = V1_010DiagnosticProducer(tools).produce(
        frozen,
        no_memory_request,
        no_memory_results,
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        evaluated_at,
    )
    no_memory_critique = V1_010CritiqueComposer().compose(
        frozen,
        no_memory_request,
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        no_memory_diagnostics,
        evaluated_at,
        expires_at,
    )
    assert no_memory_critique.status is CritiqueStatus.DEFER

    stress = next(result for result in results if result.tool.value == "cost_slippage_stress")
    scenarios = json.loads(dict(stress.metrics)["scenarios"])
    assert {item["changed_variable"] for item in scenarios} == {
        "none",
        "round_trip_cost_bps",
        "slippage_bps",
    }
    assert all(set(item) == {"changed_variable", "multiplier", "net_mean"} for item in scenarios)

    with pytest.raises(ValueError, match="lifetime must be fixed"):
        replace(request, snapshot_ref=replace(snapshot_ref, valid_until=at(16)))
    with pytest.raises(ValueError, match="pinned V1-005"):
        replace(feature, feature_name="caller_feature")
    with pytest.raises(TypeError, match="owner FeatureObservation"):
        feature_authority.issue(feature_payload, snapshot_ref, valid_until, scope)  # type: ignore[arg-type]
    nan_payload = json.loads(json.dumps(feature_payload))
    nan_payload["value"]["amount"] = "NaN"
    with pytest.raises(TypeError, match="finite Decimal"):
        FeatureObservation.hydrate(EntityId.new("feature_observation"), nan_payload)
    bad_window = json.loads(json.dumps(feature_payload))
    bad_window["input_window_size"] = 1
    with pytest.raises(ValueError, match="window must exactly"):
        FeatureObservation.hydrate(EntityId.new("feature_observation"), bad_window)
    bad_observation_refs = json.loads(json.dumps(feature_payload))
    bad_observation_refs["observation_ids"] = bad_observation_refs["observation_ids"][:-1]
    with pytest.raises(TypeError, match="per-observation refs"):
        FeatureObservation.hydrate(EntityId.new("feature_observation"), bad_observation_refs)
    bad_spec = json.loads(json.dumps(feature_payload))
    bad_spec["feature_spec_content_sha256"] = "0" * 64
    bad_spec["feature_spec"]["content_sha256"] = "0" * 64
    bad_spec_observation = FeatureObservation.hydrate(EntityId.new("feature_observation"), bad_spec)
    with pytest.raises(ValueError, match="target/spec/snapshot"):
        feature_authority.issue(bad_spec_observation, snapshot_ref, valid_until, scope)
    wrong_definition_namespace = json.loads(json.dumps(feature_payload))
    wrong_definition_namespace["feature_definition"]["definition_id"] = str(EntityId.new("artifact"))
    with pytest.raises(ValueError, match="feature_definition id"):
        FeatureObservation.hydrate(EntityId.new("feature_observation"), wrong_definition_namespace)
    wrong_definition_hash = json.loads(json.dumps(feature_payload))
    wrong_definition_hash["feature_definition"]["content_sha256"] = "1" * 64
    with pytest.raises(ValueError, match="refs must agree"):
        FeatureObservation.hydrate(EntityId.new("feature_observation"), wrong_definition_hash)
    spec_definition_mismatch = json.loads(json.dumps(feature_payload))
    spec_definition_mismatch["feature_spec"]["definition"]["definition_id"] = str(EntityId.new("feature_definition"))
    with pytest.raises(ValueError, match="refs must agree"):
        FeatureObservation.hydrate(EntityId.new("feature_observation"), spec_definition_mismatch)
    duplicate_snapshot = json.loads(json.dumps(feature_payload))
    duplicate_snapshot["market_snapshot_refs"][0]["snapshot_id"] = duplicate_snapshot["market_snapshot_refs"][1][
        "snapshot_id"
    ]
    with pytest.raises(ValueError, match="repeat a market snapshot"):
        FeatureObservation.hydrate(EntityId.new("feature_observation"), duplicate_snapshot)
    wrong_target = json.loads(json.dumps(feature_payload))
    wrong_target["target_reference_id"] = "SHFE.CU2606"
    wrong_target_observation = FeatureObservation.hydrate(EntityId.new("feature_observation"), wrong_target)
    with pytest.raises(ValueError, match="target/spec/snapshot"):
        feature_authority.issue(wrong_target_observation, snapshot_ref, valid_until, scope)
    wrong_snapshot = json.loads(json.dumps(feature_payload))
    wrong_snapshot["market_snapshot_refs"][-1]["content_sha256"] = "6" * 64
    wrong_snapshot_observation = FeatureObservation.hydrate(EntityId.new("feature_observation"), wrong_snapshot)
    with pytest.raises(ValueError, match="target/spec/snapshot"):
        feature_authority.issue(wrong_snapshot_observation, snapshot_ref, valid_until, scope)
    with pytest.raises(ValueError, match="cannot be empty"):
        replace(scope, tags=())
    unrelated = replace(failed_experiment, tags=("CU",))
    with pytest.raises(ValueError, match="exact research query scope"):
        replace(request, experiment_batch=experiment_authority.issue((unrelated,)))

    sources = V1_010CriticTaskSources(
        frozen,
        request,
        results,
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        diagnostics,
        evaluated_at,
        expires_at,
    )
    agent = V1_010ResearchCriticAgent()
    correlation_id = EntityId.new("correlation")
    task = AgentTaskEnvelope(
        EntityId.new("agent_task"),
        EntityId.new("session"),
        correlation_id,
        TraceContext(correlation_id, EntityId.new("trace")),
        AgentRoleId.PRE_TRADE_CRITIC.value,
        SchemaVersion(1, 5),
        "compose the frozen research diagnostics",
        "emit one replayable research critique",
        (TriggerSource.DATA,),
        agent.expected_inputs(sources),
        (),
        (),
        definition_for(AgentRoleId.PRE_TRADE_CRITIC.value, SchemaVersion(1, 5)).budget,
        (ArtifactKind.CRITIQUE,),
        frozen.as_of,
        expires_at,
    )
    producer_run = EntityId.new("agent_run")
    packaged = agent.run(task, sources, producer_run)
    serialized_diagnostics = tuple(json.loads(json.dumps(item.evidence.to_dict())) for item in diagnostics)
    assert agent.run_serialized_diagnostics(task, sources, serialized_diagnostics, producer_run) == packaged
    missing_gate = agent.run_serialized_diagnostics(task, sources, serialized_diagnostics[:-1], producer_run)
    assert missing_gate.status is ResultStatus.FAILED
    assert missing_gate.artifacts == ()
    assert "DIAGNOSTIC_MISSING" in missing_gate.unknowns
    tampered_diagnostics = list(serialized_diagnostics)
    tampered_diagnostics[0] = {**tampered_diagnostics[0], "content_sha256": "0" * 64}
    invalid_gate = agent.run_serialized_diagnostics(task, sources, tuple(tampered_diagnostics), producer_run)
    assert invalid_gate.status is ResultStatus.FAILED
    assert invalid_gate.artifacts == ()
    assert "DIAGNOSTIC_INVALID" in invalid_gate.warnings
    duplicated_diagnostics = (*serialized_diagnostics[:-1], serialized_diagnostics[0])
    duplicate_gate = agent.run_serialized_diagnostics(task, sources, duplicated_diagnostics, producer_run)
    assert duplicate_gate.status is ResultStatus.FAILED
    assert "DIAGNOSTIC_INVALID" in duplicate_gate.unknowns
    expired_diagnostics = list(serialized_diagnostics)
    expired_ref = dict(expired_diagnostics[0]["market_snapshot_ref"])
    expired_ref["valid_until"] = expired_diagnostics[0]["evaluated_at"]
    expired_diagnostics[0] = {
        **expired_diagnostics[0],
        "market_snapshot_ref": expired_ref,
    }
    expired_gate = agent.run_serialized_diagnostics(task, sources, tuple(expired_diagnostics), producer_run)
    assert expired_gate.status is ResultStatus.FAILED
    assert expired_gate.artifacts == ()
    serialized = json.loads(json.dumps(packaged.to_dict()))
    recovered = V1_010ResearchCriticAgent().recover(serialized, task, sources, producer_run)
    assert recovered == packaged
    assert recovered.artifact.ref.content_hash == "sha256:" + critique.content_sha256
    assert all(ref.created_at == evaluated_at for ref in recovered.artifact.source_refs[4:])
    with pytest.raises(ValueError, match="task envelope|task boundary"):
        agent.run(replace(task, catalog_version=SchemaVersion(1, 4)), sources, producer_run)
    serialized["artifact"]["warnings"] = ["tampered"]
    with pytest.raises(ValueError, match="content hash|deterministic replay"):
        V1_010ResearchCriticAgent().recover(serialized, task, sources, producer_run)
