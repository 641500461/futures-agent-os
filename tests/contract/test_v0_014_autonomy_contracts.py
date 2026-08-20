from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.decision import (
    AutonomyGate,
    ApprovalAction,
    ApprovalScope,
    AutonomyMode,
    AutonomyModeBinding,
    BindingStatus,
    BindingArtifactCoordinator,
    BasisIssuanceRegistry,
    CompositePause,
    CompositeResume,
    EffectiveAutonomy,
    ExecutionOrigin,
    FinalGateOutcome,
    GateRequest,
    MandateScope,
    MandateStatus,
    PlanApproval,
    PlanApprovalRegistry,
    PlanApprovalStatus,
    PreflightOutcome,
    ReceiptRegistry,
    ReceiptIssuanceRegistry,
    SimulationAutonomyMandate,
)
from futures_agent_os.learning_review import DecisionJournal, JournalPhase, SourceEvent, TradeEpisode
from futures_agent_os.portfolio_risk import (
    ReservationAction,
    ReservationSourceKind,
    RiskBudgetLedger,
    RiskBudgetReservation,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 19, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _hash(value: str) -> str:
    return canonical_sha256({"value": value})


def _scope() -> MandateScope:
    return MandateScope(
        EntityId.new("simulation_account"),
        ("I",),
        ("trend_v1",),
        ("DAY",),
        frozenset({ApprovalAction.OPEN, ApprovalAction.REDUCE}),
        Decimal("2"),
        "risk://v1",
        "notify://v1",
        "escalate://v1",
    )


def _approval_scope(
    account_id: EntityId, expiry: int = 20, actions: frozenset[ApprovalAction] | None = None
) -> ApprovalScope:
    return ApprovalScope(
        account_id,
        ("I",),
        ("trend_v1",),
        ("DAY",),
        actions or frozenset({ApprovalAction.OPEN}),
        Decimal("2"),
        _at(),
        _at(expiry),
    )


def _mandate(status: MandateStatus = MandateStatus.ACTIVE, expiry: int = 60) -> SimulationAutonomyMandate:
    return SimulationAutonomyMandate(EntityId.new("mandate"), 1, status, _scope(), _at(expiry), _at(), "user:owner")


def _binding(
    mandate: SimulationAutonomyMandate, mode: AutonomyMode = AutonomyMode.AUTONOMOUS_SIMULATION
) -> AutonomyModeBinding:
    return AutonomyModeBinding(
        EntityId.new("mode_binding"),
        1,
        mode,
        BindingStatus.ACTIVE,
        mandate.scope.simulation_account_id,
        mandate.mandate_id,
        mandate.version,
        _hash("runs"),
        _at(50),
        _at(),
        mandate.scope.sha256,
        "scan-policy://v1",
        "universe-policy://v1",
        "qualified-run://v1" if mode is AutonomyMode.AUTONOMOUS_SIMULATION else None,
        "INITIAL_BINDING",
        "user:owner",
        "evidence://binding",
    )


def _request(
    mandate: SimulationAutonomyMandate, origin: ExecutionOrigin = ExecutionOrigin.AUTONOMOUS_AGENT
) -> GateRequest:
    return GateRequest(
        EntityId.new("trade_plan"),
        1,
        _hash("plan"),
        mandate.scope.simulation_account_id,
        "I",
        "trend_v1",
        "DAY",
        ApprovalAction.OPEN,
        Decimal("1"),
        origin,
        _hash("snapshot"),
        _at(30),
        _hash("runs"),
    )


def _reservation(request: GateRequest, basis: object) -> RiskBudgetReservation:
    from futures_agent_os.decision import AuthorizationBasis

    assert isinstance(basis, AuthorizationBasis)
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
        "risk://v1",
        1,
        _hash("constitution"),
        Decimal("100"),
        Decimal("10"),
        Decimal("1"),
        _at(10),
        quantity=request.quantity,
        action=ReservationAction(request.action.value),
        source_kind=ReservationSourceKind.MANDATE
        if basis.kind.value == "MANDATE"
        else ReservationSourceKind.PLAN_APPROVAL,
        source_ref=basis.source_id,
        source_hash=basis.source_hash,
    )


def _ledger(reservation: RiskBudgetReservation) -> RiskBudgetLedger:
    ledger = RiskBudgetLedger(Decimal("100"), "risk://v1", 1, _hash("constitution"))
    assert ledger.reserve(reservation, _at())
    return ledger


def test_mandate_nine_state_expiry_revoke_and_agent_recovery_denial() -> None:
    mandate = _mandate(MandateStatus.DRAFT)
    validated = mandate.transition(MandateStatus.VALIDATED, _at(1), actor_is_human=False)
    approved = validated.transition(MandateStatus.APPROVED, _at(2), actor_is_human=True)
    active = approved.transition(MandateStatus.ACTIVE, _at(3), actor_is_human=True)
    suspended = active.transition(MandateStatus.SUSPENDED, _at(4), actor_is_human=False)
    assert suspended.transition(MandateStatus.ACTIVE, _at(5), actor_is_human=True).status is MandateStatus.ACTIVE
    halted = active.transition(MandateStatus.HALTED, _at(4), actor_is_human=False)
    recovering = halted.transition(MandateStatus.RECOVERING, _at(5), actor_is_human=True)
    assert recovering.transition(MandateStatus.ACTIVE, _at(6), actor_is_human=True).status is MandateStatus.ACTIVE
    assert (
        active.transition(MandateStatus.REVOKED, _at(4), actor_is_human=True, reason="owner choice").status
        is MandateStatus.REVOKED
    )
    assert active.status_at(_at(60)) is MandateStatus.EXPIRED
    with pytest.raises(PermissionError):
        halted.transition(MandateStatus.RECOVERING, _at(5), actor_is_human=False)
    with pytest.raises(ValueError):
        active.transition(MandateStatus.REVOKED, _at(4), actor_is_human=True)


def test_mode_v1_nullable_semantics_and_effective_autonomy_composite_pause() -> None:
    observe = AutonomyModeBinding(
        EntityId.new("mode_binding"),
        1,
        AutonomyMode.OBSERVE,
        BindingStatus.ACTIVE,
        None,
        None,
        None,
        _hash("runs"),
        _at(5),
        _at(),
        _hash("scope"),
        "scan-policy://v1",
        "universe-policy://v1",
        None,
        "INITIAL_BINDING",
        "user:owner",
        "evidence://binding",
    )
    assert observe.simulation_account_id is None
    mandate = _mandate()
    binding = _binding(mandate)
    assert EffectiveAutonomy.evaluate(mandate, binding, qualified=True, health_permits=True, now=_at()).permitted
    for invalid_reference in (" ", " qualified-run://v1", "qualified run://v1", "qualified-run://v1\t"):
        with pytest.raises(ValueError):
            replace(binding, qualified_artifact_ref=invalid_reference)
    with pytest.raises(ValueError):
        replace(binding, qualified_artifact_ref=None)
    paused = CompositePause.apply(
        mandate,
        binding,
        _at(1),
        coordinator=BindingArtifactCoordinator(
            ReceiptIssuanceRegistry(), RiskBudgetLedger(Decimal("100"), "risk://v1", 1, _hash("constitution"))
        ),
    )
    assert paused.mandate.status is MandateStatus.SUSPENDED
    assert paused.binding.mode is AutonomyMode.PAUSED
    assert not EffectiveAutonomy.evaluate(
        paused.mandate, paused.binding, qualified=True, health_permits=True, now=_at(1)
    ).permitted
    assert (
        AutonomyGate.preflight(
            _request(mandate),
            mandate,
            binding,
            qualified=True,
            health_permits=False,
            now=_at(),
            approval_allowed=False,
            basis_registry=BasisIssuanceRegistry(),
        ).outcome
        is PreflightOutcome.PROTECT_ONLY
    )
    assert (
        AutonomyGate.preflight(
            _request(mandate),
            paused.mandate,
            paused.binding,
            qualified=True,
            health_permits=True,
            now=_at(1),
            approval_allowed=False,
            basis_registry=BasisIssuanceRegistry(),
        ).outcome
        is PreflightOutcome.PROTECT_ONLY
    )
    with pytest.raises(ValueError):
        AutonomyModeBinding(
            EntityId.new("mode_binding"),
            1,
            AutonomyMode.AUTONOMOUS_SIMULATION,
            BindingStatus.ACTIVE,
            None,
            None,
            None,
            _hash("runs"),
            _at(5),
            _at(),
            _hash("scope"),
            "scan-policy://v1",
            "universe-policy://v1",
            None,
            "INITIAL_BINDING",
            "user:owner",
            "evidence://binding",
        )


def test_scope_collections_are_lexically_canonical_and_action_hashes_are_stable() -> None:
    account = EntityId.new("simulation_account")
    mandate_scope = MandateScope(
        account,
        ("A", "Z"),
        ("alpha", "zeta"),
        ("DAY", "NIGHT"),
        frozenset((ApprovalAction.OPEN, ApprovalAction.REDUCE)),
        Decimal("2"),
        "risk://v1",
        "notify://v1",
        "escalate://v1",
    )
    approval_a = ApprovalScope(
        account,
        ("A", "Z"),
        ("alpha", "zeta"),
        ("DAY", "NIGHT"),
        frozenset((ApprovalAction.OPEN, ApprovalAction.REDUCE)),
        Decimal("2"),
        _at(),
        _at(10),
    )
    approval_b = ApprovalScope(
        account,
        ("A", "Z"),
        ("alpha", "zeta"),
        ("DAY", "NIGHT"),
        frozenset((ApprovalAction.REDUCE, ApprovalAction.OPEN)),
        Decimal("2"),
        _at(),
        _at(10),
    )
    assert approval_a.scope_hash == approval_b.scope_hash
    assert (
        mandate_scope.sha256
        == MandateScope(
            account,
            ("A", "Z"),
            ("alpha", "zeta"),
            ("DAY", "NIGHT"),
            frozenset((ApprovalAction.REDUCE, ApprovalAction.OPEN)),
            Decimal("2"),
            "risk://v1",
            "notify://v1",
            "escalate://v1",
        ).sha256
    )
    for invalid in (("Z", "A"), ("A", "A"), (" I",)):
        with pytest.raises(ValueError):
            MandateScope(
                account,
                invalid,
                ("alpha",),
                ("DAY",),
                frozenset({ApprovalAction.OPEN}),
                Decimal("2"),
                "risk://v1",
                "notify://v1",
                "escalate://v1",
            )
        with pytest.raises(ValueError):
            ApprovalScope(
                account,
                invalid,
                ("alpha",),
                ("DAY",),
                frozenset({ApprovalAction.OPEN}),
                Decimal("2"),
                _at(),
                _at(10),
            )
    for invalid_reference in (" ", " risk://v1", "risk://v1\t"):
        with pytest.raises(ValueError):
            replace(mandate_scope, risk_constitution_ref=invalid_reference)
        with pytest.raises(ValueError):
            replace(mandate_scope, notification_policy_ref=invalid_reference)
        with pytest.raises(ValueError):
            replace(mandate_scope, escalation_policy_ref=invalid_reference)


def test_plan_approval_is_atomically_consumed_once_under_race() -> None:
    account = EntityId.new("simulation_account")
    requested = PlanApproval(
        EntityId.new("plan_approval"),
        1,
        PlanApprovalStatus.REQUESTED,
        EntityId.new("trade_plan"),
        1,
        _hash("plan"),
        account,
        _approval_scope(account, 10),
        EntityId.new("approval_token"),
        "user:requester",
        _at(10),
        _at(),
    )
    approval = requested.decide(PlanApprovalStatus.GRANTED, _at(1))
    assert requested.decide(PlanApprovalStatus.REJECTED, _at(1)).status is PlanApprovalStatus.REJECTED
    registry = PlanApprovalRegistry()
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _: registry.consume(
                    approval,
                    _at(1),
                    EntityId.new("authorization_basis"),
                    plan_id=approval.plan_id,
                    plan_version=approval.plan_version,
                    plan_hash=approval.plan_hash,
                    account_id=account,
                    instrument="I",
                    strategy="trend_v1",
                    session="DAY",
                    action=ApprovalAction.OPEN,
                    quantity=Decimal("1"),
                ),
                range(8),
            )
        )
    bases = [basis for _, basis in results if basis is not None]
    assert len({basis.basis_id for basis in bases}) == 1
    assert any(result.status is PlanApprovalStatus.CONSUMED for result, _ in results)
    expired_account = EntityId.new("simulation_account")
    expiring = PlanApproval(
        EntityId.new("plan_approval"),
        1,
        PlanApprovalStatus.REQUESTED,
        EntityId.new("trade_plan"),
        1,
        _hash("expired"),
        expired_account,
        _approval_scope(expired_account, 1),
        EntityId.new("approval_token"),
        "user:requester",
        _at(1),
        _at(),
    ).decide(PlanApprovalStatus.GRANTED, _at())
    expired, basis = registry.consume(
        expiring,
        _at(1),
        EntityId.new("authorization_basis"),
        plan_id=expiring.plan_id,
        plan_version=expiring.plan_version,
        plan_hash=expiring.plan_hash,
        account_id=expired_account,
        instrument="I",
        strategy="trend_v1",
        session="DAY",
        action=ApprovalAction.OPEN,
        quantity=Decimal("1"),
    )
    assert expired.status is PlanApprovalStatus.EXPIRED and basis is None
    with pytest.raises(PermissionError):
        requested.decide(PlanApprovalStatus.GRANTED, _at(1), actor="service:approval-worker")
    assert requested.decide(PlanApprovalStatus.REJECTED, _at(1), actor="service:approval-worker").status is (
        PlanApprovalStatus.REJECTED
    )


def test_preflight_basis_issuance_is_shared_idempotent_and_conflicts_fail_closed() -> None:
    mandate = _mandate()
    binding = _binding(mandate)
    request = _request(mandate)
    registry = BasisIssuanceRegistry()

    def preflight(candidate: GateRequest) -> object:
        return AutonomyGate.preflight(
            candidate,
            mandate,
            binding,
            qualified=True,
            health_permits=True,
            now=_at(),
            approval_allowed=False,
            basis_registry=registry,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: preflight(request), range(8)))
    bases = [result.basis for result in results]
    assert all(result.outcome is PreflightOutcome.AUTHORIZED for result in results)
    assert len({basis.basis_id for basis in bases if basis is not None}) == 1
    conflict = preflight(replace(request, quantity=Decimal("2")))
    assert conflict.outcome is PreflightOutcome.REJECT and conflict.reason == "BASIS_ISSUANCE_CONFLICT"


def test_final_gate_requires_authoritative_reservation_and_receipt_consumption_is_shared() -> None:
    mandate = _mandate()
    binding = _binding(mandate)
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
    ledger = RiskBudgetLedger(Decimal("100"), "risk://v1", 1, _hash("constitution"))
    issuance = ReceiptIssuanceRegistry()
    kwargs = dict(
        mandate=mandate,
        approval=None,
        reservation=reservation,
        binding=binding,
        qualified=True,
        health_permits=True,
        now=_at(),
        issuance_registry=issuance,
        risk_ledger=ledger,
    )
    assert AutonomyGate.final_gate(request, basis, **kwargs).outcome is FinalGateOutcome.REJECT
    assert ledger.reserve(reservation, _at())
    assert (
        AutonomyGate.final_gate(
            request, basis, **{**kwargs, "reservation": replace(reservation, worst_case_loss=Decimal("9"))}
        ).outcome
        is FinalGateOutcome.REJECT
    )
    receipt = AutonomyGate.final_gate(request, basis, **kwargs).receipt
    assert receipt is not None
    consume_kwargs = dict(
        request=request,
        basis=basis,
        mandate=mandate,
        approval=None,
        reservation=reservation,
        binding=binding,
        qualified=True,
        health_permits=True,
    )
    first, second = ReceiptRegistry(issuance), ReceiptRegistry(issuance)
    with ThreadPoolExecutor(max_workers=2) as executor:
        consumed = list(
            executor.map(lambda registry: registry.consume(receipt, _at(1), **consume_kwargs), (first, second))
        )
    assert consumed.count(True) == 1


def test_two_phase_gate_and_full_single_use_receipt_binding() -> None:
    mandate = _mandate()
    binding = _binding(mandate)
    request = _request(mandate)
    preflight = AutonomyGate.preflight(
        request,
        mandate,
        binding,
        qualified=True,
        health_permits=True,
        now=_at(),
        approval_allowed=False,
        basis_registry=BasisIssuanceRegistry(),
    )
    assert preflight.outcome is PreflightOutcome.AUTHORIZED and preflight.basis is not None
    reservation = _reservation(request, preflight.basis)
    ledger = _ledger(reservation)
    issuance = ReceiptIssuanceRegistry()
    final = AutonomyGate.final_gate(
        request,
        preflight.basis,
        mandate=mandate,
        approval=None,
        reservation=reservation,
        binding=binding,
        qualified=True,
        health_permits=True,
        now=_at(),
        issuance_registry=issuance,
        risk_ledger=ledger,
    )
    assert final.outcome is FinalGateOutcome.PERMIT and final.receipt is not None
    stale_mandate = replace(mandate, status=MandateStatus.SUSPENDED)
    assert (
        AutonomyGate.final_gate(
            request,
            preflight.basis,
            mandate=stale_mandate,
            approval=None,
            reservation=reservation,
            binding=binding,
            qualified=True,
            health_permits=True,
            now=_at(),
            issuance_registry=issuance,
            risk_ledger=ledger,
        ).outcome
        is FinalGateOutcome.REJECT
    )
    assert (
        AutonomyGate.final_gate(
            request,
            replace(preflight.basis, plan_hash=_hash("different-plan")),
            mandate=mandate,
            approval=None,
            reservation=reservation,
            binding=binding,
            qualified=True,
            health_permits=True,
            now=_at(),
            issuance_registry=issuance,
            risk_ledger=ledger,
        ).outcome
        is FinalGateOutcome.REJECT
    )
    receipt = final.receipt
    for invalid_scope_text in (" I ", "\tI", "I\n"):
        for field in ("instrument", "strategy", "session"):
            with pytest.raises(ValueError):
                replace(request, **{field: invalid_scope_text})
            with pytest.raises(ValueError):
                replace(preflight.basis, **{field: invalid_scope_text})
            with pytest.raises(ValueError):
                replace(reservation, **{field: invalid_scope_text})
            with pytest.raises(ValueError):
                replace(receipt, **{field: invalid_scope_text})
    registry = ReceiptRegistry(issuance)
    kwargs = dict(
        request=request,
        basis=preflight.basis,
        mandate=mandate,
        approval=None,
        reservation=reservation,
        binding=binding,
        qualified=True,
        health_permits=True,
    )
    assert registry.consume(receipt, _at(1), **kwargs)
    assert not registry.consume(receipt, _at(1), **kwargs)
    assert (
        AutonomyGate.preflight(
            request,
            mandate,
            binding,
            qualified=True,
            health_permits=False,
            now=_at(),
            approval_allowed=False,
            basis_registry=BasisIssuanceRegistry(),
        ).outcome
        is PreflightOutcome.PROTECT_ONLY
    )
    assert (
        AutonomyGate.preflight(
            _request(mandate, ExecutionOrigin.MANUAL_TEST),
            mandate,
            binding,
            qualified=True,
            health_permits=True,
            now=_at(),
            approval_allowed=True,
            basis_registry=BasisIssuanceRegistry(),
        ).outcome
        is PreflightOutcome.ESCALATE
    )


def test_atomic_reservation_prevents_aggregate_breach_and_never_relaxes_constitution() -> None:
    ledger = RiskBudgetLedger(Decimal("100"), "risk://v1", 1, _hash("constitution"))

    def make_reservation(loss: str) -> RiskBudgetReservation:
        return RiskBudgetReservation(
            EntityId.new("risk_budget_reservation"),
            EntityId.new("simulation_account"),
            EntityId.new("trade_plan"),
            1,
            _hash("plan"),
            "I",
            "trend_v1",
            "DAY",
            EntityId.new("authorization_basis"),
            _hash("basis"),
            "risk://v1",
            1,
            _hash("constitution"),
            Decimal("100"),
            Decimal(loss),
            Decimal("10"),
            _at(10),
            quantity=Decimal("1"),
            source_kind=ReservationSourceKind.MANDATE,
            source_ref=EntityId.new("mandate"),
            source_hash=_hash("source"),
        )

    reservations = [make_reservation("60"), make_reservation("60")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = list(executor.map(lambda reservation: ledger.reserve(reservation, _at()), reservations))
    assert decisions.count(True) == 1
    with pytest.raises(ValueError):
        make_reservation("101")
    assert all(item.worst_case_loss <= item.risk_constitution_ceiling for item in ledger.reservations)


def test_autonomy_binding_account_scope_hash_and_snapshot_are_revalidated() -> None:
    mandate = _mandate()
    binding = _binding(mandate)
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
    ledger = _ledger(reservation)
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
    common = dict(
        mandate=mandate,
        approval=None,
        reservation=reservation,
        qualified=True,
        health_permits=True,
        now=_at(1),
        issuance_registry=issuance,
        risk_ledger=ledger,
    )
    for invalid_binding in (
        replace(binding, simulation_account_id=EntityId.new("simulation_account")),
        replace(binding, scope_snapshot_hash=_hash("different-scope")),
    ):
        assert not EffectiveAutonomy.evaluate(
            mandate, invalid_binding, qualified=True, health_permits=True, now=_at(1)
        ).permitted
        assert (
            AutonomyGate.preflight(
                request,
                mandate,
                invalid_binding,
                qualified=True,
                health_permits=True,
                now=_at(1),
                approval_allowed=False,
                basis_registry=BasisIssuanceRegistry(),
            ).outcome
            is PreflightOutcome.REJECT
        )
        assert (
            AutonomyGate.final_gate(request, basis, binding=invalid_binding, **common).outcome
            is FinalGateOutcome.REJECT
        )
        assert not ReceiptRegistry(issuance).consume(
            receipt,
            _at(1),
            request=request,
            basis=basis,
            mandate=mandate,
            approval=None,
            reservation=reservation,
            binding=invalid_binding,
            qualified=True,
            health_permits=True,
        )
    for stale_snapshot in (_at(), _at(-1)):
        assert (
            AutonomyGate.final_gate(
                replace(request, snapshot_expires_at=stale_snapshot), basis, binding=binding, **common
            ).outcome
            is FinalGateOutcome.REJECT
        )
    assert not ReceiptRegistry(issuance).consume(
        receipt,
        _at(1),
        request=replace(request, snapshot_expires_at=_at(1)),
        basis=basis,
        mandate=mandate,
        approval=None,
        reservation=reservation,
        binding=binding,
        qualified=True,
        health_permits=True,
    )


def test_reservation_identity_is_singleton_per_plan_version_and_basis() -> None:
    mandate = _mandate()
    request = _request(mandate)
    basis = AutonomyGate.preflight(
        request,
        mandate,
        _binding(mandate),
        qualified=True,
        health_permits=True,
        now=_at(),
        approval_allowed=False,
        basis_registry=BasisIssuanceRegistry(),
    ).basis
    assert basis is not None
    original = replace(_reservation(request, basis), worst_case_loss=Decimal("100"))
    ledger = RiskBudgetLedger(Decimal("100"), "risk://v1", 1, _hash("constitution"))
    assert ledger.reserve(original, _at())
    assert ledger.reserve(original, _at())  # Exact command replay is idempotent.
    conflict = replace(original, reservation_id=EntityId.new("risk_budget_reservation"))
    assert not ledger.reserve(conflict, _at())
    assert not hasattr(ledger, "replace")
    shrunk = ledger.shrink(original.reservation_id, Decimal("50"))
    assert shrunk is not None and shrunk.status.value == "HELD"
    assert ledger.release(original.reservation_id) is not None
    next_request = replace(request, plan_id=EntityId.new("trade_plan"), plan_hash=_hash("next-plan"))
    next_basis = AutonomyGate.preflight(
        next_request,
        mandate,
        _binding(mandate),
        qualified=True,
        health_permits=True,
        now=_at(1),
        approval_allowed=False,
        basis_registry=BasisIssuanceRegistry(),
    ).basis
    assert next_basis is not None and ledger.reserve(_reservation(next_request, next_basis), _at(1))

    raced = RiskBudgetLedger(Decimal("100"), "risk://v1", 1, _hash("constitution"))
    candidates = (
        replace(original, reservation_id=EntityId.new("risk_budget_reservation")),
        replace(original, reservation_id=EntityId.new("risk_budget_reservation")),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda candidate: raced.reserve(candidate, _at()), candidates))
    assert outcomes.count(True) == 1
    assert len(raced.reservations) == 1


def test_manual_path_requires_consumed_approval_and_autonomous_path_rejects_it() -> None:
    mandate = _mandate()
    request = _request(mandate, ExecutionOrigin.MANUAL_TEST)
    requested = PlanApproval(
        EntityId.new("plan_approval"),
        1,
        PlanApprovalStatus.REQUESTED,
        request.plan_id,
        request.plan_version,
        request.plan_hash,
        request.account_id,
        _approval_scope(request.account_id),
        EntityId.new("approval_token"),
        "user:requester",
        _at(20),
        _at(),
    )
    granted = requested.decide(PlanApprovalStatus.GRANTED, _at(1))
    consumed, basis = PlanApprovalRegistry().consume(
        granted,
        _at(2),
        EntityId.new("authorization_basis"),
        plan_id=request.plan_id,
        plan_version=request.plan_version,
        plan_hash=request.plan_hash,
        account_id=request.account_id,
        instrument=request.instrument,
        strategy=request.strategy,
        session=request.session,
        action=request.action,
        quantity=request.quantity,
    )
    assert basis is not None
    reservation = _reservation(request, basis)
    ledger = _ledger(reservation)
    issuance = ReceiptIssuanceRegistry()
    assert (
        AutonomyGate.final_gate(
            request,
            basis,
            mandate=None,
            approval=consumed,
            reservation=reservation,
            binding=None,
            qualified=False,
            health_permits=False,
            now=_at(2),
            issuance_registry=issuance,
            risk_ledger=ledger,
        ).outcome
        is FinalGateOutcome.REJECT
    )
    final = AutonomyGate.final_gate(
        request,
        basis,
        mandate=None,
        approval=consumed,
        reservation=reservation,
        binding=None,
        qualified=False,
        health_permits=True,
        now=_at(2),
        issuance_registry=issuance,
        risk_ledger=ledger,
    )
    assert final.outcome is FinalGateOutcome.PERMIT and final.receipt is not None
    assert final.receipt.manual_actor_ref == consumed.decided_by
    manual_consume_kwargs = dict(
        request=request,
        basis=basis,
        mandate=None,
        approval=consumed,
        reservation=reservation,
        binding=None,
        qualified=False,
    )
    manual_receipts = ReceiptRegistry(issuance)
    assert not manual_receipts.consume(final.receipt, _at(2), health_permits=False, **manual_consume_kwargs)
    assert manual_receipts.consume(final.receipt, _at(2), health_permits=True, **manual_consume_kwargs)
    assert (
        AutonomyGate.final_gate(
            request,
            basis,
            mandate=None,
            approval=replace(consumed, decided_by="user:other-approver"),
            reservation=reservation,
            binding=None,
            qualified=False,
            health_permits=True,
            now=_at(2),
            issuance_registry=ReceiptIssuanceRegistry(),
            risk_ledger=ledger,
        ).outcome
        is FinalGateOutcome.REJECT
    )
    autonomous = replace(request, execution_origin=ExecutionOrigin.AUTONOMOUS_AGENT)
    assert (
        AutonomyGate.final_gate(
            autonomous,
            basis,
            mandate=mandate,
            approval=consumed,
            reservation=reservation,
            binding=_binding(mandate),
            qualified=True,
            health_permits=True,
            now=_at(2),
            issuance_registry=issuance,
            risk_ledger=ledger,
        ).outcome
        is FinalGateOutcome.REJECT
    )


def test_decision_time_post_hoc_journal_and_trade_episode_are_rebuildable_projections() -> None:
    event = SourceEvent(
        EntityId.new("domain_event"),
        "Decision",
        1,
        "TradePlanValidated",
        _at(),
        _at(1),
        _hash("event"),
        EntityId.new("correlation"),
    )
    journal = DecisionJournal(EntityId.new("decision_journal"))
    first = journal.append(event, JournalPhase.DECISION_TIME, _at(1), decision_cutoff_at=_at(1))
    assert journal.append(event, JournalPhase.DECISION_TIME, _at(1), decision_cutoff_at=_at(1)) == first
    with pytest.raises(ValueError):
        journal.append(event, JournalPhase.POST_HOC, _at(2))
    rebuilt = journal.rebuild((event,), _at(2), phase_for_event={event.event_id: JournalPhase.POST_HOC})
    assert len(rebuilt) == 1 and rebuilt[0].phase is JournalPhase.POST_HOC
    episode_a = TradeEpisode.rebuild(EntityId.new("trade_episode"), EntityId.new("decision_episode"), (event,))
    episode_b = TradeEpisode.rebuild(episode_a.episode_id, episode_a.decision_episode_id, (event,))
    assert episode_a.projection_hash == episode_b.projection_hash and episode_a.source_event_ids == (event.event_id,)
    assert journal.rebuild(
        (event, event), _at(2), phase_for_event={event.event_id: JournalPhase.POST_HOC}
    ) == journal.rebuild((event,), _at(2), phase_for_event={event.event_id: JournalPhase.POST_HOC})
    assert TradeEpisode.rebuild(episode_a.episode_id, episode_a.decision_episode_id, (event, event)) == episode_a
    conflict = replace(event, payload_hash=_hash("conflicting-payload"))
    with pytest.raises(ValueError):
        journal.rebuild((event, conflict), _at(2))
    with pytest.raises(ValueError):
        TradeEpisode.rebuild(episode_a.episode_id, episode_a.decision_episode_id, (conflict, event))
    before_failed_rebuild = journal.entries
    late_decision_fact = replace(event, event_id=EntityId.new("domain_event"), available_at=_at(3))
    with pytest.raises(ValueError):
        journal.rebuild(
            (event, late_decision_fact),
            _at(3),
            phase_for_event={event.event_id: JournalPhase.POST_HOC},
            decision_cutoff_at=_at(1),
        )
    assert journal.entries == before_failed_rebuild


def test_expiry_boundaries_increment_state_and_binding_coordinator_invalidates_artifacts() -> None:
    mandate = _mandate(expiry=1)
    assert mandate.is_active_at(_at())
    expired_mandate = mandate.transition(MandateStatus.EXPIRED, _at(1), actor_is_human=False)
    assert expired_mandate.version == mandate.version + 1 and expired_mandate.status is MandateStatus.EXPIRED
    assert mandate.transition(MandateStatus.EXPIRED, _at(2), actor_is_human=False).recorded_at == _at(2)
    binding = _binding(_mandate())
    with pytest.raises(ValueError):
        binding.expire(_at(49))
    expired_binding = binding.expire(_at(50))
    assert expired_binding.status is BindingStatus.EXPIRED and expired_binding.recorded_at == _at(50)
    approval_account = EntityId.new("simulation_account")
    approval = PlanApproval(
        EntityId.new("plan_approval"),
        1,
        PlanApprovalStatus.REQUESTED,
        EntityId.new("trade_plan"),
        1,
        _hash("expired-plan"),
        approval_account,
        _approval_scope(approval_account, 1),
        EntityId.new("approval_token"),
        "user:requester",
        _at(1),
        _at(),
    ).decide(PlanApprovalStatus.GRANTED, _at())
    expired_approval, no_basis = PlanApprovalRegistry().consume(
        approval,
        _at(1),
        EntityId.new("authorization_basis"),
        plan_id=approval.plan_id,
        plan_version=approval.plan_version,
        plan_hash=approval.plan_hash,
        account_id=approval.account_id,
        instrument="I",
        strategy="trend_v1",
        session="DAY",
        action=ApprovalAction.OPEN,
        quantity=Decimal("1"),
    )
    assert no_basis is None and expired_approval.status is PlanApprovalStatus.EXPIRED and expired_approval.version == 3
    active_mandate = _mandate()
    active_binding = _binding(active_mandate)
    request = _request(active_mandate)
    basis = AutonomyGate.preflight(
        request,
        active_mandate,
        active_binding,
        qualified=True,
        health_permits=True,
        now=_at(),
        approval_allowed=False,
        basis_registry=BasisIssuanceRegistry(),
    ).basis
    assert basis is not None
    reservation = _reservation(request, basis)
    ledger = RiskBudgetLedger(Decimal("100"), "risk://v1", 1, _hash("constitution"))
    assert ledger.reserve(reservation, _at())
    issuance = ReceiptIssuanceRegistry()
    receipt = AutonomyGate.final_gate(
        request,
        basis,
        mandate=active_mandate,
        approval=None,
        reservation=reservation,
        binding=active_binding,
        qualified=True,
        health_permits=True,
        now=_at(),
        issuance_registry=issuance,
        risk_ledger=ledger,
    ).receipt
    assert receipt is not None
    coordinator = BindingArtifactCoordinator(issuance, ledger)
    coordinator.track(active_binding, basis, reservation.reservation_id)
    invalidated = coordinator.supersede(active_binding, _at(1))
    assert invalidated.stale_bases[0].status.value == "STALE"
    assert invalidated.released_reservation_ids == (reservation.reservation_id,)
    assert not ReceiptRegistry(issuance).consume(
        receipt,
        _at(1),
        request=request,
        basis=basis,
        mandate=active_mandate,
        approval=None,
        reservation=ledger.reservations[0],
        binding=active_binding,
        qualified=True,
        health_permits=True,
    )
    consumed_ledger = RiskBudgetLedger(Decimal("100"), "risk://v1", 1, _hash("constitution"))
    assert consumed_ledger.reserve(reservation, _at())
    assert consumed_ledger.consume(reservation.reservation_id, _at(1)) is not None
    consumed_coordinator = BindingArtifactCoordinator(ReceiptIssuanceRegistry(), consumed_ledger)
    consumed_coordinator.track(active_binding, basis, reservation.reservation_id)
    consumed_invalidation = consumed_coordinator.supersede(active_binding, _at(1))
    assert consumed_invalidation.released_reservations == ()


def test_receipt_issuance_is_atomic_per_basis_and_second_receipt_cannot_consume() -> None:
    mandate = _mandate()
    binding = _binding(mandate)
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
    ledger = _ledger(reservation)
    issuance = ReceiptIssuanceRegistry()

    def issue() -> object:
        return AutonomyGate.final_gate(
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

    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = list(executor.map(lambda _: issue(), range(8)))
    assert all(receipt is not None for receipt in receipts)
    assert len({receipt.nonce for receipt in receipts if receipt is not None}) == 1
    receipt = receipts[0]
    assert receipt is not None
    forged = replace(receipt, receipt_id=EntityId.new("autonomy_gate_receipt"), nonce=EntityId.new("receipt_nonce"))
    consumption = ReceiptRegistry(issuance)
    kwargs = dict(
        request=request,
        basis=basis,
        mandate=mandate,
        approval=None,
        reservation=reservation,
        binding=binding,
        qualified=True,
        health_permits=True,
    )
    assert not consumption.consume(forged, _at(1), **kwargs)
    assert consumption.consume(receipt, _at(1), **kwargs)


def test_composite_pause_resume_versions_stale_old_artifacts_and_health_pause_is_mode_only() -> None:
    mandate = _mandate()
    binding = _binding(mandate)
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
    ledger = _ledger(reservation)
    issuance = ReceiptIssuanceRegistry()
    issued = AutonomyGate.final_gate(
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
    )
    assert issued.receipt is not None
    coordinator = BindingArtifactCoordinator(issuance, ledger)
    coordinator.track(binding, basis, reservation.reservation_id)
    paused = CompositePause.apply(
        mandate,
        binding,
        _at(1),
        coordinator=coordinator,
        actor="user:owner",
        evidence_ref="evidence://pause",
    )
    assert paused.mandate.version == mandate.version + 1
    assert paused.binding.mandate_version == paused.mandate.version
    assert paused.stale_bases[0].status.value == "STALE"
    assert paused.invalidated_receipts == (issued.receipt,)
    assert paused.released_reservation_ids == (reservation.reservation_id,)
    assert coordinator.basis_state(basis.basis_id) == paused.stale_bases[0]
    assert ledger.reservation(reservation.reservation_id) == paused.released_reservations[0]
    assert (
        AutonomyGate.final_gate(
            request,
            basis,
            mandate=mandate,
            approval=None,
            reservation=reservation,
            binding=binding,
            qualified=True,
            health_permits=True,
            now=_at(1),
            issuance_registry=issuance,
            risk_ledger=ledger,
        ).outcome
        is FinalGateOutcome.REJECT
    )
    with pytest.raises(ValueError):
        CompositeResume.apply(
            paused.mandate,
            paused.binding,
            _at(2),
            actor="user:owner",
            qualified=False,
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
    assert resumed.mandate.version == paused.mandate.version + 1
    assert resumed.binding.mandate_version == resumed.mandate.version
    assert resumed.binding.binding_hash != binding.binding_hash
    assert not ReceiptRegistry(issuance).consume(
        issued.receipt,
        _at(2),
        request=request,
        basis=basis,
        mandate=resumed.mandate,
        approval=None,
        reservation=reservation,
        binding=resumed.binding,
        qualified=True,
        health_permits=True,
    )
    health_paused = binding.pause(_at(1), reason="HEALTH_PAUSE", actor="system:watch", evidence_ref="watch://health")
    assert health_paused.mandate_version == mandate.version and mandate.status is MandateStatus.ACTIVE


def test_approval_scope_is_not_mutable_or_expandable_and_reservation_lifecycle_is_monotonic() -> None:
    mandate = _mandate()
    request = _request(mandate, ExecutionOrigin.MANUAL_TEST)
    scope = _approval_scope(request.account_id)
    approval = PlanApproval(
        EntityId.new("plan_approval"),
        1,
        PlanApprovalStatus.REQUESTED,
        request.plan_id,
        request.plan_version,
        request.plan_hash,
        request.account_id,
        scope,
        EntityId.new("approval_token"),
        "user:requester",
        _at(20),
        _at(),
    ).decide(PlanApprovalStatus.GRANTED, _at(1))
    registry = PlanApprovalRegistry()
    denied, basis = registry.consume(
        approval,
        _at(2),
        EntityId.new("authorization_basis"),
        plan_id=approval.plan_id,
        plan_version=approval.plan_version,
        plan_hash=approval.plan_hash,
        account_id=approval.account_id,
        instrument=request.instrument,
        strategy=request.strategy,
        session=request.session,
        action=ApprovalAction.REDUCE,
        quantity=Decimal("1"),
    )
    assert denied is approval and basis is None
    consumed, basis = registry.consume(
        approval,
        _at(2),
        EntityId.new("authorization_basis"),
        plan_id=approval.plan_id,
        plan_version=approval.plan_version,
        plan_hash=approval.plan_hash,
        account_id=approval.account_id,
        instrument=request.instrument,
        strategy=request.strategy,
        session=request.session,
        action=ApprovalAction.OPEN,
        quantity=Decimal("1"),
    )
    assert basis is not None and consumed.status is PlanApprovalStatus.CONSUMED
    mutated_scope = ApprovalScope(
        request.account_id,
        ("I",),
        ("trend_v1",),
        ("DAY",),
        frozenset({ApprovalAction.OPEN}),
        Decimal("3"),
        _at(),
        _at(20),
    )
    assert (
        registry.consume(
            replace(approval, scope=mutated_scope),
            _at(2),
            EntityId.new("authorization_basis"),
            plan_id=approval.plan_id,
            plan_version=approval.plan_version,
            plan_hash=approval.plan_hash,
            account_id=approval.account_id,
            instrument=request.instrument,
            strategy=request.strategy,
            session=request.session,
            action=ApprovalAction.OPEN,
            quantity=Decimal("1"),
        )[1]
        is None
    )
    reservation = _reservation(request, basis)
    ledger = RiskBudgetLedger(Decimal("100"), "risk://v1", 1, _hash("constitution"))
    assert ledger.reserve(reservation, _at())
    shrunk = ledger.shrink(reservation.reservation_id, Decimal("5"))
    assert shrunk is not None and shrunk.version == reservation.version + 1
    released = ledger.release(reservation.reservation_id)
    assert released is not None and released.status.value == "RELEASED" and released.state_version == 3
    assert ledger.consume(reservation.reservation_id, _at(1)) is None


def test_action_quantity_token_window_and_multi_action_selection_are_bound_end_to_end() -> None:
    mandate = _mandate()
    request = replace(_request(mandate, ExecutionOrigin.MANUAL_TEST), action=ApprovalAction.REDUCE)
    approval = PlanApproval(
        EntityId.new("plan_approval"),
        1,
        PlanApprovalStatus.REQUESTED,
        request.plan_id,
        request.plan_version,
        request.plan_hash,
        request.account_id,
        _approval_scope(request.account_id, actions=frozenset({ApprovalAction.OPEN, ApprovalAction.REDUCE})),
        EntityId.new("approval_token"),
        "user:requester",
        _at(20),
        _at(),
    ).decide(PlanApprovalStatus.GRANTED, _at(1), actor="user:approver")
    consumed, basis = PlanApprovalRegistry().consume(
        approval,
        _at(2),
        EntityId.new("authorization_basis"),
        plan_id=request.plan_id,
        plan_version=request.plan_version,
        plan_hash=request.plan_hash,
        account_id=request.account_id,
        instrument=request.instrument,
        strategy=request.strategy,
        session=request.session,
        action=request.action,
        quantity=request.quantity,
    )
    assert basis is not None and basis.authorized_action is ApprovalAction.REDUCE
    reservation = _reservation(request, basis)
    ledger = _ledger(reservation)
    issuance = ReceiptIssuanceRegistry()
    kwargs = dict(
        mandate=None,
        approval=consumed,
        reservation=reservation,
        binding=None,
        qualified=False,
        health_permits=True,
        now=_at(2),
        issuance_registry=issuance,
        risk_ledger=ledger,
    )
    assert AutonomyGate.final_gate(request, basis, **kwargs).outcome is FinalGateOutcome.PERMIT
    assert (
        AutonomyGate.final_gate(replace(request, quantity=Decimal("2")), basis, **kwargs).outcome
        is FinalGateOutcome.REJECT
    )
    assert (
        AutonomyGate.final_gate(replace(request, action=ApprovalAction.OPEN), basis, **kwargs).outcome
        is FinalGateOutcome.REJECT
    )
    assert (
        AutonomyGate.final_gate(
            request, replace(basis, approval_token=EntityId.new("approval_token")), **kwargs
        ).outcome
        is FinalGateOutcome.REJECT
    )
    assert (
        AutonomyGate.final_gate(
            request,
            replace(basis, approval_valid_until_at=_at(19), expires_at=_at(19)),
            **kwargs,
        ).outcome
        is FinalGateOutcome.REJECT
    )
    approval_outside_scope = replace(
        consumed,
        scope=ApprovalScope(
            request.account_id,
            ("OTHER",),
            ("trend_v1",),
            ("DAY",),
            consumed.scope.actions,
            consumed.scope.quantity_ceiling,
            consumed.scope.valid_from_at,
            consumed.scope.valid_until_at,
        ),
    )
    assert (
        AutonomyGate.final_gate(request, basis, **{**kwargs, "approval": approval_outside_scope}).outcome
        is FinalGateOutcome.REJECT
    )
    assert (
        AutonomyGate.final_gate(
            request,
            basis,
            reservation=replace(reservation, quantity=Decimal("999")),
            **{key: value for key, value in kwargs.items() if key != "reservation"},
        ).outcome
        is FinalGateOutcome.REJECT
    )


def test_risk_dimensions_are_canonical_immutable_mapping_and_actors_are_canonical() -> None:
    mandate = _mandate()
    request = _request(mandate)
    basis = AutonomyGate.preflight(
        request,
        mandate,
        _binding(mandate),
        qualified=True,
        health_permits=True,
        now=_at(),
        approval_allowed=False,
        basis_registry=BasisIssuanceRegistry(),
    ).basis
    assert basis is not None
    reservation = _reservation(request, basis)
    dimensions = (("delta", "1"), ("margin_class", "initial"))
    canonical = replace(reservation, risk_dimensions=dimensions)
    assert canonical.reservation_hash == replace(reservation, risk_dimensions=dimensions).reservation_hash
    with pytest.raises(TypeError):
        replace(reservation, risk_dimensions={"delta": "1"})
    with pytest.raises(ValueError):
        replace(reservation, risk_dimensions=(("delta", "1"), ("delta", "2")))
    for invalid_quantity in (Decimal("0"), Decimal("NaN"), Decimal("Infinity"), Decimal("-1")):
        with pytest.raises(ValueError):
            replace(reservation, quantity=invalid_quantity)
    for invalid_reference in (" ", " risk://v1", "risk://v1\t"):
        with pytest.raises(ValueError):
            replace(reservation, risk_constitution_ref=invalid_reference)
        with pytest.raises(ValueError):
            RiskBudgetLedger(Decimal("100"), invalid_reference, 1, _hash("constitution"))
    with pytest.raises(ValueError):
        SimulationAutonomyMandate(EntityId.new("mandate"), 1, MandateStatus.ACTIVE, _scope(), _at(10), _at(), "user:")
    with pytest.raises(ValueError):
        PlanApproval(
            EntityId.new("plan_approval"),
            1,
            PlanApprovalStatus.REQUESTED,
            request.plan_id,
            request.plan_version,
            request.plan_hash,
            request.account_id,
            _approval_scope(request.account_id),
            EntityId.new("approval_token"),
            " service:approver",
            _at(20),
            _at(),
        )
    for invalid_actor in ("user:two words", "service:tab\tactor", "system:line\nbreak"):
        with pytest.raises(ValueError):
            SimulationAutonomyMandate(
                EntityId.new("mandate"), 1, MandateStatus.ACTIVE, _scope(), _at(10), _at(), invalid_actor
            )


def test_execution_scope_dimensions_and_action_quantity_reject_any_post_preflight_drift() -> None:
    mandate = _mandate()
    binding = _binding(mandate)
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
    ledger = _ledger(reservation)
    issuance = ReceiptIssuanceRegistry()
    common = dict(
        mandate=mandate,
        approval=None,
        reservation=reservation,
        binding=binding,
        qualified=True,
        health_permits=True,
        now=_at(),
        issuance_registry=issuance,
        risk_ledger=ledger,
    )
    for replacement in (
        replace(request, instrument="OUT_OF_SCOPE"),
        replace(request, strategy="other_strategy"),
        replace(request, session="OVERNIGHT"),
    ):
        assert AutonomyGate.final_gate(replacement, basis, **common).outcome is FinalGateOutcome.REJECT
    for field, value in (("instrument", "OUT_OF_SCOPE"), ("strategy", "other_strategy"), ("session", "OVERNIGHT")):
        assert (
            AutonomyGate.final_gate(
                request,
                basis,
                reservation=replace(reservation, **{field: value}),
                **{key: item for key, item in common.items() if key != "reservation"},
            ).outcome
            is FinalGateOutcome.REJECT
        )
    narrowed_scope = MandateScope(
        mandate.scope.simulation_account_id,
        ("OTHER",),
        mandate.scope.strategies,
        mandate.scope.sessions,
        mandate.scope.actions,
        mandate.scope.quantity_ceiling,
        mandate.scope.risk_constitution_ref,
        mandate.scope.notification_policy_ref,
        mandate.scope.escalation_policy_ref,
    )
    assert (
        AutonomyGate.final_gate(request, basis, **{**common, "mandate": replace(mandate, scope=narrowed_scope)}).outcome
        is FinalGateOutcome.REJECT
    )
    with pytest.raises(ValueError):
        replace(request, quantity=Decimal("0"))
    with pytest.raises(TypeError):
        replace(request, action="OPEN")
    with pytest.raises(TypeError):
        ApprovalScope(
            request.account_id,
            ("I",),
            ("trend_v1",),
            ("DAY",),
            frozenset({"OPEN"}),
            Decimal("1"),
            _at(),
            _at(1),
        )
