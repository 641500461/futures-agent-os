from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.decision import ProtectionIntent, TradeAction, TradeDirection, TradePlan
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def _at(hours: int = 1) -> RecordedAt:
    return RecordedAt.from_datetime(datetime.now(UTC) + timedelta(hours=hours))


def _plan(**changes: object) -> TradePlan:
    values: dict[str, object] = {
        "plan_id": EntityId.new("trade_plan"),
        "account_id": EntityId.new("simulation_account"),
        "instrument": "SHFE_AG_2601",
        "strategy_ref": "strategy:test",
        "action": TradeAction.OPEN,
        "direction": TradeDirection.LONG,
        "quantity": Decimal("2"),
        "entry_price": Decimal("100"),
        "protection": ProtectionIntent(stop_price=Decimal("95"), max_loss=Decimal("10")),
        "thesis": "price rejects support",
        "invalidation": "support breaks",
        "evidence_refs": ("a" * 64,),
        "snapshot_ref": "snapshot:test",
        "expires_at": _at(),
    }
    values.update(changes)
    return TradePlan(**values)  # type: ignore[arg-type]


def test_trade_plan_is_hashed_and_requires_protection() -> None:
    plan = _plan()
    assert len(plan.plan_hash) == 64
    with pytest.raises(TypeError):
        _plan(protection=None)


def test_trade_plan_rejects_empty_evidence() -> None:
    with pytest.raises(ValueError):
        _plan(evidence_refs=())
