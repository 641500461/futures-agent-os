"""V2-003 Risk Constitution acceptance contracts.

These tests exercise the hard gates independently from the reservation and
submission services.  A missing fact is deliberately a rejection when the
corresponding rule is enabled; no best-effort default is allowed.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, strategies as st

from futures_agent_os.decision import ProtectionIntent, RiskDecisionOutcome, TradeAction, TradeDirection, TradePlan
from futures_agent_os.portfolio_risk import RiskConstitution, RiskEngine, RiskRuleCode
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _plan() -> TradePlan:
    return TradePlan(
        EntityId.deterministic("trade_plan", "v2-003"),
        EntityId.deterministic("simulation_account", "v2-003"),
        "SHFE_AG_2601",
        "strategy:v2-003",
        TradeAction.OPEN,
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        ProtectionIntent(Decimal("95"), Decimal("5"), created_at=_at()),
        "support holds",
        "support breaks",
        (canonical_sha256({"evidence": "v2-003"}),),
        "snapshot:v2-003",
        _at(30),
        created_at=_at(),
    )


def _constitution(**kwargs: object) -> RiskConstitution:
    values: dict[str, object] = {
        "ref": "risk://v2-003",
        "version": 7,
        "content_hash": "a" * 64,
        "max_single_loss": Decimal("100"),
        "max_margin": Decimal("1000"),
        "max_quantity": Decimal("10"),
        "margin_rate": Decimal("0.1"),
    }
    values.update(kwargs)
    return RiskConstitution(**values)  # type: ignore[arg-type]


def _decide(engine: RiskEngine, **kwargs: object):
    return engine.decide(_plan(), decision_id=EntityId.deterministic("risk_decision", str(kwargs)), now=_at(), **kwargs)


def test_dimension_drawdown_and_margin_buffer_gates_are_fail_closed() -> None:
    constitution = _constitution(
        max_instrument_concentration=Decimal("0.60"),
        max_direction_concentration=Decimal("0.70"),
        max_portfolio_concentration=Decimal("0.80"),
        max_daily_drawdown=Decimal("50"),
        margin_buffer=Decimal("0.20"),
    )
    engine = RiskEngine(constitution)
    checks = (
        ({}, RiskRuleCode.INSTRUMENT_CONCENTRATION_UNAVAILABLE),
        ({"instrument_concentration": Decimal("0.61")}, RiskRuleCode.INSTRUMENT_CONCENTRATION_LIMIT),
        (
            {"instrument_concentration": Decimal("0.10")},
            RiskRuleCode.DIRECTION_CONCENTRATION_UNAVAILABLE,
        ),
        (
            {"instrument_concentration": Decimal("0.10"), "direction_concentration": Decimal("0.71")},
            RiskRuleCode.DIRECTION_CONCENTRATION_LIMIT,
        ),
        (
            {
                "instrument_concentration": Decimal("0.10"),
                "direction_concentration": Decimal("0.10"),
            },
            RiskRuleCode.PORTFOLIO_CONCENTRATION_UNAVAILABLE,
        ),
        (
            {
                "instrument_concentration": Decimal("0.10"),
                "direction_concentration": Decimal("0.10"),
                "portfolio_concentration": Decimal("0.81"),
            },
            RiskRuleCode.PORTFOLIO_CONCENTRATION_LIMIT,
        ),
        (
            {
                "instrument_concentration": Decimal("0.10"),
                "direction_concentration": Decimal("0.10"),
                "portfolio_concentration": Decimal("0.10"),
            },
            RiskRuleCode.DAILY_DRAWDOWN_UNAVAILABLE,
        ),
        (
            {
                "instrument_concentration": Decimal("0.10"),
                "direction_concentration": Decimal("0.10"),
                "portfolio_concentration": Decimal("0.10"),
                "daily_drawdown": Decimal("51"),
            },
            RiskRuleCode.DAILY_DRAWDOWN_LIMIT,
        ),
        (
            {
                "instrument_concentration": Decimal("0.10"),
                "direction_concentration": Decimal("0.10"),
                "portfolio_concentration": Decimal("0.10"),
                "daily_drawdown": Decimal("0"),
            },
            RiskRuleCode.MARGIN_HEADROOM_UNAVAILABLE,
        ),
    )
    for arguments, code in checks:
        decision = _decide(engine, **arguments)
        assert decision.outcome is RiskDecisionOutcome.REJECT
        assert decision.rule_refs == (code,)
        assert decision.rule_version == constitution.version

    accepted = _decide(
        engine,
        instrument_concentration=Decimal("0.10"),
        direction_concentration=Decimal("0.10"),
        portfolio_concentration=Decimal("0.10"),
        daily_drawdown=Decimal("0"),
        current_margin=Decimal("0"),
    )
    assert accepted.outcome is RiskDecisionOutcome.APPROVE
    assert accepted.rule_refs == (RiskRuleCode.RISK_WITHIN_LIMITS,)
    assert accepted.rule_version == 7


def test_margin_buffer_counts_existing_margin_and_delivery_rejects_negative_days() -> None:
    engine = RiskEngine(_constitution(margin_buffer=Decimal("0.20"), delivery_horizon_days=3))
    common = {
        "days_to_delivery": 10,
        "current_margin": Decimal("750"),
    }
    # Candidate margin is 10; 750 + 10 is below the 800 headroom ceiling.
    assert _decide(engine, **common).outcome is RiskDecisionOutcome.APPROVE
    assert _decide(engine, **{**common, "current_margin": Decimal("795")}).rule_refs == (
        RiskRuleCode.MARGIN_BUFFER_LIMIT,
    )
    assert _decide(engine, **{**common, "days_to_delivery": -1}).rule_refs == (
        RiskRuleCode.DELIVERY_HORIZON_UNAVAILABLE,
    )
    assert _decide(engine, **{**common, "days_to_delivery": 3}).rule_refs == (RiskRuleCode.DELIVERY_TOO_NEAR,)


@given(
    quality=st.decimals(min_value="0", max_value="1", allow_nan=False, allow_infinity=False, places=3),
    concentration=st.decimals(min_value="0", max_value="1", allow_nan=False, allow_infinity=False, places=3),
)
def test_stable_rule_code_and_version_never_depend_on_numeric_representation(
    quality: Decimal, concentration: Decimal
) -> None:
    constitution = _constitution(min_data_quality=Decimal("0.5"), max_concentration=Decimal("0.8"))
    decision = RiskEngine(constitution).decide(
        _plan(),
        decision_id=EntityId.deterministic("risk_decision", f"{quality}:{concentration}"),
        now=_at(),
        data_quality=quality,
        concentration=concentration,
    )
    assert decision.rule_version == constitution.version
    assert len(decision.rule_refs) == 1
    assert isinstance(decision.rule_refs[0], str)
    assert decision.rule_refs[0] in {code.value for code in RiskRuleCode}


@pytest.mark.parametrize(
    "field,value",
    [
        ("margin_buffer", Decimal("1001")),
        ("margin_buffer", Decimal("-0.1")),
        ("max_daily_drawdown", Decimal("0")),
        ("max_instrument_concentration", Decimal("0")),
    ],
)
def test_constitution_rejects_invalid_v2_003_limits(field: str, value: Decimal) -> None:
    with pytest.raises(ValueError):
        _constitution(**{field: value})
