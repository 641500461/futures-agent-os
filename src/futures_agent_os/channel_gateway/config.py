"""Configuration for the channel gateway runtime."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    database_url: str
    feishu_app_id: str
    feishu_app_secret: str
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""
    feishu_domain: str | None = None
    require_identity_mapping: bool = True

    def __repr__(self) -> str:
        return (
            "GatewayConfig(database_url=<configured>, "
            f"feishu_app_id={self.feishu_app_id!r}, feishu_app_secret=<redacted>, "
            f"require_identity_mapping={self.require_identity_mapping!r})"
        )

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        return cls(
            database_url=os.environ.get("FAO_DATABASE_URL", ""),
            feishu_app_id=os.environ.get("FAO_FEISHU_APP_ID", ""),
            feishu_app_secret=os.environ.get("FAO_FEISHU_APP_SECRET", ""),
            feishu_verification_token=os.environ.get("FAO_FEISHU_VERIFICATION_TOKEN", ""),
            feishu_encrypt_key=os.environ.get("FAO_FEISHU_ENCRYPT_KEY", ""),
            feishu_domain=os.environ.get("FAO_FEISHU_DOMAIN") or None,
            require_identity_mapping=os.environ.get("FAO_REQUIRE_IDENTITY_MAPPING", "1").lower()
            not in {"0", "false", "no"},
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "GatewayConfig":
        config_path = Path(path)
        raw = config_path.read_bytes()
        data: Mapping[str, Any]
        if config_path.suffix.lower() == ".toml":
            data = tomllib.loads(raw.decode("utf-8"))
        elif config_path.suffix.lower() == ".json":
            value = json.loads(raw)
            if not isinstance(value, Mapping):
                raise ValueError("gateway config must be a JSON object")
            data = value
        else:
            raise ValueError("gateway config must be .toml or .json")
        # Environment variables are the preferred secret source. A config
        # file may provide non-secret defaults, but never gets printed.
        env = cls.from_env()
        return cls(
            database_url=str(data.get("database_url", env.database_url)),
            feishu_app_id=str(data.get("feishu_app_id", env.feishu_app_id)),
            feishu_app_secret=str(data.get("feishu_app_secret", env.feishu_app_secret)),
            feishu_verification_token=str(data.get("feishu_verification_token", env.feishu_verification_token)),
            feishu_encrypt_key=str(data.get("feishu_encrypt_key", env.feishu_encrypt_key)),
            feishu_domain=data.get("feishu_domain", env.feishu_domain),
            require_identity_mapping=bool(data.get("require_identity_mapping", env.require_identity_mapping)),
        )

    def validate(self) -> None:
        if not self.database_url.strip():
            raise ValueError("FAO_DATABASE_URL/database_url is required")
        if not self.feishu_app_id.strip() or not self.feishu_app_secret.strip():
            raise ValueError("Feishu app credentials are required")

    def public_summary(self) -> dict[str, object]:
        return {
            "database_configured": bool(self.database_url),
            "feishu_app_configured": bool(self.feishu_app_id),
            "identity_mapping_required": self.require_identity_mapping,
            "domain": self.feishu_domain,
        }


__all__ = ["GatewayConfig"]
