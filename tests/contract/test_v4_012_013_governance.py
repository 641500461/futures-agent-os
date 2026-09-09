import pytest
from futures_agent_os.research_experiment import DriftKind, DriftTriggerEngine, GovernanceAgent


def test_trigger_idempotent_and_pause():
    e = DriftTriggerEngine()
    a = e.emit(DriftKind.OOS_DECAY, "strategy:x", "decay")
    assert a and e.emit(DriftKind.OOS_DECAY, "strategy:x", "decay") is None
    e.pause()
    assert e.emit(DriftKind.REGIME_CHANGE, "x", "shift") is None


def test_governance_only_proposes_with_complete_evidence():
    g = GovernanceAgent()
    p = g.inspect("strategy:x", ("hist", "oos"), ("hist", "oos"), "ACTIVATE")
    assert p.complete
    with pytest.raises(ValueError):
        g.inspect("strategy:x", ("hist",), ("hist", "oos"), "ACTIVATE")
