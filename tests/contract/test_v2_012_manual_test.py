from datetime import UTC, datetime, timedelta
from dataclasses import replace
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import json
import pytest

from futures_agent_os.decision import (
    ApprovalAction,
    ApprovalScope,
    ExecutionOrigin,
    ManualTestApprovalStore,
    ManualTestContext,
    PlanApproval,
    PlanApprovalStatus,
    require_manual_test,
)
from futures_agent_os.cli import main
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256
from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.decision import Fill, Order, OrderStatus, StopPolicy, TradeDirection
from futures_agent_os.execution_simulation import (
    L1Bar,
    ProtectionTriggerEvaluator,
    ProtectionValidator,
    ValidationOutcome,
    run_manual_shadow_episode,
    SimulationEngine,
)


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def test_manual_test_context_is_simulation_only() -> None:
    context = ManualTestContext("user:test", "environment://simulation-only", "basis:test")
    require_manual_test(ExecutionOrigin.MANUAL_TEST, context)
    with pytest.raises(ValueError):
        require_manual_test(ExecutionOrigin.AUTONOMOUS_AGENT, context)


def test_manual_test_rejects_non_simulation_environment() -> None:
    with pytest.raises(ValueError):
        ManualTestContext("user:test", "environment://live", "basis:test")


def test_manual_approval_durable_state_survives_restart_and_consumes_once(tmp_path) -> None:
    account = EntityId.deterministic("simulation_account", "manual-durable-account")
    plan = EntityId.deterministic("trade_plan", "manual-durable-plan")
    approval = PlanApproval(
        EntityId.deterministic("plan_approval", "manual-durable-approval"),
        1,
        PlanApprovalStatus.REQUESTED,
        plan,
        1,
        canonical_sha256({"plan": "manual-durable"}),
        account,
        ApprovalScope(
            account,
            ("SHFE_AG_2601",),
            ("strategy:test",),
            ("DAY",),
            frozenset({ApprovalAction.OPEN}),
            Decimal("2"),
            _at(),
            _at(10),
        ),
        EntityId.deterministic("approval_token", "manual-durable-token"),
        "user:owner",
        _at(10),
        _at(),
    )
    store = ManualTestApprovalStore(tmp_path / "manual.json")
    assert store.request(approval).changed
    granted = store.decide(approval.approval_id, PlanApprovalStatus.GRANTED, _at(1)).approval
    restarted = ManualTestApprovalStore(tmp_path / "manual.json")
    assert restarted.get(approval.approval_id) == granted
    request_replay = restarted.request(approval)
    assert not request_replay.changed and request_replay.reason == "REPLAYED"
    assert request_replay.approval == granted
    decision_replay = restarted.decide(approval.approval_id, PlanApprovalStatus.GRANTED, _at(1))
    assert not decision_replay.changed and decision_replay.reason == "REPLAYED"
    consumed = restarted.consume(
        approval.approval_id,
        _at(2),
        EntityId.deterministic("authorization_basis", "manual-durable-basis"),
        plan_id=plan,
        plan_version=1,
        plan_hash=approval.plan_hash,
        account_id=account,
        instrument="SHFE_AG_2601",
        strategy="strategy:test",
        session="DAY",
        action=ApprovalAction.OPEN,
        quantity=Decimal("1"),
    )
    assert consumed.changed and consumed.approval.status is PlanApprovalStatus.CONSUMED and consumed.basis is not None
    replay = ManualTestApprovalStore(tmp_path / "manual.json").consume(
        approval.approval_id,
        _at(2),
        EntityId.deterministic("authorization_basis", "manual-durable-basis"),
        plan_id=plan,
        plan_version=1,
        plan_hash=approval.plan_hash,
        account_id=account,
        instrument="SHFE_AG_2601",
        strategy="strategy:test",
        session="DAY",
        action=ApprovalAction.OPEN,
        quantity=Decimal("1"),
    )
    assert not replay.changed and replay.reason == "REPLAYED"
    mismatch = ManualTestApprovalStore(tmp_path / "manual.json").consume(
        approval.approval_id,
        _at(2),
        EntityId.deterministic("authorization_basis", "manual-durable-basis"),
        plan_id=plan,
        plan_version=1,
        plan_hash=approval.plan_hash,
        account_id=account,
        instrument="SHFE_AG_2601",
        strategy="strategy:test",
        session="DAY",
        action=ApprovalAction.OPEN,
        quantity=Decimal("2"),
    )
    assert not mismatch.changed and mismatch.reason == "CONSUME_REPLAY_SCOPE_MISMATCH"


def test_manual_approval_concurrent_consume_has_one_durable_winner(tmp_path) -> None:
    account = EntityId.deterministic("simulation_account", "manual-concurrent-account")
    plan = EntityId.deterministic("trade_plan", "manual-concurrent-plan")
    approval = PlanApproval(
        EntityId.deterministic("plan_approval", "manual-concurrent-approval"),
        1,
        PlanApprovalStatus.REQUESTED,
        plan,
        1,
        canonical_sha256({"plan": "manual-concurrent"}),
        account,
        ApprovalScope(
            account,
            ("SHFE_AG_2601",),
            ("strategy:test",),
            ("DAY",),
            frozenset({ApprovalAction.OPEN}),
            Decimal("2"),
            _at(),
            _at(10),
        ),
        EntityId.deterministic("approval_token", "manual-concurrent-token"),
        "user:owner",
        _at(10),
        _at(),
    )
    store = ManualTestApprovalStore(tmp_path / "manual-concurrent.json")
    store.request(approval)
    granted = store.decide(approval.approval_id, PlanApprovalStatus.GRANTED, _at(1)).approval

    def consume(basis_id: EntityId):
        return store.consume(
            granted.approval_id,
            _at(2),
            basis_id,
            plan_id=plan,
            plan_version=1,
            plan_hash=granted.plan_hash,
            account_id=account,
            instrument="SHFE_AG_2601",
            strategy="strategy:test",
            session="DAY",
            action=ApprovalAction.OPEN,
            quantity=Decimal("1"),
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                consume,
                [EntityId.deterministic("authorization_basis", f"manual-concurrent-{index}") for index in range(4)],
            )
        )
    assert sum(result.changed for result in results) == 1
    winner = next(result for result in results if result.changed)
    assert winner.approval.status is PlanApprovalStatus.CONSUMED
    assert winner.approval.consumer_basis_id is not None

    restarted = ManualTestApprovalStore(tmp_path / "manual-concurrent.json")
    losing_basis = EntityId.deterministic("authorization_basis", "manual-concurrent-loser")
    replay = restarted.consume(
        granted.approval_id,
        _at(2),
        losing_basis,
        plan_id=plan,
        plan_version=1,
        plan_hash=granted.plan_hash,
        account_id=account,
        instrument="SHFE_AG_2601",
        strategy="strategy:test",
        session="DAY",
        action=ApprovalAction.OPEN,
        quantity=Decimal("1"),
    )
    assert not replay.changed and replay.reason == "APPROVAL_ALREADY_CONSUMED"


@pytest.mark.parametrize("export_fails", [False, True])
def test_manual_test_cli_request_grant_consume_survives_process_boundaries(
    tmp_path, capsys, monkeypatch, export_fails
) -> None:
    account = EntityId.deterministic("simulation_account", "manual-cli-account")
    plan = EntityId.deterministic("trade_plan", "manual-cli-plan")
    plan_hash = canonical_sha256({"plan": "manual-cli"})
    state = str(tmp_path / "manual-cli.json")
    at = _at().to_dict()["recorded_at"]

    assert (
        main(
            [
                "manual-test",
                "request",
                "--state",
                state,
                "--plan-id",
                str(plan),
                "--plan-hash",
                plan_hash,
                "--account-id",
                str(account),
                "--strategy",
                "strategy:test",
                "--at",
                at,
            ]
        )
        == 0
    )
    requested = json.loads(capsys.readouterr().out)
    assert requested["status"] == "REQUESTED"

    assert (
        main(
            [
                "manual-test",
                "grant",
                "--state",
                state,
                "--approval-id",
                requested["approval_id"],
                "--at",
                _at(1).to_dict()["recorded_at"],
            ]
        )
        == 0
    )
    granted = json.loads(capsys.readouterr().out)
    assert granted["status"] == "GRANTED"

    basis_id = EntityId.deterministic("authorization_basis", "manual-cli-basis")
    assert (
        main(
            [
                "manual-test",
                "consume",
                "--state",
                state,
                "--approval-id",
                requested["approval_id"],
                "--basis-id",
                str(basis_id),
                "--quantity",
                "1",
                "--strategy",
                "strategy:test",
                "--at",
                _at(2).to_dict()["recorded_at"],
            ]
        )
        == 0
    )
    consumed = json.loads(capsys.readouterr().out)
    assert consumed["status"] == "CONSUMED"
    assert consumed["changed"] is True

    # A fresh CLI invocation reading the same state cannot consume another
    # basis, even if the command uses a different identity.
    assert (
        main(
            [
                "manual-test",
                "consume",
                "--state",
                state,
                "--approval-id",
                requested["approval_id"],
                "--basis-id",
                str(EntityId.deterministic("authorization_basis", "manual-cli-loser")),
                "--quantity",
                "1",
                "--strategy",
                "strategy:test",
                "--at",
                _at(2).to_dict()["recorded_at"],
            ]
        )
        == 0
    )
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["reason"] == "APPROVAL_ALREADY_CONSUMED"

    from futures_agent_os import cli

    original_export = cli._export_shadow_report
    if export_fails:

        def fail_export(*args):
            raise OSError("injected export failure")

        monkeypatch.setattr(cli, "_export_shadow_report", fail_export)
    shadow_args = [
        "manual-test",
        "shadow",
        "--state",
        state,
        "--approval-id",
        requested["approval_id"],
        "--strategy",
        "strategy:test",
        "--entry-price",
        "100",
        "--stop-price",
        "95",
        "--exit-price",
        "94",
        "--at",
        _at(3).to_dict()["recorded_at"],
    ]
    if export_fails:
        with pytest.raises(OSError, match="injected export failure"):
            main(shadow_args)
        monkeypatch.setattr(cli, "_export_shadow_report", original_export)

        def never_run(*args, **kwargs):
            raise AssertionError("report recovery must not simulate another trade")

        monkeypatch.setattr(cli, "run_manual_shadow_episode", never_run)
        assert (
            main(
                [
                    "manual-test",
                    "report",
                    "--state",
                    state,
                    "--approval-id",
                    requested["approval_id"],
                ]
            )
            == 0
        )
        recovered = json.loads(capsys.readouterr().out)
        assert recovered["status"] == "REPORT_EXPORTED"
        assert recovered["report_hash"]
        from futures_agent_os.execution_simulation.manual_shadow import verify_manual_shadow_report

        verified = verify_manual_shadow_report(tmp_path / "manual-cli.shadow.json")
        assert verified["basis_id"] == str(basis_id)
        assert ManualTestApprovalStore(state).shadow_report(EntityId.parse(requested["approval_id"])) == verified
        with pytest.raises(ValueError, match="already been consumed"):
            # The claim is checked after the separate input-validation probe.
            main(shadow_args)
        return
    assert (
        main(
            [
                "manual-test",
                "shadow",
                "--state",
                state,
                "--approval-id",
                requested["approval_id"],
                "--strategy",
                "strategy:test",
                "--entry-price",
                "100",
                "--stop-price",
                "95",
                "--exit-price",
                "94",
                "--at",
                _at(3).to_dict()["recorded_at"],
            ]
        )
        == 0
    )
    shadow = json.loads(capsys.readouterr().out)
    assert shadow["execution_origin"] == "MANUAL_TEST"
    assert shadow["report_hash"]
    assert (tmp_path / "manual-cli.shadow.json").exists()
    from futures_agent_os.execution_simulation.manual_shadow import verify_manual_shadow_report

    verified = verify_manual_shadow_report(tmp_path / "manual-cli.shadow.json")
    assert verified["basis_id"] == str(basis_id)
    assert verified["plan_hash"] == plan_hash
    from futures_agent_os.execution_simulation.manual_shadow import replay_manual_shadow_report

    assert replay_manual_shadow_report(tmp_path / "manual-cli.shadow.json")["report_hash"] == shadow["report_hash"]


def test_manual_shadow_plan_runs_fill_protection_exit_and_settlement(tmp_path) -> None:
    """Exercise the no-LLM emergency path through accounting and protection."""
    account_id = EntityId.deterministic("simulation_account", "manual-e2e")
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    now = _at(3)
    order = Order(
        EntityId.deterministic("order", "manual-e2e"),
        EntityId.deterministic("execution_plan", "manual-e2e"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    fill = Fill(
        EntityId.deterministic("fill", "manual-e2e-open"),
        order.order_id,
        order.instrument,
        order.direction,
        Decimal("1"),
        Decimal("100"),
        Decimal("0"),
        now,
    )
    account.apply_fill(fill, lot_id=EntityId.deterministic("position_lot", str(fill.fill_id)), account_id=account_id)
    lot = account.state.lots[0]
    policy = StopPolicy(EntityId.deterministic("stop_policy", "manual-e2e"), lot.lot_id, Decimal("95"), Decimal("5"))
    request = ProtectionTriggerEvaluator().price_stop(lot, policy, Decimal("94"), now)
    assert request is not None
    validation = ProtectionValidator().validate(request, lot, policy, position_version=lot.version, now=now)
    assert validation.outcome is ValidationOutcome.VALIDATED
    action = ProtectionValidator().action(request, validation, now=now)
    assert action.target_quantity == Decimal("0")
    exit_fill = Fill(
        EntityId.deterministic("fill", "manual-e2e-close"),
        order.order_id,
        order.instrument,
        TradeDirection.SHORT,
        Decimal("1"),
        Decimal("94"),
        Decimal("0"),
        now,
    )
    account.close(exit_fill)
    settlement = account.mark_to_market(
        EntityId.deterministic("settlement", "manual-e2e"), "2026-09-05", Decimal("94"), now
    )
    account.settle(settlement)
    account.assert_conservation()
    assert account.state.lots == ()


def test_manual_shadow_runner_returns_complete_report() -> None:
    account_id = EntityId.deterministic("simulation_account", "manual-runner")
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    now = _at(3)
    order = Order(
        EntityId.deterministic("order", "manual-runner"),
        EntityId.deterministic("execution_plan", "manual-runner"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    probe = SimulationAccount(Decimal("1000"), account_id=account_id)
    probe_result = SimulationEngine().execute_l1(
        order, L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1")), probe, now=now
    )
    assert probe_result.fill is not None
    policy = StopPolicy(
        EntityId.deterministic("stop_policy", "manual-runner"),
        EntityId.deterministic("position_lot", str(probe_result.fill.fill_id)),
        Decimal("95"),
        Decimal("5"),
    )
    report = run_manual_shadow_episode(
        order,
        account,
        open_bar=L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1")),
        exit_bar=L1Bar(Decimal("94"), Decimal("95"), Decimal("93"), Decimal("94"), Decimal("1")),
        stop_policy=policy,
        now=now,
    )
    assert report.open_result.fill is not None and report.protective_action is not None and account.state.lots == ()


def test_manual_shadow_runner_does_not_fabricate_entry_without_liquidity() -> None:
    account_id = EntityId.deterministic("simulation_account", "manual-no-liquidity")
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    now = _at(3)
    order = Order(
        EntityId.deterministic("order", "manual-no-liquidity"),
        EntityId.deterministic("execution_plan", "manual-no-liquidity"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    policy = StopPolicy(
        EntityId.deterministic("stop_policy", "manual-no-liquidity"),
        EntityId.deterministic("position_lot", "never-created"),
        Decimal("95"),
        Decimal("5"),
    )
    report = run_manual_shadow_episode(
        order,
        account,
        open_bar=L1Bar(Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("0")),
        exit_bar=L1Bar(Decimal("94"), Decimal("94"), Decimal("94"), Decimal("94"), Decimal("1")),
        stop_policy=policy,
        now=now,
    )
    assert report.status == "NO_ENTRY_FILL" and report.open_result.fill is None and account.state.lots == ()


def test_consumed_approval_claims_shadow_once(tmp_path) -> None:
    # The durable store must prevent a second successful SHADOW side effect.
    approval_id = EntityId.deterministic("plan_approval", "shadow-once")
    account = EntityId.deterministic("simulation_account", "shadow-once")
    plan = EntityId.deterministic("trade_plan", "shadow-once")
    approval = PlanApproval(
        approval_id,
        1,
        PlanApprovalStatus.CONSUMED,
        plan,
        1,
        canonical_sha256({"p": 1}),
        account,
        ApprovalScope(
            account,
            ("SHFE_AG_2601",),
            ("strategy:test",),
            ("DAY",),
            frozenset({ApprovalAction.OPEN}),
            Decimal("1"),
            _at(),
            _at(10),
        ),
        EntityId.deterministic("approval_token", "shadow-once"),
        "user:owner",
        _at(10),
        _at(),
        consumer_basis_id=EntityId.deterministic("authorization_basis", "shadow-once"),
        consumed_at=_at(1),
        decided_at=_at(1),
        decided_by="user:owner",
    )
    store = ManualTestApprovalStore(tmp_path / "shadow-once.json")
    store.request(
        replace(
            approval,
            status=PlanApprovalStatus.REQUESTED,
            consumer_basis_id=None,
            consumed_at=None,
            decided_at=None,
            decided_by=None,
        )
    )
    store.decide(approval_id, PlanApprovalStatus.GRANTED, _at(1))
    store.consume(
        approval_id,
        _at(2),
        approval.consumer_basis_id,
        plan_id=plan,
        plan_version=1,
        plan_hash=approval.plan_hash,
        account_id=account,
        instrument="SHFE_AG_2601",
        strategy="strategy:test",
        session="DAY",
        action=ApprovalAction.OPEN,
        quantity=Decimal("1"),
    )
    assert store.claim_shadow(approval_id, _at(3)) is True
    assert store.claim_shadow(approval_id, _at(4)) is False
    report = {
        "approval_id": str(approval_id),
        "basis_id": str(approval.consumer_basis_id),
        "plan_id": str(plan),
        "plan_version": 1,
        "plan_hash": approval.plan_hash,
        "execution_origin": "MANUAL_TEST",
    }
    report["report_hash"] = canonical_sha256(report)
    with pytest.raises(ValueError, match="binding mismatch"):
        store.complete_shadow(approval_id, _at(5), report={**report, "plan_hash": "wrong"})
    assert store.complete_shadow(approval_id, _at(5), report=report) is True
    assert store.complete_shadow(approval_id, _at(6), report=report) is False
    assert ManualTestApprovalStore(tmp_path / "shadow-once.json").shadow_report(approval_id) == report
    state = json.loads((tmp_path / "shadow-once.json").read_text(encoding="utf-8"))
    state[str(approval_id)]["shadow_report"]["cash"] = "999"
    (tmp_path / "shadow-once.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        ManualTestApprovalStore(tmp_path / "shadow-once.json").shadow_report(approval_id)
