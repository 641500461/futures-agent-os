from __future__ import annotations

import importlib.util
import threading
from pathlib import Path

import pytest

from futures_agent_os.channel_gateway.config import GatewayConfig
from futures_agent_os.channel_gateway.runtime import GatewayRuntime, GatewayRuntimeFailure


def _load_wrapper():
    path = Path(__file__).parents[2] / "scripts" / "run_local_gateway.py"
    spec = importlib.util.spec_from_file_location("run_local_gateway", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeStore:
    def ingest(self, event: object) -> object:
        return event

    def recover_expired(self) -> None:
        return None

    def claim_outbox(self, _worker_id: str, *, limit: int = 10) -> list[object]:
        return []


class FakeAdapter:
    channel = "fake"

    def __init__(self, *, failure: BaseException | None = None, wait_for_stop: bool = False) -> None:
        self.failure = failure
        self.wait_for_stop = wait_for_stop
        self.started = threading.Event()
        self.stopped = threading.Event()

    def bind_sinks(self, *, event_sink: object, control_sink: object = None) -> None:
        return None

    def start(self) -> None:
        self.started.set()
        if self.failure is not None:
            raise self.failure
        if self.wait_for_stop:
            self.stopped.wait(2)

    def stop(self) -> None:
        self.stopped.set()

    def receive(self) -> list[object]:
        return []

    def receive_callbacks(self) -> list[object]:
        return []

    def send(self, notification: object) -> None:
        return None


def _config() -> GatewayConfig:
    return GatewayConfig(
        database_url="postgresql+psycopg://local/test",
        feishu_app_id="x",
        feishu_app_secret="x",
    )


def test_sdk_exception_causes_stable_runtime_failure_without_thread_output(capsys: pytest.CaptureFixture[str]) -> None:
    adapter = FakeAdapter(failure=RuntimeError("vendor failure detail"))
    runtime = GatewayRuntime(_config(), adapter=adapter, store=FakeStore(), sleep_seconds=0.001)

    with pytest.raises(GatewayRuntimeFailure) as failure:
        runtime.run()

    assert failure.value.code == "GATEWAY_SDK_UNEXPECTED_EXIT"
    assert adapter.stopped.is_set()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_sdk_normal_stop_is_not_a_failure() -> None:
    adapter = FakeAdapter(wait_for_stop=True)
    runtime = GatewayRuntime(_config(), adapter=adapter, store=FakeStore(), sleep_seconds=0.001)
    error: list[BaseException] = []

    def run() -> None:
        try:
            runtime.run()
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            error.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert adapter.started.wait(1)
    runtime.stop()
    thread.join(2)

    assert not thread.is_alive()
    assert error == []
    assert adapter.stopped.is_set()


def test_adapter_return_without_stop_is_unexpected_exit() -> None:
    adapter = FakeAdapter()
    runtime = GatewayRuntime(_config(), adapter=adapter, store=FakeStore(), sleep_seconds=0.001)

    with pytest.raises(GatewayRuntimeFailure):
        runtime.run()


def test_state_lock_rejects_duplicate_and_releases(tmp_path: Path) -> None:
    wrapper = _load_wrapper()
    first = wrapper.StateDirectoryLock(tmp_path)
    second = wrapper.StateDirectoryLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(wrapper.GatewayAlreadyRunningError):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_wrapper_rejects_invalid_config_with_stable_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wrapper = _load_wrapper()
    result = wrapper.run_local_gateway(tmp_path / "missing.toml", tmp_path / "state")

    assert result == 64
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "LOCAL_GATEWAY_ERROR code=GATEWAY_CONFIGURATION_INVALID type=GatewayConfigurationError\n"


def test_wrapper_releases_lock_after_runtime_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _load_wrapper()
    config_path = tmp_path / "gateway.json"
    config_path.write_text(
        '{"database_url":"postgresql+psycopg://local/test","feishu_app_id":"x","feishu_app_secret":"x"}',
        encoding="utf-8",
    )

    class FakeRuntime:
        def __init__(self, config: object, *, operator_state_directory: Path) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

        def run(self) -> None:
            return None

    monkeypatch.setattr(wrapper, "GatewayRuntime", FakeRuntime)
    assert wrapper.run_local_gateway(config_path, tmp_path / "state") == 0

    lock = wrapper.StateDirectoryLock(tmp_path / "state")
    lock.acquire()
    lock.release()
