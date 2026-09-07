"""Process entrypoint for the Feishu gateway runtime."""

from __future__ import annotations

import threading
from typing import Callable, Any

from sqlalchemy import create_engine

from .config import GatewayConfig
from .contracts import ControlCallback
from .feishu import FeishuLongConnectionAdapter
from .gateway import ChannelGateway
from .durable import OutboxWorker, PostgresGatewayStore


class GatewayRuntime:
    """Run SDK callbacks and durable inbox ingestion in separate loops."""

    def __init__(self, config: GatewayConfig, *, sleep_seconds: float = 0.05, control_handler: Any = None) -> None:
        config.validate()
        self.config = config
        self.adapter = FeishuLongConnectionAdapter(
            config.feishu_app_id,
            config.feishu_app_secret,
            verification_token=config.feishu_verification_token,
            encrypt_key=config.feishu_encrypt_key,
            domain=config.feishu_domain,
            fixture_mode=False,
        )
        self.store = PostgresGatewayStore(
            create_engine(config.database_url, pool_pre_ping=True),
            require_identity_mapping=config.require_identity_mapping,
        )
        self.gateway = ChannelGateway(self.store)
        self.control_handler = control_handler
        self.adapter.bind_sinks(
            event_sink=self.store.ingest,
            control_sink=self._dispatch_control if control_handler is not None else None,
        )
        self.outbox_worker = OutboxWorker(self.store, {self.adapter.channel: self.adapter}, "gateway-outbox")
        self.sleep_seconds = sleep_seconds
        self._stop = threading.Event()

    def run(self, *, on_event: Callable[[object], None] | None = None) -> None:
        sdk_thread = threading.Thread(target=self.adapter.start, name="feishu-sdk", daemon=True)
        sdk_thread.start()
        try:
            while not self._stop.is_set():
                self.process_once(on_event=on_event)
                self._stop.wait(self.sleep_seconds)
        finally:
            self.adapter.stop()
            sdk_thread.join(timeout=5)

    def stop(self) -> None:
        self._stop.set()

    def _dispatch_control(self, callback: ControlCallback) -> object:
        if self.control_handler is None:
            raise RuntimeError("control handler is not configured")
        return self.store.dispatch_control(callback, self.control_handler)

    def process_once(self, *, on_event: Callable[[object], None] | None = None) -> int:
        """Drain queued adapter payloads once; useful for workers and tests."""

        processed = 0
        for event in self.adapter.receive():
            result = self.store.ingest(event)
            if on_event is not None:
                on_event(result)
            processed += 1
        for callback in self.adapter.receive_callbacks():
            if self.control_handler is not None:
                self.store.dispatch_control(callback, self.control_handler)
            processed += 1
        self.store.recover_expired()
        processed += len(self.outbox_worker.run_once())
        return processed


__all__ = ["GatewayRuntime"]
