"""Versioned, structured falsification predicates for MVP-R-005 correction-v2."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Mapping

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    ExperimentResultPacket,
    FinalVerdict,
    HypothesisSpec,
    ResearchFinalVerdict,
    _exact_keys,
    _integer,
    _mapping,
    _sequence,
    _text,
)
from futures_agent_os.research_experiment.mvp_r_004.metrics import packet_metric_map
from futures_agent_os.research_experiment.mvp_r_005.contracts import DecisionBrief
from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

PREDICATE_SCHEMA_VERSION = "mvp-r-005.falsification-predicate.v1"
PREDICATE_MARKER = "mvp-r-005.falsification-predicate.v1"
PREDICATE_SEPARATOR = "\n---\n"
CONTROL_BY_PRIMARY = {
    "signal_accuracy": "counterfactual_signal_accuracy",
    "proxy_net_return": "counterfactual_net_return",
    "stressed_net_return": "counterfactual_stressed_net_return",
    "positive_fold_ratio": "counterfactual_positive_fold_ratio",
}
FOLD_METRIC_FIELDS = {
    "signal_accuracy": ("fold_{index}_signal_accuracy", "fold_{index}_counterfactual_signal_accuracy"),
    "proxy_net_return": ("fold_{index}_proxy_net_return", "fold_{index}_counterfactual_net_return"),
}


def fold_metric_templates(metric: str) -> tuple[str, str]:
    if metric not in FOLD_METRIC_FIELDS:
        raise ValueError(f"{metric} has no registered per-fold fields")
    return FOLD_METRIC_FIELDS[metric]


def fold_metric_fields(metric: str, index: int) -> tuple[str, str]:
    primary, control = fold_metric_templates(metric)
    return primary.format(index=index), control.format(index=index)


class PredicateClauseKind(StrEnum):
    AGGREGATE_PRIMARY_BEATS_CONTROL = "aggregate_primary_beats_control"
    PRIMARY_POSITIVE_AND_BEATS_CONTROL = "primary_positive_and_beats_control"
    EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL = "each_oos_fold_primary_beats_control"
    AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD = "at_least_n_oos_folds_above_threshold"
    MINIMUM_FULL_WINDOW_SIGNAL_COUNT = "minimum_full_window_signal_count"
    REQUIRED_OOS_FOLD_COUNT = "required_oos_fold_count"


class ClauseOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT = "INSUFFICIENT"


class PredicateVerdictMismatch(ValueError):
    """Agent verdict is not congruent with the deterministic predicate outcome."""


@dataclass(frozen=True, slots=True)
class PredicateClause:
    kind: PredicateClauseKind
    metric: str | None
    threshold: str | None
    fold_n: int | None
    minimum_count: int | None

    def __post_init__(self) -> None:
        if type(self.kind) is not PredicateClauseKind:
            raise TypeError("predicate clause requires a registered kind")
        if self.kind in {
            PredicateClauseKind.AGGREGATE_PRIMARY_BEATS_CONTROL,
            PredicateClauseKind.PRIMARY_POSITIVE_AND_BEATS_CONTROL,
        }:
            if self.metric not in CONTROL_BY_PRIMARY:
                raise ValueError("predicate clause metric must be a registered primary")
        elif self.kind in {
            PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL,
            PredicateClauseKind.AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD,
        }:
            if self.metric not in FOLD_METRIC_FIELDS:
                raise ValueError(
                    "fold predicate metric must have registered per-fold ResultPacket fields; "
                    f"{self.metric} cannot be used"
                )
        elif self.metric is not None:
            raise ValueError(f"{self.kind.value} must not set a metric")
        if self.kind is PredicateClauseKind.AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD:
            if self.threshold is None or self.fold_n is None:
                raise ValueError("at-least-N clause requires threshold and fold_n")
            Decimal(self.threshold)
        elif self.threshold is not None:
            raise ValueError(f"{self.kind.value} must not set a threshold")
        if self.kind is PredicateClauseKind.REQUIRED_OOS_FOLD_COUNT:
            if self.fold_n is None:
                raise ValueError("required OOS fold count requires fold_n")
        elif self.kind is not PredicateClauseKind.AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD and self.fold_n is not None:
            raise ValueError(f"{self.kind.value} must not set fold_n")
        if self.kind is PredicateClauseKind.MINIMUM_FULL_WINDOW_SIGNAL_COUNT:
            if self.minimum_count is None:
                raise ValueError("minimum sample clause requires minimum_count")
        elif self.minimum_count is not None:
            raise ValueError(f"{self.kind.value} must not set minimum_count")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "metric": self.metric,
            "threshold": self.threshold,
            "fold_n": self.fold_n,
            "minimum_count": self.minimum_count,
        }

    def render(self) -> str:
        if self.kind is PredicateClauseKind.AGGREGATE_PRIMARY_BEATS_CONTROL:
            assert self.metric is not None
            return f"{self.metric} > {CONTROL_BY_PRIMARY[self.metric]}"
        if self.kind is PredicateClauseKind.PRIMARY_POSITIVE_AND_BEATS_CONTROL:
            assert self.metric is not None
            return f"{self.metric} > 0 and {self.metric} > {CONTROL_BY_PRIMARY[self.metric]}"
        if self.kind is PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL:
            assert self.metric is not None
            primary_template, control_template = fold_metric_templates(self.metric)
            primary_name = primary_template.format(index="N")
            control_name = control_template.format(index="N")
            return (
                f"each evaluated OOS {primary_name} > {control_name} "
                f"(registered metric {self.metric}); "
                "positive_fold_ratio must not substitute the registered per-fold metric"
            )
        if self.kind is PredicateClauseKind.AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD:
            assert self.metric is not None
            names = ", ".join(fold_metric_fields(self.metric, index)[0] for index in range(1, (self.fold_n or 0) + 1))
            return f"at least {self.fold_n} OOS folds have {self.metric} > {self.threshold} using {names}"
        if self.kind is PredicateClauseKind.MINIMUM_FULL_WINDOW_SIGNAL_COUNT:
            return (
                f"full-window signal_count >= {self.minimum_count} "
                "(minimum_samples constrains train_bars/full-window eligibility, not OOS sample count)"
            )
        return f"required authentic OOS fold_count is {self.fold_n}; do not synthesize missing folds"


@dataclass(frozen=True, slots=True)
class FalsificationPredicate:
    clauses: tuple[PredicateClause, ...]

    def __post_init__(self) -> None:
        if type(self.clauses) is not tuple or not self.clauses:
            raise ValueError("falsification predicate requires at least one clause")
        if any(type(item) is not PredicateClause for item in self.clauses):
            raise TypeError("falsification predicate clauses must be exact")

    @property
    def schema_version(self) -> str:
        return PREDICATE_SCHEMA_VERSION

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.payload())

    def payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": PREDICATE_SCHEMA_VERSION,
            "clauses": tuple(item.payload() for item in self.clauses),
        }

    def render(self) -> str:
        body = "; ".join(item.render() for item in self.clauses)
        return (
            "REJECT unless all of: "
            f"{body}. "
            "positive_fold_ratio is OOS net-positive fold share and must not substitute the registered per-fold metric. "
            "Any FAIL clause yields REJECT. INSUFFICIENT yields NEED_MORE_DATA only when no clause FAILed "
            "and missing data could still change the conclusion."
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {**self.payload(), "content_sha256": self.content_sha256}


@dataclass(frozen=True, slots=True)
class PredicateEvaluation:
    outcome: FinalVerdict
    clause_results: tuple[tuple[str, str], ...]
    missing_metrics: tuple[str, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": "mvp-r-005.predicate-evaluation.v1",
            "outcome": self.outcome.value,
            "clause_results": self.clause_results,
            "missing_metrics": self.missing_metrics,
        }


def parse_predicate_mapping(value: object) -> FalsificationPredicate:
    payload = _mapping(value, "falsification predicate")
    allowed = {"clauses", "schema_version", "content_sha256"}
    extra = set(payload) - allowed
    if extra or "clauses" not in payload:
        raise ValueError("falsification predicate keys must be exact")
    clauses = tuple(
        clause
        for clause in (_clause(_mapping(item, "predicate clause")) for item in _sequence(payload["clauses"], "clauses"))
        if clause is not None
    )
    if not clauses:
        raise ValueError("falsification predicate has no evaluable clauses")
    return FalsificationPredicate(clauses)


def _clause(value: Mapping[str, object]) -> PredicateClause | None:
    _exact_keys(value, {"kind", "metric", "threshold", "fold_n", "minimum_count"}, "predicate clause")
    kind = PredicateClauseKind(_text(value["kind"], "predicate kind"))
    metric = None if value["metric"] is None else _text(value["metric"], "predicate metric")
    threshold = None if value["threshold"] is None else _text(value["threshold"], "predicate threshold")
    fold_n = None if value["fold_n"] is None else _integer(value["fold_n"], "predicate fold_n")
    minimum_count = None if value["minimum_count"] is None else _integer(value["minimum_count"], "predicate minimum")
    if kind in {
        PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL,
        PredicateClauseKind.AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD,
    }:
        if metric is not None and metric not in FOLD_METRIC_FIELDS:
            raise ValueError(f"fold predicate metric {metric} has no registered per-fold fields and cannot be used")
    if kind in {
        PredicateClauseKind.AGGREGATE_PRIMARY_BEATS_CONTROL,
        PredicateClauseKind.PRIMARY_POSITIVE_AND_BEATS_CONTROL,
        PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL,
    }:
        threshold = None
        fold_n = None
        minimum_count = None
        if kind is PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL and metric is None:
            return None
    elif kind is PredicateClauseKind.AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD:
        if threshold is None or fold_n is None or metric is None:
            return None
        minimum_count = None
    elif kind is PredicateClauseKind.MINIMUM_FULL_WINDOW_SIGNAL_COUNT:
        if minimum_count is None:
            return None
        metric = None
        threshold = None
        fold_n = None
    elif kind is PredicateClauseKind.REQUIRED_OOS_FOLD_COUNT:
        if fold_n is None:
            return None
        metric = None
        threshold = None
        minimum_count = None
    return PredicateClause(
        kind=kind,
        metric=metric,
        threshold=threshold,
        fold_n=fold_n,
        minimum_count=minimum_count,
    )


def bind_falsification_condition(predicate: FalsificationPredicate) -> str:
    if type(predicate) is not FalsificationPredicate:
        raise TypeError("falsification binding requires an exact predicate")
    rendered = predicate.render()
    text = f"{PREDICATE_MARKER}\n{canonical_json_text(predicate.payload())}{PREDICATE_SEPARATOR}{rendered}"
    parsed = parse_falsification_condition(text)
    if parsed is None or parsed.content_sha256 != predicate.content_sha256 or parsed.render() != rendered:
        raise ValueError("falsification predicate failed exact render binding")
    return text


def parse_falsification_condition(condition: str) -> FalsificationPredicate | None:
    if type(condition) is not str or not condition.startswith(PREDICATE_MARKER + "\n"):
        return None
    rest = condition[len(PREDICATE_MARKER) + 1 :]
    if PREDICATE_SEPARATOR not in rest:
        raise ValueError("typed falsification condition is missing the render binding")
    raw, rendered = rest.split(PREDICATE_SEPARATOR, 1)
    import json

    loaded = json.loads(raw)
    if type(loaded) is not dict:
        raise ValueError("typed falsification payload must be an object")
    payload = {str(key): value for key, value in loaded.items()}
    if payload.get("schema_version") != PREDICATE_SCHEMA_VERSION:
        raise ValueError("unsupported falsification predicate schema")
    predicate = parse_predicate_mapping({"clauses": payload["clauses"]})
    if rendered != predicate.render():
        raise ValueError("human-readable falsification text does not exact-bind the typed predicate")
    return predicate


def default_fallback_predicate() -> FalsificationPredicate:
    return FalsificationPredicate(
        (
            PredicateClause(
                PredicateClauseKind.AGGREGATE_PRIMARY_BEATS_CONTROL,
                "signal_accuracy",
                None,
                None,
                None,
            ),
            PredicateClause(
                PredicateClauseKind.AGGREGATE_PRIMARY_BEATS_CONTROL,
                "stressed_net_return",
                None,
                None,
                None,
            ),
            PredicateClause(
                PredicateClauseKind.AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD,
                "signal_accuracy",
                "0.50",
                3,
                None,
            ),
            PredicateClause(PredicateClauseKind.REQUIRED_OOS_FOLD_COUNT, None, None, 3, None),
            PredicateClause(PredicateClauseKind.MINIMUM_FULL_WINDOW_SIGNAL_COUNT, None, None, None, 20),
        )
    )


def evaluate_falsification_predicate(
    predicate: FalsificationPredicate,
    source: object,
) -> PredicateEvaluation:
    if type(predicate) is not FalsificationPredicate:
        raise TypeError("predicate evaluation requires an exact FalsificationPredicate")
    metrics = _source_metrics(source)
    results: list[tuple[str, str]] = []
    missing: list[str] = []
    for clause in predicate.clauses:
        outcome, clause_missing = _evaluate_clause(clause, metrics)
        results.append((clause.kind.value, outcome.value))
        missing.extend(clause_missing)
    if any(status == ClauseOutcome.FAIL.value for _, status in results):
        verdict = FinalVerdict.REJECT
    elif any(status == ClauseOutcome.INSUFFICIENT.value for _, status in results):
        verdict = FinalVerdict.NEED_MORE_DATA
    else:
        verdict = FinalVerdict.ACCEPT
    return PredicateEvaluation(verdict, tuple(results), tuple(dict.fromkeys(missing)))


def _source_metrics(source: object) -> dict[str, str]:
    if type(source) is ExperimentResultPacket:
        return packet_metric_map(source)
    if type(source) is dict:
        return {str(key): str(value) for key, value in source.items()}
    metrics = getattr(source, "metric_map", None)
    if callable(metrics):
        loaded = metrics()
        if type(loaded) is dict:
            return {str(key): str(value) for key, value in loaded.items()}
    if type(metrics) is dict:
        return {str(key): str(value) for key, value in metrics.items()}
    raise TypeError("predicate evaluation requires a packet, treatment view, or metric map")


def enforce_verdict_predicate_congruence(
    verdict: ResearchFinalVerdict,
    brief: DecisionBrief,
    hypothesis: HypothesisSpec,
    source: object,
) -> tuple[ResearchFinalVerdict, DecisionBrief, PredicateEvaluation]:
    predicate = parse_falsification_condition(hypothesis.falsification_condition)
    if predicate is None:
        raise ValueError("R-005 correction-v2 requires a typed falsification predicate")
    evaluation = evaluate_falsification_predicate(predicate, source)
    expected = evaluation.outcome
    if verdict.verdict is FinalVerdict.MODIFY:
        if expected is not FinalVerdict.REJECT:
            raise PredicateVerdictMismatch("MODIFY cannot rewrite a non-REJECT predicate outcome")
        if verdict.modified_hypothesis is None or verdict.auto_execute_modified:
            raise PredicateVerdictMismatch("MODIFY must create a new hypothesis version and must not auto-execute")
        return verdict, brief, evaluation
    if verdict.verdict is not expected or brief.verdict is not expected:
        raise PredicateVerdictMismatch(
            f"agent verdict {verdict.verdict.value} does not match predicate outcome {expected.value}"
        )
    return verdict, brief, evaluation


def _evaluate_clause(clause: PredicateClause, metrics: dict[str, str]) -> tuple[ClauseOutcome, tuple[str, ...]]:
    if clause.kind is PredicateClauseKind.MINIMUM_FULL_WINDOW_SIGNAL_COUNT:
        count = _full_window_signal_count(metrics)
        if count is None:
            return ClauseOutcome.INSUFFICIENT, ("signal_count",)
        assert clause.minimum_count is not None
        return (ClauseOutcome.PASS if count >= clause.minimum_count else ClauseOutcome.FAIL), ()
    if clause.kind is PredicateClauseKind.REQUIRED_OOS_FOLD_COUNT:
        if "fold_count" not in metrics:
            return ClauseOutcome.INSUFFICIENT, ("fold_count",)
        assert clause.fold_n is not None
        actual = int(metrics["fold_count"])
        if actual >= clause.fold_n:
            return ClauseOutcome.PASS, ()
        missing = tuple(f"fold_{index}_signal_accuracy" for index in range(actual + 1, clause.fold_n + 1))
        if metrics.get("stopped_early") == "true":
            return ClauseOutcome.FAIL, ()
        return ClauseOutcome.INSUFFICIENT, missing
    assert clause.metric is not None
    if clause.kind is PredicateClauseKind.AGGREGATE_PRIMARY_BEATS_CONTROL:
        return _beats_control(clause.metric, metrics)
    if clause.kind is PredicateClauseKind.PRIMARY_POSITIVE_AND_BEATS_CONTROL:
        if clause.metric not in metrics:
            return ClauseOutcome.INSUFFICIENT, (clause.metric,)
        if Decimal(metrics[clause.metric]) <= 0:
            return ClauseOutcome.FAIL, ()
        return _beats_control(clause.metric, metrics)
    if clause.kind is PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL:
        return _each_fold_beats_control(clause, metrics)
    return _at_least_n_folds(clause, metrics)


def _beats_control(metric: str, metrics: dict[str, str]) -> tuple[ClauseOutcome, tuple[str, ...]]:
    control = CONTROL_BY_PRIMARY[metric]
    missing = tuple(name for name in (metric, control) if name not in metrics)
    if missing:
        return ClauseOutcome.INSUFFICIENT, missing
    if Decimal(metrics[metric]) > Decimal(metrics[control]):
        return ClauseOutcome.PASS, ()
    return ClauseOutcome.FAIL, ()


def _each_fold_beats_control(clause: PredicateClause, metrics: dict[str, str]) -> tuple[ClauseOutcome, tuple[str, ...]]:
    assert clause.metric is not None
    if clause.metric not in FOLD_METRIC_FIELDS:
        raise ValueError(f"{clause.metric} cannot be evaluated as a per-fold predicate metric")
    if "fold_count" not in metrics:
        return ClauseOutcome.INSUFFICIENT, ("fold_count",)
    fold_count = int(metrics["fold_count"])
    if fold_count < 1:
        primary, _control = fold_metric_fields(clause.metric, 1)
        return ClauseOutcome.INSUFFICIENT, (primary,)
    missing: list[str] = []
    failed = False
    for index in range(1, fold_count + 1):
        primary, control = fold_metric_fields(clause.metric, index)
        if primary not in metrics or control not in metrics:
            missing.extend(name for name in (primary, control) if name not in metrics)
            continue
        if Decimal(metrics[primary]) <= Decimal(metrics[control]):
            failed = True
    if failed:
        return ClauseOutcome.FAIL, ()
    if missing:
        return ClauseOutcome.INSUFFICIENT, tuple(missing)
    return ClauseOutcome.PASS, ()


def _at_least_n_folds(clause: PredicateClause, metrics: dict[str, str]) -> tuple[ClauseOutcome, tuple[str, ...]]:
    assert clause.fold_n is not None and clause.threshold is not None and clause.metric is not None
    if clause.metric not in FOLD_METRIC_FIELDS:
        raise ValueError(f"{clause.metric} cannot be evaluated as a per-fold predicate metric")
    if "fold_count" not in metrics:
        return ClauseOutcome.INSUFFICIENT, ("fold_count",)
    fold_count = int(metrics["fold_count"])
    planned = int(metrics["planned_fold_count"]) if "planned_fold_count" in metrics else fold_count
    stopped = metrics.get("stopped_early") == "true"
    threshold = Decimal(clause.threshold)
    missing_fields: list[str] = []
    passed = 0
    for index in range(1, fold_count + 1):
        name, _control = fold_metric_fields(clause.metric, index)
        count_name = f"fold_{index}_signal_count"
        if name not in metrics:
            missing_fields.append(name)
            continue
        if count_name in metrics and Decimal(metrics[count_name]) < 1:
            continue
        if Decimal(metrics[name]) > threshold:
            passed += 1
    if passed >= clause.fold_n:
        return ClauseOutcome.PASS, ()
    if stopped:
        remaining = 0
    else:
        remaining = max(0, planned - fold_count) + len(missing_fields)
        if "planned_fold_count" not in metrics:
            remaining = max(remaining, max(0, clause.fold_n - fold_count) + len(missing_fields))
    if passed + remaining < clause.fold_n:
        return ClauseOutcome.FAIL, ()
    missing = tuple(missing_fields) or tuple(
        fold_metric_fields(clause.metric, index)[0] for index in range(fold_count + 1, max(clause.fold_n, planned) + 1)
    )
    return ClauseOutcome.INSUFFICIENT, missing


def _full_window_signal_count(metrics: dict[str, str]) -> int | None:
    if "full_window_signal_count" in metrics:
        return int(metrics["full_window_signal_count"])
    if "signal_count" in metrics:
        return int(metrics["signal_count"])
    return None


PREDICATE_CLAUSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "metric", "threshold", "fold_n", "minimum_count"],
    "properties": {
        "kind": {"type": "string", "enum": [item.value for item in PredicateClauseKind]},
        "metric": {"type": ["string", "null"]},
        "threshold": {
            "type": ["string", "null"],
            "description": "Required string for at_least_n_oos_folds_above_threshold, otherwise null.",
        },
        "fold_n": {
            "type": ["integer", "null"],
            "minimum": 1,
            "description": "Required for at_least_n_oos_folds_above_threshold and required_oos_fold_count, otherwise null.",
        },
        "minimum_count": {
            "type": ["integer", "null"],
            "minimum": 1,
            "description": "Required for minimum_full_window_signal_count, otherwise null.",
        },
    },
}
PREDICATE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["clauses"],
    "properties": {
        "clauses": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": PREDICATE_CLAUSE_SCHEMA,
        }
    },
}
