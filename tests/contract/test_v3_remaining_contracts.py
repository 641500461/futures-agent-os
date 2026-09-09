from datetime import datetime, timedelta, timezone

import pytest

from futures_agent_os.agent_orchestration import (
    AgentVersion,
    BoundedAutonomyCycle,
    CycleBudget,
    CycleOutcome,
    DeterministicWatch,
    QualificationRegistry,
    RiskReductionRequest,
    WatchEvent,
    WatchCoordinator,
    WatchTrigger,
    AutonomyGateReceipt,
    AutonomyGoldenCycle,
    DecisionJournalAppender,
    DeterministicProtectionWatchOwner,
)
from futures_agent_os.learning_review import (
    DecisionJournal,
    PostTradeReviewer,
    ReviewQuality,
    SourceEvent,
    TradeEpisode,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt
from futures_agent_os.decision import PositionLot, StopPolicy, TradeDirection
from futures_agent_os.execution_simulation import ProtectionTriggerKind, ProtectionValidator, ValidationOutcome
from decimal import Decimal
from futures_agent_os.agent_orchestration.autonomy_gate import GateOutcome
from futures_agent_os.channel_gateway.supervision import SupervisionCard


def test_registry_requires_qualification_before_activation():
    registry = QualificationRegistry()
    registry.register(AgentVersion("strategy", "1", "p", "m", "t"))
    with pytest.raises(ValueError):
        registry.activate("strategy", "1")
    registry.qualify("strategy", "1", metrics={"schema": 1}, thresholds={"schema": 1})
    with pytest.raises(PermissionError):
        registry.activate("strategy", "1", actor="agent:strategy")
    assert registry.activate("strategy", "1").status.value == "ACTIVE"
    assert registry.events == (
        "REGISTER:strategy:1:baseline:unspecified",
        "QUALIFY:strategy:1:QUALIFIED",
        "ACTIVATE:strategy:1:user:operator",
    )
    with pytest.raises(AttributeError):
        registry.events.append("tamper")  # type: ignore[attr-defined]
    restored = QualificationRegistry.from_snapshot(registry.snapshot(), registry.events)
    assert restored.snapshot() == registry.snapshot()
    assert restored.events == registry.events


def test_registry_rejects_missing_or_non_finite_qualification_metrics():
    registry = QualificationRegistry()
    registry.register(AgentVersion("risk", "1", "prompt:1", "model:1", "tools:1", "baseline:risk:1"))
    with pytest.raises(ValueError):
        registry.qualify("risk", "1", metrics={}, thresholds={"accuracy": 0.9})
    with pytest.raises(ValueError):
        registry.qualify("risk", "1", metrics={"accuracy": float("nan")}, thresholds={"accuracy": 0.9})
    assert registry.events == ("REGISTER:risk:1:baseline:risk:1",)


def test_watch_deduplicates_and_only_emits_injected_reduction_request():
    calls = []

    def owner(event):
        calls.append(event.event_id)
        return RiskReductionRequest("r", "p", 3, "0", "stop", "idem")

    watch = DeterministicWatch(owner)
    event = WatchEvent("e", WatchTrigger.POSITION, datetime.now(timezone.utc), "snapshot:1")
    assert watch.process(event) is not None and watch.process(event) is None
    assert calls == ["e"]


def test_watch_enforces_cooldown_backpressure_and_typed_owner_output():
    calls = []

    def owner(event):
        calls.append(event.event_id)
        return RiskReductionRequest("r", "p", 3, "0", "stop", event.event_id)

    watch = DeterministicWatch(owner, max_inflight=1, cooldown_seconds=60)
    first = WatchEvent("e1", WatchTrigger.POSITION, datetime(2026, 1, 1, tzinfo=timezone.utc), "position:p")
    second = WatchEvent("e2", WatchTrigger.POSITION, datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc), "position:p")
    assert watch.process(first) is not None
    assert watch.process(second) is None
    assert calls == ["e1"]


def test_watch_coordinator_isolates_domains_and_degrades_missing_or_failed_owner():
    calls: list[str] = []
    coordinator = WatchCoordinator()
    coordinator.register(WatchTrigger.MARKET, lambda event: calls.append(event.event_id) or None)
    coordinator.register(WatchTrigger.POSITION, lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    event = WatchEvent("market-1", WatchTrigger.MARKET, datetime.now(timezone.utc), "market:1")
    assert coordinator.process(event) is None
    assert coordinator.process(WatchEvent("unknown", WatchTrigger.ORDER, datetime.now(timezone.utc), "order:1")) is None
    assert (
        coordinator.process(WatchEvent("position-1", WatchTrigger.POSITION, datetime.now(timezone.utc), "position:1"))
        is None
    )
    assert calls == ["market-1"]
    assert WatchTrigger.POSITION in coordinator.degraded_triggers


def test_watch_retry_reuses_event_and_recovers_transient_owner_failure():
    attempts = 0

    def owner(event):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("temporary")
        return RiskReductionRequest("r", "p", 1, "0", "retry", "idem")

    watch = DeterministicWatch(owner)
    event = WatchEvent("retry-1", WatchTrigger.ORDER, datetime.now(timezone.utc), "order:1")
    assert watch.process_with_retry(event, max_attempts=2) is not None
    assert attempts == 2
    assert watch.process(event) is None


def test_deterministic_protection_owner_survives_agent_and_channel_outage():
    now = RecordedAt.from_datetime(datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc))
    position = EntityId.deterministic("position_lot", "v3-015-fallback")
    lot = PositionLot(
        position,
        EntityId.deterministic("simulation_account", "v3-015-fallback"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        now,
    )
    policy = StopPolicy(EntityId.deterministic("stop_policy", "v3-015-fallback"), position, Decimal("95"), Decimal("5"))
    owner = DeterministicProtectionWatchOwner(
        lambda ref: (lot, policy, now, {"trigger": ProtectionTriggerKind.KILL_SWITCH})
    )
    request = owner(
        WatchEvent("kill-1", WatchTrigger.SYSTEM, datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc), "facts:1")
    )
    assert request is not None
    assert request.trigger is ProtectionTriggerKind.KILL_SWITCH
    assert request.position_id == position


def test_default_coordinator_registers_all_five_domains_on_deterministic_owner():
    now = RecordedAt.from_datetime(datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc))
    position = EntityId.deterministic("position_lot", "v3-015-all-domains")
    lot = PositionLot(
        position,
        EntityId.deterministic("simulation_account", "v3-015-all-domains"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        now,
    )
    coordinator = WatchCoordinator.with_deterministic_protection(lambda ref: (lot, None, now, {}), max_inflight=2)
    for index, trigger in enumerate(WatchTrigger):
        request = coordinator.process(
            WatchEvent(f"domain-{index}", trigger, datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc), f"facts:{index}")
        )
        assert request is not None and request.trigger is ProtectionTriggerKind.KILL_SWITCH


def test_agent_thesis_watch_degrades_to_position_protection_on_worker_outage():
    now = RecordedAt.from_datetime(datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc))
    position = EntityId.deterministic("position_lot", "v3-015-agent-fallback")
    lot = PositionLot(
        position,
        EntityId.deterministic("simulation_account", "v3-015-agent-fallback"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        now,
    )
    coordinator = WatchCoordinator.with_deterministic_protection(
        lambda ref: (lot, None, now, {}),
        agent_thesis_owner=lambda event: (_ for _ in ()).throw(ConnectionError("LLM offline")),
    )
    request = coordinator.process(
        WatchEvent(
            "agent-offline", WatchTrigger.POSITION, datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc), "facts:agent"
        )
    )
    assert request is not None and request.trigger is ProtectionTriggerKind.KILL_SWITCH
    assert not coordinator.degraded_triggers


def test_watch_request_crosses_execution_t4_safe_before_action():
    now = RecordedAt.from_datetime(datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc))
    position = EntityId.deterministic("position_lot", "v3-015-t4-safe")
    lot = PositionLot(
        position,
        EntityId.deterministic("simulation_account", "v3-015-t4-safe"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        now,
    )
    policy = StopPolicy(EntityId.deterministic("stop_policy", "v3-015-t4-safe"), position, Decimal("95"), Decimal("5"))
    request = DeterministicProtectionWatchOwner(
        lambda ref: (lot, policy, now, {"trigger": ProtectionTriggerKind.KILL_SWITCH})
    )(WatchEvent("t4-safe", WatchTrigger.POSITION, datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc), "facts:t4"))
    assert request is not None
    validation = ProtectionValidator().validate(request, lot, policy, position_version=1, now=now)
    assert validation.outcome is ValidationOutcome.VALIDATED
    action = ProtectionValidator().action(request, validation, now=now)
    assert action.position_id == lot.lot_id


def test_bounded_cycle_and_reviewer_require_boundaries():
    cycle = BoundedAutonomyCycle(CycleBudget(max_steps=4))
    result = cycle.run(scan=lambda: "candidate", decide=lambda _: CycleOutcome.NO_TRADE)
    assert result.outcome is CycleOutcome.NO_TRADE
    reviewer = PostTradeReviewer()
    with pytest.raises(ValueError):
        reviewer.review(
            episode_id="e",
            closed=False,
            process_quality=ReviewQuality.GOOD,
            outcome_quality=ReviewQuality.GOOD,
            execution_quality=ReviewQuality.GOOD,
            evidence_refs=("decision:d1", "execution:x1", "accounting:a1"),
            findings=("f",),
        )
    review = reviewer.review(
        episode_id="e",
        closed=True,
        process_quality=ReviewQuality.GOOD,
        outcome_quality=ReviewQuality.MIXED,
        execution_quality=ReviewQuality.GOOD,
        evidence_refs=("decision:d1", "execution:x1", "accounting:a1"),
        findings=("f",),
    )
    assert reviewer.reflect(review=review, observation="observe").episode_id == "e"


def test_gate_receipt_is_single_use_and_bound_to_all_hashes():
    now = datetime.now(timezone.utc)
    receipt = AutonomyGateReceipt("r", "p", "ph", "bh", "mh", now, now + timedelta(minutes=1), GateOutcome.PERMIT)
    consumed = receipt.consume(plan_id="p", plan_hash="ph", basis_hash="bh", mode_hash="mh", now=now)
    assert consumed.consumed
    with pytest.raises(ValueError):
        consumed.consume(plan_id="p", plan_hash="ph", basis_hash="bh", mode_hash="mh", now=now)


def test_supervision_card_contains_only_fact_and_action_references():
    card = SupervisionCard("c", "risk", "RISK", ("risk:1",), ("pause:1",))
    notification = card.notification(channel="feishu", conversation_id="chat")
    assert "risk:1" in notification.text and "pause:1" in notification.text
    assert notification.payload is not None and notification.payload["card_id"] == "c"
    assert card.dedupe_key() == notification.idempotency_key == "c"
    assert card.content_digest == SupervisionCard("c", "risk", "RISK", ("risk:1",), ("pause:1",)).content_digest
    assert card.content_digest != SupervisionCard("c", "risk", "RISK", ("risk:2",), ("pause:1",)).content_digest
    with pytest.raises(ValueError):
        SupervisionCard("c2", "risk", "RISK", ())
    with pytest.raises(ValueError):
        SupervisionCard("c3", "risk", "INFO", ("unscoped",))
    with pytest.raises(ValueError):
        SupervisionCard("c4", "risk", "DEBUG", ("risk:1",))
    with pytest.raises(ValueError):
        SupervisionCard("c5", "risk", "RISK", ("risk:1",), ("pause",))
    with pytest.raises(ValueError):
        SupervisionCard("c6", "trade", "TRADE", ("trade:1",), ("pause:1",))
    lifecycle = SupervisionCard.trade_lifecycle(
        "lifecycle:1",
        severity="TRADE",
        mandate_ref="mandate:1",
        opportunity_ref="opportunity:1",
        plan_ref="plan:1",
        risk_ref="risk:1",
        execution_ref="execution:1",
        position_ref="position:1",
        protection_ref="protection:1",
        margin_ref="margin:1",
        worst_loss_ref="loss:1",
        review_ref="review:1",
    )
    assert len(lifecycle.fact_refs) == 10
    payload = lifecycle.render_payload()
    assert payload["card_id"] == "lifecycle:1"
    assert payload["content_digest"] == lifecycle.content_digest
    assert "mandate:1" in payload["elements"][0]["content"]


def test_golden_cycle_completes_without_user_callback():
    result = AutonomyGoldenCycle().run(
        snapshot=lambda: "snapshot",
        opportunity_scan=lambda _: "opportunity",
        strategy=lambda _: "draft",
        critic=lambda _: "pass",
        submit=lambda draft, critique: CycleOutcome.NO_TRADE,
    )
    assert result.outcome is CycleOutcome.NO_TRADE
    assert result.steps[-1] == "OWNER_SUBMIT"


def test_full_golden_cycle_runs_owner_mediated_simulation_and_review():
    calls: list[str] = []

    def mark(name: str, value: str):
        calls.append(name)
        return value

    result = AutonomyGoldenCycle().run_full(
        snapshot=lambda: mark("snapshot", "s"),
        opportunity_scan=lambda _: mark("scan", "o"),
        strategy=lambda _: mark("strategy", "d"),
        critic=lambda _: mark("critic", "c"),
        authorize=lambda _, __: mark("authorize", "b"),
        risk=lambda _, __: mark("risk", "r"),
        execute=lambda _: calls.append("execute") or CycleOutcome.TRADE,
        protect=lambda _: mark("protect", "p"),
        notify=lambda _: mark("notify", "n"),
        review=lambda _: mark("review", "v"),
    )
    assert result.outcome is CycleOutcome.TRADE
    assert result.steps[-1] == "POST_TRADE_REVIEW"
    assert calls == [
        "snapshot",
        "scan",
        "strategy",
        "critic",
        "authorize",
        "risk",
        "execute",
        "protect",
        "notify",
        "review",
    ]


def test_full_golden_cycle_appends_journal_and_defers_on_append_failure():
    journal: list[str] = []
    common = dict(
        snapshot=lambda: "s",
        opportunity_scan=lambda _: "o",
        strategy=lambda _: "d",
        critic=lambda _: "c",
        authorize=lambda _, __: "b",
        risk=lambda _, __: "r",
        execute=lambda _: CycleOutcome.NO_TRADE,
        protect=lambda _: "p",
        notify=lambda _: "n",
        review=lambda _: "v",
    )
    result = AutonomyGoldenCycle().run_full(**common, journal_append=lambda ref: journal.append(ref) is None)
    assert result.outcome is CycleOutcome.NO_TRADE
    assert journal == ["s", "o", "d", "c", "b", "r", "p", "n", "v"]
    failed = AutonomyGoldenCycle().run_full(**common, journal_append=lambda _: False)
    assert failed.outcome is CycleOutcome.DEFER and failed.reason == "journal append failed"


def test_decision_journal_appender_is_idempotent_and_deterministic():
    now = RecordedAt(datetime.now(timezone.utc))
    journal = DecisionJournal(EntityId.new("decision_journal"))
    appender = DecisionJournalAppender(journal, now=now, correlation_id=EntityId.new("cycle"))
    assert appender("risk:r1") and appender("risk:r1")
    assert len(journal.entries) == 1
    assert not appender("")


def test_post_trade_reviewer_requires_reconstructible_source_events() -> None:
    reviewer = PostTradeReviewer()
    with pytest.raises(ValueError, match="source events"):
        reviewer.review_episode(
            episode_id="e",
            closed=True,
            process_quality=ReviewQuality.GOOD,
            outcome_quality=ReviewQuality.MIXED,
            execution_quality=ReviewQuality.GOOD,
            source_event_refs=("decision:d1", "execution:x1"),
            findings=("ok",),
        )
    result = reviewer.review_episode(
        episode_id="e",
        closed=True,
        process_quality=ReviewQuality.GOOD,
        outcome_quality=ReviewQuality.MIXED,
        execution_quality=ReviewQuality.GOOD,
        source_event_refs=("decision:d1", "execution:x1", "accounting:a1"),
        findings=("ok",),
    )
    assert result.evidence_refs == ("decision:d1", "execution:x1", "accounting:a1")


def test_post_trade_reviewer_hydrates_only_matching_trade_episode_sources() -> None:
    now = RecordedAt(datetime.now(timezone.utc))
    correlation = EntityId.new("correlation")
    sources = tuple(
        SourceEvent(
            EntityId.new(kind),
            "owner",
            1,
            kind,
            now,
            now,
            "a" * 64,
            correlation,
        )
        for kind in ("decision", "execution", "accounting")
    )
    episode = TradeEpisode.rebuild(EntityId.new("trade_episode"), EntityId.new("decision_episode"), sources)
    review = PostTradeReviewer().review_trade_episode(
        episode=episode,
        sources=sources,
        closed=True,
        process_quality=ReviewQuality.GOOD,
        outcome_quality=ReviewQuality.MIXED,
        execution_quality=ReviewQuality.GOOD,
        findings=("f",),
    )
    assert review.episode_id == episode.episode_id.value.__str__()
    with pytest.raises(ValueError, match="closed"):
        PostTradeReviewer().review_trade_episode(
            episode=episode,
            sources=sources,
            closed=False,
            process_quality=ReviewQuality.GOOD,
            outcome_quality=ReviewQuality.GOOD,
            execution_quality=ReviewQuality.GOOD,
            findings=("f",),
        )
