"""Contracts for immutable point-in-time market snapshots and quality gates."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from dataclasses import FrozenInstanceError, replace

import pytest

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
    TradingDate,
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
