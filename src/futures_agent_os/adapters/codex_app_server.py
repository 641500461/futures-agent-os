"""ChatGPT-session Codex App Server adapter for bounded MVP-R turns.

Each provider invocation uses an ephemeral thread in an empty read-only
directory. Codex dynamic tools are used only to capture one typed request; the
deterministic SerialResearchLoop executes that request after the turn. All
built-in Codex tool activity and model reroutes fail closed.
"""

from __future__ import annotations

import json
import math
import tempfile
from time import perf_counter_ns
from collections.abc import Callable, Mapping
from threading import Event, Timer
from typing import Any, cast

from openai_codex import CodexError
from openai_codex.client import CodexClient, CodexConfig
from openai_codex.models import JsonValue as CodexJsonValue

from futures_agent_os.research_experiment.mvp_validation import (
    ModelInvocation,
    ModelTurn,
    ModelTurnKind,
    ModelUsage,
    ResearchConclusion,
    ToolCall,
)
from futures_agent_os.research_experiment.mvp_pivot_critic import (
    PivotCriticModelTurn,
    PivotCriticRequest,
    PivotCriticReview,
)
from futures_agent_os.shared_kernel import canonical_json_text
from futures_agent_os.shared_kernel.observability import JsonValue

from .research_model_payload import (
    CONCLUSION_SCHEMA,
    PIVOT_CONCLUSION_SCHEMA,
    PIVOT_CRITIQUE_SCHEMA,
    agent_episode_input,
)


CodexTurnTransport = Callable[[Mapping[str, object]], Mapping[str, object]]
_PASSIVE_ITEM_TYPES = frozenset({"agentMessage", "reasoning", "userMessage", "dynamicToolCall"})


class LocalWireSerializationError(ValueError):
    """A frozen local value cannot cross the official SDK JSON boundary."""


def _sdk_json_copy(value: object) -> object:
    """Thaw frozen contract values into ordinary finite JSON for the SDK only."""

    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise LocalWireSerializationError("SDK JSON value must be finite")
        return value
    if type(value) in {tuple, list}:
        return [_sdk_json_copy(item) for item in cast(tuple[object, ...] | list[object], value)]
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise LocalWireSerializationError("SDK JSON object keys must be text")
        return {cast(str, key): _sdk_json_copy(item) for key, item in value.items()}
    raise LocalWireSerializationError("SDK JSON value has an unsupported local type")


class OfficialCodexAppServerTransport:
    """Invoke the pinned official SDK without reading or copying login files."""

    def __call__(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        started_at_ns = perf_counter_ns()
        dynamic_calls: list[dict[str, object]] = []
        server_requests: list[str] = []

        def approval_handler(method: str, params: dict[str, CodexJsonValue] | None) -> dict[str, CodexJsonValue]:
            server_requests.append(method)
            if method == "item/tool/call" and params is not None:
                dynamic_calls.append(
                    {
                        "call_id": params.get("callId"),
                        "name": params.get("tool"),
                        "arguments": params.get("arguments"),
                    }
                )
                return {
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": "Tool request recorded. The deterministic owner will execute it after this turn.",
                        }
                    ],
                    "success": False,
                }
            # Defense in depth: the SDK default accepts command/file approvals.
            return {"decision": "decline"}

        with tempfile.TemporaryDirectory(prefix="fao-mvp-r-codex-") as cwd:
            client = CodexClient(CodexConfig(cwd=cwd), approval_handler=approval_handler)
            try:
                client.start()
                client.initialize()
                thread_params: Any = {
                    "model": payload["model"],
                    "cwd": cwd,
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "baseInstructions": payload["instructions"],
                    "developerInstructions": payload.get(
                        "developer_instructions",
                        (
                            "Use only the supplied dynamic research tools. Call at most one tool in this turn. "
                            "Never use shell, files, web, MCP, skills, collaboration, or computer tools. "
                            "If a dynamic tool is called, stop research after the request is recorded and return "
                            "a schema-valid DEFER placeholder; the caller ignores that placeholder and executes "
                            "the request deterministically. Otherwise return the final grounded conclusion."
                        ),
                    ),
                    "dynamicTools": payload["tools"],
                    "config": {"mcp_servers": {}},
                }
                started = client.thread_start(cast(Any, _sdk_json_copy(thread_params)))
                started_metadata = cast(Any, started).model_dump(mode="json", by_alias=True)
                turn_params: Any = {
                    "effort": payload["effort"],
                    "sandboxPolicy": {"type": "readOnly"},
                    "outputSchema": payload["output_schema"],
                }
                turn = client.turn_start(
                    started.thread.id,
                    cast(str, payload["input"]),
                    cast(Any, _sdk_json_copy(turn_params)),
                )
                provider_turn_started = True
                turn_metadata = cast(Any, turn.turn).model_dump(mode="json", by_alias=True)
                timed_out = Event()

                def interrupt_on_timeout() -> None:
                    timed_out.set()
                    try:
                        client.turn_interrupt(started.thread.id, turn.turn.id)
                    except CodexError:
                        pass

                timer = Timer(cast(int, payload["timeout_seconds"]), interrupt_on_timeout)
                timer.daemon = True
                timer.start()
                item_types: list[str] = []
                final_texts: list[str] = []
                reroutes: list[dict[str, object]] = []
                usage: dict[str, object] | None = None
                status = "unknown"
                completed: dict[str, object] = {}
                try:
                    while True:
                        event = client.next_turn_notification(turn.turn.id)
                        if event.method == "item/completed":
                            item = cast(Any, event.payload).item.model_dump(mode="json", by_alias=True)
                            item_type = item.get("type")
                            if type(item_type) is str:
                                item_types.append(item_type)
                            if item_type == "agentMessage" and type(item.get("text")) is str:
                                final_texts.append(item["text"])
                        elif event.method == "thread/tokenUsage/updated":
                            usage = cast(Any, event.payload).token_usage.last.model_dump(mode="json", by_alias=True)
                        elif event.method == "model/rerouted":
                            reroutes.append(cast(Any, event.payload).model_dump(mode="json", by_alias=True))
                        elif event.method == "turn/completed":
                            completed = cast(Any, event.payload).turn.model_dump(mode="json", by_alias=True)
                            status_value = completed.get("status")
                            status = status_value if type(status_value) is str else "unknown"
                            break
                finally:
                    timer.cancel()
                result: dict[str, object] = {
                    "response_id": turn.turn.id,
                    "model": started.model,
                    "model_provider": started.model_provider,
                    "status": status,
                    "usage": usage,
                    "final_texts": final_texts,
                    "dynamic_calls": dynamic_calls,
                    "server_requests": server_requests,
                    "item_types": item_types,
                    "reroutes": reroutes,
                    "timed_out": timed_out.is_set(),
                    "latencyMs": (perf_counter_ns() - started_at_ns) // 1_000_000,
                    "provider_turn_started": provider_turn_started,
                    "provider_response_observed": True,
                    "cost_mode": "SUBSCRIPTION_UNAVAILABLE",
                    "cost_available": False,
                    "cost_amount": None,
                }
                try:
                    actual_effort = _actual_reasoning_effort(started_metadata, turn_metadata, completed)
                except PermissionError:
                    result["reasoning_effort_error"] = "EFFORT_METADATA_CONFLICT"
                else:
                    if actual_effort is not None:
                        result["reasoning_effort"] = actual_effort
                return result
            finally:
                client.close()


class CodexAppServerProvider:
    """Translate one isolated App Server turn into the domain model port."""

    def __init__(self, transport: CodexTurnTransport) -> None:
        self._transport = transport

    @classmethod
    def official(cls) -> CodexAppServerProvider:
        return cls(OfficialCodexAppServerTransport())

    def respond(self, invocation: ModelInvocation) -> ModelTurn:
        try:
            response = self._transport(self._request_payload(invocation))
        except CodexError, OSError, RuntimeError:
            return self._failure(invocation, "CODEX_PROVIDER_FAILED")
        try:
            return self._parse_response(response, invocation)
        except json.JSONDecodeError:
            return self._failure(invocation, "CODEX_RESPONSE_INVALID_JSON")
        except PermissionError:
            return self._failure(invocation, "CODEX_RESPONSE_POLICY_VIOLATION")
        except (KeyError, TypeError, ValueError) as error:
            return self._failure(invocation, _contract_failure_code("CODEX_RESPONSE", error))

    def respond_pivot_critic(
        self,
        *,
        request: PivotCriticRequest,
        model_id: str,
        reasoning_effort: str,
        instructions: str,
        timeout_seconds: int,
    ) -> PivotCriticModelTurn:
        if (
            type(request) is not PivotCriticRequest
            or not model_id.strip()
            or reasoning_effort not in {"low", "medium", "high"}
            or not instructions.strip()
            or type(timeout_seconds) is not int
            or timeout_seconds < 1
        ):
            raise ValueError("Pivot Critic invocation requires frozen request and model settings")
        try:
            response = self._transport(
                {
                    "model": model_id,
                    "effort": reasoning_effort,
                    "instructions": instructions,
                    "developer_instructions": (
                        "Review only the supplied future-blind research proposal and deterministic family evidence. "
                        "Never use tools, shell, files, web, MCP, skills, collaboration, or computer access. "
                        "Return exactly one schema-valid independent ACCEPT or VETO review."
                    ),
                    "input": "PIVOT CRITIC REQUEST (contains no future reveal):\n"
                    + canonical_json_text(request.payload()),
                    "tools": (),
                    "output_schema": PIVOT_CRITIQUE_SCHEMA,
                    "timeout_seconds": timeout_seconds,
                }
            )
        except CodexError, OSError, RuntimeError:
            return PivotCriticModelTurn(
                "codex-critic-response-unparseable",
                model_id,
                ModelUsage(0, 0, 0, 0, 0),
                None,
                "CODEX_CRITIC_PROVIDER_FAILED",
            )
        try:
            return self._parse_pivot_critic_response(response, request, model_id)
        except json.JSONDecodeError:
            code = "CODEX_CRITIC_RESPONSE_INVALID_JSON"
        except PermissionError:
            code = "CODEX_CRITIC_RESPONSE_POLICY_VIOLATION"
        except (KeyError, TypeError, ValueError) as error:
            code = _contract_failure_code("CODEX_CRITIC_RESPONSE", error)
        return PivotCriticModelTurn(
            "codex-critic-response-unparseable",
            model_id,
            ModelUsage(0, 0, 0, 0, 0),
            None,
            code,
        )

    @staticmethod
    def _failure(invocation: ModelInvocation, code: str) -> ModelTurn:
        return ModelTurn(
            "codex-response-unparseable",
            invocation.config.model_id,
            ModelTurnKind.FAILED,
            ModelUsage(0, 0, 0, 0, 0),
            failure_code=code,
        )

    @staticmethod
    def _request_payload(invocation: ModelInvocation) -> dict[str, object]:
        return {
            "model": invocation.config.model_id,
            "effort": invocation.config.reasoning_effort.value,
            "instructions": invocation.instructions,
            "input": agent_episode_input(invocation),
            "tools": tuple(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": json.loads(tool.parameters_json),
                }
                for tool in invocation.tools
            ),
            "output_schema": (
                PIVOT_CONCLUSION_SCHEMA
                if invocation.config.resolved_profile.output_schema_binding == "mvp-r.pivot-conclusion.v1"
                else CONCLUSION_SCHEMA
            ),
            "timeout_seconds": invocation.config.timeout_seconds,
        }

    def _parse_response(self, response: Mapping[str, object], invocation: ModelInvocation) -> ModelTurn:
        response_id = _required_str(response, "response_id")
        model = _required_str(response, "model")
        usage = _usage(_mapping(response.get("usage")))
        if response.get("timed_out") is True:
            return ModelTurn(response_id, model, ModelTurnKind.FAILED, usage, failure_code="PROVIDER_TIMEOUT")
        if response.get("status") != "completed":
            return ModelTurn(response_id, model, ModelTurnKind.FAILED, usage, failure_code="CODEX_TURN_INCOMPLETE")
        if response.get("model_provider") != "openai" or _sequence(response.get("reroutes")):
            return ModelTurn(response_id, model, ModelTurnKind.FAILED, usage, failure_code="MODEL_VERSION_MISMATCH")
        server_requests = tuple(_required_text(value) for value in _sequence(response.get("server_requests")))
        if any(method != "item/tool/call" for method in server_requests):
            return ModelTurn(
                response_id, model, ModelTurnKind.FAILED, usage, failure_code="CODEX_TOOL_SURFACE_VIOLATION"
            )
        item_types = tuple(_required_text(value) for value in _sequence(response.get("item_types")))
        if any(item_type not in _PASSIVE_ITEM_TYPES for item_type in item_types):
            return ModelTurn(
                response_id, model, ModelTurnKind.FAILED, usage, failure_code="CODEX_TOOL_SURFACE_VIOLATION"
            )
        calls = _sequence(response.get("dynamic_calls"))
        if len(calls) > 1:
            return ModelTurn(
                response_id, model, ModelTurnKind.FAILED, usage, failure_code="PARALLEL_TOOL_CALL_REJECTED"
            )
        if calls:
            call = _mapping(calls[0])
            return ModelTurn(
                response_id,
                model,
                ModelTurnKind.TOOL_CALL,
                usage,
                tool_call=ToolCall(
                    _required_str(call, "call_id"),
                    _required_str(call, "name"),
                    _freeze_json(call["arguments"]),
                ),
            )
        texts = _sequence(response.get("final_texts"))
        if len(texts) != 1:
            return ModelTurn(response_id, model, ModelTurnKind.FAILED, usage, failure_code="FINAL_OUTPUT_MISSING")
        conclusion = ResearchConclusion.hydrate(_mapping(_freeze_json(json.loads(_required_text(texts[0])))))
        return ModelTurn(response_id, model, ModelTurnKind.FINAL, usage, conclusion=conclusion)

    def _parse_pivot_critic_response(
        self,
        response: Mapping[str, object],
        request: PivotCriticRequest,
        expected_model_id: str,
    ) -> PivotCriticModelTurn:
        response_id = _required_str(response, "response_id")
        model = _required_str(response, "model")
        usage = _usage(_mapping(response.get("usage")))

        def failed(code: str) -> PivotCriticModelTurn:
            return PivotCriticModelTurn(response_id, model, usage, None, code)

        if response.get("timed_out") is True:
            return failed("PROVIDER_TIMEOUT")
        if response.get("status") != "completed":
            return failed("CODEX_TURN_INCOMPLETE")
        if (
            model != expected_model_id
            or response.get("model_provider") != "openai"
            or _sequence(response.get("reroutes"))
        ):
            return failed("MODEL_VERSION_MISMATCH")
        if _sequence(response.get("server_requests")) or _sequence(response.get("dynamic_calls")):
            return failed("CODEX_TOOL_SURFACE_VIOLATION")
        item_types = tuple(_required_text(value) for value in _sequence(response.get("item_types")))
        if any(item_type not in _PASSIVE_ITEM_TYPES for item_type in item_types):
            return failed("CODEX_TOOL_SURFACE_VIOLATION")
        texts = _sequence(response.get("final_texts"))
        if len(texts) != 1:
            return failed("FINAL_OUTPUT_MISSING")
        review = PivotCriticReview.hydrate(_mapping(_freeze_json(json.loads(_required_text(texts[0])))))
        review.verify_request(request)
        return PivotCriticModelTurn(response_id, model, usage, review, None)


def _usage(value: Mapping[str, object]) -> ModelUsage:
    input_tokens = _nonnegative_int(value.get("inputTokens"))
    output_tokens = _nonnegative_int(value.get("outputTokens"))
    total_tokens = _nonnegative_int(value.get("totalTokens"))
    if total_tokens != input_tokens + output_tokens:
        raise ValueError("Codex token total is inconsistent")
    return ModelUsage(
        input_tokens,
        output_tokens,
        _nonnegative_int(value.get("reasoningOutputTokens")),
        _nonnegative_int(value.get("cacheWriteInputTokens")),
        0,
    )


def _actual_reasoning_effort(*metadata: Mapping[str, object]) -> str | None:
    """Read only effort echoed by official start/turn completion metadata."""

    observed: list[str] = []
    for value in metadata:
        for key in ("reasoningEffort", "reasoning_effort", "effort"):
            candidate = value.get(key)
            if candidate is not None:
                observed.append(_required_text(candidate))
        reasoning = value.get("reasoning")
        if isinstance(reasoning, Mapping) and reasoning.get("effort") is not None:
            observed.append(_required_text(reasoning["effort"]))
    if not observed:
        return None
    if any(value not in {"low", "medium", "high", "xhigh"} for value in observed) or len(set(observed)) != 1:
        raise PermissionError("Codex metadata does not prove one exact reasoning effort")
    return observed[0]


def _freeze_json(value: object) -> JsonValue:
    if value is None or type(value) in {str, int, bool}:
        return cast(JsonValue, value)
    if type(value) is list:
        return tuple(_freeze_json(item) for item in cast(list[object], value))
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("Codex JSON object keys must be text")
        return {cast(str, key): _freeze_json(item) for key, item in value.items()}
    raise TypeError("Codex JSON must be finite and exact")


def _contract_failure_code(prefix: str, error: KeyError | TypeError | ValueError) -> str:
    """Map parser exceptions to non-sensitive, stable diagnostic buckets."""

    message = str(error)
    if any(fragment in message for fragment in ("numeric claims", "hypothesis prose")):
        suffix = "PROSE_DIGITS"
    elif any(fragment in message for fragment in ("evidence pointer", "JSON Pointer")):
        suffix = "GROUNDING_POINTER_SHAPE"
    elif any(fragment in message for fragment in ("numeric grounding", "numeric claim", "numeric span")):
        suffix = "NUMERIC_GROUNDING"
    elif any(fragment in message for fragment in ("token", "usage")):
        suffix = "USAGE_INVALID"
    elif any(fragment in message for fragment in ("conclusion", "hypothesis", "grounded claim", "keys are not exact")):
        suffix = "PAYLOAD_SHAPE"
    else:
        suffix = "CONTRACT_VIOLATION"
    return f"{prefix}_{suffix}"


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError("Codex object must be string-keyed")
    return value


def _sequence(value: object) -> tuple[object, ...] | list[object]:
    if type(value) not in {tuple, list}:
        raise TypeError("Codex collection must be a sequence")
    return cast(tuple[object, ...] | list[object], value)


def _required_str(value: Mapping[str, object], key: str) -> str:
    return _required_text(value[key])


def _required_text(value: object) -> str:
    if type(value) is not str or not value:
        raise TypeError("Codex value must be non-empty text")
    return value


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise TypeError("Codex token usage must be a non-negative integer")
    return value


__all__ = ["CodexAppServerProvider", "CodexTurnTransport", "OfficialCodexAppServerTransport"]
