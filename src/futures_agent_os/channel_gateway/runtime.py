"""Process entrypoint for the Feishu gateway runtime."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import create_engine

from .config import GatewayConfig
from .contracts import ControlCallback
from .feishu import FeishuLongConnectionAdapter
from .gateway import ChannelGateway
from .durable import OutboxWorker, PostgresGatewayStore
from .operator_commands import GatewayInboundWorker, LocalOperatorCommandHandler


class GatewayRuntimeFailure(RuntimeError):
    """Stable, credential-free failure raised when the SDK loop terminates."""

    code = "GATEWAY_SDK_UNEXPECTED_EXIT"

    def __init__(self) -> None:
        # Do not retain or expose the vendor exception.  SDK errors can include
        # request headers, app credentials, or other transport details.
        super().__init__(self.code)


class GatewayRuntime:
    """Run SDK callbacks and durable inbox ingestion in separate loops."""

    def __init__(
        self,
        config: GatewayConfig,
        *,
        sleep_seconds: float = 0.05,
        control_handler: Any = None,
        operator_state_directory: Path | None = None,
        adapter: Any | None = None,
        store: Any | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.adapter = (
            adapter
            if adapter is not None
            else FeishuLongConnectionAdapter(
                config.feishu_app_id,
                config.feishu_app_secret,
                verification_token=config.feishu_verification_token,
                encrypt_key=config.feishu_encrypt_key,
                domain=config.feishu_domain,
                fixture_mode=False,
            )
        )
        self.store = (
            store
            if store is not None
            else PostgresGatewayStore(
                create_engine(config.database_url, pool_pre_ping=True),
                require_identity_mapping=config.require_identity_mapping,
            )
        )
        self.gateway = ChannelGateway(self.store)
        self.control_handler = control_handler
        self.adapter.bind_sinks(
            event_sink=self.store.ingest,
            control_sink=self._dispatch_control if control_handler is not None else None,
        )
        self.outbox_worker = OutboxWorker(self.store, {self.adapter.channel: self.adapter}, "gateway-outbox")
        self.inbound_worker = (
            GatewayInboundWorker(self.store, LocalOperatorCommandHandler(operator_state_directory))
            if operator_state_directory is not None
            else None
        )
        self.sleep_seconds = sleep_seconds
        self._stop = threading.Event()
        self._adapter_done = threading.Event()
        self._adapter_failed = threading.Event()

    def run(self, *, on_event: Callable[[object], None] | None = None) -> None:
        def run_adapter() -> None:
            try:
                self.adapter.start()
            except BaseException:
                # Keep vendor exception details out of thread excepthooks and
                # logs.  The main loop observes only the stable failure state.
                self._adapter_failed.set()
            finally:
                self._adapter_done.set()

        self._adapter_done.clear()
        self._adapter_failed.clear()
        sdk_thread = threading.Thread(target=run_adapter, name="feishu-sdk", daemon=True)
        sdk_thread.start()
        try:
            while not self._stop.is_set():
                if self._adapter_done.is_set() and not self._stop.is_set():
                    raise GatewayRuntimeFailure()
                self.process_once(on_event=on_event)
                if self._stop.wait(self.sleep_seconds):
                    break
        finally:
            try:
                self.adapter.stop()
            except BaseException:
                # Stop is best effort.  A normal shutdown must not become a
                # failure merely because the SDK already closed its socket.
                pass
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
        if self.inbound_worker is not None:
            processed += self.inbound_worker.run_once()
        processed += len(self.outbox_worker.run_once())
        return processed


__all__ = ["GatewayRuntime", "GatewayRuntimeFailure"]
