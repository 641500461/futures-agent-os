"""PostgreSQL acceptance for Research -> Critic actual artifact fan-in."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from sqlalchemy import create_engine, text

from futures_agent_os.agent_orchestration import (
    AgentBudget,
    AgentRoleId,
    ArtifactKind,
    ArtifactRef,
    CycleTrigger,
    DelegationPlan,
    DelegationStep,
    PostgresWorkflowRepository,
    TriggerSource,
)
from futures_agent_os.research_experiment import CritiqueStatus
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_json_text, canonical_sha256


DATABASE_URL = os.environ.get("FAO_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires isolated PostgreSQL via FAO_DATABASE_URL")


def _ref(kind: ArtifactKind, now: datetime) -> ArtifactRef:
    namespaces = {
        ArtifactKind.HYPOTHESIS: "hypothesis",
        ArtifactKind.EVIDENCE_SYNTHESIS: "evidence_synthesis",
        ArtifactKind.EXPERIMENT_REQUEST: "experiment_request",
        ArtifactKind.CRITIQUE: "critique",
    }
    return ArtifactRef(
        EntityId.new(namespaces.get(kind, "artifact")),
        kind,
        SchemaVersion(1, 4),
        "sha256:" + kind.value.encode().hex().ljust(64, "0")[:64],
        RecordedAt(now),
        RecordedAt(now),
    )


def _payload(reference: ArtifactRef) -> dict[str, str]:
    return {
        "id": str(reference.artifact_id.value),
        "namespace": reference.artifact_id.namespace,
        "kind": reference.artifact_kind.value,
        "schema": str(reference.schema_version),
        "hash": reference.content_hash,
        "created_at": reference.created_at.value.isoformat(),
        "as_of": reference.as_of.value.isoformat(),
    }


def _research_refs(now: datetime) -> tuple[tuple[ArtifactRef, ...], dict[str, object]]:
    valid_until = (now + timedelta(minutes=2)).isoformat()
    hypothesis_snapshot: dict[str, object] = {
        "spec": {"schema_version": "1.4", "spec_id": str(EntityId.new("hypothesis_spec")), "version": 1},
        "market_state_assessment": {
            "assessment_id": str(EntityId.new("market_state_assessment")),
            "content_sha256": "a" * 64,
            "schema_version": "1.4",
            "as_of": now.isoformat(),
            "valid_until": valid_until,
        },
        "as_of": now.isoformat(),
        "valid_until": valid_until,
        "lifecycle": "DRAFT",
        "statement": "synthetic",
        "applicable_markets": ("CU",),
        "observable_outcome": "synthetic",
        "falsification_criterion": "synthetic",
        "required_data": ("synthetic",),
        "proposal_source": "MARKET_STATE_ASSESSMENT",
    }
    hypothesis_hash = canonical_sha256(hypothesis_snapshot)
    synthesis_snapshot: dict[str, object] = {
        "hypothesis_content_sha256": hypothesis_hash,
        "as_of": now.isoformat(),
        "valid_until": valid_until,
        "knowns": (),
        "unknowns": (),
        "conflicts": (),
        "next_steps": ("synthetic",),
        "evidence_gaps": (),
    }
    synthesis_hash = canonical_sha256(synthesis_snapshot)
    request_snapshot: dict[str, object] = {
        "spec": {"schema_version": "1.4", "spec_id": str(EntityId.new("experiment_request_spec")), "version": 1},
        "hypothesis_content_sha256": hypothesis_hash,
        "as_of": now.isoformat(),
        "valid_until": valid_until,
        "data_requirements": ("synthetic",),
        "control": "synthetic",
        "evaluation_window": "synthetic",
        "method": "synthetic",
        "metrics": ("synthetic",),
        "expected_diagnostics": ("synthetic",),
        "stop_condition": "synthetic",
        "potential_biases": (),
    }
    request_hash = canonical_sha256(request_snapshot)
    refs = (
        ArtifactRef(
            EntityId.new("hypothesis"),
            ArtifactKind.HYPOTHESIS,
            SchemaVersion(1, 4),
            "sha256:" + hypothesis_hash,
            RecordedAt(now),
            RecordedAt(now),
        ),
        ArtifactRef(
            EntityId.new("evidence_synthesis"),
            ArtifactKind.EVIDENCE_SYNTHESIS,
            SchemaVersion(1, 4),
            "sha256:" + synthesis_hash,
            RecordedAt(now),
            RecordedAt(now),
        ),
        ArtifactRef(
            EntityId.new("experiment_request"),
            ArtifactKind.EXPERIMENT_REQUEST,
            SchemaVersion(1, 4),
            "sha256:" + request_hash,
            RecordedAt(now),
            RecordedAt(now),
        ),
    )
    return refs, {
        "hypothesis": hypothesis_snapshot,
        "evidence_synthesis": synthesis_snapshot,
        "experiment_request": request_snapshot,
    }


def _critique_payload(
    sources: tuple[ArtifactRef, ...],
    now: datetime,
    status: str,
    *,
    missing_data_leakage: bool = False,
    source_snapshots: dict[str, object] | None = None,
) -> tuple[dict[str, object], EntityId]:
    identities = {
        reference.artifact_kind.value: {
            "artifact_id": str(reference.artifact_id),
            "artifact_kind": reference.artifact_kind.value,
            "schema_version": str(reference.schema_version),
            "content_sha256": reference.content_hash.removeprefix("sha256:"),
            "as_of": reference.as_of.value.isoformat(),
            "valid_until": (now + timedelta(minutes=2)).isoformat(),
        }
        for reference in sources
    }
    policy = EntityId("critique_policy", __import__("uuid").UUID("019034dd-0000-7000-8000-000000000009"))
    categories = (
        "CONCENTRATION",
        "CONCLUSION_STRENGTH",
        "COST_COVERAGE",
        "COUNTER_EVIDENCE",
        "DATA_LEAKAGE",
        "HISTORICAL_FAILURE",
        "PARAMETER_STABILITY",
        "SAMPLE_APPLICABILITY",
    )
    diagnostics: tuple[object, ...] = ()
    findings = tuple(
        {
            "category": category,
            "state": "GAP",
            "severity": "HIGH" if category == "DATA_LEAKAGE" else "MEDIUM",
            "resolution": "UNRESOLVED",
            "summary": f"No typed diagnostic evidence was supplied for {category}.",
            "evidence_hashes": (),
        }
        for category in categories
    )
    return (
        {
            "policy": {"policy_id": str(policy.value), "version": 1, "schema_version": "1.4", "max_iterations": 1},
            "hypothesis": identities["hypothesis"],
            "evidence_synthesis": identities["evidence_synthesis"],
            "experiment_request": identities["experiment_request"],
            "evaluated_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=1)).isoformat(),
            "iteration": 1,
            "source_snapshots": source_snapshots
            or {
                "hypothesis": {"source": "typed"},
                "evidence_synthesis": {"hypothesis_content_sha256": identities["hypothesis"]["content_sha256"]},
                "experiment_request": {"hypothesis_content_sha256": identities["hypothesis"]["content_sha256"]},
            },
            "diagnostics": diagnostics,
            "findings": findings,
            "status": status,
            "required_validations": tuple(f"DIAGNOSTIC_REQUIRED:{category}" for category in sorted(categories)),
        },
        policy,
    )


@pytest.mark.parametrize(
    ("verdict", "missing_data_leakage", "task_status", "episode_status"),
    (("DEFER", True, "DEFERRED", "DEFERRED"),),
)
def test_postgres_research_to_critic_claim_uses_actual_three_artifacts_across_processes(
    verdict: str, missing_data_leakage: bool, task_status: str, episode_status: str
) -> None:
    engine, repository = create_engine(DATABASE_URL), PostgresWorkflowRepository()
    now = datetime.now(UTC)
    snapshot = _ref(ArtifactKind.MARKET_SNAPSHOT, now)
    cycle_id, episode_id = EntityId.new("autonomy_cycle"), EntityId.new("decision_episode")
    trigger = CycleTrigger(TriggerSource.DATA, f"critic-fan-in:{cycle_id}", RecordedAt(now), (snapshot,))

    regime = DelegationStep(
        "regime",
        AgentRoleId.MARKET_REGIME.value,
        (snapshot,),
        (ArtifactKind.MARKET_STATE_ASSESSMENT,),
        AgentBudget(1, 1, 100, 60),
        (),
    )
    research = DelegationStep(
        "research",
        AgentRoleId.RESEARCH.value,
        (),
        (ArtifactKind.HYPOTHESIS, ArtifactKind.EVIDENCE_SYNTHESIS, ArtifactKind.EXPERIMENT_REQUEST),
        AgentBudget(1, 1, 100, 60),
        ("regime",),
    )
    critic = DelegationStep(
        "critic",
        AgentRoleId.PRE_TRADE_CRITIC.value,
        (),
        (ArtifactKind.CRITIQUE,),
        AgentBudget(1, 1, 100, 60),
        ("research",),
    )
    plan = DelegationPlan(
        EntityId.new("delegation_plan"),
        cycle_id,
        episode_id,
        RecordedAt(now),
        RecordedAt(now + timedelta(minutes=3)),
        (regime, research, critic),
        AgentBudget(3, 3, 300, 180),
    )

    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repository.start_typed_cycle(connection, cycle_id, trigger, uuid7(), RecordedAt(now + timedelta(minutes=5)))
        repository.start_episode(
            connection, episode_id.value, cycle_id.value, "CU:research-critic", now + timedelta(minutes=4)
        )
        assert repository.persist_typed_execution(connection, plan) == 1
        regime_claim = repository.claim_task(connection, episode_id.value, "regime-worker", 30)
        assert regime_claim is not None and regime_claim[3]["role_id"] == AgentRoleId.MARKET_REGIME.value
        market_state = _ref(ArtifactKind.MARKET_STATE_ASSESSMENT, now)
        assert repository.complete_task_fenced(
            connection,
            regime_claim[0],
            regime_claim[1],
            regime_claim[2],
            {"status": "COMPLETED", "artifacts": (_payload(market_state),), "unknowns": (), "warnings": ()},
        )

    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_checkpoint_owner"))
        assert not connection.execute(
            text(
                """SELECT fao.v1005_valid_execution(
                episode_id,
                jsonb_set(plan_payload,'{cycle_budget,max_tokens}','200'::jsonb),
                task_set_payload) FROM agent_checkpoint.workflow_execution WHERE episode_id=:episode"""
            ),
            {"episode": episode_id.value},
        ).scalar_one()
        for payload, required, expected in (
            ('["a","b"]', True, True),
            ('["b","a"]', True, False),
            ('["a","a"]', True, False),
            ('[" "]', False, False),
            ("[]", False, True),
            ("[]", True, False),
        ):
            assert (
                connection.execute(
                    text("SELECT fao.v1006_valid_canonical_text_set(CAST(:payload AS jsonb),:required)"),
                    {"payload": payload, "required": required},
                ).scalar_one()
                is expected
            )
        assert connection.execute(
            text(
                "SELECT fao.v1006_valid_canonical_evidence_gaps("
                '\'[{"code":"missing_cost","description":"No cost evidence"}]\'::jsonb)'
            )
        ).scalar_one()
        assert not connection.execute(
            text(
                "SELECT fao.v1006_valid_canonical_evidence_gaps("
                '\'[{"code":"BAD-CODE","description":"No cost evidence"}]\'::jsonb)'
            )
        ).scalar_one()
        valid_spec_id = str(EntityId.new("experiment_request_spec"))
        assert connection.execute(
            text("SELECT fao.v1006_valid_entity_id(to_jsonb(CAST(:value AS text)),'experiment_request_spec')"),
            {"value": valid_spec_id},
        ).scalar_one()
        assert not connection.execute(
            text(
                "SELECT fao.v1006_valid_entity_id("
                "'\"experiment_request_spec_00000000-0000-4000-8000-000000000000\"'::jsonb,"
                "'experiment_request_spec')"
            )
        ).scalar_one()
        assert not connection.execute(
            text("SELECT fao.v1006_valid_entity_id('1.4'::jsonb,'experiment_request_spec')")
        ).scalar_one()

    with engine.connect() as connection:
        assert not connection.execute(
            text("SELECT has_function_privilege('public','fao.v1006_canonical_json(jsonb)','EXECUTE')")
        ).scalar_one()
        assert not connection.execute(
            text(
                "SELECT has_function_privilege('public','agent_checkpoint.complete_critic_workflow_task(uuid,bigint,bigint,jsonb,jsonb,text,text)','EXECUTE')"
            )
        ).scalar_one()
        assert not connection.execute(
            text(
                "SELECT has_function_privilege('fao_workflow_worker','agent_checkpoint.complete_workflow_task_legacy(uuid,bigint,bigint,jsonb,text,text)','EXECUTE')"
            )
        ).scalar_one()
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        with pytest.raises(Exception):
            connection.execute(
                text(
                    "SELECT agent_checkpoint.complete_workflow_task_legacy(NULL::uuid,NULL::bigint,NULL::bigint,NULL::jsonb,NULL::text,NULL::text)"
                )
            )

    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        research_claim = repository.claim_task(connection, episode_id.value, "research-worker", 30)
        assert research_claim is not None
        assert research_claim[3]["input_artifacts"] == [_payload(market_state)]
        actual_research, source_snapshots = _research_refs(now)
        assert repository.complete_task_fenced(
            connection,
            research_claim[0],
            research_claim[1],
            research_claim[2],
            {
                "status": "COMPLETED",
                "artifacts": tuple(_payload(item) for item in actual_research),
                "unknowns": (),
                "warnings": (),
            },
        )

    # This fresh connection is the cross-process acceptance boundary.  The
    # Critic receives persisted Research results, not predeclared substitutes.
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        hydrated = repository.hydrate_typed_episode(connection, episode_id)
        hydrated_critic = next(task for task in hydrated[3] if task.role_id == AgentRoleId.PRE_TRADE_CRITIC.value)
        assert hydrated_critic.input_artifacts == actual_research
        critic_claim = repository.claim_task(connection, episode_id.value, "critic-worker", 30)
        assert critic_claim is not None
        assert critic_claim[3]["role_id"] == AgentRoleId.PRE_TRADE_CRITIC.value
        assert critic_claim[3]["input_artifacts"] == [_payload(item) for item in actual_research]
        assert not repository.complete_task_fenced(
            connection,
            critic_claim[0],
            critic_claim[1],
            critic_claim[2],
            {
                "status": "COMPLETED",
                "artifacts": (_payload(_ref(ArtifactKind.HYPOTHESIS, now)),),
                "unknowns": (),
                "warnings": (),
            },
        )
        full_critique, policy = _critique_payload(
            actual_research, now, verdict, missing_data_leakage=missing_data_leakage, source_snapshots=source_snapshots
        )
        critique_hash = canonical_sha256(full_critique)
        critique = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + critique_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert (
            repository.reserve_critique_revision(
                connection,
                episode_id,
                actual_research[0].content_hash.removeprefix("sha256:"),
                policy,
                1,
                SchemaVersion(1, 4),
                1,
                critique_hash,
            )
            == 1
        )
        # An exact retry identity includes both the evaluation digest and its
        # hypothesis: sharing only a digest cannot reset or borrow a revision.
        with pytest.raises(Exception, match="different hypothesis"):
            with connection.begin_nested():
                repository.reserve_critique_revision(
                    connection,
                    episode_id,
                    "f" * 64,
                    policy,
                    1,
                    SchemaVersion(1, 4),
                    1,
                    critique_hash,
                )
        # Generic completion is deliberately not a back door for a Critic.
        assert not repository.complete_task_fenced(
            connection,
            critic_claim[0],
            critic_claim[1],
            critic_claim[2],
            {"status": "COMPLETED", "artifacts": (_payload(critique),), "unknowns": (), "warnings": ()},
        )
        canonical = canonical_json_text(full_critique)

        def complete_raw(
            artifact: ArtifactRef, payload: dict[str, object], payload_text: str, payload_hash: str
        ) -> bool:
            return connection.execute(
                text(
                    "SELECT agent_checkpoint.complete_critic_workflow_task(:task,:version,:fence,CAST(:artifact AS jsonb),CAST(:critique AS jsonb),:canonical,:hash)"
                ),
                {
                    "task": critic_claim[0],
                    "version": critic_claim[1],
                    "fence": critic_claim[2],
                    "artifact": canonical_json_text(_payload(artifact)),
                    "critique": canonical_json_text(payload),
                    "canonical": payload_text,
                    "hash": payload_hash,
                },
            ).scalar_one()

        # Canonical representation and digest are independently authenticated.
        assert not complete_raw(critique, full_critique, canonical + " ", critique_hash)
        assert not complete_raw(critique, full_critique, canonical, "0" * 64)
        non_critique_artifact = ArtifactRef(
            EntityId.new("hypothesis"),
            ArtifactKind.HYPOTHESIS,
            SchemaVersion(1, 4),
            "sha256:" + critique_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert not complete_raw(non_critique_artifact, full_critique, canonical, critique_hash)
        fake_diagnostic = {**full_critique, "diagnostics": ({"caller": "CLEAR"},)}
        fake_diagnostic_text = canonical_json_text(fake_diagnostic)
        fake_diagnostic_hash = canonical_sha256(fake_diagnostic)
        fake_diagnostic_artifact = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + fake_diagnostic_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert not complete_raw(fake_diagnostic_artifact, fake_diagnostic, fake_diagnostic_text, fake_diagnostic_hash)
        fake_snapshot = {**full_critique, "source_snapshots": {"hypothesis": {"source": "typed"}}}
        fake_snapshot_text = canonical_json_text(fake_snapshot)
        fake_snapshot_hash = canonical_sha256(fake_snapshot)
        fake_snapshot_artifact = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + fake_snapshot_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert not complete_raw(fake_snapshot_artifact, fake_snapshot, fake_snapshot_text, fake_snapshot_hash)
        missing_valid_until = {
            **full_critique,
            "hypothesis": {key: value for key, value in full_critique["hypothesis"].items() if key != "valid_until"},
        }
        missing_valid_until_text = canonical_json_text(missing_valid_until)
        missing_valid_until_hash = canonical_sha256(missing_valid_until)
        missing_valid_until_artifact = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + missing_valid_until_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert not complete_raw(
            missing_valid_until_artifact, missing_valid_until, missing_valid_until_text, missing_valid_until_hash
        )
        wrong_namespace = {
            **full_critique,
            "hypothesis": {
                **full_critique["hypothesis"],
                "artifact_id": "wrong_" + full_critique["hypothesis"]["artifact_id"].split("_", 1)[1],
            },
        }
        wrong_namespace_text = canonical_json_text(wrong_namespace)
        wrong_namespace_hash = canonical_sha256(wrong_namespace)
        wrong_namespace_artifact = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + wrong_namespace_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert not complete_raw(wrong_namespace_artifact, wrong_namespace, wrong_namespace_text, wrong_namespace_hash)
        simplified_nested = {
            **full_critique,
            "source_snapshots": {
                **source_snapshots,
                "hypothesis": {**source_snapshots["hypothesis"], "market_state_assessment": {"as_of": now.isoformat()}},
            },
        }
        simplified_nested_text = canonical_json_text(simplified_nested)
        simplified_nested_hash = canonical_sha256(simplified_nested)
        simplified_nested_artifact = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + simplified_nested_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert not complete_raw(
            simplified_nested_artifact, simplified_nested, simplified_nested_text, simplified_nested_hash
        )
        future_eval = {**full_critique, "evaluated_at": (now + timedelta(minutes=1)).isoformat()}
        future_eval_text = canonical_json_text(future_eval)
        future_eval_hash = canonical_sha256(future_eval)
        future_eval_artifact = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + future_eval_hash,
            RecordedAt(now + timedelta(minutes=1)),
            RecordedAt(now),
        )
        assert not complete_raw(future_eval_artifact, future_eval, future_eval_text, future_eval_hash)
        over_expiry = {**full_critique, "expires_at": (now + timedelta(minutes=3)).isoformat()}
        over_expiry_text = canonical_json_text(over_expiry)
        over_expiry_hash = canonical_sha256(over_expiry)
        over_expiry_artifact = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + over_expiry_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert not complete_raw(over_expiry_artifact, over_expiry, over_expiry_text, over_expiry_hash)
        expanded_max = {**full_critique, "policy": {**full_critique["policy"], "max_iterations": 2}}
        expanded_max_text = canonical_json_text(expanded_max)
        expanded_max_hash = canonical_sha256(expanded_max)
        expanded_max_artifact = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + expanded_max_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert not complete_raw(expanded_max_artifact, expanded_max, expanded_max_text, expanded_max_hash)
        wrong_revision = {**full_critique, "iteration": 2}
        wrong_revision_text = canonical_json_text(wrong_revision)
        wrong_revision_hash = canonical_sha256(wrong_revision)
        wrong_revision_artifact = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + wrong_revision_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert not complete_raw(wrong_revision_artifact, wrong_revision, wrong_revision_text, wrong_revision_hash)

        forged = {**full_critique, "status": "PASS"}
        forged_text = canonical_json_text(forged)
        forged_hash = canonical_sha256(forged)
        forged_artifact = ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.CRITIQUE,
            SchemaVersion(1, 4),
            "sha256:" + forged_hash,
            RecordedAt(now),
            RecordedAt(now),
        )
        # A complete canonical document still cannot select PASS.
        assert not complete_raw(forged_artifact, forged, forged_text, forged_hash)
        assert complete_raw(critique, full_critique, canonical, critique_hash)

    def retry_from_new_connection() -> bool:
        with engine.begin() as retry_connection:
            retry_connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
            return retry_connection.execute(
                text(
                    "SELECT agent_checkpoint.complete_critic_workflow_task(:task,:version,:fence,CAST(:artifact AS jsonb),CAST(:critique AS jsonb),:canonical,:hash)"
                ),
                {
                    "task": critic_claim[0],
                    "version": critic_claim[1],
                    "fence": critic_claim[2],
                    "artifact": canonical_json_text(_payload(critique)),
                    "critique": canonical,
                    "canonical": canonical,
                    "hash": critique_hash,
                },
            ).scalar_one()

    # Two fresh worker connections replay the one fenced completion concurrently.
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _unused: retry_from_new_connection(), range(2))) == [True, True]

    with engine.connect() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        with pytest.raises(Exception):
            with connection.begin_nested():
                connection.execute(text("SELECT critique_status FROM agent_checkpoint.critique_completion LIMIT 1"))
        completion = repository.hydrate_critic_completion(connection, critic_claim[0], episode_id)
        assert completion is not None and completion["status"] == "DEFER"
        assert repository.hydrate_critic_verdict(connection, critic_claim[0], episode_id) is CritiqueStatus.DEFER
        # No worker may progress a downstream action after Critic closure.
        assert repository.claim_task(connection, episode_id.value, "downstream-worker", 30) is None

    # The acceptance connection observes final business/checkpoint state without
    # widening the worker role's direct table privileges.
    with engine.connect() as connection:
        status = connection.execute(
            text("SELECT episode_status FROM fao.decision_episode WHERE episode_id=:episode"),
            {"episode": episode_id.value},
        ).scalar_one()
        assert status == episode_status
        persisted_task_status = connection.execute(
            text("SELECT task_status FROM agent_checkpoint.workflow_task_checkpoint WHERE task_id=:task"),
            {"task": critic_claim[0]},
        ).scalar_one()
        assert persisted_task_status == task_status
        if verdict == "REJECT":
            assert (
                connection.execute(
                    text("SELECT cycle_status FROM fao.autonomy_cycle WHERE cycle_id=:cycle"),
                    {"cycle": cycle_id.value},
                ).scalar_one()
                == "DEFERRED"
            )
