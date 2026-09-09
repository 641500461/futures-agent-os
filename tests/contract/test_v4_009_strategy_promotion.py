import pytest
from futures_agent_os.research_experiment import (
    ValidationArtifact,
    ValidationKind,
    ArtifactStatus,
    PinnedRef,
    StrategyPromotionRequest,
    StrategyPromotionRegistry,
)
from futures_agent_os.shared_kernel import EntityId


def test_promotion_requires_all_evidence_and_separate_human_activation():
    arts = tuple(
        ValidationArtifact(
            EntityId.deterministic("validation_artifact", str(i)),
            k,
            ArtifactStatus.COMPLETE,
            "a" * 64,
            "b" * 64,
            {"k": k.value},
            {"x": 1},
            (),
            (PinnedRef("x", "1", "c" * 64),),
        )
        for i, k in enumerate(ValidationKind)
    )
    req = StrategyPromotionRequest("b" * 64, arts, ("instrument:A",))
    reg = StrategyPromotionRegistry()
    key = reg.submit(req)
    with pytest.raises(ValueError):
        reg.activate(key, "user:ops")
    reg.approve(key, "user:reviewer")
    a = reg.activate(key, "user:activator")
    assert a.approved_by == "user:reviewer" and reg.resolve(key) == a
    with pytest.raises(ValueError):
        reg.approve(key, "agent:x")
