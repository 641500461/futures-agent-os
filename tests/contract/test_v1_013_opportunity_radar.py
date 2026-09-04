from datetime import UTC, datetime, timedelta
import pytest

from futures_agent_os.research_experiment.opportunity_radar import (
    OpportunityCandidate,
    OpportunityRadar,
    ResearchEvidence,
    ScanPolicy,
    ScanResult,
    TimeHorizon,
    UniversePolicy,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def now() -> RecordedAt:
    return RecordedAt(datetime(2026, 9, 5, tzinfo=UTC))


def candidate(*, cooldown=False) -> OpportunityCandidate:
    return OpportunityCandidate(
        EntityId.new("opportunity_candidate"),
        "AG",
        TimeHorizon.SWING,
        "ag-breakout",
        (ResearchEvidence("artifact://support", "a" * 64, "trend support"),),
        (ResearchEvidence("artifact://oppose", "b" * 64, "range risk"),),
        "test the breakout",
        RecordedAt(now().value + timedelta(seconds=1)) if cooldown else None,
    )


def policy():
    return ScanPolicy("scan-policy", "1", 60, 30), UniversePolicy("universe", "1", ("AG", "CU"))


def test_scan_binds_versions_budget_universe_and_research_only_candidate():
    scan_policy, universe = policy()
    scan = OpportunityRadar().scan(
        scan_policy=scan_policy,
        universe_policy=universe,
        as_of=now(),
        data_revision="daily-1",
        feature_revision="feature-1",
        budget=100,
        candidates=(candidate(),),
    )
    assert scan.result is ScanResult.CANDIDATES
    assert scan.candidates[0].supporting_evidence and scan.candidates[0].opposing_evidence
    assert scan.candidates[0].horizon is TimeHorizon.SWING
    assert not hasattr(scan, "trade_plan") and not hasattr(scan, "order")


def test_empty_or_deduped_scan_is_explicit_no_opportunity():
    scan_policy, universe = policy()
    radar = OpportunityRadar()
    first = radar.scan(
        scan_policy=scan_policy,
        universe_policy=universe,
        as_of=now(),
        data_revision="d1",
        feature_revision="f1",
        budget=1,
        candidates=(candidate(),),
    )
    second = radar.scan(
        scan_policy=scan_policy,
        universe_policy=universe,
        as_of=now(),
        data_revision="d2",
        feature_revision="f1",
        budget=1,
        candidates=(candidate(),),
    )
    assert first.result is ScanResult.CANDIDATES
    assert second.result is ScanResult.NO_OPPORTUNITY


def test_cooldown_and_universe_violations_fail_closed():
    scan_policy, universe = policy()
    radar = OpportunityRadar()
    cool = radar.scan(
        scan_policy=scan_policy,
        universe_policy=universe,
        as_of=now(),
        data_revision="d",
        feature_revision="f",
        budget=1,
        candidates=(candidate(cooldown=True),),
    )
    assert cool.result is ScanResult.NO_OPPORTUNITY
    outside = OpportunityCandidate(
        EntityId.new("opportunity_candidate"),
        "RB",
        TimeHorizon.INTRADAY,
        "rb",
        (ResearchEvidence("r", "c" * 64, "s"),),
        (ResearchEvidence("o", "d" * 64, "risk"),),
        "h",
    )
    with pytest.raises(ValueError, match="outside"):
        radar.scan(
            scan_policy=scan_policy,
            universe_policy=universe,
            as_of=now(),
            data_revision="d",
            feature_revision="new",
            budget=1,
            candidates=(outside,),
        )


def test_missed_scan_can_be_rerun_but_regular_scan_cannot():
    scan_policy, universe = policy()
    radar = OpportunityRadar()
    missed = radar.scan(
        scan_policy=scan_policy,
        universe_policy=universe,
        as_of=now(),
        data_revision="d",
        feature_revision="f",
        budget=1,
        missed=True,
    )
    rerun = radar.rerun_missed(missed.scan_id, RecordedAt(now().value + timedelta(minutes=1)))
    assert rerun.rerun_of == missed.scan_id and not rerun.missed
    with pytest.raises(ValueError, match="missed"):
        radar.rerun_missed(rerun.scan_id, now())
