from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from futures_agent_os.reference_market_data import (
    DataQualityLevel,
    DatasetLayer,
    DatasetManifest,
    LicenseTerms,
    PointInTimeRecord,
    QualityReport,
    RevisionInfo,
    SourceProvenance,
    StoredDataset,
    TimeCoverage,
    dataset_manifest_sha256,
    sha256_digest,
)
from futures_agent_os.research_experiment import (
    DatasetAuthorizationAuthority,
    ForwardCollectionAuthority,
    ForwardRevealAuthority,
    ForwardRosterAuthority,
    PIVOT_FORWARD_UNIVERSE,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, TradingDate, canonical_json_text


def _fixture() -> tuple[
    tuple[PointInTimeRecord, ...],
    dict[tuple[str, int], object],
    ForwardCollectionAuthority,
    ForwardRosterAuthority,
    tuple[object, ...],
    tuple[object, ...],
]:
    first = date(2026, 7, 23)
    records = tuple(
        PointInTimeRecord(
            RecordedAt(datetime.combine(first + timedelta(days=index), datetime.min.time(), UTC)),
            RecordedAt(datetime.combine(first + timedelta(days=index), datetime.min.time(), UTC) + timedelta(hours=1)),
            {
                "instrument_id": instrument,
                "component_instrument": f"{instrument}.TEST",
                "trading_date": (first + timedelta(days=index)).isoformat(),
                "open": str(100 + instrument_index * 10 + index),
                "high": str(102 + instrument_index * 10 + index),
                "low": str(99 + instrument_index * 10 + index),
                "close": str(101 + instrument_index * 10 + index),
                "settle": str(101 + instrument_index * 10 + index),
                "pre_settle": str(100 + instrument_index * 10 + index),
                "volume": 1_000 + index,
                "open_interest": 2_000 + index,
            },
        )
        for index in range(58)
        for instrument_index, instrument in enumerate(PIVOT_FORWARD_UNIVERSE)
    )
    content = canonical_json_text(
        tuple(
            {
                "event_time": item.event_time.to_dict()["recorded_at"],
                "available_time": item.available_time.to_dict()["recorded_at"],
                "values": dict(item.values),
            }
            for item in records
        )
    ).encode()
    as_of = max((item.available_time for item in records), key=lambda item: item.value)
    manifest = DatasetManifest(
        EntityId.new("dataset"),
        DatasetLayer.NORMALIZED_PIT,
        f"objects/{sha256_digest(content).removeprefix('sha256:')}",
        sha256_digest(content),
        "official_futures_daily_bar_pit",
        SchemaVersion(1, 0),
        TimeCoverage(
            min((item.event_time for item in records), key=lambda item: item.value),
            max((item.event_time for item in records), key=lambda item: item.value),
        ),
        PIVOT_FORWARD_UNIVERSE,
        SourceProvenance(
            "official exchange forward fixture",
            "https://data.example.test/official-forward",
            as_of,
            source_revision="forward-fixture-v1",
        ),
        LicenseTerms(
            "governance-authorized exchange research data",
            "research and simulation",
            "immutable evidence retention",
            "no redistribution",
            "research only",
        ),
        as_of,
        as_of,
        QualityReport(DataQualityLevel.Q2_RESEARCH, "Forward contract fixture.", as_of),
        RevisionInfo(1, "initial forward fixture", as_of),
    )
    stored = StoredDataset(manifest, content)
    manifest_sha256 = dataset_manifest_sha256(manifest)
    data_authority = DatasetAuthorizationAuthority(
        "mvp-r.forward-data",
        bytes(range(32)),
        {manifest_sha256: "c" * 64},
        frozenset({"sha256:" + "0" * 64}),
    )
    dataset_ref = data_authority.authorize(stored, provider_contract_sha256="c" * 64, records=records)
    artifacts = {
        (instrument, index): data_authority.issue_artifact(
            dataset_ref,
            instrument,
            next(
                item
                for item in records
                if item.values["instrument_id"] == instrument
                and item.values["trading_date"] == (first + timedelta(days=index)).isoformat()
            ),
        )
        for index in range(58)
        for instrument in PIVOT_FORWARD_UNIVERSE
    }

    collection = ForwardCollectionAuthority("mvp-r.forward-collection", bytes(range(32, 64)))
    acquisitions = []
    previous = None
    for index in range(39, 58):
        day_artifacts = tuple(artifacts[(instrument, index)] for instrument in PIVOT_FORWARD_UNIVERSE)
        recorded_at = max((item.record.available_time for item in day_artifacts), key=lambda item: item.value)
        previous = collection.record_day(
            previous=previous,
            trading_date=TradingDate(first + timedelta(days=index)),
            recorded_at=RecordedAt(recorded_at.value + timedelta(minutes=1)),
            artifacts=day_artifacts,
        )
        acquisitions.append(previous)

    commitments = []
    for acquisition_index, cutoff_index in enumerate(range(39, 52)):
        acquisition = acquisitions[acquisition_index]
        for instrument in PIVOT_FORWARD_UNIVERSE:
            window = tuple(artifacts[(instrument, index)] for index in range(cutoff_index - 39, cutoff_index + 1))
            commitments.append(
                collection.issue_commitment(
                    episode_id=EntityId.new("evaluation_episode"),
                    acquisition=acquisition,
                    artifacts=window,
                    committed_at=acquisition.recorded_at,
                )
            )
    roster_authority = ForwardRosterAuthority("mvp-r.forward-roster", bytes(range(64, 96)), collection)
    return records, artifacts, collection, roster_authority, tuple(acquisitions), tuple(commitments)


def test_forward_protocol_freezes_fifty_before_reveal_and_scores_only_the_next_five_days() -> None:
    _, raw_artifacts, collection, roster_authority, raw_acquisitions, raw_commitments = _fixture()
    artifacts = raw_artifacts
    acquisitions = raw_acquisitions
    commitments = raw_commitments

    with pytest.raises(ValueError, match="before fifty commitments"):
        roster_authority.freeze(commitments[:49], frozen_at=commitments[48].committed_at)

    frozen_at = max((item.committed_at for item in commitments), key=lambda item: item.value)
    roster = roster_authority.freeze(commitments, frozen_at=frozen_at)
    roster_authority.verify(roster)
    assert len(roster.entries) == 50
    assert {entry.commitment.instrument_id for entry in roster.entries} == set(PIVOT_FORWARD_UNIVERSE)

    entry = roster.entries[0]
    commitment = entry.commitment
    cutoff_index = (commitment.cutoff_trading_date.value - date(2026, 7, 23)).days
    acquisition_index = cutoff_index - 39
    chain = acquisitions[acquisition_index : acquisition_index + 6]
    cutoff = artifacts[(commitment.instrument_id, cutoff_index)]
    labels = tuple(artifacts[(commitment.instrument_id, index)] for index in range(cutoff_index + 1, cutoff_index + 6))
    evaluator = ForwardRevealAuthority(
        "mvp-r.forward-evaluator",
        bytes(range(96, 128)),
        collection,
        roster_authority,
    )
    revealed_at = chain[-1].recorded_at
    reveal = evaluator.reveal(
        roster=roster,
        episode_id=commitment.episode_id,
        acquisition_chain=chain,
        cutoff_artifact=cutoff,
        label_artifacts=labels,
        revealed_at=revealed_at,
    )

    evaluator.verify(reveal)
    expected_return = (int(labels[-1].record.values["close"]) / int(cutoff.record.values["close"])) - 1
    assert float(reveal.terminal_return) == pytest.approx(expected_return)
    assert reveal.terminal_direction == 1
    assert not hasattr(commitment, "terminal_return")
    assert not hasattr(commitment, "label_record_sha256s")


def test_forward_reveal_rejects_tampered_chain_skipped_label_and_early_availability() -> None:
    _, artifacts, collection, roster_authority, acquisitions, commitments = _fixture()
    frozen_at = max((item.committed_at for item in commitments), key=lambda item: item.value)
    roster = roster_authority.freeze(commitments, frozen_at=frozen_at)
    commitment = roster.entries[0].commitment
    cutoff_index = (commitment.cutoff_trading_date.value - date(2026, 7, 23)).days
    acquisition_index = cutoff_index - 39
    chain = acquisitions[acquisition_index : acquisition_index + 6]
    cutoff = artifacts[(commitment.instrument_id, cutoff_index)]
    labels = tuple(artifacts[(commitment.instrument_id, index)] for index in range(cutoff_index + 1, cutoff_index + 6))
    evaluator = ForwardRevealAuthority(
        "mvp-r.forward-evaluator",
        bytes(range(96, 128)),
        collection,
        roster_authority,
    )

    with pytest.raises(PermissionError, match="signature is invalid"):
        collection.verify_acquisition(replace(chain[1], signature_sha256="0" * 64))
    with pytest.raises(PermissionError, match="next signed acquisition"):
        evaluator.reveal(
            roster=roster,
            episode_id=commitment.episode_id,
            acquisition_chain=chain,
            cutoff_artifact=cutoff,
            label_artifacts=tuple(
                artifacts[(commitment.instrument_id, index)] for index in range(cutoff_index + 2, cutoff_index + 7)
            ),
            revealed_at=acquisitions[acquisition_index + 6].recorded_at,
        )
    with pytest.raises(PermissionError, match="not fully available"):
        evaluator.reveal(
            roster=roster,
            episode_id=commitment.episode_id,
            acquisition_chain=chain,
            cutoff_artifact=cutoff,
            label_artifacts=labels,
            revealed_at=labels[-2].record.available_time,
        )


def test_forward_reveal_rejects_commitments_created_after_first_label_acquisition() -> None:
    _, artifacts, collection, roster_authority, acquisitions, commitments = _fixture()
    late_commitments = []
    for commitment in commitments:
        cutoff_index = (commitment.cutoff_trading_date.value - date(2026, 7, 23)).days
        acquisition_index = cutoff_index - 39
        window = tuple(
            artifacts[(commitment.instrument_id, index)] for index in range(cutoff_index - 39, cutoff_index + 1)
        )
        late_commitments.append(
            collection.issue_commitment(
                episode_id=commitment.episode_id,
                acquisition=acquisitions[acquisition_index],
                artifacts=window,
                committed_at=acquisitions[acquisition_index + 1].recorded_at,
            )
        )
    frozen_at = max((item.committed_at for item in late_commitments), key=lambda item: item.value)
    roster = roster_authority.freeze(tuple(late_commitments), frozen_at=frozen_at)
    commitment = roster.entries[0].commitment
    cutoff_index = (commitment.cutoff_trading_date.value - date(2026, 7, 23)).days
    acquisition_index = cutoff_index - 39
    evaluator = ForwardRevealAuthority(
        "mvp-r.forward-evaluator",
        bytes(range(96, 128)),
        collection,
        roster_authority,
    )

    with pytest.raises(PermissionError, match="not frozen before the first label"):
        evaluator.reveal(
            roster=roster,
            episode_id=commitment.episode_id,
            acquisition_chain=acquisitions[acquisition_index : acquisition_index + 6],
            cutoff_artifact=artifacts[(commitment.instrument_id, cutoff_index)],
            label_artifacts=tuple(
                artifacts[(commitment.instrument_id, index)] for index in range(cutoff_index + 1, cutoff_index + 6)
            ),
            revealed_at=acquisitions[acquisition_index + 5].recorded_at,
        )
