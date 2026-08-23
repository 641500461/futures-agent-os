from datetime import UTC, datetime

from hypothesis import given, strategies as st

from futures_agent_os.reference_market_data import (
    AliasMapping,
    EffectiveInterval,
    Exchange,
    Instrument,
    InstrumentRegistry,
    ReferenceProvenance,
    Variety,
    registry_content_sha256,
)
from futures_agent_os.shared_kernel import EntityId, Failure, ReasonCode, RecordedAt


@given(alias=st.from_regex(r"[A-Z]{1,8}", fullmatch=True), suffix=st.text(min_size=1, max_size=8))
def test_unregistered_supplier_style_codes_never_gain_continuous_or_tradeable_meaning(alias: str, suffix: str) -> None:
    now = RecordedAt(datetime(2026, 8, 23, tzinfo=UTC))
    variety = Variety(Exchange.DCE, "I", "iron ore")
    contract = Instrument(variety, "2609")
    provenance = ReferenceProvenance("test://registry", now, now, "1")
    registry = InstrumentRegistry(
        EntityId.new("instrument_registry"),
        1,
        (aliases := (AliasMapping("DCE.I2609", contract, EffectiveInterval(now), 1, provenance),)),
        registry_content_sha256(aliases),
    )

    candidate = f"{alias}{suffix}".upper()
    if candidate != "DCE.I2609":
        outcome = registry.resolve_tradeable(candidate, now)
        assert isinstance(outcome, Failure)
        assert outcome.reason_code in {
            ReasonCode.INSTRUMENT_UNKNOWN,
            ReasonCode.INSTRUMENT_MALFORMED,
            ReasonCode.INSTRUMENT_NOT_TRADEABLE,
        }
