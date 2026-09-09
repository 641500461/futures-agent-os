from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from futures_agent_os.decision import (
    ApprovalAction,
    AutonomyGate,
    AutonomyMode,
    AutonomyModeBinding,
    BasisIssuanceRegistry,
    BasisStatus,
    BindingArtifactCoordinator,
    BindingStatus,
    CompositePause,
    CompositeResume,
    EffectiveAutonomy,
    EscalationMode,
    ExecutionOrigin,
    GateRequest,
    MandateRecovery,
    MandateScope,
    MandateStatus,
    OperationalModePause,
    OperationalPauseReason,
    PlanApproval,
    PlanApprovalStatus,
    PreflightOutcome,
    ReceiptIssuanceRegistry,
    SimulationAutonomyMandate,
)
from futures_agent_os.portfolio_risk import (
    ReservationAction,
    ReservationSourceKind,
    ReservationStatus,
    RiskBudgetLedger,
    RiskBudgetReservation,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 9, 8, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _hash(value: str) -> str:
    return canonical_sha256({"value": value})


def _scope(escalation: EscalationMode = EscalationMode.SKIP_AND_NOTIFY) -> MandateScope:
    return MandateScope(
        EntityId.new("simulation_account"),
        ("AG", "RB"),
        ("breakout_v3", "trend_v3"),
        ("DAY", "NIGHT"),
        frozenset({ApprovalAction.OPEN, ApprovalAction.REDUCE, ApprovalAction.CLOSE}),
        Decimal("3"),
        "risk-constitution://v3/7",
        "notification-policy://important/v2",
        "escalation-policy://one-off/v1",
        escalation,
    )


def _mandate(
    status: MandateStatus = MandateStatus.ACTIVE,
    *,
    escalation: EscalationMode = EscalationMode.SKIP_AND_NOTIFY,
    expires: int = 60,
) -> SimulationAutonomyMandate:
    return SimulationAutonomyMandate(
        EntityId.new("mandate"),
        1,
        status,
        _scope(escalation),
        _at(expires),
        _at(),
        "user:owner",
    )


def _binding(mandate: SimulationAutonomyMandate, *, expires: int = 20) -> AutonomyModeBinding:
    return AutonomyModeBinding(
        EntityId.new("mode_binding"),
        1,
        AutonomyMode.AUTONOMOUS_SIMULATION,
        BindingStatus.ACTIVE,
        mandate.scope.simulation_account_id,
        mandate.mandate_id,
        mandate.version,
        _hash("qualified-run-versions"),
        _at(expires),
        _at(),
        mandate.scope.sha256,
        "scan-policy://v3/1",
        "universe-policy://v3/1",
        "qualification://v3/1",
        "INITIAL_BINDING",
        "user:owner",
        "evidence://mode-binding",
    )


def _request(mandate: SimulationAutonomyMandate, *, instrument: str = "AG") -> GateRequest:
    return GateRequest(
        EntityId.new("trade_plan"),
        1,
        _hash("plan"),
        mandate.scope.simulation_account_id,
        instrument,
        "trend_v3",
        "DAY",
        ApprovalAction.OPEN,
        Decimal("1"),
        ExecutionOrigin.AUTONOMOUS_AGENT,
        _hash("snapshot"),
        _at(15),
        _hash("qualified-run-versions"),
    )


def _reservation(request: GateRequest, basis) -> RiskBudgetReservation:
    return RiskBudgetReservation(
        EntityId.new("risk_budget_reservation"),
        request.account_id,
        request.plan_id,
        request.plan_version,
        request.plan_hash,
        request.instrument,
        request.strategy,
        request.session,
        basis.basis_id,
        basis.basis_hash,
        "risk-constitution://v3/7",
        7,
        _hash("risk-constitution-v3-7"),
        Decimal("100"),
        Decimal("10"),
        Decimal("2"),
        _at(10),
        quantity=request.quantity,
        action=ReservationAction.OPEN,
        source_kind=ReservationSourceKind.MANDATE,
        source_ref=basis.source_id,
        source_hash=basis.source_hash,
    )


def _authorization_chain(mandate: SimulationAutonomyMandate, binding: AutonomyModeBinding):
    request = _request(mandate)
    basis = AutonomyGate.preflight(
        request,
        mandate,
        binding,
        qualified=True,
        health_permits=True,
        now=_at(),
        approval_allowed=False,
        basis_registry=BasisIssuanceRegistry(),
    ).basis
    assert basis is not None
    reservation = _reservation(request, basis)
    ledger = RiskBudgetLedger(Decimal("100"), "risk-constitution://v3/7", 7, _hash("risk-constitution-v3-7"))
    assert ledger.reserve(reservation, _at())
    issuance = ReceiptIssuanceRegistry()
    receipt = AutonomyGate.final_gate(
        request,
        basis,
        mandate=mandate,
        approval=None,
        reservation=reservation,
        binding=binding,
        qualified=True,
        health_permits=True,
        now=_at(),
        issuance_registry=issuance,
        risk_ledger=ledger,
    ).receipt
    assert receipt is not None
    coordinator = BindingArtifactCoordinator(issuance, ledger)
    coordinator.track(binding, basis, reservation.reservation_id)
    return request, basis, reservation, receipt, ledger, coordinator


def test_mandate_scope_is_exact_typed_and_content_addressed() -> None:
    scope = _scope(EscalationMode.REQUEST_ONE_OFF)
    assert scope.matches(scope.simulation_account_id, "AG", "trend_v3", "DAY", ApprovalAction.OPEN, Decimal("3"))
    assert not scope.matches(scope.simulation_account_id, "CU", "trend_v3", "DAY", ApprovalAction.OPEN, Decimal("1"))
    assert not scope.matches(scope.simulation_account_id, "AG", "trend_v3", "DAY", ApprovalAction.OPEN, Decimal("4"))
    assert scope.sha256 != replace(scope, notification_policy_ref="notification-policy://critical/v1").sha256
    assert scope.sha256 != replace(scope, escalation_mode=EscalationMode.SKIP_AND_NOTIFY).sha256
    with pytest.raises(TypeError, match="typed escalation"):
        replace(scope, escalation_mode=cast(Any, "REQUEST_ONE_OFF"))


@pytest.mark.parametrize(
    "status",
    [
        MandateStatus.VALIDATED,
        MandateStatus.APPROVED,
        MandateStatus.ACTIVE,
        MandateStatus.SUSPENDED,
        MandateStatus.HALTED,
        MandateStatus.RECOVERING,
    ],
)
def test_every_non_draft_nonterminal_mandate_expires(status: MandateStatus) -> None:
    mandate = _mandate(status, expires=5)
    assert mandate.status_at(_at(5)) is MandateStatus.EXPIRED
    assert mandate.transition(MandateStatus.EXPIRED, _at(5), actor_is_human=False).status is MandateStatus.EXPIRED


@pytest.mark.parametrize(
    "status",
    [
        MandateStatus.APPROVED,
        MandateStatus.ACTIVE,
        MandateStatus.SUSPENDED,
        MandateStatus.HALTED,
        MandateStatus.RECOVERING,
    ],
)
def test_every_authorized_nonterminal_mandate_can_be_human_revoked(status: MandateStatus) -> None:
    revoked = _mandate(status).transition(
        MandateStatus.REVOKED,
        _at(1),
        actor_is_human=True,
        reason="owner revoked autonomy",
    )
    assert revoked.status is MandateStatus.REVOKED
    with pytest.raises(ValueError):
        revoked.transition(MandateStatus.ACTIVE, _at(2), actor_is_human=True)


def test_halted_recovery_requires_two_explicit_human_gates_and_evidence() -> None:
    halted = _mandate(MandateStatus.HALTED)
    with pytest.raises(PermissionError, match="explicit human recovery gate"):
        halted.transition(MandateStatus.RECOVERING, _at(1), actor_is_human=True)
    with pytest.raises(PermissionError, match="human actor"):
        MandateRecovery.begin(
            halted,
            _at(1),
            actor="service:watch",
            root_cause_ref="incident://resolved",
            reconciliation_ref="reconciliation://complete",
        )
    recovery = MandateRecovery.begin(
        halted,
        _at(1),
        actor="user:owner",
        root_cause_ref="incident://resolved",
        reconciliation_ref="reconciliation://complete",
    )
    with pytest.raises(ValueError, match="governance approval"):
        recovery.complete(
            _at(2),
            actor="user:owner",
            governance_approval_ref="approval://recovery",
            qualified=True,
            health_permits=False,
        )
    active = recovery.complete(
        _at(2),
        actor="user:owner",
        governance_approval_ref="approval://recovery",
        qualified=True,
        health_permits=True,
    )
    assert active.status is MandateStatus.ACTIVE and active.version == halted.version + 2


def test_effective_autonomy_requires_exact_active_mandate_mode_qualification_and_health() -> None:
    mandate = _mandate()
    binding = _binding(mandate)
    assert EffectiveAutonomy.evaluate(mandate, binding, qualified=True, health_permits=True, now=_at()).permitted
    cases = (
        (replace(mandate, status=MandateStatus.SUSPENDED), binding, True, True),
        (mandate, replace(binding, status=BindingStatus.SUPERSEDED), True, True),
        (
            mandate,
            replace(binding, mode=AutonomyMode.PAUSED, previous_mode=AutonomyMode.AUTONOMOUS_SIMULATION),
            True,
            True,
        ),
        (mandate, binding, False, True),
        (mandate, binding, True, False),
    )
    assert all(
        not EffectiveAutonomy.evaluate(
            item_mandate, item_binding, qualified=qualified, health_permits=healthy, now=_at()
        ).permitted
        for item_mandate, item_binding, qualified, healthy in cases
    )


def test_agent_one_off_plan_approval_is_mandate_controlled_and_still_human_granted() -> None:
    denied_mandate = _mandate()
    outside = _request(denied_mandate, instrument="CU")
    denied = AutonomyGate.preflight(
        outside,
        denied_mandate,
        _binding(denied_mandate),
        qualified=True,
        health_permits=True,
        now=_at(),
        approval_allowed=True,
        basis_registry=BasisIssuanceRegistry(),
    )
    assert denied.outcome is PreflightOutcome.REJECT

    mandate = _mandate(escalation=EscalationMode.REQUEST_ONE_OFF)
    binding = _binding(mandate)
    outside = _request(mandate, instrument="CU")
    escalated = AutonomyGate.preflight(
        outside,
        mandate,
        binding,
        qualified=True,
        health_permits=True,
        now=_at(),
        approval_allowed=True,
        basis_registry=BasisIssuanceRegistry(),
    )
    assert escalated.outcome is PreflightOutcome.ESCALATE and escalated.basis is None
    approval = PlanApproval.request_agent_exception(
        request=outside,
        mandate=mandate,
        binding=binding,
        qualified=True,
        health_permits=True,
        approval_id=EntityId.new("plan_approval"),
        approval_token=EntityId.new("approval_token"),
        expires_at=_at(5),
        now=_at(),
    )
    assert approval.status is PlanApprovalStatus.REQUESTED
    assert approval.requested_by == "service:autonomous-quant-pm"
    assert approval.scope.instruments == ("CU",)
    with pytest.raises(PermissionError):
        approval.decide(PlanApprovalStatus.GRANTED, _at(1), actor="service:autonomous-quant-pm")
    assert approval.decide(PlanApprovalStatus.GRANTED, _at(1), actor="user:owner").status is PlanApprovalStatus.GRANTED

    paused = binding.pause(
        _at(1),
        reason="HEALTH_DEGRADED",
        actor="system:health",
        evidence_ref="health://degraded",
    )
    with pytest.raises(ValueError, match="EffectiveAutonomy"):
        PlanApproval.request_agent_exception(
            request=outside,
            mandate=mandate,
            binding=paused,
            qualified=True,
            health_permits=True,
            approval_id=EntityId.new("plan_approval"),
            approval_token=EntityId.new("approval_token"),
            expires_at=_at(5),
            now=_at(1),
        )


@pytest.mark.parametrize("reason", list(OperationalPauseReason))
def test_health_or_version_pause_changes_only_mode_and_invalidates_authorization(
    reason: OperationalPauseReason,
) -> None:
    mandate = _mandate()
    binding = _binding(mandate)
    _request_value, basis, reservation, receipt, ledger, coordinator = _authorization_chain(mandate, binding)
    paused = OperationalModePause.apply(
        mandate,
        binding,
        _at(1),
        reason=reason,
        coordinator=coordinator,
        actor="system:autonomy-health",
        evidence_ref="health://pause",
    )
    assert paused.mandate is mandate and paused.mandate.status is MandateStatus.ACTIVE
    assert paused.invalidation.binding.mode is AutonomyMode.PAUSED
    assert paused.invalidation.stale_bases == (replace(basis, status=BasisStatus.STALE),)
    assert paused.invalidation.invalidated_receipts == (receipt,)
    assert ledger.reservation(reservation.reservation_id).status is ReservationStatus.RELEASED


@pytest.mark.parametrize("retirement", ["expire", "supersede"])
def test_binding_expiry_or_supersession_immediately_invalidates_all_unconsumed_artifacts(retirement: str) -> None:
    mandate = _mandate()
    binding = _binding(mandate, expires=10)
    _request_value, basis, reservation, receipt, ledger, coordinator = _authorization_chain(mandate, binding)
    invalidation = (
        coordinator.expire(binding, _at(10)) if retirement == "expire" else coordinator.supersede(binding, _at(1))
    )
    assert invalidation.binding.status in {BindingStatus.EXPIRED, BindingStatus.SUPERSEDED}
    assert not EffectiveAutonomy.evaluate(
        mandate,
        invalidation.binding,
        qualified=True,
        health_permits=True,
        now=_at(10 if retirement == "expire" else 1),
    ).permitted
    assert invalidation.stale_bases == (replace(basis, status=BasisStatus.STALE),)
    assert invalidation.invalidated_receipts == (receipt,)
    assert ledger.reservation(reservation.reservation_id).status is ReservationStatus.RELEASED


def test_user_composite_pause_and_resume_are_human_only_and_version_both_aggregates() -> None:
    mandate = _mandate()
    binding = _binding(mandate)
    _request_value, basis, reservation, receipt, _ledger, coordinator = _authorization_chain(mandate, binding)
    with pytest.raises(PermissionError, match="human actor"):
        CompositePause.apply(
            mandate,
            binding,
            _at(1),
            coordinator=coordinator,
            actor="service:agent",
            evidence_ref="evidence://pause",
        )
    paused = CompositePause.apply(
        mandate,
        binding,
        _at(1),
        coordinator=coordinator,
        actor="user:owner",
        evidence_ref="evidence://pause",
    )
    assert paused.mandate.status is MandateStatus.SUSPENDED
    assert paused.binding.mode is AutonomyMode.PAUSED
    assert paused.stale_bases == (replace(basis, status=BasisStatus.STALE),)
    assert paused.invalidated_receipts == (receipt,)
    assert paused.released_reservation_ids == (reservation.reservation_id,)
    with pytest.raises(PermissionError):
        CompositeResume.apply(
            paused.mandate,
            paused.binding,
            _at(2),
            actor="service:agent",
            qualified=True,
            health_permits=True,
            run_versions_hash=binding.run_versions_hash,
            evidence_ref="evidence://resume",
        )
    resumed = CompositeResume.apply(
        paused.mandate,
        paused.binding,
        _at(2),
        actor="user:owner",
        qualified=True,
        health_permits=True,
        run_versions_hash=binding.run_versions_hash,
        evidence_ref="evidence://resume",
    )
    assert resumed.mandate.status is MandateStatus.ACTIVE
    assert resumed.binding.mode is AutonomyMode.AUTONOMOUS_SIMULATION
    assert resumed.binding.mandate_version == resumed.mandate.version


def test_mandate_and_mode_truth_are_owned_only_by_decision_context() -> None:
    import futures_agent_os.agent_orchestration as orchestration

    forbidden = {"SimulationAutonomyMandate", "AutonomyModeBinding", "pause_autonomy", "resume_autonomy"}
    assert not forbidden.intersection(orchestration.__all__)
    assert {field.name for field in fields(SimulationAutonomyMandate)}.issuperset(
        {"mandate_id", "version", "status", "scope", "expires_at", "recorded_by"}
    )
