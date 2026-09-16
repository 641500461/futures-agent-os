"""Owner boundary for the local simulation emergency controls.

The gateway validates and consumes the signed callback.  This small owner only
changes the local synthetic simulation gate; it never writes orders, positions,
ledgers, or risk truth.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from .contracts import ControlCallback


@dataclass(frozen=True, slots=True)
class LocalSimulationControlOwner:
    state_directory: Path
    target_id: str = "account:local-simulation"

    @property
    def state_path(self) -> Path:
        return self.state_directory / "control-state.json"

    def dispatch(self, callback: ControlCallback, _connection: Connection) -> object:
        if callback.target_id != self.target_id:
            raise PermissionError("control target is outside local simulation scope")
        current = self.state()
        if callback.action == "resume" and current in {"REVOKED", "KILL_SWITCH"}:
            raise PermissionError("revoked or kill-switched simulation requires a new owner binding")
        state = {
            "resume": "RUNNING",
            "revoke": "REVOKED",
            "kill_switch": "KILL_SWITCH",
            "pause": "PAUSED",
        }[callback.action]
        payload: dict[str, Any] = {
            "schema_version": "local-simulation-control.v1",
            "state": state,
            "action": callback.action,
            "callback_id": callback.callback_id,
            "actor_id": callback.actor_id,
            "target_id": callback.target_id,
            "target_version": callback.target_version,
            "target_sha256": callback.target_sha256,
            "expires_at": callback.expires_at.isoformat() if callback.expires_at else None,
        }
        self.state_directory.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)
        return payload

    def state(self) -> str:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError, json.JSONDecodeError, OSError:
            return "RUNNING"
        return str(value.get("state", "RUNNING")) if isinstance(value, dict) else "RUNNING"

    def permits_new_simulation(self) -> bool:
        return self.state() == "RUNNING"


__all__ = ["LocalSimulationControlOwner"]
