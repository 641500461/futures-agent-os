"""Provider-neutral wire payload helpers for the frozen MVP-R agent turn."""

from __future__ import annotations

from copy import deepcopy

from futures_agent_os.research_experiment.mvp_validation import ModelInvocation
from futures_agent_os.shared_kernel import canonical_json_text


CONCLUSION_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "summary", "claims", "counter_evidence_sha256s", "warnings", "hypothesis"],
    "properties": {
        "kind": {"type": "string", "enum": ["OPPORTUNITY_CANDIDATE", "NO_OPPORTUNITY", "DEFER"]},
        "summary": {"type": "string", "minLength": 1},
        "claims": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "statement",
                    "evidence_sha256",
                    "evidence_json_pointer",
                    "numeric_value",
                    "unit",
                    "unit_json_pointer",
                ],
                "properties": {
                    "statement": {"type": "string", "minLength": 1},
                    "evidence_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "evidence_json_pointer": {"type": "string"},
                    "numeric_value": {"type": ["string", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "unit_json_pointer": {"type": ["string", "null"]},
                },
            },
        },
        "counter_evidence_sha256s": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
        "hypothesis": {
            "type": "object",
            "additionalProperties": False,
            "required": ["family", "statement", "falsification_condition", "next_test"],
            "properties": {
                "family": {
                    "type": "string",
                    "enum": [
                        "MOMENTUM_CONTINUATION",
                        "MEAN_REVERSION",
                        "BREAKOUT_CONTINUATION",
                        "FALSE_BREAKOUT_REVERSAL",
                        "PARTICIPATION_CONFIRMED_TREND",
                        "VOLATILITY_COMPRESSION_BREAKOUT",
                        "NONE",
                    ],
                },
                "statement": {"type": "string", "minLength": 1},
                "falsification_condition": {"type": "string", "minLength": 1},
                "next_test": {"type": "string", "minLength": 1},
            },
        },
    },
}


def _build_pivot_conclusion_schema() -> dict[str, object]:
    schema = deepcopy(CONCLUSION_SCHEMA)
    properties = _schema_object(schema["properties"])
    properties["summary"] = {"type": "string", "minLength": 1, "pattern": "^[^0-9]*$"}
    properties["warnings"] = {
        "type": "array",
        "items": {"type": "string", "minLength": 1, "pattern": "^[^0-9]*$"},
    }
    hypothesis = _schema_object(properties["hypothesis"])
    hypothesis_properties = _schema_object(hypothesis["properties"])
    for field in ("statement", "falsification_condition", "next_test"):
        hypothesis_properties[field] = {"type": "string", "minLength": 1, "pattern": "^[^0-9]*$"}
    claims = _schema_object(properties["claims"])
    claim = _schema_object(claims["items"])
    claim_properties = _schema_object(claim["properties"])
    claim_properties["statement"] = {"type": "string", "minLength": 1, "pattern": "^[^0-9]*$"}
    claim_properties["numeric_value"] = {"type": "null"}
    claim_properties["unit"] = {"type": "null"}
    claim_properties["unit_json_pointer"] = {"type": "null"}
    return schema


def _schema_object(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TypeError("research output schema requires string-keyed objects")
    return value


PIVOT_CONCLUSION_SCHEMA = _build_pivot_conclusion_schema()


PIVOT_CRITIQUE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "decision",
        "proposal_sha256",
        "feature_evidence_sha256",
        "high_severity_defects",
        "counter_hypothesis_family",
        "summary",
    ],
    "properties": {
        "decision": {"type": "string", "enum": ["ACCEPT", "VETO"]},
        "proposal_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "feature_evidence_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "high_severity_defects": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "counter_hypothesis_family": {
            "type": "string",
            "enum": [
                "MOMENTUM_CONTINUATION",
                "MEAN_REVERSION",
                "BREAKOUT_CONTINUATION",
                "FALSE_BREAKOUT_REVERSAL",
                "PARTICIPATION_CONFIRMED_TREND",
                "VOLATILITY_COMPRESSION_BREAKOUT",
                "NONE",
            ],
        },
        "summary": {"type": "string", "minLength": 1},
    },
}


_R002_NARRATIVES = [
    "SCREENING_SUPPORTS_RESEARCH",
    "INDEPENDENT_WINDOW_UNKNOWN",
    "FROZEN_THRESHOLD_RATIONALE",
    "FROZEN_HYPOTHESIS",
    "DETERMINISTIC_INPUT_UNAVAILABLE",
    "INPUT_RECOVERY_REEVALUATION",
    "FIXED_ABLATION",
    "ABLATION_COUNTERFACTUAL",
]
_R002_SOURCE_REF = {
    "type": "object",
    "additionalProperties": False,
    "required": ["artifact_sha256", "json_pointer", "label"],
    "properties": {
        "artifact_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "json_pointer": {"type": "string", "minLength": 1},
        "label": {"type": "string", "minLength": 1},
    },
}
_R002_CLAIM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["category", "evidence_refs", "numeric_value", "unit"],
    "properties": {
        "category": {"type": "string", "enum": _R002_NARRATIVES},
        "evidence_refs": {"type": "array", "minItems": 1, "items": _R002_SOURCE_REF},
        "numeric_value": {"type": "null"},
        "unit": {"type": "null"},
    },
}
R002_RESEARCH_SYNTHESIS_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "intent",
        "action",
        "why_now",
        "supporting_claims",
        "strongest_counter_claim",
        "additional_unknowns",
        "falsifiable_hypothesis",
        "source_refs",
    ],
    "properties": {
        "intent": {"type": "string", "enum": ["RESEARCH_ONLY"]},
        "action": {"type": "string", "enum": ["TEST_NEXT", "WATCH_FOR_DATA", "REJECT_AS_UNSUPPORTED"]},
        "why_now": {"type": "string", "enum": _R002_NARRATIVES},
        "supporting_claims": {"type": "array", "minItems": 1, "items": _R002_CLAIM},
        "strongest_counter_claim": _R002_CLAIM,
        "additional_unknowns": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": _R002_NARRATIVES}},
        "falsifiable_hypothesis": {"type": "string", "enum": _R002_NARRATIVES},
        "source_refs": {"type": "array", "minItems": 1, "items": _R002_SOURCE_REF},
    },
}
R002_EXPERIMENT_DESIGN_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["design_category"],
    "properties": {"design_category": {"type": "string", "enum": ["USE_FROZEN_BINDING"]}},
}
R002_INDEPENDENT_CRITIC_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "reason_category"],
    "properties": {
        "decision": {"type": "string", "enum": ["PASS", "REVISE", "REJECT", "DEFER"]},
        "reason_category": {"type": "string", "enum": _R002_NARRATIVES},
    },
}


def agent_episode_input(invocation: ModelInvocation) -> str:
    """Serialize only the frozen agent view; future reveal is structurally absent."""

    return "AGENT EPISODE VIEW (contains no future reveal):\n" + canonical_json_text(
        {
            "episode_id": str(invocation.episode.episode_id),
            "suite_sha256": invocation.episode.suite_sha256,
            "phase": invocation.episode.phase.value,
            "mode": invocation.episode.mode.value,
            "instrument_id": invocation.episode.instrument_id,
            "as_of": invocation.episode.as_of.to_dict()["recorded_at"],
            "market_cutoff": invocation.episode.market_cutoff.to_dict()["recorded_at"],
            "input_artifact_sha256s": invocation.episode.input_artifact_sha256s,
            "evidence": invocation.evidence,
            "prior_tool_executions": tuple(
                {
                    "call_id": output.call_id,
                    "tool_name": output.tool_name,
                    "result": output.result,
                    "result_sha256": output.result_sha256,
                    "source_artifact_sha256s": output.source_artifact_sha256s,
                }
                for output in invocation.tool_history
            ),
        }
    )


__all__ = [
    "CONCLUSION_SCHEMA",
    "PIVOT_CONCLUSION_SCHEMA",
    "PIVOT_CRITIQUE_SCHEMA",
    "R002_EXPERIMENT_DESIGN_SCHEMA",
    "R002_INDEPENDENT_CRITIC_SCHEMA",
    "R002_RESEARCH_SYNTHESIS_SCHEMA",
    "agent_episode_input",
]
