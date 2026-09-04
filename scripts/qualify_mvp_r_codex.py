"""Run the live ChatGPT-session Codex runner qualification probe.

This command never reads or prints authentication material. The official SDK
uses the existing local ChatGPT/Codex session and emits only runner metadata,
tool identities, event classes, and token usage.
"""

from __future__ import annotations

import json
from importlib.metadata import version
from typing import Mapping, cast

from futures_agent_os.adapters import OfficialCodexAppServerTransport
from futures_agent_os.research_experiment import frozen_mvp_tool_specs
from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256


def main() -> None:
    request_sha256 = "e" * 64
    specs = frozen_mvp_tool_specs(request_sha256)
    tools = tuple(
        {
            "type": "function",
            "name": spec.name,
            "description": spec.description,
            "inputSchema": json.loads(spec.parameters_json),
        }
        for spec in specs
    )
    response = OfficialCodexAppServerTransport()(
        {
            "model": "gpt-5.6-terra",
            "effort": "medium",
            "instructions": "Use only the supplied frozen research tools. Do not use built-in tools.",
            "input": ('Call market_query exactly once with the frozen request_sha256, then return {"status":"OK"}.'),
            "tools": tools,
            "timeout_seconds": 120,
            "output_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["status"],
                "properties": {"status": {"type": "string", "enum": ["OK"]}},
            },
        }
    )
    evidence = {
        "runner": "codex_app_server",
        "sdk_version": version("openai-codex"),
        "cli_version": version("openai-codex-cli-bin"),
        "requested_model": "gpt-5.6-terra",
        "requested_effort": "medium",
        "toolset_sha256": canonical_sha256(
            tuple(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters_json": spec.parameters_json,
                }
                for spec in specs
            )
        ),
        "registered_tools": tuple(spec.name for spec in specs),
        "response": _freeze_json(response),
    }
    print(canonical_json_text(evidence))


def _freeze_json(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) in {tuple, list}:
        return tuple(_freeze_json(item) for item in cast(tuple[object, ...] | list[object], value))
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("qualification evidence requires string-keyed JSON")
        return {cast(str, key): _freeze_json(item) for key, item in value.items()}
    raise TypeError("qualification evidence must be finite JSON")


if __name__ == "__main__":
    main()
