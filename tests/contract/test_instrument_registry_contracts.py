from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from futures_agent_os.reference_market_data import (
    AliasMapping,
    ContinuousAdjustment,
    ContinuousSeries,
    DominantContractReference,
    EffectiveInterval,
    Exchange,
    Instrument,
    InstrumentRegistry,
    INITIAL_ACCEPTANCE_REGISTRY_ID,
    INITIAL_ACCEPTANCE_REGISTRY_RELEASE_VERSION,
    INITIAL_ACCEPTANCE_REGISTRY_SHA256,
    ReferenceKind,
    ReferenceProvenance,
    Variety,
    initial_acceptance_registry,
    registry_content_sha256,
)
from futures_agent_os.shared_kernel import EntityId, Failure, ReasonCode, RecordedAt


def at(hour: int) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 23, hour, tzinfo=UTC))


def provenance() -> ReferenceProvenance:
    return ReferenceProvenance("test://exchange-notice", at(0), at(0), "notice-1")


def make_registry(*aliases: AliasMapping) -> InstrumentRegistry:
    return InstrumentRegistry(EntityId.new("instrument_registry"), 1, aliases, registry_content_sha256(aliases))


def test_first_acceptance_universe_has_exchange_scoped_case_insensitive_variety_aliases() -> None:
    registry = initial_acceptance_registry()
    expected = {
        "AG": Exchange.SHFE,
        "CU": Exchange.SHFE,
        "RB": Exchange.SHFE,
        "JM": Exchange.DCE,
        "I": Exchange.DCE,
        "MA": Exchange.CZCE,
        "SA": Exchange.CZCE,
        "M": Exchange.DCE,
        "P": Exchange.DCE,
        "SR": Exchange.CZCE,
        "SC": Exchange.INE,
        "JD": Exchange.DCE,
    }

    for code, exchange in expected.items():
        bare = registry.resolve(code.lower(), at(1))
        qualified = registry.resolve(f"{exchange.value.lower()}.{code.lower()}", at(1))
        assert not isinstance(bare, Failure)
        assert not isinstance(qualified, Failure)
        assert bare.kind is ReferenceKind.VARIETY
        assert bare.target.exchange is exchange
        assert qualified.target == bare.target

    wrong_exchange = registry.resolve("DCE.AG", at(1))
    assert wrong_exchange == Failure(ReasonCode.INSTRUMENT_UNKNOWN, "identifier has no mapping visible at as_of")

    expected_contracts = {
        "SHFE.AG2602",
        "SHFE.CU2603",
        "SHFE.RB2605",
        "DCE.JM2605",
        "DCE.I2605",
        "CZCE.MA605",
        "CZCE.SA605",
        "DCE.M2605",
        "DCE.P2605",
        "CZCE.SR603",
        "INE.SC2603",
        "DCE.JD2605",
    }
    for identifier in expected_contracts:
        assert isinstance(registry.resolve_tradeable(identifier.lower(), at(1)), Instrument)
    assert registry.resolve_tradeable("DCE.I9999", at(1)) == Failure(
        ReasonCode.INSTRUMENT_UNKNOWN, "identifier has no mapping visible at as_of"
    )
    assert registry.registry_id == INITIAL_ACCEPTANCE_REGISTRY_ID
    assert registry.release_version == INITIAL_ACCEPTANCE_REGISTRY_RELEASE_VERSION
    assert registry.expected_content_sha256 == INITIAL_ACCEPTANCE_REGISTRY_SHA256


def test_concrete_instrument_dominant_reference_and_continuous_series_are_distinct() -> None:
    variety = Variety(Exchange.SHFE, "AG", "silver")
    instrument = Instrument(variety, "2606")
    continuous = ContinuousSeries(variety, "FRONT", ContinuousAdjustment.BACK_ADJUSTED, "roll-rule:ag-front-v1")
    dominant = DominantContractReference(variety, instrument, EffectiveInterval(at(0), at(2)), 1, provenance())
    registry = make_registry(
        AliasMapping("SHFE.AG2606", instrument, EffectiveInterval(at(0)), 1, provenance()),
        AliasMapping("DOMINANT.SHFE.AG", dominant, EffectiveInterval(at(0), at(2)), 1, provenance()),
        AliasMapping("CONTINUOUS.SHFE.AG.FRONT", continuous, EffectiveInterval(at(0)), 1, provenance()),
    )

    assert registry.resolve("shfe.ag2606", at(1)).kind is ReferenceKind.INSTRUMENT  # type: ignore[union-attr]
    assert registry.resolve("dominant.shfe.ag", at(1)).kind is ReferenceKind.DOMINANT_CONTRACT  # type: ignore[union-attr]
    assert registry.resolve("continuous.shfe.ag.front", at(1)).kind is ReferenceKind.CONTINUOUS_SERIES  # type: ignore[union-attr]
    assert registry.resolve_tradeable("SHFE.AG2606", at(1)) == instrument
    assert registry.resolve_tradeable("CONTINUOUS.SHFE.AG.FRONT", at(1)) == Failure(
        ReasonCode.CONTINUOUS_SERIES_NOT_TRADABLE, "continuous series must resolve to an Instrument first"
    )
    assert registry.resolve_tradeable("DOMINANT.SHFE.AG", at(1)) == Failure(
        ReasonCode.INSTRUMENT_NOT_TRADEABLE, "order target must be a specific Instrument"
    )
    assert registry.resolve("DOMINANT.SHFE.AG", at(2)) == Failure(
        ReasonCode.REFERENCE_MAPPING_EXPIRED, "identifier mapping is no longer effective"
    )


def test_czce_three_digit_delivery_code_requires_a_registered_point_in_time_mapping() -> None:
    variety = Variety(Exchange.CZCE, "MA", "methanol")
    contract = Instrument(variety, "609")
    registry = make_registry(
        AliasMapping("CZCE.MA609", contract, EffectiveInterval(at(0), at(1)), 1, provenance()),
    )

    assert registry.resolve_tradeable("MA609", at(0)) == Failure(
        ReasonCode.INSTRUMENT_NOT_TRADEABLE, "order target must use an exchange-qualified Instrument alias"
    )
    assert registry.resolve_tradeable("CZCE.MA609", at(1)) == Failure(
        ReasonCode.REFERENCE_MAPPING_EXPIRED, "identifier mapping is no longer effective"
    )
    assert Instrument(variety, "609").delivery_code == "609"
    with pytest.raises(ValueError, match="delivery_code"):
        Instrument(variety, "260609")


def test_unknown_malformed_and_conflicting_aliases_fail_closed() -> None:
    variety = Variety(Exchange.DCE, "I", "iron ore")
    left = Instrument(variety, "2609")
    right = Instrument(variety, "2701")
    with pytest.raises(ValueError, match="overlapping"):
        make_registry(
            AliasMapping("DCE.I2609", left, EffectiveInterval(at(0)), 1, provenance()),
            AliasMapping("I", left, EffectiveInterval(at(0)), 1, provenance()),
            AliasMapping("I", right, EffectiveInterval(at(0)), 2, provenance()),
        )
    unambiguous = make_registry(AliasMapping("DCE.I2609", left, EffectiveInterval(at(0)), 1, provenance()))
    assert unambiguous.resolve("I9999", at(1)) == Failure(
        ReasonCode.INSTRUMENT_UNKNOWN, "identifier has no mapping visible at as_of"
    )
    assert unambiguous.resolve(" I ", at(1)) == Failure(
        ReasonCode.INSTRUMENT_MALFORMED, "identifier must be a canonical non-whitespace alias"
    )
    assert unambiguous.resolve("I@", at(1)) == Failure(
        ReasonCode.INSTRUMENT_MALFORMED, "identifier must be a canonical non-whitespace alias"
    )


def test_mapping_is_not_visible_before_its_effective_time_even_when_the_alias_exists() -> None:
    variety = Variety(Exchange.INE, "SC", "crude oil")
    instrument = Instrument(variety, "2609")
    registry = make_registry(
        AliasMapping("INE.SC2609", instrument, EffectiveInterval(at(1)), 1, provenance()),
    )

    assert registry.resolve("INE.SC2609", at(0)) == Failure(
        ReasonCode.INSTRUMENT_UNKNOWN, "identifier has no mapping visible at as_of"
    )


@pytest.mark.parametrize("invalid_as_of", ("bad", None, 123))
def test_public_point_in_time_helpers_reject_untyped_as_of(invalid_as_of: object) -> None:
    interval = EffectiveInterval(at(0), at(1))
    source = provenance()
    with pytest.raises(TypeError, match="typed as_of"):
        interval.contains(invalid_as_of)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="typed as_of"):
        interval.expired_at(invalid_as_of)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="typed as_of"):
        source.is_visible_at(invalid_as_of)  # type: ignore[arg-type]


def test_provenance_visibility_and_dominant_target_validity_are_point_in_time_gates() -> None:
    variety = Variety(Exchange.SHFE, "AG", "silver")
    instrument = Instrument(variety, "2606")
    future_provenance = ReferenceProvenance("test://notice", at(2), at(1), "2")
    future_registry = make_registry(
        AliasMapping("SHFE.AG2606", instrument, EffectiveInterval(at(0)), 1, future_provenance)
    )
    assert future_registry.resolve("SHFE.AG2606", at(1)) == Failure(
        ReasonCode.REFERENCE_NOT_YET_VISIBLE, "identifier mapping was not acquired at as_of"
    )

    late_dominant = DominantContractReference(
        variety,
        instrument,
        EffectiveInterval(at(0), at(2)),
        1,
        ReferenceProvenance("test://dominant", at(2), at(1), "2"),
    )
    late_target_registry = make_registry(
        AliasMapping("DOMINANT.SHFE.AG", late_dominant, EffectiveInterval(at(0), at(2)), 1, provenance())
    )
    assert late_target_registry.resolve("DOMINANT.SHFE.AG", at(1)) == Failure(
        ReasonCode.REFERENCE_NOT_YET_VISIBLE, "identifier target was not acquired at as_of"
    )

    dominant = DominantContractReference(variety, instrument, EffectiveInterval(at(0), at(1)), 1, provenance())
    alias_longer_than_target = make_registry(
        AliasMapping("DOMINANT.SHFE.AG", dominant, EffectiveInterval(at(0), at(2)), 1, provenance())
    )
    assert alias_longer_than_target.resolve("DOMINANT.SHFE.AG", at(1)) == Failure(
        ReasonCode.REFERENCE_MAPPING_EXPIRED, "identifier target is not effective at as_of"
    )


@pytest.mark.parametrize(
    ("exchange", "accepted", "rejected"),
    [
        (Exchange.SHFE, "2606", "606"),
        (Exchange.DCE, "2606", "606"),
        (Exchange.INE, "2606", "606"),
        (Exchange.CZCE, "606", "2606"),
    ],
)
def test_delivery_code_conventions_are_exchange_specific(exchange: Exchange, accepted: str, rejected: str) -> None:
    variety = Variety(exchange, "X", "synthetic")
    assert Instrument(variety, accepted).delivery_code == accepted
    with pytest.raises(ValueError, match="exchange-specific"):
        Instrument(variety, rejected)
    with pytest.raises(TypeError, match="delivery_code"):
        Instrument(variety, 2606)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="RecordedAt"):
        EffectiveInterval("2026-08-23")  # type: ignore[arg-type]


def test_ascii_normalization_precedes_uppercase_and_release_hash_is_verifiable() -> None:
    variety = Variety(Exchange.DCE, "I", "iron ore")
    instrument = Instrument(variety, "2609")
    alias = AliasMapping("DCE.I2609", instrument, EffectiveInterval(at(0)), 1, provenance())
    expected = registry_content_sha256((alias,))
    release_id = EntityId.new("instrument_registry")
    registry = InstrumentRegistry(release_id, 1, (alias,), expected)

    assert registry.resolve("ſhfe.ag2609", at(1)) == Failure(
        ReasonCode.INSTRUMENT_MALFORMED, "identifier must be a canonical non-whitespace alias"
    )
    assert registry.resolve("ı", at(1)) == Failure(
        ReasonCode.INSTRUMENT_MALFORMED, "identifier must be a canonical non-whitespace alias"
    )
    outcome = registry.resolve("DCE.I2609", at(1))
    assert not isinstance(outcome, Failure)
    assert outcome.registry_id == release_id
    assert outcome.release_version == 1
    assert outcome.registry_content_sha256 == expected
    with pytest.raises(ValueError, match="expected_content_sha256"):
        InstrumentRegistry(release_id, 1, (alias,), "0" * 64)


def test_release_rejects_overlaps_but_allows_half_open_adjacency() -> None:
    variety = Variety(Exchange.DCE, "I", "iron ore")
    first = Instrument(variety, "2609")
    second = Instrument(variety, "2701")
    aliases = (
        AliasMapping("DCE.I", first, EffectiveInterval(at(0), at(1)), 1, provenance()),
        AliasMapping("DCE.I", second, EffectiveInterval(at(1), at(2)), 2, provenance()),
    )
    registry = make_registry(*aliases)
    assert registry.resolve("DCE.I", at(1)).target == second  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="overlapping"):
        make_registry(aliases[0], AliasMapping("DCE.I", second, EffectiveInterval(at(0), at(1)), 2, provenance()))


def test_initial_release_oracle_rejects_a_single_field_drift_and_registry_namespace_is_fixed() -> None:
    fixture = initial_acceptance_registry()
    drifted = list(fixture.aliases)
    original = drifted[0]
    drifted[0] = AliasMapping(
        original.alias, original.target, original.effective, original.version + 1, original.provenance
    )
    with pytest.raises(ValueError, match="expected_content_sha256"):
        InstrumentRegistry(
            INITIAL_ACCEPTANCE_REGISTRY_ID,
            INITIAL_ACCEPTANCE_REGISTRY_RELEASE_VERSION,
            tuple(drifted),
            INITIAL_ACCEPTANCE_REGISTRY_SHA256,
        )
    with pytest.raises(ValueError, match="namespace"):
        InstrumentRegistry(EntityId.new("dataset"), 1, fixture.aliases, fixture.expected_content_sha256)


def test_tradeable_alias_exchange_prefix_must_match_the_resolved_instrument() -> None:
    shfe_instrument = Instrument(Variety(Exchange.SHFE, "AG", "silver"), "2606")
    registry = make_registry(
        AliasMapping("DCE.SYNTHETIC", shfe_instrument, EffectiveInterval(at(0)), 1, provenance()),
        AliasMapping("SHFE.SYNTHETIC", shfe_instrument, EffectiveInterval(at(0)), 1, provenance()),
    )
    assert registry.resolve_tradeable("DCE.SYNTHETIC", at(1)) == Failure(
        ReasonCode.INSTRUMENT_NOT_TRADEABLE, "order target exchange does not match Instrument exchange"
    )
    assert registry.resolve_tradeable("SHFE.SYNTHETIC", at(1)) == shfe_instrument


def test_variety_and_explicit_supplier_style_continuous_aliases_are_never_tradeable() -> None:
    variety = Variety(Exchange.DCE, "I", "iron ore")
    continuous = ContinuousSeries(variety, "VENDOR_9999", ContinuousAdjustment.UNADJUSTED, "roll-rule:i-vendor-v1")
    registry = make_registry(
        AliasMapping("DCE.I", variety, EffectiveInterval(at(0)), 1, provenance()),
        AliasMapping("DCE.I9999", continuous, EffectiveInterval(at(0)), 1, provenance()),
    )
    assert registry.resolve_tradeable("DCE.I", at(1)) == Failure(
        ReasonCode.INSTRUMENT_NOT_TRADEABLE, "order target must be a specific Instrument"
    )
    assert registry.resolve_tradeable("DCE.I9999", at(1)) == Failure(
        ReasonCode.CONTINUOUS_SERIES_NOT_TRADABLE, "continuous series must resolve to an Instrument first"
    )


def test_release_snapshot_is_immutable_and_concurrent_reads_have_identical_evidence() -> None:
    variety = Variety(Exchange.DCE, "I", "iron ore")
    instrument = Instrument(variety, "2609")
    aliases = [AliasMapping("DCE.I2609", instrument, EffectiveInterval(at(0)), 1, provenance())]
    registry = InstrumentRegistry(
        EntityId.new("instrument_registry"), 1, aliases, registry_content_sha256(tuple(aliases))
    )
    aliases.clear()

    with pytest.raises(FrozenInstanceError):
        registry.release_version = 2  # type: ignore[misc]
    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(executor.map(lambda _: registry.resolve("DCE.I2609", at(1)), range(32)))
    assert all(outcome == outcomes[0] for outcome in outcomes)
    assert not isinstance(outcomes[0], Failure)
