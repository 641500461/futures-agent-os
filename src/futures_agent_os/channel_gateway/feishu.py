"""Feishu channel adapter using the official ``lark-oapi`` SDK.

The adapter translates SDK callbacks into channel-neutral contracts. It does
not persist business state and never calls an order, risk, or ledger API.
Fixture dictionaries are supported for deterministic local tests; production
long-polling is provided by :class:`FeishuAdapter.start`.
"""

from __future__ import annotations

import json
import hashlib
import queue
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from .contracts import ControlCallback, InboundEvent, OutboundNotification


def _value(obj: object, name: str, default: object = None) -> object:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _first(*values: object, default: str = "") -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value)
    return default


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError("invalid callback expiry")


class FeishuAdapter:
    """Replaceable Feishu adapter with SDK long-connection support."""

    channel = "feishu"

    def __repr__(self) -> str:
        return f"FeishuAdapter(channel='feishu', app_id={self.app_id!r}, sdk_started={self._sdk_client is not None})"

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        *,
        verification_token: str = "",
        encrypt_key: str = "",
        domain: str | None = None,
        fixture_mode: bool | None = None,
    ) -> None:
        self.app_id = app_id
        self._app_secret = app_secret
        self.verification_token = verification_token
        self.encrypt_key = encrypt_key
        self.domain = domain
        self.fixture_mode = fixture_mode if fixture_mode is not None else app_id is None and app_secret is None
        self._inbox: queue.Queue[InboundEvent] = queue.Queue()
        self._callbacks: queue.Queue[ControlCallback] = queue.Queue()
        self._sdk_client: Any = None
        self._ws_client: Any = None
        self._event_sink: Callable[[InboundEvent], object] | None = None
        self._control_sink: Callable[[ControlCallback], object] | None = None
        self.outbox: list[OutboundNotification] = []

    def bind_sinks(
        self,
        *,
        event_sink: Callable[[InboundEvent], object],
        control_sink: Callable[[ControlCallback], object] | None = None,
    ) -> None:
        """Bind durable application handlers used before SDK callback ACK.

        The production websocket callback persists synchronously. The local
        queues remain available only when no sink is bound (fixture mode).
        """

        self._event_sink = event_sink
        self._control_sink = control_sink

    def parse_event(self, payload: Mapping[str, Any]) -> InboundEvent:
        """Parse a real-shaped event envelope or the compact test fixture."""

        event = payload.get("event", payload)
        message = event.get("message", event) if isinstance(event, Mapping) else event
        sender = event.get("sender", {}) if isinstance(event, Mapping) else {}
        sender_id = sender.get("sender_id", sender) if isinstance(sender, Mapping) else sender
        header = payload.get("header", {})
        event_id = _first(
            payload.get("event_id"),
            header.get("event_id") if isinstance(header, Mapping) else None,
            _value(message, "message_id"),
        )
        if not event_id:
            raise ValueError("Feishu message event is missing event id")
        actor_id = _first(
            payload.get("actor_id"),
            _value(sender_id, "open_id"),
            _value(sender_id, "user_id"),
            _value(sender_id, "union_id"),
        )
        conversation_id = _first(
            payload.get("conversation_id"), _value(message, "chat_id"), _value(message, "conversation_id")
        )
        if not actor_id or not conversation_id:
            raise ValueError("Feishu message event is missing actor or conversation")
        occurred = payload.get("occurred_at")
        if isinstance(occurred, datetime):
            when = occurred
        else:
            raw_time = _value(message, "create_time")
            when = datetime.fromtimestamp(int(str(raw_time)) / 1000, UTC) if raw_time else datetime.now(UTC)
        data = payload.get("data")
        if data is None:
            data = {
                "message_id": _value(message, "message_id"),
                "chat_type": _value(message, "chat_type"),
                "message_type": _value(message, "message_type"),
                "content": _value(message, "content"),
            }
        return InboundEvent(
            self.channel,
            event_id,
            actor_id,
            conversation_id,
            str(payload.get("kind", "message")),
            dict(data) if isinstance(data, Mapping) else {"content": data},
            when,
        )

    def parse_sdk_event(self, event: object) -> InboundEvent:
        header = _value(event, "header", {})
        body = _value(event, "event", {})
        message = _value(body, "message", {})
        sender = _value(body, "sender", {})
        sender_id = _value(sender, "sender_id", {})
        payload: dict[str, Any] = {
            "event_id": _first(_value(header, "event_id"), _value(message, "message_id")),
            "actor_id": _first(
                _value(sender_id, "open_id"), _value(sender_id, "user_id"), _value(sender_id, "union_id")
            ),
            "conversation_id": _first(_value(message, "chat_id")),
            "kind": "message",
            "data": {
                "message_id": _value(message, "message_id"),
                "chat_type": _value(message, "chat_type"),
                "message_type": _value(message, "message_type"),
                "content": _value(message, "content"),
            },
        }
        create_time = _value(message, "create_time")
        if create_time:
            payload["occurred_at"] = datetime.fromtimestamp(int(str(create_time)) / 1000, UTC)
        return self.parse_event(payload)

    def receive(self) -> list[InboundEvent]:
        events: list[InboundEvent] = []
        while True:
            try:
                events.append(self._inbox.get_nowait())
            except queue.Empty:
                return events

    def receive_callbacks(self) -> list[ControlCallback]:
        callbacks: list[ControlCallback] = []
        while True:
            try:
                callbacks.append(self._callbacks.get_nowait())
            except queue.Empty:
                return callbacks

    def enqueue(self, payload: Mapping[str, Any]) -> InboundEvent:
        event = self.parse_event(payload)
        self._inbox.put(event)
        return event

    def parse_callback(self, payload: Mapping[str, Any]) -> ControlCallback:
        action_data = payload.get("action", payload.get("data", {}))
        action = (
            action_data.get("action", action_data.get("value", "")) if isinstance(action_data, Mapping) else action_data
        )
        if isinstance(action, Mapping):
            action = action.get("action", action.get("name", ""))
        return ControlCallback(
            self.channel,
            _first(payload.get("callback_id"), payload.get("token")),
            _first(payload.get("actor_id"), payload.get("operator_id")),
            str(action),
            dict(payload.get("data", {})) if isinstance(payload.get("data", {}), Mapping) else {},
            target_id=payload.get("target_id"),
            target_version=int(payload["target_version"]) if payload.get("target_version") is not None else None,
            target_sha256=payload.get("target_sha256"),
            expires_at=_timestamp(payload.get("expires_at")),
            token=payload.get("token"),
        )

    def parse_sdk_callback(self, event: object) -> ControlCallback:
        body = _value(event, "event", {})
        operator = _value(body, "operator", {})
        action = _value(body, "action", {})
        value = _value(action, "value", {})
        payload = dict(value) if isinstance(value, Mapping) else {}
        callback_id = _first(payload.get("callback_id"), _value(body, "token"), default="")
        callback_token = _first(payload.get("control_token"), payload.get("token"), _value(body, "token")) or None
        return ControlCallback(
            self.channel,
            callback_id,
            _first(_value(operator, "open_id"), _value(operator, "user_id"), _value(operator, "union_id")),
            _first(payload.get("action"), _value(action, "option")),
            payload,
            target_id=payload.get("target_id"),
            target_version=int(payload["target_version"]) if payload.get("target_version") is not None else None,
            target_sha256=payload.get("target_sha256"),
            expires_at=_timestamp(payload.get("expires_at")),
            token=callback_token,
        )

    def send(self, notification: OutboundNotification) -> None:
        if notification.channel != self.channel:
            raise ValueError("wrong channel")
        if self._sdk_client is None:
            if self.fixture_mode:
                self.outbox.append(notification)
                return
            raise RuntimeError("Feishu SDK client is not started")
        from lark_oapi.api.im.v1 import (  # type: ignore[import-untyped]
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        msg_type = "interactive" if notification.payload is not None else "text"
        content = notification.payload if notification.payload is not None else {"text": notification.text}
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(notification.conversation_id)
            .msg_type(msg_type)
            .content(json.dumps(content, ensure_ascii=False))
            .uuid(hashlib.sha256(notification.delivery_key.encode("utf-8")).hexdigest())
            .build()
        )
        request = CreateMessageRequest.builder().receive_id_type("chat_id").request_body(body).build()
        response = self._sdk_client.im.v1.message.create(request)
        if hasattr(response, "success") and not response.success():
            raise RuntimeError("Feishu message delivery failed")

    def capabilities(self) -> frozenset[str]:
        return frozenset({"notify", "explain", "pause", "resume", "revoke", "kill_switch"})

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities()

    def _on_sdk_message(self, event: object) -> None:
        inbound = self.parse_sdk_event(event)
        if self._event_sink is not None:
            self._event_sink(inbound)
            return
        self._inbox.put(inbound)

    def _on_sdk_callback(self, event: object) -> object:
        callback = self.parse_sdk_callback(event)
        if self._control_sink is not None:
            self._control_sink(callback)
        else:
            self._callbacks.put(callback)
        from lark_oapi.event.callback.model.p2_card_action_trigger import (  # type: ignore[import-untyped]
            P2CardActionTriggerResponse,
        )

        return P2CardActionTriggerResponse()

    def start(self) -> None:
        """Start the official SDK websocket client (blocking)."""

        if not self.app_id or not self._app_secret:
            raise ValueError("Feishu app_id and app_secret are required for long connection")
        from lark_oapi import EventDispatcherHandler, LogLevel, ws  # type: ignore[import-untyped]

        dispatcher = (
            EventDispatcherHandler.builder(self.encrypt_key, self.verification_token, LogLevel.ERROR)
            .register_p2_im_message_receive_v1(self._on_sdk_message)
            .register_p2_card_action_trigger(self._on_sdk_callback)
            .build()
        )
        kwargs: dict[str, Any] = {"log_level": LogLevel.ERROR, "event_handler": dispatcher, "auto_reconnect": True}
        if self.domain:
            kwargs["domain"] = self.domain
        self._ws_client = ws.Client(self.app_id, self._app_secret, **kwargs)
        from lark_oapi import Client

        builder = Client.builder().app_id(self.app_id).app_secret(self._app_secret)
        if self.domain:
            builder = builder.domain(self.domain)
        self._sdk_client = builder.build()
        self._ws_client.start()

    def stop(self) -> None:
        client = self._ws_client
        if client is not None and hasattr(client, "stop"):
            client.stop()
        self._ws_client = None


class FeishuLongConnectionAdapter(FeishuAdapter):
    """Explicit production name for the websocket-backed adapter."""

    pass


__all__ = ["FeishuAdapter", "FeishuLongConnectionAdapter"]
