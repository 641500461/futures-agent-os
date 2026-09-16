from dataclasses import fields, replace
from decimal import Decimal

import pytest

from futures_agent_os.research_experiment import (
    OfflineRlEvaluation,
    OfflineRlModule,
    OfflineRlPlan,
    OfflineRlResearchRegistry,
    OfflineRlRuntimeLane,
    OfflineRlState,
)


DATASET_DIGEST = "a" * 64


def _plan(module: OfflineRlModule = OfflineRlModule.EXECUTION) -> OfflineRlPlan:
    return OfflineRlPlan(
        "offline-rl:execution:v1",
        module,
        ("spread", "queue_ahead", "remaining_quantity"),
        ("WAIT", "PASSIVE_CHILD", "MARKETABLE_CHILD"),
        "reward:implementation-shortfall:v1",
        "dataset:frozen-l3:v1",
        DATASET_DIGEST,
        "behavior-policy:twap:v1",
        "evaluation:wis-plus-bootstrap:v1",
        "deadbeef",
        "env:offline-rl:v1",
        20260910,
    )


def _evaluation(plan: OfflineRlPlan, *, passed: bool = True, violations: int = 0) -> OfflineRlEvaluation:
    return OfflineRlEvaluation(
        plan.digest,
        "policy:offline-rl:execution:v1",
        DATASET_DIGEST,
        500,
        Decimal("0.12"),
        Decimal("0.08"),
        Decimal("0.16"),
        violations,
        "comparison:deterministic-baselines:v1",
        "replay:offline-rl:v1",
        passed,
    )


def _evaluated_registry(plan: OfflineRlPlan) -> OfflineRlResearchRegistry:
    registry = OfflineRlResearchRegistry()
    registry.register(plan)
    registry.record_evaluation(_evaluation(plan))
    return registry


def test_only_closed_low_dimensional_modules_are_representable() -> None:
    assert {module.value for module in OfflineRlModule} == {
        "EXECUTION",
        "PORTFOLIO_ALLOCATION",
        "POSITION_ADJUSTMENT",
    }
    for module in OfflineRlModule:
        assert _plan(module).module is module
    with pytest.raises(ValueError):
        OfflineRlModule("HIGH_LEVEL_AGENT")
    with pytest.raises(ValueError, match="1-16"):
        replace(_plan(), state_features=tuple(f"feature-{index}" for index in range(17)))
    with pytest.raises(ValueError, match="2-16"):
        replace(_plan(), actions=("ONLY_ACTION",))


def test_plan_is_reproducible_and_binds_frozen_dataset() -> None:
    plan = _plan()
    assert plan.digest == _plan().digest
    assert replace(plan, seed=plan.seed + 1).digest != plan.digest
    registry = OfflineRlResearchRegistry()
    registry.register(plan)
    with pytest.raises(ValueError, match="frozen research plan"):
        registry.record_evaluation(replace(_evaluation(plan), dataset_digest="b" * 64))


def test_default_path_requires_separate_review_approval_and_activation() -> None:
    plan = _plan()
    registry = OfflineRlResearchRegistry()
    registry.register(plan)
    with pytest.raises(ValueError, match="not activated"):
        registry.resolve(plan.digest, OfflineRlRuntimeLane.DEFAULT_SIMULATION)
    registry.record_evaluation(_evaluation(plan))
    with pytest.raises(ValueError, match="review and governance approval"):
        registry.activate(plan.digest, actor="user:qiu", scope=("account:paper",))
    registry.review(plan.digest, actor="user:research-reviewer", decision="APPROVE", evidence_refs=("review:v1",))
    with pytest.raises(ValueError, match="review and governance approval"):
        registry.activate(plan.digest, actor="user:qiu", scope=("account:paper",))


def test_independent_gates_allow_only_exact_approved_runtime_lane() -> None:
    plan = _plan()
    registry = _evaluated_registry(plan)
    reviewed = registry.review(
        plan.digest,
        actor="user:research-reviewer",
        decision="APPROVE",
        evidence_refs=("review:offline-rl:v1",),
    )
    assert reviewed.state is OfflineRlState.RESEARCH_REVIEWED
    approved = registry.approve(
        plan.digest,
        actor="user:governance-owner",
        target_lane=OfflineRlRuntimeLane.DEFAULT_SIMULATION,
        deterministic_override_ref="override:execution-domain-service:v1",
        fallback_ref="fallback:twap:v1",
    )
    assert approved.state is OfflineRlState.GOVERNANCE_APPROVED
    active = registry.activate(plan.digest, actor="user:operator", scope=("account:paper", "instrument:IF"))
    assert active.state is OfflineRlState.ACTIVE
    resolved = registry.resolve(plan.digest, OfflineRlRuntimeLane.DEFAULT_SIMULATION)
    assert resolved.scope == ("account:paper", "instrument:IF")
    assert resolved.approval_digest == approved.approval.digest  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="not activated"):
        registry.resolve(plan.digest, OfflineRlRuntimeLane.CONTROLLED_SIMULATION)


def test_failed_evaluation_or_rejected_review_is_retained_and_blocks_governance() -> None:
    plan = _plan()
    failed = OfflineRlResearchRegistry()
    failed.register(plan)
    rejected = failed.record_evaluation(_evaluation(plan, passed=False, violations=3))
    assert rejected.state is OfflineRlState.REJECTED and rejected.evaluation is not None
    with pytest.raises(ValueError, match="passed evaluation"):
        failed.review(plan.digest, actor="user:reviewer", decision="APPROVE", evidence_refs=("review:v1",))

    second_plan = replace(plan, plan_id="offline-rl:execution:v2", seed=2)
    reviewed = _evaluated_registry(second_plan)
    rejected = reviewed.review(
        second_plan.digest, actor="user:reviewer", decision="REJECT", evidence_refs=("finding:unsafe:v1",)
    )
    assert rejected.state is OfflineRlState.REJECTED and rejected.review is not None
    with pytest.raises(ValueError, match="approved independent research review"):
        reviewed.approve(
            second_plan.digest,
            actor="user:owner",
            target_lane=OfflineRlRuntimeLane.RESEARCH_SHADOW,
            deterministic_override_ref="override:v1",
            fallback_ref="fallback:v1",
        )


def test_agents_cannot_approve_or_activate_and_policy_cannot_replace_agent_authority() -> None:
    plan = _plan()
    registry = _evaluated_registry(plan)
    with pytest.raises(ValueError, match="human user"):
        registry.review(plan.digest, actor="agent:critic", decision="APPROVE", evidence_refs=("review:v1",))
    registry.review(plan.digest, actor="user:reviewer", decision="APPROVE", evidence_refs=("review:v1",))
    with pytest.raises(ValueError, match="human user"):
        registry.approve(
            plan.digest,
            actor="agent:governance",
            target_lane=OfflineRlRuntimeLane.DEFAULT_SIMULATION,
            deterministic_override_ref="override:v1",
            fallback_ref="fallback:v1",
        )
    output_fields = {field.name for field in fields(OfflineRlPlan)}
    assert output_fields.isdisjoint({"order", "trade_plan", "risk_decision", "agent_prompt", "agent_profile"})
    assert not hasattr(plan, "activate") and not hasattr(plan, "submit_order")


def test_passing_evaluation_cannot_hide_constraint_violations() -> None:
    with pytest.raises(ValueError, match="cannot have constraint violations"):
        _evaluation(_plan(), passed=True, violations=1)
