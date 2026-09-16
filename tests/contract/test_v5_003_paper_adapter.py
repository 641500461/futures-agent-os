from decimal import Decimal

import pytest

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation import Fill
from futures_agent_os.execution_simulation.paper_adapter import (
    AdapterCapabilities,
    ConnectorHealth,
    ExternalExecution,
    ExternalFill,
    ExternalStatus,
    PaperTradingAdapter,
    ReconciliationOutcome,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt


AT = RecordedAt.parse("2026-01-01T00:00:00Z")


def _order(quantity: str = "3", filled: str = "3") -> Order:
    order = Order(
        EntityId.deterministic("order", f"v5-003:{quantity}:{filled}"),
        EntityId.deterministic("execution_plan", "v5-003"),
        "SHFE:AG",
        TradeDirection.LONG,
        Decimal(quantity),
        OrderStatus.WORKING,
        created_at=AT,
    )
    return order if filled == "0" else order.apply_fill(Decimal(filled))


def _external_fill(order_id: str = "paper-1", quantity: str = "3") -> ExternalFill:
    return ExternalFill(
        "trade-1",
        order_id,
        "SHFE:AG",
        TradeDirection.LONG,
        Decimal(quantity),
        Decimal("101"),
        Decimal("1.5"),
        AT,
    )


def _local_fill(order: Order, quantity: str = "3") -> Fill:
    return Fill(
        EntityId.deterministic("fill", f"v5-003:{quantity}"),
        order.order_id,
        order.instrument,
        order.direction,
        Decimal(quantity),
        Decimal("101"),
        Decimal("1.5"),
        AT,
    )


def test_compatibility_reconcile_matches_external_execution() -> None:
    result = PaperTradingAdapter().reconcile("o1", 3, ExternalExecution("o1", ExternalStatus.FILLED, 3))
    assert result.matched and result.reason == "MATCHED" and result.can_assume_success


def test_local_order_maps_outbound_without_claiming_external_acceptance() -> None:
    adapter = PaperTradingAdapter()
    order = _order(filled="0")
    intent = adapter.prepare_order(order, external_client_order_id="paper-1", idempotency_key="submit:paper-1")
    assert intent.local_order_id == order.order_id and intent.quantity == order.quantity
    assert intent.external_client_order_id == "paper-1" and intent.manifest_digest == adapter.capabilities.digest
    with pytest.raises(ValueError, match="unfilled live order"):
        adapter.prepare_order(_order(), external_client_order_id="paper-2", idempotency_key="submit:paper-2")


@pytest.mark.parametrize("health", (ConnectorHealth.DEGRADED, ConnectorHealth.UNKNOWN))
def test_connector_health_never_assumes_success(health: ConnectorHealth) -> None:
    order = _order()
    external = ExternalExecution("paper-1", ExternalStatus.FILLED, Decimal("3"), Decimal("3"))
    result = PaperTradingAdapter().reconcile_state(
        order, (_local_fill(order),), external, external_order_id="paper-1", health=health
    )
    assert not result.matched and not result.can_assume_success
    assert result.outcome in {ReconciliationOutcome.DEGRADED, ReconciliationOutcome.UNKNOWN}


def test_unknown_external_state_fails_closed() -> None:
    result = PaperTradingAdapter().reconcile("o1", 0, ExternalExecution("o1", ExternalStatus.UNKNOWN, 0))
    assert not result.matched and result.reason == "UNKNOWN_EXTERNAL_STATE"
    assert result.outcome is ReconciliationOutcome.UNKNOWN and not result.can_assume_success


def test_bidirectional_order_and_fill_reconciliation_normalizes_canonical_fills() -> None:
    order = _order()
    external = ExternalExecution(
        "paper-1",
        ExternalStatus.FILLED,
        Decimal("3"),
        Decimal("3"),
        (_external_fill(),),
        AT,
    )
    adapter = PaperTradingAdapter()
    first = adapter.reconcile_state(order, (_local_fill(order),), external, external_order_id="paper-1")
    second = adapter.reconcile_state(order, (_local_fill(order),), external, external_order_id="paper-1")
    assert first.matched and first.outcome is ReconciliationOutcome.MATCHED
    assert len(first.imported_fills) == 1 and first.imported_fills[0].source_ref.startswith("l5:local-paper:v1")
    assert first.imported_fills[0].fill_id == second.imported_fills[0].fill_id
    assert first.imported_fills[0].order_id == order.order_id


@pytest.mark.parametrize(
    ("external", "reason"),
    (
        (ExternalExecution("wrong", ExternalStatus.FILLED, Decimal("3"), Decimal("3")), "ORDER_ID_MAPPING_MISMATCH"),
        (ExternalExecution("paper-1", ExternalStatus.FILLED, Decimal("2"), Decimal("3")), "CROSS_SYSTEM_FILL_MISMATCH"),
        (ExternalExecution("paper-1", ExternalStatus.WORKING, Decimal("3"), Decimal("3")), "ORDER_STATUS_MISMATCH"),
    ),
)
def test_any_cross_system_mismatch_is_explicit(external: ExternalExecution, reason: str) -> None:
    order = _order()
    result = PaperTradingAdapter().reconcile_state(order, (_local_fill(order),), external, external_order_id="paper-1")
    assert not result.matched and not result.can_assume_success and reason in result.discrepancies


def test_external_fill_set_must_reconcile_with_external_order() -> None:
    order = _order()
    external = ExternalExecution(
        "paper-1",
        ExternalStatus.FILLED,
        Decimal("3"),
        Decimal("3"),
        (_external_fill(quantity="2"),),
        AT,
    )
    result = PaperTradingAdapter().reconcile_state(order, (_local_fill(order),), external, external_order_id="paper-1")
    assert result.reason == "EXTERNAL_FILL_ORDER_MISMATCH" and not result.matched


def test_tqsim_manifest_records_official_limitations_and_rejects_partial_claim() -> None:
    manifest = AdapterCapabilities.tqsim("runtime:explicit-test-version")
    adapter = PaperTradingAdapter(manifest)
    assert manifest.fidelity == "L5_PAPER" and not manifest.supports_partial_fills
    assert "all-or-none-simulated-fills-no-partial-fills" in manifest.limitations
    assert manifest.documentation_url.endswith("tqsdk.sim.html") and manifest.verified_at == "2026-09-10"
    order = _order(filled="1")
    external = ExternalExecution("paper-1", ExternalStatus.PARTIALLY_FILLED, Decimal("1"), Decimal("3"))
    result = adapter.reconcile_state(order, (_local_fill(order, "1"),), external, external_order_id="paper-1")
    assert result.outcome is ReconciliationOutcome.UNSUPPORTED and not result.can_assume_success


def test_missing_external_quantity_and_unsupported_cancel_fail_closed() -> None:
    order = _order()
    missing = PaperTradingAdapter().reconcile_state(
        order,
        (_local_fill(order),),
        ExternalExecution("paper-1", ExternalStatus.FILLED, Decimal("3")),
        external_order_id="paper-1",
    )
    assert missing.outcome is ReconciliationOutcome.UNKNOWN and not missing.can_assume_success
    adapter = PaperTradingAdapter(AdapterCapabilities("no-cancel", "v1", True, False, ("cancel-unsupported",)))
    assert adapter.validate_cancel_support() is ReconciliationOutcome.UNSUPPORTED
