"""OpenAI Responses API adapter for the bounded MVP-R model port."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, cast

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from futures_agent_os.research_experiment.mvp_validation import (
    ModelInvocation,
    ModelRunConfig,
    ModelTurn,
    ModelTurnKind,
    ModelUsage,
    ResearchConclusion,
    ToolCall,
)
from futures_agent_os.shared_kernel.observability import JsonValue
from .research_model_payload import CONCLUSION_SCHEMA, agent_episode_input


ResponseTransport = Callable[[Mapping[str, object]], Mapping[str, object]]


class OpenAIResponsesProvider:
    """Translate the provider API into exact model turns without reasoning text."""

    def __init__(self, transport: ResponseTransport) -> None:
        self._transport = transport

    @classmethod
    def from_client(cls, client: OpenAI) -> OpenAIResponsesProvider:
        def transport(payload: Mapping[str, object]) -> Mapping[str, object]:
            # The SDK validates the concrete request.  The cast is isolated at
            # this adapter seam so domain code never imports provider types.
            response = client.responses.create(**cast(dict[str, Any], dict(payload)))
            parsed = json.loads(response.model_dump_json())
            return _mapping(parsed)

        return cls(transport)

    def respond(self, invocation: ModelInvocation) -> ModelTurn:
        payload = self._request_payload(invocation)
        try:
            response = self._transport(payload)
            return self._parse_response(response, invocation.config)
        except APITimeoutError:
            return self._failure(invocation.config, "PROVIDER_TIMEOUT")
        except APIConnectionError:
            return self._failure(invocation.config, "PROVIDER_CONNECTION_FAILED")
        except APIStatusError:
            return self._failure(invocation.config, "PROVIDER_STATUS_FAILED")
        except KeyError, TypeError, ValueError, json.JSONDecodeError:
            return self._failure(invocation.config, "PROVIDER_RESPONSE_INVALID")

    @staticmethod
    def _failure(config: ModelRunConfig, code: str) -> ModelTurn:
        return ModelTurn(
            "provider-response-unparseable",
            config.model_id,
            ModelTurnKind.FAILED,
            ModelUsage(0, 0, 0, 0, 0),
            failure_code=code,
        )

    def _request_payload(self, invocation: ModelInvocation) -> dict[str, object]:
        return {
            "model": invocation.config.model_id,
            "reasoning": {"effort": invocation.config.reasoning_effort.value},
            "instructions": invocation.instructions,
            "input": agent_episode_input(invocation),
            "tools": tuple(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": json.loads(tool.parameters_json),
                    "strict": True,
                }
                for tool in invocation.tools
            ),
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tool_calls": invocation.config.max_tool_calls,
            "max_output_tokens": invocation.output_token_limit or invocation.config.max_output_tokens,
            "temperature": invocation.config.temperature_millis / 1_000,
            "timeout": invocation.config.timeout_seconds,
            "store": False,
            "truncation": "disabled",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "mvp_r_research_conclusion_v1",
                    "strict": True,
                    "schema": CONCLUSION_SCHEMA,
                }
            },
            "metadata": {
                "episode_id": str(invocation.episode.episode_id),
                "model_config_sha256": invocation.config.content_sha256,
            },
        }

    def _parse_response(self, response: Mapping[str, object], config: ModelRunConfig) -> ModelTurn:
        response_id = _required_str(response, "id")
        provider_model = _required_str(response, "model")
        status = _required_str(response, "status")
        usage_value = response.get("usage")
        if status == "completed" and usage_value is None:
            raise ValueError("completed provider response requires usage")
        usage = _usage(_mapping(usage_value or {}), config, require_counts=status == "completed")
        if status != "completed":
            return ModelTurn(
                response_id,
                provider_model,
                ModelTurnKind.FAILED,
                usage,
                failure_code="PROVIDER_RESPONSE_INCOMPLETE",
            )

        function_calls: list[Mapping[str, object]] = []
        output_texts: list[str] = []
        for item in _sequence(response.get("output", ())):
            output_item = _mapping(item)
            item_type = output_item.get("type")
            if item_type == "function_call":
                function_calls.append(output_item)
            elif item_type == "message":
                for content in _sequence(output_item.get("content", ())):
                    content_item = _mapping(content)
                    if content_item.get("type") == "output_text":
                        output_texts.append(_required_str(content_item, "text"))

        if len(function_calls) > 1:
            return ModelTurn(
                response_id,
                provider_model,
                ModelTurnKind.FAILED,
                usage,
                failure_code="PARALLEL_TOOL_CALL_REJECTED",
            )
        if function_calls:
            item = function_calls[0]
            arguments = _freeze_json(json.loads(_required_str(item, "arguments")))
            return ModelTurn(
                response_id,
                provider_model,
                ModelTurnKind.TOOL_CALL,
                usage,
                tool_call=ToolCall(_required_str(item, "call_id"), _required_str(item, "name"), arguments),
            )
        if len(output_texts) != 1:
            return ModelTurn(
                response_id,
                provider_model,
                ModelTurnKind.FAILED,
                usage,
                failure_code="FINAL_OUTPUT_MISSING",
            )
        conclusion_value = _mapping(_freeze_json(json.loads(output_texts[0])))
        return ModelTurn(
            response_id,
            provider_model,
            ModelTurnKind.FINAL,
            usage,
            conclusion=ResearchConclusion.hydrate(conclusion_value),
        )


def _usage(value: Mapping[str, object], config: ModelRunConfig, *, require_counts: bool) -> ModelUsage:
    if require_counts and not {"input_tokens", "output_tokens", "total_tokens"} <= set(value):
        raise ValueError("completed provider response requires explicit token counts")
    input_tokens = _nonnegative_int(value.get("input_tokens", 0))
    output_tokens = _nonnegative_int(value.get("output_tokens", 0))
    if require_counts and _nonnegative_int(value["total_tokens"]) != input_tokens + output_tokens:
        raise ValueError("provider total_tokens is inconsistent")
    details = _mapping(value.get("output_tokens_details") or {})
    reasoning_tokens = _nonnegative_int(details.get("reasoning_tokens", 0))
    input_details = _mapping(value.get("input_tokens_details") or {})
    cache_write_tokens = _nonnegative_int(input_details.get("cache_write_tokens", 0))
    cache_write_surcharge = (
        cache_write_tokens
        * config.input_cost_microusd_per_token
        * (config.cache_write_cost_numerator - config.cache_write_cost_denominator)
        + config.cache_write_cost_denominator
        - 1
    ) // config.cache_write_cost_denominator
    return ModelUsage(
        input_tokens,
        output_tokens,
        reasoning_tokens,
        cache_write_tokens,
        input_tokens * config.input_cost_microusd_per_token
        + output_tokens * config.output_cost_microusd_per_token
        + cache_write_surcharge,
    )


def _freeze_json(value: object) -> JsonValue:
    if value is None or type(value) in {str, int, bool}:
        return cast(JsonValue, value)
    if type(value) is list:
        return tuple(_freeze_json(item) for item in cast(list[object], value))
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("JSON object keys must be text")
        return {cast(str, key): _freeze_json(item) for key, item in value.items()}
    raise TypeError("provider JSON must be finite and exact")


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError("provider object must be string-keyed")
    return value


def _sequence(value: object) -> tuple[object, ...] | list[object]:
    if type(value) not in {tuple, list}:
        raise TypeError("provider collection must be a sequence")
    return cast(tuple[object, ...] | list[object], value)


def _required_str(value: Mapping[str, object], key: str) -> str:
    item = value[key]
    if type(item) is not str or not item:
        raise TypeError(f"provider {key} must be non-empty text")
    return item


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise TypeError("provider token usage must be a non-negative integer")
    return value


__all__ = ["OpenAIResponsesProvider", "ResponseTransport"]
