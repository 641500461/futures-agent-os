"""Validate the V0-013 donor-asset qualification record without accessing a donor."""

from __future__ import annotations

from hashlib import sha256
from collections import Counter
import json
from pathlib import Path
from typing import Any


ALLOWED_REUSE_LEVELS = frozenset({"R1_PORT", "R2_REIMPLEMENT", "R3_EVIDENCE_ONLY", "R4_REJECT"})
ALLOWED_STATUSES = frozenset({"CANDIDATE", "DEFERRED", "EVIDENCE_ONLY", "REJECTED", "QUALIFIED"})
REQUIRED_GATES = frozenset(
    {"provenance", "target_interface", "isolation", "security_scan", "license", "new_project_tests"}
)
EXPECTED_ASSETS = {
    "symbol_registry": ("R1_PORT", ("futures_symbol_registry.py",)),
    "symbol_resolver": ("R2_REIMPLEMENT", ("futures_symbol_resolver.py",)),
    "contract_metadata": ("R2_REIMPLEMENT", ("contract_metadata.py",)),
    "market_data_service": ("R2_REIMPLEMENT", ("market_data_service.py",)),
    "external_quote_adapters": (
        "R2_REIMPLEMENT",
        ("akshare_fallback_v2.py", "akshare_kline_fallback.py", "tqsdk_quote_runner.py"),
    ),
    "technical_indicators": ("R1_PORT", ("technical_indicators.py",)),
    "kline_analyzer": ("R2_REIMPLEMENT", ("kline_analyzer.py",)),
    "intraday_context": ("R2_REIMPLEMENT", ("intraday_context.py",)),
    "candidate_screener": ("R2_REIMPLEMENT", ("futures_candidate_screener.py",)),
    "intraday_candidate_screener": ("R3_EVIDENCE_ONLY", ("intraday_candidate_screener.py",)),
    "strategy_spec": (
        "R2_REIMPLEMENT",
        ("strategy_spec.py", "strategy_specs/intraday_auto_v1.json", "strategy_specs/intraday_auto_v2.json"),
    ),
    "trade_setup": ("R3_EVIDENCE_ONLY", ("futures_trade_setup.py",)),
    "watch_trigger_engine": ("R3_EVIDENCE_ONLY", ("watch_trigger_engine.py",)),
    "llm_router": ("R3_EVIDENCE_ONLY", ("llm_router.py",)),
    "external_backtest_evidence": ("R3_EVIDENCE_ONLY", ("strategy_experiment_service.py",)),
    "position_sizing": ("R2_REIMPLEMENT", ("position_sizing.py",)),
    "account_capital": ("R2_REIMPLEMENT", ("account_capital.py",)),
    "execution_safety": ("R2_REIMPLEMENT", ("execution_safety.py",)),
    "sim_trade_bridge": ("R4_REJECT", ("futures_sim_trade_bridge.py",)),
    "position_management": ("R3_EVIDENCE_ONLY", ("position_management.py",)),
    "execution_quality": ("R1_PORT", ("execution_quality.py",)),
    "db_manager": ("R4_REJECT", ("db_manager.py",)),
    "trade_events_and_position_ledger": ("R3_EVIDENCE_ONLY", ("db_manager.py",)),
    "notification_inbox": ("R2_REIMPLEMENT", ("db_manager.py",)),
    "daily_weekly_review": ("R2_REIMPLEMENT", ("daily_review.py", "weekly_review.py")),
    "trade_kline_review": ("R2_REIMPLEMENT", ("trade_kline_review.py",)),
    "post_exit_review": ("R1_PORT", ("post_exit_review.py",)),
    "unexecuted_setup_review": ("R2_REIMPLEMENT", ("unexecuted_setup_review.py",)),
    "review_action_items": ("R2_REIMPLEMENT", ("review_action_items.py",)),
    "experiment_strategy_pool": ("R3_EVIDENCE_ONLY", ("experiment_strategy_pool.py",)),
    "strategy_experiment_service": ("R3_EVIDENCE_ONLY", ("strategy_experiment_service.py",)),
    "improvement_governance": ("R2_REIMPLEMENT", ("improvement_governance.py",)),
    "development_task_runner": ("R3_EVIDENCE_ONLY", ("development_task_runner.py",)),
    "interactive_chart_report": ("R1_PORT", ("interactive_chart_report.py",)),
}
# The canonical whole-record digest locks source blob parts and every other decision.
EXPECTED_MANIFEST_SHA256 = "f 6 b 0 4 7 7 c e b 6 8 4 2 2 2 3 6 9 e 9 d 6 6 2 6 f 8 4 8 4 6 1 8 2 e 5 a 0 5 c 3 5 2 1 6 6 1 b 3 3 0 3 f 7 2 f f 8 2 3 0 c b"


def repository_qualification_manifest_path() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "v0_013_legacy_asset_qualification.json"


def load_qualification_manifest(path: Path | None = None) -> dict[str, Any]:
    candidate_path = path or repository_qualification_manifest_path()
    return json.loads(candidate_path.read_text(encoding="utf-8"))


def validate_qualification_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != "1.0":
        raise ValueError("qualification manifest schema_version must be 1.0")
    donor = manifest.get("donor")
    donor_commit_parts = donor.get("git_commit_parts") if isinstance(donor, dict) else None
    donor_commit = (
        "".join(part.replace(" ", "") for part in donor_commit_parts) if isinstance(donor_commit_parts, list) else ""
    )
    if (
        not isinstance(donor, dict)
        or len(donor_commit) != 40
        or any(char not in "0123456789abcdef" for char in donor_commit)
    ):
        raise ValueError("qualification manifest must pin the donor git commit")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("qualification manifest must contain assets")

    seen_ids: set[str] = set()
    qualified = 0
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("each asset must be an object")
        asset_id = asset.get("id")
        if not isinstance(asset_id, str) or not asset_id or asset_id in seen_ids:
            raise ValueError("asset ids must be unique and non-empty")
        seen_ids.add(asset_id)
        if asset.get("reuse_level") not in ALLOWED_REUSE_LEVELS:
            raise ValueError(f"{asset_id} has an invalid reuse level")
        status = asset.get("qualification_status")
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"{asset_id} has an invalid qualification status")
        gates = asset.get("gates")
        if not isinstance(gates, dict) or set(gates) != REQUIRED_GATES:
            raise ValueError(f"{asset_id} must record every mandatory gate")
        for gate_name, evidence in gates.items():
            if not isinstance(evidence, dict) or not isinstance(evidence.get("status"), str):
                raise ValueError(f"{asset_id} has malformed {gate_name} evidence")
            if not str(evidence.get("detail", "")).strip():
                raise ValueError(f"{asset_id} has empty {gate_name} evidence")
        sources = asset.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"{asset_id} must identify donor sources")
        for source in sources:
            if not isinstance(source, dict) or not str(source.get("path", "")).strip():
                raise ValueError(f"{asset_id} has malformed source provenance")
            blob_parts = source.get("blob_parts")
            if blob_parts == "ABSENT":
                continue
            blob = "".join(part.replace(" ", "") for part in blob_parts) if isinstance(blob_parts, list) else ""
            if (
                not isinstance(blob_parts, list)
                or len(blob) != 40
                or any(char not in "0123456789abcdef" for char in blob)
            ):
                raise ValueError(f"{asset_id} source must contain a split blob hash or ABSENT")
        expected_asset = EXPECTED_ASSETS.get(asset_id)
        actual_asset = (asset["reuse_level"], tuple(source["path"] for source in sources))
        if expected_asset != actual_asset:
            raise ValueError(f"{asset_id} does not match the target-owned qualification baseline")
        if status == "QUALIFIED":
            qualified += 1
            if asset["reuse_level"] == "R4_REJECT":
                raise ValueError(f"{asset_id} cannot qualify an R4 rejection")
            if any(gates[name]["status"] != "PASS" for name in REQUIRED_GATES):
                raise ValueError(f"{asset_id} cannot qualify with an unmet gate")
        if status == "REJECTED" and not str(asset.get("rejection_reason", "")).strip():
            raise ValueError(f"{asset_id} rejection requires a reason")
        if status != "QUALIFIED" and not str(asset.get("next_action", "")).strip():
            raise ValueError(f"{asset_id} requires a next action or deferral statement")

    summary = manifest.get("summary")
    expected_summary = Counter(asset["qualification_status"].lower() for asset in assets)
    if not isinstance(summary, dict) or summary != dict(expected_summary):
        raise ValueError("summary must exactly equal asset qualification statuses")
    if summary.get("qualified", 0) != qualified:
        raise ValueError("summary qualified count must equal qualified assets")
    if donor.get("license") != "VERIFIED" and qualified:
        raise ValueError("an unverified donor license prohibits qualification")
    if qualified != 0:
        raise ValueError("V0-013 may not qualify an asset before a new implementation and tests exist")
    if seen_ids != set(EXPECTED_ASSETS):
        raise ValueError("manifest asset ids do not match the target-owned qualification baseline")
    canonical_manifest = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    if sha256(canonical_manifest).hexdigest() != EXPECTED_MANIFEST_SHA256.replace(" ", ""):
        raise ValueError("manifest content does not match the target-owned qualification baseline digest")
