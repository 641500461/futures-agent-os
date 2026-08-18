import re
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE = PROJECT_ROOT / "docs" / "DOMAIN-BOUNDARY-BASELINE.md"
CONTEXT_MAP = PROJECT_ROOT / "docs" / "CONTEXT-MAP.md"
CONTEXTS_ROOT = PROJECT_ROOT / "docs" / "contexts"

EXPECTED_CONTEXTS = {
    "Reference Market Data": ("core", "reference-market-data"),
    "Market Intelligence": ("core", "market-intelligence"),
    "Research & Experiment": ("core", "research-experiment"),
    "Decision": ("core", "decision"),
    "Portfolio & Risk": ("core", "portfolio-risk"),
    "Execution & Simulation": ("core", "execution-simulation"),
    "Accounting & Settlement": ("core", "accounting-settlement"),
    "Learning & Review": ("core", "learning-review"),
    "Governance & Registry": ("core", "governance-registry"),
    "Agent Orchestration": ("supporting", "agent-orchestration"),
}

EXPECTED_OWNERS = {
    "Simulation Autonomy Mandate": "Decision",
    "Autonomy Mode Binding": "Decision",
    "Authorization Basis": "Decision",
    "Autonomy Gate Receipt": "Decision",
    "Risk Budget Reservation": "Portfolio & Risk",
    "Risk Decision": "Portfolio & Risk",
    "Protection Mandate": "Portfolio & Risk",
    "Risk Reduction Request": "Decision",
    "Risk Reduction Validation": "Execution & Simulation",
    "Protective Risk Action": "Execution & Simulation",
    "Order": "Execution & Simulation",
    "Fill": "Execution & Simulation",
    "Position": "Accounting & Settlement",
    "Ledger": "Accounting & Settlement",
    "Decision Journal": "Learning & Review",
    "Trade Episode": "Learning & Review",
}


def _table_rows(section: str) -> list[list[str]]:
    content = BASELINE.read_text(encoding="utf-8")
    match = re.search(rf"## {re.escape(section)}\n\n.*?(?=\n## |\Z)", content, re.DOTALL)
    assert match, section
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in match.group(0).splitlines()
        if line.startswith("|") and not set(line.replace("|", "").strip()) <= {"-", " "}
    ][1:]


def test_context_roster_has_nine_core_contexts_and_one_supporting_context() -> None:
    rows = _table_rows("Context roster")
    actual = {name: (classification, path) for name, classification, path in rows}
    context_map = CONTEXT_MAP.read_text(encoding="utf-8")

    assert set(actual) == set(EXPECTED_CONTEXTS)
    assert Counter(classification for classification, _ in actual.values()) == {"core": 9, "supporting": 1}
    assert "./DOMAIN-BOUNDARY-BASELINE.md" in context_map
    for name, (classification, directory) in EXPECTED_CONTEXTS.items():
        assert actual[name][0] == classification
        assert (CONTEXTS_ROOT / directory / "CONTEXT.md").is_file()
        assert name in context_map


def test_each_boundary_aggregate_has_one_owner_and_owner_defines_its_language() -> None:
    rows = _table_rows("Aggregate ownership")
    owners = {aggregate: owner for aggregate, owner, _ in rows}

    assert owners == EXPECTED_OWNERS
    assert len(owners) == len(rows)
    for aggregate, owner in owners.items():
        directory = EXPECTED_CONTEXTS[owner][1]
        context = (CONTEXTS_ROOT / directory / "CONTEXT.md").read_text(encoding="utf-8")
        assert f"**{aggregate}**:" in context, f"{aggregate} must be defined by {owner}"


def test_ubiquitous_language_terms_are_unique_and_have_avoid_guidance() -> None:
    definitions: dict[str, list[str]] = {}

    for context_file in sorted(CONTEXTS_ROOT.glob("*/CONTEXT.md")):
        content = context_file.read_text(encoding="utf-8")
        matches = list(re.finditer(r"^\*\*(.+?)\*\*:\n", content, re.MULTILINE))
        assert matches, f"{context_file} has no canonical language"
        for index, match in enumerate(matches):
            term = match.group(1)
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            definition = content[match.end():end]
            relative_path = str(context_file.relative_to(PROJECT_ROOT))
            definitions.setdefault(term, []).append(relative_path)
            assert "_Avoid_:" in definition, f"{term} in {relative_path} has no _Avoid_ guidance"

    duplicates = {term: paths for term, paths in definitions.items() if len(paths) > 1}
    assert duplicates == {}
    assert len(definitions) >= 200


def test_critical_owner_separation_is_explicit() -> None:
    owners = {aggregate: owner for aggregate, owner, _ in _table_rows("Aggregate ownership")}

    assert {owners[name] for name in (
        "Simulation Autonomy Mandate",
        "Autonomy Mode Binding",
        "Authorization Basis",
        "Autonomy Gate Receipt",
    )} == {"Decision"}
    assert owners["Risk Decision"] == owners["Protection Mandate"] == "Portfolio & Risk"
    assert owners["Risk Reduction Validation"] == owners["Protective Risk Action"] == "Execution & Simulation"
    assert owners["Position"] == owners["Ledger"] == "Accounting & Settlement"
    assert owners["Decision Journal"] == owners["Trade Episode"] == "Learning & Review"


def test_projection_and_reduction_invariants_are_documented() -> None:
    content = BASELINE.read_text(encoding="utf-8")

    assert "`Risk Reduction Validation` must precede `Protective Risk Action`" in content
    assert "`Decision Journal` and `Trade Episode` are projections only" in content
    assert "cannot write back to their sources" in content
