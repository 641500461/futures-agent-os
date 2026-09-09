from decimal import Decimal
import pytest
from futures_agent_os.learning_review import Reflection, MemoryCurator


def test_curator_requires_validation_fields():
    r = Reflection("e", "obs", None, ("decision:x", "execution:y", "accounting:z"))
    c = MemoryCurator().curate(
        r,
        candidate_id="c",
        evidence_requirements=("oos",),
        scope=("trend",),
        confidence=Decimal(".7"),
        expiry_policy="30d",
        validation_plan="replay",
    )
    assert c.content_sha256
    with pytest.raises(ValueError):
        MemoryCurator().curate(
            r,
            candidate_id="c",
            evidence_requirements=(),
            scope=("x",),
            confidence=Decimal(".7"),
            expiry_policy="30d",
            validation_plan="replay",
        )
    with pytest.raises(ValueError):
        MemoryCurator().curate(
            r,
            candidate_id="c",
            evidence_requirements=("x",),
            scope=("x",),
            confidence=Decimal("1.1"),
            expiry_policy="30d",
            validation_plan="replay",
        )
