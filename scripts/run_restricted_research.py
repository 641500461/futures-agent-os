"""Run the approved SHFE-only research lane.

This entry point deliberately reuses the already qualified MVP-R-005 research
composition while narrowing its data authority to the active SHFE AG/CU
manifest.  It never loads CZCE data and never creates trading facts.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import run_mvp_r_005 as runner

from futures_agent_os.adapters import OfficialCodexAppServerTransport
from futures_agent_os.reference_market_data import DatasetLayer, LocalFileDataStore
from futures_agent_os.research_experiment.mvp_r_005 import MvpR005ModelWorkloads
from futures_agent_os.research_experiment.mvp_r_003 import StructuredModelConfig
from futures_agent_os.shared_kernel import EntityId, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

ROOT = Path(__file__).resolve().parents[1]


MANIFEST_PATH = ROOT / "evidence" / "v5-012" / "deployment-data-manifest-shfe-research-2026-09-12.json"
DATA_ROOT = ROOT / "datasets" / "mvp-r-001"
ALLOWED_INSTRUMENTS = frozenset({"SHFE.AG.DOMINANT_OI", "SHFE.CU.DOMINANT_OI"})


def _load_authorized_shfe():
    manifest = cast(dict[str, object], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    if manifest.get("status") != "ACTIVE_RESEARCH_ONLY" or manifest.get("provider") != "SHFE":
        raise RuntimeError("SHFE research manifest is not active")
    if (
        manifest.get("decision_or_execution_use") is not False
        or manifest.get("real_money_or_order_routing") is not False
    ):
        raise RuntimeError("research manifest has an unsafe use boundary")
    dataset = cast(dict[str, object], manifest["dataset"])
    instruments = frozenset(cast(list[str], dataset["instrument_universe"]))
    if instruments != ALLOWED_INSTRUMENTS:
        raise RuntimeError("research manifest instrument scope is not exactly SHFE AG/CU")
    dataset_id = EntityId.parse(cast(str, dataset["dataset_id"]))
    store = LocalFileDataStore(DATA_ROOT / "normalized", DatasetLayer.NORMALIZED_PIT)
    loaded = store.get(dataset_id)
    expected_hash = cast(str, dataset["content_hash"])
    if loaded.manifest.content_hash != expected_hash:
        raise RuntimeError("local SHFE object does not match the deployment manifest")
    if frozenset(loaded.manifest.instrument_universe) != ALLOWED_INSTRUMENTS:
        raise RuntimeError("local dataset contains an instrument outside SHFE AG/CU")
    return loaded


def _filtered_roster(allowed_manifest_sha: str) -> dict[str, object]:
    source = cast(dict[str, object], json.loads((ROOT / "evidence" / "mvp-r-005" / "roster.json").read_text()))
    episodes = tuple(
        item
        for item in cast(list[object], source["episodes"])
        if cast(dict[str, object], item)["instrument"] in ALLOWED_INSTRUMENTS
    )
    if not episodes:
        raise RuntimeError("frozen roster contains no SHFE episodes")
    payload: dict[str, object] = {
        "schema_version": "restricted-shfe-research.roster.v1",
        "source_roster_sha256": source.get("content_sha256"),
        "manifest_content_hash": allowed_manifest_sha,
        "instrument_scope": tuple(sorted(ALLOWED_INSTRUMENTS)),
        "episodes": episodes,
    }
    return {**payload, "content_sha256": canonical_sha256(cast(JsonValue, payload))}


def run(
    *,
    episode: str | None,
    limit: int,
    execute: bool,
    model: str,
    effort: str,
    provider: str = "custom",
    timeout_seconds: int = 300,
) -> dict[str, object]:
    if limit < 1 or timeout_seconds < 1:
        raise ValueError("limit and timeout_seconds must be positive")
    dataset = _load_authorized_shfe()
    filtered = _filtered_roster(dataset.manifest.content_hash)
    episodes = cast(tuple[object, ...], filtered["episodes"])
    if episode is not None:
        episodes = tuple(item for item in episodes if cast(dict[str, object], item)["episode_id"] == episode)
        if not episodes:
            raise ValueError("episode is not an approved SHFE episode")
    episodes = episodes[:limit]
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_root = DATA_ROOT / "runs" / "restricted-shfe" / run_id
    evidence_root = ROOT / "evidence" / "restricted-shfe" / run_id
    evidence_root.mkdir(parents=True, exist_ok=False)
    run_root.mkdir(parents=True, exist_ok=False)
    roster_payload = {**filtered, "episodes": episodes}
    roster = {**roster_payload, "content_sha256": canonical_sha256(cast(JsonValue, roster_payload))}
    (evidence_root / "roster.json").write_text(canonical_json_text(cast(JsonValue, roster)) + "\n", encoding="utf-8")
    summary: dict[str, object] = {
        "schema_version": "restricted-shfe-research.run.v1",
        "run_id": run_id,
        "status": "PLANNED" if not execute else "RUNNING",
        "manifest": str(MANIFEST_PATH.relative_to(ROOT)),
        "manifest_content_hash": dataset.manifest.content_hash,
        "instrument_scope": tuple(sorted(ALLOWED_INSTRUMENTS)),
        "episode_ids": tuple(cast(str, cast(dict[str, object], item)["episode_id"]) for item in episodes),
        "model": model,
        "reasoning_effort": effort,
        "expected_provider": provider,
        "timeout_seconds": timeout_seconds,
        "real_money_or_order_routing": False,
        "research_only": True,
    }
    if not execute:
        summary["status"] = "PLAN_READY"
        (evidence_root / "run.json").write_text(canonical_json_text(cast(JsonValue, summary)) + "\n", encoding="utf-8")
        return summary

    original_stored = runner._stored_datasets
    original_run_root = runner.RUN_ROOT
    original_evidence_root = runner.EVIDENCE_ROOT
    original_active_mode = runner.ACTIVE_EXECUTION_MODE
    original_suite = runner._suite
    try:
        runner._stored_datasets = lambda: (dataset,)
        runner.RUN_ROOT = run_root
        runner.EVIDENCE_ROOT = evidence_root
        runner.ACTIVE_EXECUTION_MODE = "RESTRICTED_SHFE_RESEARCH"
        runner._suite = _restricted_suite
        issued, result_port, config = runner._issue_episodes(roster)
        workloads = MvpR005ModelWorkloads(OfficialCodexAppServerTransport())
        for item in issued:
            try:
                runner._run_episode(
                    item,
                    config,
                    result_port,
                    workloads,
                    StructuredModelConfig(model, effort, expected_provider=provider, timeout_seconds=timeout_seconds),
                    StructuredModelConfig(model, effort, expected_provider=provider, timeout_seconds=timeout_seconds),
                    StructuredModelConfig(model, effort, expected_provider=provider, timeout_seconds=timeout_seconds),
                )
            except Exception as error:
                failure: dict[str, object] = {
                    "schema_version": "restricted-shfe-research.failure.v1",
                    "status": "FAILED_CLOSED",
                    "episode_id": item.contract.episode_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "model": model,
                    "reasoning_effort": effort,
                    "expected_provider": provider,
                    "research_only": True,
                    "real_money_or_order_routing": False,
                }
                evidence_payload = getattr(error, "evidence_payload", None)
                if callable(evidence_payload):
                    failure["observation"] = evidence_payload()
                (evidence_root / f"{item.contract.episode_id}-failure.json").write_text(
                    json.dumps(failure, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
                )
                raise
        summary["status"] = "COMPLETED"
        summary["output_root"] = str(run_root.relative_to(ROOT))
    finally:
        runner._stored_datasets = original_stored
        runner.RUN_ROOT = original_run_root
        runner.EVIDENCE_ROOT = original_evidence_root
        runner.ACTIVE_EXECUTION_MODE = original_active_mode
        runner._suite = original_suite
    (evidence_root / "run.json").write_text(canonical_json_text(cast(JsonValue, summary)) + "\n", encoding="utf-8")
    return summary


def _restricted_suite(dataset_refs, authority_id):
    """Build a research-only suite whose universe is exactly AG/CU.

    The normal MVP evaluation suite intentionally requires 3–4 instruments.
    This separate typed flag preserves that gate while allowing the approved
    two-instrument deployment lane to run without smuggling CZCE into scope.
    """

    model_config = runner._model_config()
    tools = runner.frozen_mvp_tool_specs(runner.REQUEST_SHA256)
    runtime = runner.FrozenRuntimeIdentity(
        runner.canonical_sha256({"prompt": "restricted-shfe-research"}),
        runner.hashlib.sha256(runner.Path(__file__).read_bytes()).hexdigest(),
        runner.canonical_sha256({"policy": "research-only-no-trading"}),
    )
    return runner.EvaluationSuite(
        runner.semantic_entity_id("evaluation_suite", {"task": "restricted-shfe-research", "roster": "v1"}),
        1,
        model_config.content_sha256,
        runtime.agent_sha256,
        runner.canonical_sha256(
            tuple(
                {"name": tool.name, "description": tool.description, "parameters_json": tool.parameters_json}
                for tool in tools
            )
        ),
        runtime.content_sha256,
        authority_id,
        "restricted-shfe-research.evaluator",
        tuple(dataset_refs),
        tuple(sorted(ALLOWED_INSTRUMENTS)),
        "approved-shfe-ag-cu-research.v1",
        "restricted-shfe-research.v1",
        ("decision_brief.v1", "fold_signal_accuracy.v1"),
        runner.MVP_R_REQUIRED_BASELINES,
        30,
        50,
        10,
        3,
        True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the active SHFE AG/CU research-only lane")
    parser.add_argument("--episode")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--execute", action="store_true", help="invoke the configured research model")
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--effort", choices=("medium", "high", "xhigh"), default="high")
    parser.add_argument("--provider", default="custom")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.limit < 1 or args.timeout_seconds < 1:
        raise SystemExit("--limit and --timeout-seconds must be positive")
    print(
        json.dumps(
            run(
                episode=args.episode,
                limit=args.limit,
                execute=args.execute,
                model=args.model,
                effort=args.effort,
                provider=args.provider,
                timeout_seconds=args.timeout_seconds,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
