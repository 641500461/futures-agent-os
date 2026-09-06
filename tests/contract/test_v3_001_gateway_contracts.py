from datetime import datetime, timezone
import pytest
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


from futures_agent_os.channel_gateway.gateway import ChannelGateway


def test_gateway_composes_idempotent_boundaries():
    g = ChannelGateway()
    a = FeishuAdapter()
    e = a.parse_event({"event_id": "e", "actor_id": "u", "conversation_id": "c"})
    assert g.ingest(e) and not g.ingest(e)
    n = OutboundNotification("feishu", "c", "INFO", "x", "k")
    assert g.notify(a, n) and not g.notify(a, n)


from futures_agent_os.agent_orchestration.v3_durable import *


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
