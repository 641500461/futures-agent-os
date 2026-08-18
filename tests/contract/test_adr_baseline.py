import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADR_ROOT = PROJECT_ROOT / "docs" / "adr"
BASELINE_NUMBERS = set(range(1, 8))
ALLOWED_STATUSES = {"proposed", "accepted", "deprecated"}
REQUIRED_HEADINGS = {"## Context", "## Decision", "## Consequences", "## Considered Options"}


def _decision_files() -> list[Path]:
    return sorted(ADR_ROOT.glob("[0-9][0-9][0-9][0-9]-*.md"))


def test_adr_numbers_are_unique_and_contiguous() -> None:
    files = _decision_files()
    numbers = [int(path.name[:4]) for path in files]

    assert numbers == list(range(1, len(files) + 1))
    assert len({path.name for path in files}) == len(files)


def test_adrs_record_status_tradeoffs_and_consequences() -> None:
    for path in _decision_files():
        content = path.read_text(encoding="utf-8")
        headings = {line for line in content.splitlines() if line.startswith("## ")}
        status_match = re.search(r"\A---\nstatus: ([a-z]+)\n---\n", content)

        assert status_match, path.name
        assert status_match.group(1) in ALLOWED_STATUSES, path.name
        assert REQUIRED_HEADINGS <= headings, path.name
        assert "拒绝" in content or "暂不采用" in content, path.name


def test_v0_architecture_baseline_is_accepted() -> None:
    for path in _decision_files():
        if int(path.name[:4]) not in BASELINE_NUMBERS:
            continue
        content = path.read_text(encoding="utf-8")
        assert re.search(r"\A---\nstatus: accepted\n---\n", content), path.name
