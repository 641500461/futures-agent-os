from __future__ import annotations

import json
from pathlib import Path

from futures_agent_os.shared_kernel import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence/v5-012/release-review-2026-09-12.json"


def _load() -> dict[str, object]:
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _immutable(value: object) -> object:
    if isinstance(value, list):
        return tuple(_immutable(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _immutable(item) for key, item in value.items()}
    return value


def test_release_review_package_is_complete_and_blocks_unrestricted_enablement() -> None:
    package = _load()
    assert package["schema"] == "v5-012.simulation-launch-review.v1"
    assert package["task"] == "V5-012"
    assert package["status"] == "COMPLETE"
    assert package["decision"] == "RESTRICTED_SIMULATION_ONLY"
    assert package["enablement_gate"] == "DENY_UNTIL_BLOCKERS_CLOSED"
    assert package["research_and_simulation_only"] is True
    assert package["independent_version_exit_review"] is False
    domains = package["review_domains"]
    assert isinstance(domains, dict)
    assert set(domains) == {"product", "architecture", "risk", "data", "operations"}
    blockers = package["blocking_items"]
    assert isinstance(blockers, list) and len(blockers) == 4
    assert {item["status"] for item in blockers} == {"OPEN"}
    assert (ROOT / "docs/V5-012-SIMULATION-LAUNCH-REVIEW.md").exists()


def test_release_review_digest_is_content_addressed_and_references_prior_evidence() -> None:
    package = _load()
    digest = package.pop("evidence_digest")
    assert digest == canonical_sha256(_immutable(package))  # type: ignore[arg-type]
    refs = package["evidence_refs"]
    assert isinstance(refs, list)
    assert "evidence/v5-010/implementation-2026-09-11.json" in refs
    assert "evidence/v5-011/stability-run-2026-09-12.json" in refs
    assert "evidence/v5-012/runtime-cost-baseline-2026-09-12.json" in refs


def test_runtime_cost_baseline_does_not_turn_unavailable_pricing_into_zero() -> None:
    value = json.loads((ROOT / "evidence/v5-012/runtime-cost-baseline-2026-09-12.json").read_text(encoding="utf-8"))
    digest = value.pop("evidence_digest")
    assert digest == canonical_sha256(_immutable(value))  # type: ignore[arg-type]
    pricing = value["pricing"]
    assert isinstance(pricing, dict)
    assert pricing["model_provider_cost"] == "SUBSCRIPTION_UNAVAILABLE"
    assert pricing["token_cost"] == "SUBSCRIPTION_UNAVAILABLE"
    assert pricing["local_compute_currency_cost"] == "NOT_MEASURED"
