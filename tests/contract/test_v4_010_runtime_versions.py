import pytest
from futures_agent_os.research_experiment import RuntimeVersionRegistry, RuntimeVersionSet


def test_runtime_requires_qualification_then_activation():
    r = RuntimeVersionRegistry()
    d = r.register(RuntimeVersionSet("agent:1", "prompt:1", "model:1", "tools:1"))
    with pytest.raises(ValueError):
        r.resolve_for_mandate(d)
    q = r.qualify(d)
    a = r.activate(q.content_sha256)
    assert r.resolve_for_mandate(a.content_sha256).active
    with pytest.raises(ValueError):
        RuntimeVersionSet("a", "p", "m", "t", active=True)
