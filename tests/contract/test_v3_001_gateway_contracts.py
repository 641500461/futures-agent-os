from datetime import datetime, timezone
import pytest

# ruff: noqa: E402
from futures_agent_os.channel_gateway.contracts import InboundEvent, IdempotentInbox


def event(payload={"x": 1}):
    return InboundEvent("feishu", "e1", "u1", "c1", "message", payload, datetime.now(timezone.utc))


def test_duplicate_is_idempotent():
    inbox = IdempotentInbox()
    e = event()
    assert inbox.ingest(e) is True
    assert inbox.ingest(e) is False


def test_same_id_conflicting_payload_fails_closed():
    inbox = IdempotentInbox()
    inbox.ingest(event())
    with pytest.raises(ValueError):
        inbox.ingest(event({"x": 2}))


def test_channel_namespaces_event_ids():
    inbox = IdempotentInbox()
    a = event()
    b = InboundEvent("other", "e1", "u1", "c1", "message", {}, a.occurred_at)
    assert inbox.ingest(a) and inbox.ingest(b)


from futures_agent_os.channel_gateway.contracts import (
    ControlCallback,
    IdempotentControls,
    NotificationDispatcher,
    OutboundNotification,
)


class Adapter:
    channel = "feishu"

    def __init__(self):
        self.sent = []

    def send(self, n):
        self.sent.append(n)


def test_control_callback_replay_and_notification_dedup():
    c = ControlCallback("feishu", "cb1", "u", "PAUSE", {})
    controls = IdempotentControls()
    assert controls.accept(c) is True
    assert controls.accept(c) is False
    a = Adapter()
    d = NotificationDispatcher()
    n = OutboundNotification("feishu", "g", "INFO", "ok", "n1")
    assert d.dispatch(a, n) is True
    assert d.dispatch(a, n) is False
    assert len(a.sent) == 1


from futures_agent_os.channel_gateway.feishu import FeishuAdapter


def test_feishu_is_protocol_translation_adapter():
    a = FeishuAdapter()
    e = a.parse_event({"event_id": "x", "actor_id": "u", "conversation_id": "g", "data": {"text": "hi"}})
    assert e.channel == "feishu" and e.payload["text"] == "hi"
    c = a.parse_callback({"callback_id": "c", "actor_id": "u", "action": "pause"})
    assert c.action == "pause" and "kill_switch" in a.capabilities()


def test_feishu_control_translation_preserves_version_hash_and_expiry():
    expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    digest = "a" * 64
    callback = FeishuAdapter().parse_callback(
        {
            "callback_id": "control-1",
            "actor_id": "operator-1",
            "action": "pause",
            "target_id": "mandate-1",
            "target_version": 7,
            "target_sha256": digest,
            "expires_at": expiry.isoformat(),
            "token": "secret",
        }
    )
    assert callback.target_version == 7
    assert callback.target_sha256 == digest
    assert callback.expires_at == expiry


def test_adapter_capability_rejection_is_explicit():
    class ReadOnlyAdapter(Adapter):
        channel = "readonly"

        def capabilities(self):
            return frozenset({"explain"})

    with pytest.raises(NotImplementedError):
        NotificationDispatcher().dispatch(
            ReadOnlyAdapter(), OutboundNotification("readonly", "c", "INFO", "text", "key")
        )


def test_feishu_sdk_callback_invokes_durable_sink_before_return():
    adapter = FeishuAdapter()
    persisted = []
    adapter.bind_sinks(event_sink=persisted.append)
    adapter._on_sdk_message(
        {
            "header": {"event_id": "sdk-event"},
            "event": {
                "sender": {"sender_id": {"open_id": "operator"}},
                "message": {"message_id": "message", "chat_id": "chat", "create_time": "1000"},
            },
        }
    )
    assert [item.event_id for item in persisted] == ["sdk-event"]
    assert adapter.receive() == []


from futures_agent_os.channel_gateway.gateway import ChannelGateway


def test_gateway_composes_idempotent_boundaries():
    g = ChannelGateway()
    a = FeishuAdapter()
    e = a.parse_event({"event_id": "e", "actor_id": "u", "conversation_id": "c"})
    assert g.ingest(e) and not g.ingest(e)
    n = OutboundNotification("feishu", "c", "INFO", "x", "k")
    assert g.notify(a, n) and not g.notify(a, n)


from futures_agent_os.agent_orchestration.v3_durable import Checkpoint, DurableState, DurableOrchestrator, advance


def test_v3_durable_checkpoint_recovers_only_matching_inputs():
    o = DurableOrchestrator()
    s = DurableState("r", Checkpoint.PLAN, "p", "s")
    o.save(s)
    assert o.recover("r", plan_hash="p", snapshot_hash="s") == s
    with pytest.raises(ValueError):
        o.recover("r", plan_hash="old", snapshot_hash="s")


def test_checkpoint_transitions_are_ordered():
    s = DurableState("r", Checkpoint.SNAPSHOT, "p", "s")
    assert advance(s, Checkpoint.SCAN).checkpoint is Checkpoint.SCAN
    with pytest.raises(ValueError):
        advance(s, Checkpoint.PLAN)


def test_orchestrator_start_and_advance():
    o = DurableOrchestrator()
    assert o.start("x", "p", "s").checkpoint is Checkpoint.SNAPSHOT
    assert o.advance("x", Checkpoint.SCAN).checkpoint is Checkpoint.SCAN


from futures_agent_os.channel_gateway.registry import ChannelRegistry


def test_channel_registry_is_replaceable():
    r = ChannelRegistry()
    a = FeishuAdapter()
    r.register(a)
    assert r.get("feishu") is a
    with pytest.raises(ValueError):
        r.register(a)


def test_trigger_is_idempotent():
    o = DurableOrchestrator()
    a = o.trigger("r", "p", "s")
    b = o.trigger("r", "p", "s")
    assert a == b


from futures_agent_os.agent_orchestration.strategy_agent import StrategyAgent, StrategyCandidate


def test_strategy_agent_outputs_candidate_without_order():
    c = StrategyAgent().propose(thesis="t", invalidation="i", evidence=("e",), target_risk="r", exit_intent="x")
    assert isinstance(c, StrategyCandidate) and not hasattr(c, "order")


from decimal import Decimal
from futures_agent_os.agent_orchestration.portfolio_agent import PortfolioAgent, PortfolioProposal


def test_portfolio_agent_outputs_proposal():
    p = PortfolioAgent().propose(target_exposure=Decimal("1.0"), rationale="r")
    assert isinstance(p, PortfolioProposal)


from futures_agent_os.agent_orchestration.risk_analyst_agent import RiskAnalystAgent, RiskAssessment


def test_risk_analyst_is_non_authoritative():
    a = RiskAnalystAgent().assess(scenarios=("stress",), counter_evidence=("ce",), proposed_loss=Decimal("10"))
    assert isinstance(a, RiskAssessment) and not hasattr(a, "risk_decision")


from futures_agent_os.agent_orchestration.execution_advisor import ExecutionAdvisor, ExecutionRecommendation


def test_execution_advisor_only_recommends_registered_algorithms():
    assert isinstance(ExecutionAdvisor().recommend(algorithm="MARKET", rationale="cost"), ExecutionRecommendation)
    with pytest.raises(ValueError):
        ExecutionAdvisor().recommend(algorithm="TWAP", rationale="x")


from futures_agent_os.agent_orchestration.pre_trade_critic import PreTradeCritic, PreTradeCritique


def test_pre_trade_critic_is_distinct_structured_role():
    c = PreTradeCritic().review(concerns=("cost",), verdict="DEFER")
    assert isinstance(c, PreTradeCritique)


from futures_agent_os.agent_orchestration.v3_parallel import ParallelFanout


def test_parallel_fanout_returns_named_results():
    assert ParallelFanout().run({"risk": lambda: "r", "critic": lambda: "c"}) == {"risk": "r", "critic": "c"}


from datetime import timedelta
from futures_agent_os.agent_orchestration.autonomy_mandate import SimulationAutonomyMandate, MandateStatus


def test_mandate_effective_requires_active_and_unexpired():
    m = SimulationAutonomyMandate(
        "m", "a", "scope", datetime.now(timezone.utc) + timedelta(hours=1), MandateStatus.ACTIVE
    )
    assert m.effective
