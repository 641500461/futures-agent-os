"""MVP-R-003 reuses the existing deterministic replay calculations."""

from __future__ import annotations

import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from futures_agent_os.research_experiment import (
    EpisodeIssuer,
    EpisodeMode,
    EpisodePhase,
    RetrospectiveWindowIssuer,
    TrustedResearchToolsPort,
    ValidationConfig,
)
from futures_agent_os.research_experiment.mvp_r_003.experiment_adapter import (
    MvpR003ExperimentAdapter,
)
from futures_agent_os.research_experiment.mvp_roster import EpisodeStratum
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id

sys.path.insert(0, str(Path(__file__).parents[1] / "contract"))

from test_mvp_r_003_contracts import episode, hypothesis  # noqa: E402
from test_mvp_r_validation_contracts import (  # noqa: E402
    _DATASET_AUTHORITY,
    _at,
    _config,
    _external_dataset,
    _historical_pit_record,
    _pit_record,
    _suite,
)


def governed_replay_inputs():
    records = tuple(
        sorted(
            (*(_historical_pit_record(offset) for offset in range(25, 0, -1)), _pit_record()),
            key=lambda item: item.event_time.value,
        )
    )
    dataset = _external_dataset()
    artifacts = tuple(_DATASET_AUTHORITY.issue_artifact(dataset, "CU", record) for record in records)
    window = RetrospectiveWindowIssuer().issue(
        instrument_id="CU",
        acquisition_as_of=_at(11),
        market_cutoff=records[-1].event_time,
        artifacts=artifacts,
    )
    issued_episode = EpisodeIssuer().issue(
        suite=_suite(_config()),
        episode_id=semantic_entity_id("evaluation_episode", {"task": "MVP-R-003", "fixture": "episode-001"}),
        phase=EpisodePhase.DIAGNOSTIC,
        mode=EpisodeMode.RETROSPECTIVE_SEALED_REPLAY,
        instrument_id="CU",
        as_of=_at(11),
        market_cutoff=records[-1].event_time,
        future_reveal_at=_at(10),
        artifacts=artifacts,
        retrospective_window=window,
    )
    config = ValidationConfig(
        semantic_entity_id("research_validation_config", {"task": "MVP-R-003", "revision": 1}),
        1,
        20,
        5,
        5,
        20,
        Decimal("0.010"),
        Decimal("2.00000000"),
        Decimal("1.00000000"),
        (Decimal("1.00000000"), Decimal("2.00000000")),
        2,
    )
    return records, window, issued_episode.agent_view(), config


def test_selected_hypothesis_executes_all_existing_v1_010_experiments_and_replays() -> None:
    records, window, episode_view, config = governed_replay_inputs()
    contract_episode = replace(
        episode(),
        instrument="CU",
        as_of=_at(11).to_dict()["recorded_at"],
        market_cutoff=records[-1].event_time.to_dict()["recorded_at"],
        acquired_at=_at(11).to_dict()["recorded_at"],
    )
    adapter = MvpR003ExperimentAdapter()
    plan = adapter.instantiate(contract_episode, hypothesis(), config, code_ref="git:test-fixture")
    authority = TrustedResearchToolsPort(bytes(range(4, 36)))

    first = adapter.execute_replay(
        plan=plan,
        episode=episode_view,
        window=window,
        records=records,
        market_state=EpisodeStratum.RANGE,
        config=config,
        result_authority=authority,
        hypothesis=hypothesis(),
    )
    second = adapter.execute_replay(
        plan=plan,
        episode=episode_view,
        window=window,
        records=records,
        market_state=EpisodeStratum.RANGE,
        config=config,
        result_authority=authority,
        hypothesis=hypothesis(),
    )

    assert first.complete is True
    assert len(first.tool_runs) == 5
    assert {run.tool for run in first.tool_runs} == set(plan.tool_requests)
    assert all(run.metrics for run in first.tool_runs)
    assert first.content_sha256 == second.content_sha256
    assert first.to_dict() == second.to_dict()
