from datetime import UTC, datetime, timedelta
import pytest
from futures_agent_os.research_experiment import ExternalEvidence, EvidenceFormat, EvidenceCatalog


def test_evidence_is_point_in_time_and_non_authoritative():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    e = ExternalEvidence(
        "e", "wire", "CC-BY", now, now + timedelta(hours=1), "HIGH", EvidenceFormat.UNSTRUCTURED, "a" * 64
    )
    c = EvidenceCatalog()
    assert not e.can_be_business_instruction
    assert c.at(now) == ()
    with pytest.raises(ValueError):
        ExternalEvidence("e", "s", "l", now, now - timedelta(seconds=1), "q", EvidenceFormat.STRUCTURED, "x")
