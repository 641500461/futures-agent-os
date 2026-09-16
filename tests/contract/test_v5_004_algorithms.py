from decimal import Decimal

import pytest

from futures_agent_os.execution_simulation.advanced_algorithms import (
    AdvancedExecutionPlanner,
    AlgorithmSpec,
    ExecutionAlgorithm,
    ExecutionAlgorithmRegistry,
    ExecutionIntent,
    recommend,
    schedule,
)
from futures_agent_os.shared_kernel import RecordedAt


def _registry():
    registry = ExecutionAlgorithmRegistry()
    specs = (
        AlgorithmSpec(ExecutionAlgorithm.TWAP, "v1", (ExecutionIntent.ENTER, ExecutionIntent.EXIT), 2, 10),
        AlgorithmSpec(ExecutionAlgorithm.VWAP, "v1", (ExecutionIntent.ENTER, ExecutionIntent.EXIT), 2, 10),
        AlgorithmSpec(ExecutionAlgorithm.ICEBERG, "v2", (ExecutionIntent.ENTER, ExecutionIntent.EXIT), 2, 10),
        AlgorithmSpec(ExecutionAlgorithm.BATCHED_ENTRY, "v1", (ExecutionIntent.ENTER,), 2, 10),
        AlgorithmSpec(ExecutionAlgorithm.BATCHED_EXIT, "v1", (ExecutionIntent.EXIT,), 2, 10),
    )
    for spec in specs:
        registry.register(spec)
    return registry, registry.activate(tuple((spec.algorithm, spec.version) for spec in specs), actor="user:qiu")


def test_twap_conserves_quantity_and_assigns_deterministic_times() -> None:
    start = RecordedAt.parse("2026-01-01T00:00:00Z")
    end = RecordedAt.parse("2026-01-01T00:04:00Z")
    out = schedule(ExecutionAlgorithm.TWAP, Decimal("10"), 4, lot_size=Decimal("1"), start_at=start, end_at=end)
    assert [item.quantity for item in out] == [Decimal("3"), Decimal("3"), Decimal("2"), Decimal("2")]
    assert sum((item.quantity for item in out), Decimal("0")) == Decimal("10")
    assert [item.scheduled_at for item in out] == [
        RecordedAt.parse(f"2026-01-01T00:0{minute}:00Z") for minute in range(4)
    ]


def test_vwap_rounding_conserves_parent() -> None:
    out = schedule(
        ExecutionAlgorithm.VWAP,
        Decimal("11"),
        3,
        volumes=(Decimal("1"), Decimal("2"), Decimal("1")),
        lot_size=Decimal("1"),
    )
    assert [item.quantity for item in out] == [Decimal("3"), Decimal("5"), Decimal("3")]


def test_iceberg_caps_display_and_requires_enough_slices() -> None:
    out = schedule(
        ExecutionAlgorithm.ICEBERG,
        Decimal("10"),
        4,
        display_quantity=Decimal("3"),
        lot_size=Decimal("1"),
    )
    assert [item.quantity for item in out] == [Decimal("3"), Decimal("3"), Decimal("3"), Decimal("1")]
    assert all(item.display_quantity == item.quantity <= Decimal("3") for item in out)
    with pytest.raises(ValueError, match="capacity"):
        schedule(
            ExecutionAlgorithm.ICEBERG,
            Decimal("10"),
            3,
            display_quantity=Decimal("3"),
            lot_size=Decimal("1"),
        )


@pytest.mark.parametrize("algorithm", (ExecutionAlgorithm.BATCHED_ENTRY, ExecutionAlgorithm.BATCHED_EXIT))
def test_batched_entry_and_exit_use_explicit_weights(algorithm: ExecutionAlgorithm) -> None:
    out = schedule(
        algorithm,
        Decimal("10"),
        3,
        batch_weights=(Decimal("2"), Decimal("3"), Decimal("5")),
        lot_size=Decimal("1"),
    )
    assert [item.quantity for item in out] == [Decimal("2"), Decimal("3"), Decimal("5")]


def test_agent_only_recommends_active_registered_version_and_planner_executes() -> None:
    registry, activation = _registry()
    proposal = recommend(
        activation, ExecutionAlgorithm.VWAP, intent=ExecutionIntent.ENTER, rationale="frozen volume profile"
    )
    for forbidden in ("quantity", "children", "orders", "submit"):
        assert not hasattr(proposal, forbidden)
    plan = AdvancedExecutionPlanner(registry).plan(
        proposal,
        Decimal("10"),
        2,
        volumes=(Decimal("1"), Decimal("3")),
        lot_size=Decimal("1"),
    )
    assert [child.quantity for child in plan.children] == [Decimal("3"), Decimal("7")]
    assert sum((child.quantity for child in plan.children), Decimal("0")) == plan.parent_quantity


def test_inactive_wrong_intent_stale_activation_and_agent_activation_fail_closed() -> None:
    registry, activation = _registry()
    with pytest.raises(ValueError, match="active for this intent"):
        recommend(
            activation,
            ExecutionAlgorithm.BATCHED_ENTRY,
            intent=ExecutionIntent.EXIT,
            rationale="wrong intent",
        )
    proposal = recommend(
        activation, ExecutionAlgorithm.TWAP, intent=ExecutionIntent.ENTER, rationale="current activation"
    )
    registry.register(AlgorithmSpec(ExecutionAlgorithm.TWAP, "v2", (ExecutionIntent.ENTER,), 2, 5))
    registry.activate(((ExecutionAlgorithm.TWAP, "v2"),), actor="user:qiu")
    with pytest.raises(ValueError, match="not active"):
        AdvancedExecutionPlanner(registry).plan(proposal, Decimal("2"), 2, lot_size=Decimal("1"))
    with pytest.raises(ValueError, match="human governance"):
        registry.activate(((ExecutionAlgorithm.TWAP, "v2"),), actor="agent:pm")


def test_invalid_profiles_lot_sizes_and_bounds_are_rejected() -> None:
    with pytest.raises(ValueError, match="every slice"):
        schedule(ExecutionAlgorithm.VWAP, Decimal("2"), 2, volumes=(Decimal("1"),))
    with pytest.raises(ValueError, match="multiple"):
        schedule(ExecutionAlgorithm.TWAP, Decimal("2.5"), 2, lot_size=Decimal("1"))
    registry, activation = _registry()
    proposal = recommend(activation, ExecutionAlgorithm.TWAP, intent=ExecutionIntent.EXIT, rationale="exit")
    with pytest.raises(ValueError, match="bounds"):
        AdvancedExecutionPlanner(registry).plan(proposal, Decimal("10"), 11, lot_size=Decimal("1"))
