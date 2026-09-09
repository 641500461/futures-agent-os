from datetime import UTC, datetime
from decimal import Decimal
import pytest
from futures_agent_os.learning_review import Reflection, MemoryCurator, LessonValidationService, LessonStatus


def test_lesson_validation_lifecycle():
    r = Reflection("e", "obs", None, ("decision:x",))
    c = MemoryCurator().curate(
        r,
        candidate_id="c",
        evidence_requirements=("oos",),
        scope=("trend",),
        confidence=Decimal(".7"),
        expiry_policy="30d",
        validation_plan="replay",
    )
    s = LessonValidationService()
    lesson = s.validate(c, "v", ("oos:1",), True, "passed", datetime(2026, 1, 1, tzinfo=UTC))
    assert lesson.status is LessonStatus.ACTIVE
    assert s.expire(lesson, datetime(2026, 2, 2, tzinfo=UTC)).status is LessonStatus.EXPIRED
    assert s.revoke(lesson).status is LessonStatus.REVOKED
    with pytest.raises(ValueError):
        s.validate(c, "v2", ("x",), False, "failed", datetime(2026, 1, 1, tzinfo=UTC))
