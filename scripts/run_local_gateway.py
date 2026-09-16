#!/usr/bin/env python3
"""Run the local research/simulation gateway under launchd.

The wrapper owns process-level concerns only: configuration loading, a
single-process state-directory lock, and signal-to-stop translation.  The
gateway itself remains a channel adapter and durable queue boundary; it does
not create or route real orders.
"""

from __future__ import annotations

import argparse
import fcntl
import signal
import sys
from pathlib import Path
from types import FrameType
from typing import Sequence

from futures_agent_os.channel_gateway.config import GatewayConfig
from futures_agent_os.channel_gateway.runtime import GatewayRuntime, GatewayRuntimeFailure


class GatewayAlreadyRunningError(RuntimeError):
    """The requested state directory is already owned by another process."""

    code = "GATEWAY_STATE_DIRECTORY_LOCKED"


class StateDirectoryLock:
    """Advisory single-process lock for one local gateway state directory."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self._handle = None

    def acquire(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        handle = (self.state_dir / ".gateway.lock").open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise GatewayAlreadyRunningError(GatewayAlreadyRunningError.code) from exc
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "StateDirectoryLock":
        self.acquire()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.release()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_local_gateway.py")
    parser.add_argument("--config", required=True, help="JSON or TOML gateway configuration")
    parser.add_argument("--state-dir", required=True, type=Path, help="local durable operator state directory")
    return parser


def _stable_error(code: str, error_type: str) -> None:
    print(f"LOCAL_GATEWAY_ERROR code={code} type={error_type}", file=sys.stderr)


def run_local_gateway(config_path: Path, state_dir: Path) -> int:
    try:
        config = GatewayConfig.from_file(config_path)
        config.validate()
    except Exception:
        _stable_error("GATEWAY_CONFIGURATION_INVALID", "GatewayConfigurationError")
        return 64

    try:
        with StateDirectoryLock(state_dir):
            runtime = GatewayRuntime(config, operator_state_directory=state_dir)

            def request_stop(_signum: int, _frame: FrameType | None) -> None:
                runtime.stop()

            previous_term = signal.signal(signal.SIGTERM, request_stop)
            previous_int = signal.signal(signal.SIGINT, request_stop)
            try:
                runtime.run()
            finally:
                signal.signal(signal.SIGTERM, previous_term)
                signal.signal(signal.SIGINT, previous_int)
    except GatewayAlreadyRunningError:
        _stable_error(GatewayAlreadyRunningError.code, "GatewayAlreadyRunningError")
        return 73
    except GatewayRuntimeFailure as exc:
        _stable_error(exc.code, "GatewayRuntimeFailure")
        return 70
    except Exception:
        # Startup/database/transport details are intentionally not propagated
        # through a launchd-facing process log.
        _stable_error("GATEWAY_RUNTIME_FAILED", "GatewayRuntimeError")
        return 70
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return run_local_gateway(arguments.config, arguments.state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
