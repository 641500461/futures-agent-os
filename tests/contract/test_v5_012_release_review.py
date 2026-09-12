from __future__ import annotations

import json
from pathlib import Path

from futures_agent_os.shared_kernel import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence/v5-012/release-review-2026-09-12.json"
EXIT_EVIDENCE = ROOT / "evidence/v5-exit/independent-review-2026-09-12.json"


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
    assert package["enablement_gate"] == "ALLOW_RESTRICTED_RESEARCH_SIMULATION"
    assert package["research_and_simulation_only"] is True
    assert package["independent_version_exit_review"] is True
    assert package["reviewer_model"] == "gpt-5.6-sol"
    assert package["reviewer_reasoning_effort"] == "high"
    domains = package["review_domains"]
    assert isinstance(domains, dict)
    assert set(domains) == {"product", "architecture", "risk", "data", "operations"}
    blockers = package["blocking_items"]
    assert isinstance(blockers, list) and len(blockers) == 4
    assert {item["id"]: item["status"] for item in blockers} == {
        "V5-012-B1": "CLOSED",
        "V5-012-B2": "CLOSED",
        "V5-012-B3": "CLOSED",
        "V5-012-B4": "CLOSED",
    }
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
    assert "evidence/v5-012/deployment-data-inventory-2026-09-12.json" in refs
    assert "evidence/v5-012/source-terms-observation-2026-09-12.json" in refs
    assert "evidence/v5-012/paper-scope-decision-2026-09-12.json" in refs
    assert "evidence/v5-012/deployment-data-manifest-shfe-research-2026-09-12.json" in refs
    assert "evidence/v5-exit/independent-review-2026-09-12.json" in refs


def test_independent_v5_exit_review_is_content_addressed_and_keeps_release_blockers_open() -> None:
    review = json.loads(EXIT_EVIDENCE.read_text(encoding="utf-8"))
    digest = review.pop("evidence_digest")
    assert digest == canonical_sha256(_immutable(review))
    assert review["reviewer_model"] == "gpt-5.6-sol"
    assert review["reviewer_reasoning_effort"] == "high"
    assert review["reviewer_identity"] == "/root/v5_exit_independent_sol"
    expected_source_commit = "".join(("3a99e32d", "09f35477", "70e3fb55", "9dacd547", "d2a78ea7"))
    assert review["source_commit"] == expected_source_commit
    assert review["verdict"] == "PASS"
    assert review["enablement_gate"] == "DENY_UNTIL_BLOCKERS_CLOSED"
    blockers = review["remaining_release_blockers"]
    assert isinstance(blockers, list)
    assert {item["id"]: item["status"] for item in blockers} == {
        "V5-012-B1": "CLOSED",
        "V5-012-B2": "OPEN",
        "V5-012-B3": "OPEN",
        "V5-012-B4": "OPEN",
    }


def test_runtime_cost_baseline_does_not_turn_unavailable_pricing_into_zero() -> None:
    value = json.loads((ROOT / "evidence/v5-012/runtime-cost-baseline-2026-09-12.json").read_text(encoding="utf-8"))
    digest = value.pop("evidence_digest")
    assert digest == canonical_sha256(_immutable(value))  # type: ignore[arg-type]
    pricing = value["pricing"]
    assert isinstance(pricing, dict)
    assert pricing["model_provider_cost"] == "SUBSCRIPTION_UNAVAILABLE"
    assert pricing["token_cost"] == "SUBSCRIPTION_UNAVAILABLE"
    assert pricing["local_compute_currency_cost"] == "NOT_MEASURED"


def test_paper_scope_closure_does_not_claim_calibration_or_enablement() -> None:
    package = _load()
    scope = json.loads((ROOT / "evidence/v5-012/paper-scope-decision-2026-09-12.json").read_text())
    digest = scope.pop("evidence_digest")
    assert digest == canonical_sha256(_immutable(scope))
    assert package["paper_scope_decision"] == scope["decision"] == "PAPER_DISABLED_BY_SCOPE"
    assert scope["status"] == "DISABLED"
    assert scope["representative_observations_present"] is False
    assert scope["calibration_status"] == "NOT_APPLICABLE_WHILE_DISABLED"
    assert "L5_paper_realism" in scope["claims_forbidden"]
    assert package["enablement_gate"] == "ALLOW_RESTRICTED_RESEARCH_SIMULATION"
    assert next(item for item in package["realism_levels"] if item["level"] == "L5")["status"] == "NOT_ENABLED"
