"""V1-008: append-only observe workflow facts and fenced worker checkpoints."""

from __future__ import annotations
from collections.abc import Sequence
from alembic import op

revision = "0005_v1_008"
down_revision: str | Sequence[str] | None = "0004_v0_014_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgcrypto is a cluster shared dependency.  Downgrade intentionally leaves
    # it installed: removing a pre-existing extension could break another app.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        "DO $$ BEGIN CREATE ROLE fao_workflow_worker NOLOGIN NOINHERIT; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(
        "DO $$ BEGIN CREATE ROLE fao_learning_projector NOLOGIN NOINHERIT; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(
        "GRANT USAGE ON SCHEMA fao,agent_checkpoint TO fao_workflow_worker; GRANT USAGE ON SCHEMA fao TO fao_learning_projector"
    )
    op.execute("SET ROLE fao_business_owner")
    op.execute("""CREATE TABLE fao.autonomy_cycle(
      cycle_id UUID PRIMARY KEY, version BIGINT NOT NULL DEFAULT 1 CHECK(version>0), trigger_source TEXT NOT NULL CHECK(trigger_source IN ('USER','SCHEDULE','MARKET','DATA')),
      idempotency_key TEXT NOT NULL CHECK(idempotency_key=btrim(idempotency_key) AND idempotency_key<>''), correlation_id UUID NOT NULL,
      trigger_payload JSONB NOT NULL, trigger_canonical TEXT NOT NULL, trigger_sha256 TEXT NOT NULL CHECK(trigger_sha256~'^[0-9a-f]{64}$'),
      started_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL, cycle_status TEXT NOT NULL DEFAULT 'RUNNING' CHECK(cycle_status IN ('RUNNING','COMPLETED','DEFERRED','CANCELLED','TIMED_OUT')), terminal_reason TEXT,
      UNIQUE(trigger_source,idempotency_key), CHECK(expires_at>started_at), CHECK((cycle_status='RUNNING')=(terminal_reason IS NULL)))""")
    op.execute("""CREATE TABLE fao.decision_episode(
      episode_id UUID PRIMARY KEY, cycle_id UUID NOT NULL REFERENCES fao.autonomy_cycle(cycle_id), version BIGINT NOT NULL DEFAULT 1 CHECK(version>0), candidate_key TEXT NOT NULL CHECK(candidate_key=btrim(candidate_key) AND candidate_key<>''), correlation_id UUID NOT NULL,
      started_at TIMESTAMPTZ NOT NULL, decision_cutoff_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL, episode_status TEXT NOT NULL DEFAULT 'RUNNING' CHECK(episode_status IN ('RUNNING','COMPLETED','DEFERRED','CANCELLED','TIMED_OUT')), terminal_reason TEXT,
      UNIQUE(cycle_id,candidate_key), CHECK(expires_at>started_at), CHECK((episode_status='RUNNING')=(terminal_reason IS NULL)))""")
    op.execute(
        """CREATE TABLE fao.workflow_source_payload(event_id UUID PRIMARY KEY REFERENCES fao.domain_event(event_id), canonical_payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL CHECK(payload_sha256~'^[0-9a-f]{64}$'))"""
    )
    op.execute(
        "CREATE TABLE fao.workflow_episode_source(event_id UUID PRIMARY KEY REFERENCES fao.workflow_source_payload(event_id),episode_id UUID NOT NULL REFERENCES fao.decision_episode(episode_id))"
    )
    op.execute("""CREATE TABLE fao.decision_journal_binding(
      journal_id UUID PRIMARY KEY REFERENCES fao.decision_journal(journal_id), episode_id UUID NOT NULL REFERENCES fao.decision_episode(episode_id), correlation_id UUID NOT NULL,
      decision_cutoff_at TIMESTAMPTZ NOT NULL, projection_version BIGINT NOT NULL DEFAULT 1 CHECK(projection_version=1), created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""")
    # V0 headers remain readable (nullable columns); every V1 projector call
    # creates and verifies this immutable binding in both the legacy header and
    # the normalized binding relation.  Existing unbound journals fail closed.
    op.execute(
        "ALTER TABLE fao.decision_journal ADD COLUMN decision_episode_id UUID, ADD COLUMN correlation_id UUID, ADD COLUMN decision_cutoff_at TIMESTAMPTZ"
    )
    op.execute(
        "GRANT REFERENCES,SELECT ON fao.decision_episode TO fao_checkpoint_owner; GRANT SELECT ON fao.autonomy_cycle TO fao_checkpoint_owner"
    )
    op.execute("RESET ROLE; SET ROLE fao_checkpoint_owner")
    op.execute("""CREATE TABLE agent_checkpoint.workflow_execution(
      episode_id UUID PRIMARY KEY REFERENCES fao.decision_episode(episode_id), plan_payload JSONB NOT NULL, plan_canonical TEXT NOT NULL, plan_sha256 TEXT NOT NULL CHECK(plan_sha256~'^[0-9a-f]{64}$'),
      task_set_payload JSONB NOT NULL, task_set_canonical TEXT NOT NULL, task_set_sha256 TEXT NOT NULL CHECK(task_set_sha256~'^[0-9a-f]{64}$'),
      checkpoint_version BIGINT NOT NULL DEFAULT 1 CHECK(checkpoint_version>0), updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""")
    op.execute("""CREATE TABLE agent_checkpoint.workflow_task_checkpoint(
      task_id UUID PRIMARY KEY, episode_id UUID NOT NULL REFERENCES agent_checkpoint.workflow_execution(episode_id), step_key TEXT NOT NULL, task_payload JSONB NOT NULL, task_canonical TEXT NOT NULL, task_sha256 TEXT NOT NULL CHECK(task_sha256~'^[0-9a-f]{64}$'),
      task_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(task_status IN ('PENDING','RUNNING','COMPLETED','DEFERRED','FAILED','SKIPPED','CANCELLED','TIMED_OUT')), result_payload JSONB, result_canonical TEXT, result_sha256 TEXT,
      version BIGINT NOT NULL DEFAULT 1 CHECK(version>0), worker_id TEXT, fencing_token BIGINT NOT NULL DEFAULT 0 CHECK(fencing_token>=0), lease_expires_at TIMESTAMPTZ, UNIQUE(episode_id,step_key))""")
    op.execute(
        "GRANT USAGE ON SCHEMA agent_checkpoint TO fao_business_owner; GRANT SELECT ON agent_checkpoint.workflow_execution TO fao_business_owner; GRANT SELECT,UPDATE ON agent_checkpoint.workflow_task_checkpoint TO fao_business_owner"
    )
    op.execute("RESET ROLE; SET ROLE fao_business_owner")
    # The checkpoint schema is deliberately untrusted input even though the
    # normal repository serializes typed objects.  These helpers make raw SQL
    # writes fail closed and are also reused while hydrating a recovered run.
    op.execute(
        """CREATE OR REPLACE FUNCTION fao.v1005_valid_artifact(p JSONB) RETURNS BOOLEAN LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,pg_temp AS $$
        SELECT jsonb_typeof(p)='object'
          AND p ?& ARRAY['id','namespace','kind','schema','hash','created_at','as_of']
          AND (SELECT count(*) FROM jsonb_object_keys(p))=7
          AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(p) k WHERE k NOT IN ('id','namespace','kind','schema','hash','created_at','as_of'))
          AND jsonb_typeof(p->'id')='string' AND jsonb_typeof(p->'namespace')='string' AND jsonb_typeof(p->'kind')='string' AND jsonb_typeof(p->'schema')='string'
          AND jsonb_typeof(p->'hash')='string' AND jsonb_typeof(p->'created_at')='string' AND jsonb_typeof(p->'as_of')='string'
          AND p->>'id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND substring(p->>'id' from 15 for 1)='7' AND substring(p->>'id' from 20 for 1)~'^[89ab]$'
          AND p->>'namespace' IN ('artifact','dataset','feature_observation','market_snapshot','market_state_assessment','regime_assessment','hypothesis','evidence_synthesis','experiment_request','research_synthesis','signal_result')
          AND p->>'kind' IN ('research_brief','market_snapshot','feature_observation','regime_assessment','market_state_assessment','hypothesis','evidence_synthesis','experiment_request')
          AND p->>'schema' ~ '^[0-9]+\\.[0-9]+$'
          AND p->>'hash' ~ '^sha256:[0-9a-f]{64}$'
          AND (p->>'created_at')::timestamptz >= (p->>'as_of')::timestamptz $$"""
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION fao.v1005_valid_execution(p_episode UUID,p_plan JSONB,p_tasks JSONB) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$
        DECLARE e fao.decision_episode%ROWTYPE; s JSONB; t JSONB; names TEXT[]; allowed TEXT[]:=ARRAY['research_brief','market_snapshot','feature_observation','regime_assessment','market_state_assessment','hypothesis','evidence_synthesis','experiment_request']; BEGIN
          SELECT * INTO e FROM fao.decision_episode WHERE episode_id=p_episode;
          IF NOT FOUND OR jsonb_typeof(p_plan)<>'object' OR jsonb_typeof(p_tasks)<>'array'
             OR (SELECT count(*) FROM jsonb_object_keys(p_plan))<>7 OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_plan) k WHERE k NOT IN ('plan_id','cycle_id','episode_id','as_of','expires_at','cycle_budget','steps'))
             OR jsonb_typeof(p_plan->'plan_id')<>'string' OR p_plan->>'plan_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR substring(p_plan->>'plan_id' from 15 for 1)<>'7' OR substring(p_plan->>'plan_id' from 20 for 1)!~'^[89ab]$'
             OR jsonb_typeof(p_plan->'cycle_id')<>'string' OR jsonb_typeof(p_plan->'episode_id')<>'string'
             OR jsonb_typeof(p_plan->'as_of')<>'string' OR jsonb_typeof(p_plan->'expires_at')<>'string'
             OR p_plan->>'episode_id'<>p_episode::text OR p_plan->>'cycle_id'<>e.cycle_id::text
             OR (p_plan->>'expires_at')::timestamptz <= (p_plan->>'as_of')::timestamptz
             OR jsonb_typeof(p_plan->'steps')<>'array' OR jsonb_array_length(p_plan->'steps')<>jsonb_array_length(p_tasks)
             OR jsonb_typeof(p_plan->'cycle_budget')<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p_plan->'cycle_budget'))<>5
             OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_plan->'cycle_budget') k WHERE k NOT IN ('max_turns','max_tool_calls','max_tokens','timeout_seconds','max_parallel_tasks'))
             OR EXISTS(SELECT 1 FROM jsonb_each(p_plan->'cycle_budget') b WHERE jsonb_typeof(b.value)<>'number' OR (b.value #>> '{}')::numeric<=0 OR (b.value #>> '{}')::numeric<>trunc((b.value #>> '{}')::numeric)) THEN RETURN FALSE; END IF;
          SELECT array_agg(x.value) INTO names FROM jsonb_array_elements(p_plan->'steps') x0, LATERAL jsonb_array_elements_text(jsonb_build_array(x0.value->>'step_key')) x;
          IF names IS NULL OR array_length(names,1)<> (SELECT count(DISTINCT n) FROM unnest(names) n) THEN RETURN FALSE; END IF;
          FOR s IN SELECT value FROM jsonb_array_elements(p_plan->'steps') LOOP
            IF jsonb_typeof(s)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(s))<>6 OR EXISTS(SELECT 1 FROM jsonb_object_keys(s) k WHERE k NOT IN ('step_key','role_id','input_artifacts','required_outputs','budget','depends_on')) OR jsonb_typeof(s->'step_key')<>'string' OR jsonb_typeof(s->'role_id')<>'string' OR s->>'step_key' IS NULL OR s->>'step_key'<>btrim(s->>'step_key')
               OR s->>'role_id' NOT IN ('market_regime','research') OR jsonb_typeof(s->'depends_on')<>'array'
               OR jsonb_typeof(s->'required_outputs')<>'array' OR jsonb_array_length(s->'required_outputs')=0
               OR EXISTS(SELECT 1 FROM jsonb_array_elements(s->'depends_on') d WHERE jsonb_typeof(d.value)<>'string')
               OR jsonb_array_length(s->'depends_on')<>(SELECT count(DISTINCT value) FROM jsonb_array_elements_text(s->'depends_on'))
               OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(s->'depends_on') d WHERE NOT d.value=ANY(names) OR d.value=s->>'step_key')
               OR EXISTS(SELECT 1 FROM jsonb_array_elements(s->'required_outputs') o WHERE jsonb_typeof(o.value)<>'string')
               OR jsonb_array_length(s->'required_outputs')<>(SELECT count(DISTINCT value) FROM jsonb_array_elements_text(s->'required_outputs'))
               OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(s->'required_outputs') o WHERE NOT o.value=ANY(allowed))
               OR jsonb_typeof(s->'input_artifacts')<>'array' OR jsonb_array_length(s->'input_artifacts')<>(SELECT count(DISTINCT value::text) FROM jsonb_array_elements(s->'input_artifacts'))
               OR (s->>'role_id'='market_regime' AND (jsonb_array_length(s->'input_artifacts')=0 OR s->'required_outputs'<>jsonb_build_array('market_state_assessment') OR EXISTS(SELECT 1 FROM jsonb_array_elements(s->'input_artifacts') a WHERE a.value->>'kind' NOT IN ('research_brief','market_snapshot','feature_observation','regime_assessment'))))
               OR (s->>'role_id'='research' AND (EXISTS(SELECT 1 FROM jsonb_array_elements_text(s->'required_outputs') o WHERE o.value NOT IN ('hypothesis','evidence_synthesis','experiment_request')) OR EXISTS(SELECT 1 FROM jsonb_array_elements(s->'input_artifacts') a WHERE a.value->>'kind'<>'market_state_assessment') OR (jsonb_array_length(s->'input_artifacts')=0 AND jsonb_array_length(s->'depends_on')=0) OR (jsonb_array_length(s->'input_artifacts')<>0 AND jsonb_array_length(s->'depends_on')<>0) OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(s->'depends_on') d JOIN jsonb_array_elements(p_plan->'steps') upstream ON upstream.value->>'step_key'=d.value WHERE upstream.value->>'role_id'<>'market_regime' OR upstream.value->'required_outputs'<>jsonb_build_array('market_state_assessment'))))
               OR jsonb_typeof(s->'budget')<>'object' OR (SELECT count(*) FROM jsonb_object_keys(s->'budget'))<>5 OR EXISTS(SELECT 1 FROM jsonb_object_keys(s->'budget') k WHERE k NOT IN ('max_turns','max_tool_calls','max_tokens','timeout_seconds','max_parallel_tasks')) OR EXISTS(SELECT 1 FROM jsonb_each(s->'budget') b WHERE jsonb_typeof(b.value)<>'number' OR (b.value #>> '{}')::numeric<=0 OR (b.value #>> '{}')::numeric<>trunc((b.value #>> '{}')::numeric)) OR EXISTS(SELECT 1 FROM jsonb_array_elements(s->'input_artifacts') a WHERE NOT fao.v1005_valid_artifact(a.value)) THEN RETURN FALSE; END IF;
            SELECT value INTO t FROM jsonb_array_elements(p_tasks) WHERE value->>'step_key'=s->>'step_key';
            IF t IS NULL OR jsonb_typeof(t)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(t))<>9 OR EXISTS(SELECT 1 FROM jsonb_object_keys(t) k WHERE k NOT IN ('task_id','episode_id','step_key','role_id','deadline_at','depends_on','required_outputs','input_artifacts','budget')) OR (SELECT count(*) FROM jsonb_array_elements(p_tasks) q WHERE q.value->>'step_key'=s->>'step_key')<>1
               OR t->>'task_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR substring(t->>'task_id' from 15 for 1)<>'7' OR substring(t->>'task_id' from 20 for 1)!~'^[89ab]$'
               OR jsonb_typeof(t->'task_id')<>'string' OR jsonb_typeof(t->'episode_id')<>'string' OR jsonb_typeof(t->'step_key')<>'string' OR jsonb_typeof(t->'role_id')<>'string' OR jsonb_typeof(t->'deadline_at')<>'string' OR jsonb_typeof(t->'depends_on')<>'array' OR jsonb_typeof(t->'required_outputs')<>'array' OR jsonb_typeof(t->'input_artifacts')<>'array' OR jsonb_typeof(t->'budget')<>'object'
               OR t->>'episode_id'<>p_episode::text OR t->>'step_key'<>s->>'step_key' OR t->>'role_id'<>s->>'role_id'
               OR t->'depends_on'<>s->'depends_on' OR t->'required_outputs'<>s->'required_outputs'
               OR t->'input_artifacts'<>s->'input_artifacts' OR t->'budget'<>s->'budget'
               OR (t->>'deadline_at')::timestamptz>(p_plan->>'expires_at')::timestamptz THEN RETURN FALSE; END IF;
          END LOOP;
          IF EXISTS(SELECT 1 FROM (SELECT SUM((value->'budget'->>'max_turns')::bigint) turns,SUM((value->'budget'->>'max_tool_calls')::bigint) calls,SUM((value->'budget'->>'max_tokens')::bigint) tokens,SUM((value->'budget'->>'timeout_seconds')::bigint) seconds,MAX((value->'budget'->>'max_parallel_tasks')::bigint) parallel FROM jsonb_array_elements(p_plan->'steps')) s WHERE s.turns>(p_plan->'cycle_budget'->>'max_turns')::bigint OR s.calls>(p_plan->'cycle_budget'->>'max_tool_calls')::bigint OR s.tokens>(p_plan->'cycle_budget'->>'max_tokens')::bigint OR s.seconds>(p_plan->'cycle_budget'->>'timeout_seconds')::bigint OR s.parallel>(p_plan->'cycle_budget'->>'max_parallel_tasks')::bigint) THEN RETURN FALSE; END IF;
          IF EXISTS(WITH RECURSIVE walk(root,node,path) AS (
              SELECT s.value->>'step_key', d.value, ARRAY[s.value->>'step_key',d.value] FROM jsonb_array_elements(p_plan->'steps') s, LATERAL jsonb_array_elements_text(s.value->'depends_on') d
              UNION ALL SELECT w.root,d.value,w.path||d.value FROM walk w JOIN jsonb_array_elements(p_plan->'steps') s ON s.value->>'step_key'=w.node CROSS JOIN LATERAL jsonb_array_elements_text(s.value->'depends_on') d WHERE NOT d.value=ANY(w.path)) SELECT 1 FROM walk WHERE root=node) THEN RETURN FALSE; END IF;
          RETURN TRUE;
        EXCEPTION WHEN others THEN RETURN FALSE; END $$"""
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION fao.v1005_valid_cycle_trigger(p_source TEXT,p_key TEXT,p_payload JSONB) RETURNS BOOLEAN LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,fao,pg_temp AS $$ BEGIN
          IF jsonb_typeof(p_payload)<>'object' OR NOT (p_payload ?& ARRAY['source','idempotency_key','occurred_at','input_artifacts']) OR (SELECT count(*) FROM jsonb_object_keys(p_payload))<>4 OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_payload) k WHERE k NOT IN ('source','idempotency_key','occurred_at','input_artifacts')) OR jsonb_typeof(p_payload->'source')<>'string' OR jsonb_typeof(p_payload->'idempotency_key')<>'string' OR jsonb_typeof(p_payload->'occurred_at')<>'string' OR jsonb_typeof(p_payload->'input_artifacts')<>'array' OR p_payload->>'source'<>p_source OR p_payload->>'idempotency_key'<>p_key OR p_key<>btrim(p_key) OR p_key='' OR jsonb_array_length(p_payload->'input_artifacts')=0 OR jsonb_array_length(p_payload->'input_artifacts')<>(SELECT count(DISTINCT value::text) FROM jsonb_array_elements(p_payload->'input_artifacts')) OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_payload->'input_artifacts') a WHERE NOT fao.v1005_valid_artifact(a.value)) THEN RETURN FALSE; END IF;
          PERFORM (p_payload->>'occurred_at')::timestamptz;
          RETURN TRUE;
        EXCEPTION WHEN others THEN RETURN FALSE; END $$"""
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION fao.v1005_valid_task_result(p_task JSONB,p_result JSONB) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$ BEGIN
          IF jsonb_typeof(p_result)<>'object' OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_result) k WHERE k NOT IN ('task_id','status','artifacts','unknowns','warnings')) OR NOT (p_result ?& ARRAY['task_id','status','artifacts','unknowns','warnings']) OR p_result->>'task_id'<>p_task->>'task_id' OR p_result->>'status' NOT IN ('COMPLETED','DEFERRED','FAILED') OR jsonb_typeof(p_result->'task_id')<>'string' OR jsonb_typeof(p_result->'status')<>'string' OR jsonb_typeof(p_result->'artifacts')<>'array' OR jsonb_typeof(p_result->'unknowns')<>'array' OR jsonb_typeof(p_result->'warnings')<>'array' OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_result->'unknowns') x WHERE jsonb_typeof(x.value)<>'string' OR x.value#>>'{}'='' OR x.value#>>'{}'<>btrim(x.value#>>'{}')) OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_result->'warnings') x WHERE jsonb_typeof(x.value)<>'string' OR x.value#>>'{}'='' OR x.value#>>'{}'<>btrim(x.value#>>'{}')) OR (SELECT count(*) FROM jsonb_array_elements_text(p_result->'unknowns'))<>(SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p_result->'unknowns')) OR (SELECT count(*) FROM jsonb_array_elements_text(p_result->'warnings'))<>(SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p_result->'warnings')) THEN RETURN FALSE; END IF;
          IF p_result->>'status'='COMPLETED' THEN RETURN jsonb_typeof(p_result->'artifacts')='array' AND p_result->'artifacts'<> '[]'::jsonb AND (SELECT jsonb_agg(a.value->>'kind' ORDER BY a.ordinality) FROM jsonb_array_elements(p_result->'artifacts') WITH ORDINALITY a(value,ordinality))=p_task->'required_outputs' AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_result->'artifacts') a WHERE NOT fao.v1005_valid_artifact(a.value)); END IF;
          RETURN p_result->'artifacts'='[]'::jsonb AND jsonb_typeof(COALESCE(p_result->'unknowns','[]'::jsonb))='array' AND jsonb_typeof(COALESCE(p_result->'warnings','[]'::jsonb))='array' AND (jsonb_array_length(COALESCE(p_result->'unknowns','[]'::jsonb))+jsonb_array_length(COALESCE(p_result->'warnings','[]'::jsonb)))>0;
        EXCEPTION WHEN others THEN RETURN FALSE; END $$"""
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION fao.v1005_valid_artifact(JSONB),fao.v1005_valid_execution(UUID,JSONB,JSONB),fao.v1005_valid_task_result(JSONB,JSONB) TO fao_checkpoint_owner"
    )
    op.execute("RESET ROLE; SET ROLE fao_checkpoint_owner")
    op.execute(
        """CREATE OR REPLACE FUNCTION agent_checkpoint.v1005_valid_materialized_execution(p_episode UUID) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$ DECLARE x agent_checkpoint.workflow_execution%ROWTYPE; BEGIN
          SELECT * INTO x FROM agent_checkpoint.workflow_execution WHERE episode_id=p_episode;
          IF NOT FOUND OR NOT fao.v1005_valid_canonical(x.plan_payload,x.plan_canonical,x.plan_sha256) OR NOT fao.v1005_valid_canonical(x.task_set_payload,x.task_set_canonical,x.task_set_sha256) OR NOT fao.v1005_valid_execution(p_episode,x.plan_payload,x.task_set_payload) OR (SELECT count(*) FROM agent_checkpoint.workflow_task_checkpoint t WHERE t.episode_id=p_episode)<>jsonb_array_length(x.task_set_payload) OR EXISTS(SELECT 1 FROM agent_checkpoint.workflow_task_checkpoint t LEFT JOIN LATERAL jsonb_array_elements(x.task_set_payload) q(value) ON (q.value->>'task_id')::uuid=t.task_id WHERE t.episode_id=p_episode AND (q.value IS NULL OR t.step_key<>q.value->>'step_key' OR t.task_payload<>q.value OR t.task_canonical<>q.value::text OR t.task_sha256<>encode(public.digest(convert_to(q.value::text,'UTF8'),'sha256'),'hex') OR (t.result_payload IS NOT NULL AND (NOT fao.v1005_valid_canonical(t.result_payload,t.result_canonical,t.result_sha256) OR NOT fao.v1005_valid_task_result(t.task_payload,t.result_payload))) OR (t.result_payload IS NULL AND (t.result_canonical IS NOT NULL OR t.result_sha256 IS NOT NULL)))) OR EXISTS(SELECT 1 FROM jsonb_array_elements(x.task_set_payload) q(value) LEFT JOIN agent_checkpoint.workflow_task_checkpoint t ON t.episode_id=p_episode AND t.task_id=(q.value->>'task_id')::uuid WHERE t.task_id IS NULL) THEN RETURN FALSE; END IF;
          RETURN TRUE;
        EXCEPTION WHEN others THEN RETURN FALSE; END $$"""
    )
    op.execute("RESET ROLE; SET ROLE fao_business_owner")
    op.execute(
        """CREATE OR REPLACE FUNCTION fao.recoverable_workflow_cycles() RETURNS TABLE(cycle_id UUID) LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$ DECLARE n TIMESTAMPTZ:=clock_timestamp(); changed INT; ep UUID; BEGIN
          FOR ep IN SELECT episode_id FROM fao.decision_episode WHERE episode_status='RUNNING' AND expires_at<=n LOOP PERFORM fao.v1005_close_episode(ep); END LOOP;
          UPDATE agent_checkpoint.workflow_task_checkpoint t SET task_status='TIMED_OUT',version=t.version+1,lease_expires_at=NULL WHERE t.task_status IN ('PENDING','RUNNING') AND COALESCE(t.task_payload->>'deadline_at','infinity')::timestamptz<=n;
          LOOP UPDATE agent_checkpoint.workflow_task_checkpoint d SET task_status='SKIPPED',version=d.version+1 WHERE d.task_status='PENDING' AND EXISTS(SELECT 1 FROM jsonb_array_elements_text(COALESCE(d.task_payload->'depends_on','[]')) x JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=d.episode_id AND u.step_key=x.value WHERE u.task_status IN ('DEFERRED','FAILED','TIMED_OUT','CANCELLED','SKIPPED')); GET DIAGNOSTICS changed=ROW_COUNT; EXIT WHEN changed=0; END LOOP;
          FOR ep IN SELECT DISTINCT t.episode_id FROM agent_checkpoint.workflow_task_checkpoint t WHERE NOT EXISTS(SELECT 1 FROM agent_checkpoint.workflow_task_checkpoint u WHERE u.episode_id=t.episode_id AND u.task_status NOT IN ('COMPLETED','DEFERRED','FAILED','SKIPPED','CANCELLED','TIMED_OUT')) LOOP PERFORM fao.v1005_close_episode(ep); END LOOP;
          UPDATE fao.autonomy_cycle c SET version=c.version+1,cycle_status=CASE WHEN c.expires_at<=n THEN 'TIMED_OUT' ELSE 'DEFERRED' END,terminal_reason=CASE WHEN c.expires_at<=n THEN 'deadline_exceeded' ELSE 'all_episodes_terminal' END WHERE c.cycle_status='RUNNING' AND (c.expires_at<=n OR (EXISTS(SELECT 1 FROM fao.decision_episode e WHERE e.cycle_id=c.cycle_id) AND NOT EXISTS(SELECT 1 FROM fao.decision_episode e WHERE e.cycle_id=c.cycle_id AND e.episode_status='RUNNING')));
          RETURN QUERY SELECT c.cycle_id FROM fao.autonomy_cycle c WHERE c.cycle_status='RUNNING'; END $$"""
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION fao.cancel_decision_episode(p_episode UUID,p_reason TEXT) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$ DECLARE e fao.decision_episode%ROWTYPE; n TIMESTAMPTZ:=clock_timestamp(); BEGIN SELECT * INTO e FROM fao.decision_episode WHERE episode_id=p_episode FOR UPDATE; IF NOT FOUND OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR p_reason='' THEN RETURN FALSE; END IF; IF e.expires_at<=n THEN UPDATE agent_checkpoint.workflow_task_checkpoint SET task_status='TIMED_OUT',version=version+1,lease_expires_at=NULL WHERE episode_id=p_episode AND task_status IN ('PENDING','RUNNING'); UPDATE fao.decision_episode SET version=version+1,episode_status='TIMED_OUT',terminal_reason='deadline_exceeded' WHERE episode_id=p_episode AND episode_status='RUNNING'; ELSE UPDATE agent_checkpoint.workflow_task_checkpoint SET task_status='CANCELLED',version=version+1,lease_expires_at=NULL WHERE episode_id=p_episode AND task_status IN ('PENDING','RUNNING'); UPDATE fao.decision_episode SET version=version+1,episode_status='CANCELLED',terminal_reason=p_reason WHERE episode_id=p_episode AND episode_status='RUNNING'; END IF; UPDATE fao.autonomy_cycle c SET version=version+1,cycle_status='DEFERRED',terminal_reason='all_episodes_terminal' WHERE c.cycle_id=e.cycle_id AND c.cycle_status='RUNNING' AND NOT EXISTS(SELECT 1 FROM fao.decision_episode x WHERE x.cycle_id=c.cycle_id AND x.episode_status='RUNNING'); RETURN e.episode_status='RUNNING'; END $$"""
    )
    # Canonical text is intentionally supplied by the Python contract.  JSONB
    # is only a query projection; byte digest is checked over canonical UTF-8.
    op.execute("""CREATE FUNCTION fao.v1005_valid_canonical(p_json JSONB,p_text TEXT,p_hash TEXT) RETURNS BOOLEAN LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,pg_temp AS $$
      SELECT p_hash ~ '^[0-9a-f]{64}$' AND p_json IS NOT DISTINCT FROM p_text::jsonb AND p_hash=encode(public.digest(convert_to(p_text,'UTF8'),'sha256'),'hex') $$""")
    op.execute("""CREATE FUNCTION fao.start_autonomy_cycle(p_id UUID,p_source TEXT,p_key TEXT,p_corr UUID,p_payload JSONB,p_canonical TEXT,p_hash TEXT,p_expires TIMESTAMPTZ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$
      DECLARE r fao.autonomy_cycle%ROWTYPE; n timestamptz:=clock_timestamp(); BEGIN
      IF p_id IS NULL OR substring(p_id::text from 15 for 1)<>'7' OR substring(p_id::text from 20 for 1)!~'^[89ab]$' OR p_corr IS NULL OR p_source NOT IN ('USER','SCHEDULE','MARKET','DATA') OR p_key IS NULL OR p_key<>btrim(p_key) OR p_expires<=n OR NOT fao.v1005_valid_canonical(p_payload,p_canonical,p_hash) OR NOT fao.v1005_valid_cycle_trigger(p_source,p_key,p_payload) OR (p_payload->>'occurred_at')::timestamptz>n THEN RAISE EXCEPTION 'invalid cycle'; END IF;
      INSERT INTO fao.autonomy_cycle(cycle_id,trigger_source,idempotency_key,correlation_id,trigger_payload,trigger_canonical,trigger_sha256,started_at,expires_at) VALUES(p_id,p_source,p_key,p_corr,p_payload,p_canonical,p_hash,n,p_expires) ON CONFLICT DO NOTHING;
      SELECT * INTO r FROM fao.autonomy_cycle WHERE trigger_source=p_source AND idempotency_key=p_key FOR UPDATE;
      IF r.cycle_id IS DISTINCT FROM p_id OR r.correlation_id IS DISTINCT FROM p_corr OR r.trigger_source IS DISTINCT FROM p_source OR r.idempotency_key IS DISTINCT FROM p_key OR r.trigger_payload IS DISTINCT FROM p_payload OR r.trigger_canonical IS DISTINCT FROM p_canonical OR r.trigger_sha256 IS DISTINCT FROM p_hash OR r.expires_at IS DISTINCT FROM p_expires OR NOT fao.v1005_valid_canonical(r.trigger_payload,r.trigger_canonical,r.trigger_sha256) OR NOT fao.v1005_valid_cycle_trigger(r.trigger_source,r.idempotency_key,r.trigger_payload) THEN RAISE EXCEPTION 'cycle idempotency conflict'; END IF; RETURN r.cycle_id; END $$""")
    op.execute("""CREATE FUNCTION fao.start_decision_episode(p_id UUID,p_cycle UUID,p_candidate TEXT,p_expires TIMESTAMPTZ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$
      DECLARE c fao.autonomy_cycle%ROWTYPE; e fao.decision_episode%ROWTYPE; n timestamptz:=clock_timestamp(); BEGIN SELECT * INTO c FROM fao.autonomy_cycle WHERE cycle_id=p_cycle FOR UPDATE;
      IF NOT FOUND OR c.cycle_status<>'RUNNING' OR p_id IS NULL OR substring(p_id::text from 15 for 1)<>'7' OR substring(p_id::text from 20 for 1)!~'^[89ab]$' OR p_candidate IS NULL OR p_candidate<>btrim(p_candidate) OR p_expires<=n OR p_expires>c.expires_at THEN RAISE EXCEPTION 'invalid episode'; END IF;
      INSERT INTO fao.decision_episode(episode_id,cycle_id,candidate_key,correlation_id,started_at,decision_cutoff_at,expires_at) VALUES(p_id,p_cycle,p_candidate,c.correlation_id,n,n,p_expires) ON CONFLICT(cycle_id,candidate_key) DO NOTHING;
      SELECT * INTO e FROM fao.decision_episode WHERE cycle_id=p_cycle AND candidate_key=p_candidate FOR UPDATE; IF e.episode_id IS DISTINCT FROM p_id OR e.cycle_id IS DISTINCT FROM p_cycle OR e.correlation_id IS DISTINCT FROM c.correlation_id OR e.candidate_key IS DISTINCT FROM p_candidate OR e.expires_at IS DISTINCT FROM p_expires OR e.decision_cutoff_at IS DISTINCT FROM e.started_at THEN RAISE EXCEPTION 'episode conflict'; END IF; RETURN e.episode_id; END $$""")
    op.execute(
        """CREATE FUNCTION fao.recoverable_workflow_episodes() RETURNS TABLE(episode_id UUID) LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$ SELECT e.episode_id FROM fao.decision_episode e JOIN fao.autonomy_cycle c ON c.cycle_id=e.cycle_id WHERE e.episode_status='RUNNING' AND c.cycle_status='RUNNING' $$"""
    )
    op.execute(
        """CREATE FUNCTION fao.v1005_close_episode(p_episode UUID) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$ DECLARE e fao.decision_episode%ROWTYPE; bad boolean; n timestamptz:=clock_timestamp(); BEGIN SELECT * INTO e FROM fao.decision_episode WHERE episode_id=p_episode FOR UPDATE; IF NOT FOUND THEN RETURN; END IF; IF e.episode_status='RUNNING' AND e.expires_at<=n THEN UPDATE fao.decision_episode SET version=version+1,episode_status='TIMED_OUT',terminal_reason='deadline_exceeded' WHERE episode_id=p_episode AND episode_status='RUNNING'; UPDATE agent_checkpoint.workflow_task_checkpoint SET task_status='TIMED_OUT',version=version+1,lease_expires_at=NULL WHERE episode_id=p_episode AND task_status IN ('PENDING','RUNNING'); END IF; SELECT * INTO e FROM fao.decision_episode WHERE episode_id=p_episode; IF e.episode_status='RUNNING' AND NOT EXISTS(SELECT 1 FROM agent_checkpoint.workflow_task_checkpoint WHERE episode_id=p_episode AND task_status NOT IN ('COMPLETED','DEFERRED','FAILED','SKIPPED','CANCELLED','TIMED_OUT')) THEN SELECT EXISTS(SELECT 1 FROM agent_checkpoint.workflow_task_checkpoint WHERE episode_id=p_episode AND task_status<>'COMPLETED') INTO bad; UPDATE fao.decision_episode SET version=version+1,episode_status=CASE WHEN bad THEN 'DEFERRED' ELSE 'COMPLETED' END,terminal_reason='all_tasks_terminal' WHERE episode_id=p_episode; END IF; UPDATE fao.autonomy_cycle c SET version=version+1,cycle_status=CASE WHEN c.expires_at<=n THEN 'TIMED_OUT' WHEN EXISTS(SELECT 1 FROM fao.decision_episode e2 WHERE e2.cycle_id=c.cycle_id AND e2.episode_status<>'COMPLETED') THEN 'DEFERRED' ELSE 'COMPLETED' END,terminal_reason=CASE WHEN c.expires_at<=n THEN 'deadline_exceeded' ELSE 'all_episodes_terminal' END WHERE c.cycle_id=e.cycle_id AND c.cycle_status='RUNNING' AND EXISTS(SELECT 1 FROM fao.decision_episode e2 WHERE e2.cycle_id=c.cycle_id) AND NOT EXISTS(SELECT 1 FROM fao.decision_episode e2 WHERE e2.cycle_id=c.cycle_id AND e2.episode_status='RUNNING'); END $$"""
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION fao.v1005_valid_canonical(JSONB,TEXT,TEXT),fao.v1005_close_episode(UUID) TO fao_checkpoint_owner"
    )
    op.execute("RESET ROLE; SET ROLE fao_checkpoint_owner")
    op.execute(
        """CREATE FUNCTION agent_checkpoint.claim_workflow_task(p_episode UUID,p_worker TEXT,p_lease_seconds INT) RETURNS TABLE(task_id UUID,version BIGINT,fencing_token BIGINT,task_payload JSONB) LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$ DECLARE n timestamptz:=clock_timestamp(); lim int; changed int; BEGIN PERFORM pg_advisory_xact_lock(hashtextextended(p_episode::text,0)); IF p_worker IS NULL OR p_worker<>btrim(p_worker) OR p_lease_seconds NOT BETWEEN 1 AND 3600 THEN RAISE EXCEPTION 'invalid lease'; END IF; IF NOT agent_checkpoint.v1005_valid_materialized_execution(p_episode) THEN RAISE EXCEPTION 'checkpoint integrity drift'; END IF; PERFORM fao.v1005_close_episode(p_episode); UPDATE agent_checkpoint.workflow_task_checkpoint t SET task_status='PENDING',worker_id=NULL,lease_expires_at=NULL,version=t.version+1 WHERE t.episode_id=p_episode AND t.task_status='RUNNING' AND t.lease_expires_at<=n; UPDATE agent_checkpoint.workflow_task_checkpoint t SET task_status='TIMED_OUT',version=t.version+1,lease_expires_at=NULL WHERE t.episode_id=p_episode AND t.task_status IN ('PENDING','RUNNING') AND COALESCE(t.task_payload->>'deadline_at','infinity')::timestamptz<=n; LOOP UPDATE agent_checkpoint.workflow_task_checkpoint d SET task_status='SKIPPED',version=d.version+1,lease_expires_at=NULL WHERE d.episode_id=p_episode AND d.task_status='PENDING' AND EXISTS(SELECT 1 FROM jsonb_array_elements_text(COALESCE(d.task_payload->'depends_on','[]')) x JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=d.episode_id AND u.step_key=x.value WHERE u.task_status IN ('DEFERRED','FAILED','TIMED_OUT','CANCELLED','SKIPPED')); GET DIAGNOSTICS changed=ROW_COUNT; EXIT WHEN changed=0; END LOOP; PERFORM fao.v1005_close_episode(p_episode); SELECT COALESCE((plan_payload->'cycle_budget'->>'max_parallel_tasks')::int,1) INTO lim FROM agent_checkpoint.workflow_execution WHERE episode_id=p_episode; RETURN QUERY WITH candidate AS (SELECT t.task_id FROM agent_checkpoint.workflow_task_checkpoint t WHERE t.episode_id=p_episode AND t.task_status='PENDING' AND EXISTS(SELECT 1 FROM fao.decision_episode e WHERE e.episode_id=p_episode AND e.episode_status='RUNNING' AND e.expires_at>n) AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(COALESCE(t.task_payload->'depends_on','[]')) d JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=t.episode_id AND u.step_key=d.value WHERE u.task_status<>'COMPLETED') AND (SELECT count(*) FROM agent_checkpoint.workflow_task_checkpoint r WHERE r.episode_id=p_episode AND r.task_status='RUNNING' AND r.lease_expires_at>n)<lim ORDER BY t.step_key FOR UPDATE SKIP LOCKED LIMIT 1) UPDATE agent_checkpoint.workflow_task_checkpoint t SET task_status='RUNNING',worker_id=p_worker,fencing_token=t.fencing_token+1,lease_expires_at=n+make_interval(secs=>p_lease_seconds),version=t.version+1 FROM candidate c WHERE t.task_id=c.task_id RETURNING t.task_id,t.version,t.fencing_token,t.task_payload || jsonb_build_object('input_artifacts',t.task_payload->'input_artifacts' || COALESCE((SELECT jsonb_agg(a.value ORDER BY d.ordinality,a.ordinality) FROM jsonb_array_elements_text(t.task_payload->'depends_on') WITH ORDINALITY d(value,ordinality) JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=t.episode_id AND u.step_key=d.value CROSS JOIN LATERAL jsonb_array_elements(u.result_payload->'artifacts') WITH ORDINALITY a(value,ordinality)),'[]'::jsonb)); END $$"""
    )
    # The Python reference model rejects duplicate ArtifactRef values after
    # deterministic fan-in.  Do the same before changing task state, so a
    # worker never receives an ambiguous merged input set.
    op.execute(
        """CREATE OR REPLACE FUNCTION agent_checkpoint.claim_workflow_task(p_episode UUID,p_worker TEXT,p_lease_seconds INT)
        RETURNS TABLE(task_id UUID,version BIGINT,fencing_token BIGINT,task_payload JSONB)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$
        DECLARE n timestamptz:=clock_timestamp(); lim int; changed int;
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtextextended(p_episode::text,0));
          IF p_worker IS NULL OR p_worker<>btrim(p_worker) OR p_lease_seconds NOT BETWEEN 1 AND 3600 THEN RAISE EXCEPTION 'invalid lease'; END IF;
          IF NOT agent_checkpoint.v1005_valid_materialized_execution(p_episode) THEN RAISE EXCEPTION 'checkpoint integrity drift'; END IF;
          PERFORM fao.v1005_close_episode(p_episode);
          UPDATE agent_checkpoint.workflow_task_checkpoint t SET task_status='PENDING',worker_id=NULL,lease_expires_at=NULL,version=t.version+1 WHERE t.episode_id=p_episode AND t.task_status='RUNNING' AND t.lease_expires_at<=n;
          UPDATE agent_checkpoint.workflow_task_checkpoint t SET task_status='TIMED_OUT',version=t.version+1,lease_expires_at=NULL WHERE t.episode_id=p_episode AND t.task_status IN ('PENDING','RUNNING') AND COALESCE(t.task_payload->>'deadline_at','infinity')::timestamptz<=n;
          LOOP
            UPDATE agent_checkpoint.workflow_task_checkpoint d SET task_status='SKIPPED',version=d.version+1,lease_expires_at=NULL WHERE d.episode_id=p_episode AND d.task_status='PENDING' AND EXISTS(SELECT 1 FROM jsonb_array_elements_text(COALESCE(d.task_payload->'depends_on','[]')) x JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=d.episode_id AND u.step_key=x.value WHERE u.task_status IN ('DEFERRED','FAILED','TIMED_OUT','CANCELLED','SKIPPED'));
            GET DIAGNOSTICS changed=ROW_COUNT; EXIT WHEN changed=0;
          END LOOP;
          PERFORM fao.v1005_close_episode(p_episode);
          SELECT COALESCE((plan_payload->'cycle_budget'->>'max_parallel_tasks')::int,1) INTO lim FROM agent_checkpoint.workflow_execution WHERE episode_id=p_episode;
          IF EXISTS(
            SELECT 1 FROM agent_checkpoint.workflow_task_checkpoint t
            WHERE t.episode_id=p_episode AND t.task_status='PENDING'
              AND EXISTS(SELECT 1 FROM fao.decision_episode e WHERE e.episode_id=p_episode AND e.episode_status='RUNNING' AND e.expires_at>n)
              AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(COALESCE(t.task_payload->'depends_on','[]')) d JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=t.episode_id AND u.step_key=d.value WHERE u.task_status<>'COMPLETED')
              AND EXISTS(
                SELECT 1 FROM (
                  SELECT a.value AS artifact FROM jsonb_array_elements(t.task_payload->'input_artifacts') a
                  UNION ALL
                  SELECT a.value FROM jsonb_array_elements_text(t.task_payload->'depends_on') d JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=t.episode_id AND u.step_key=d.value CROSS JOIN LATERAL jsonb_array_elements(u.result_payload->'artifacts') a
                ) merged GROUP BY artifact HAVING count(*)>1
              )
          ) THEN RAISE EXCEPTION 'fan-in input artifacts must remain unique'; END IF;
          RETURN QUERY WITH candidate AS (
            SELECT t.task_id FROM agent_checkpoint.workflow_task_checkpoint t
            WHERE t.episode_id=p_episode AND t.task_status='PENDING'
              AND EXISTS(SELECT 1 FROM fao.decision_episode e WHERE e.episode_id=p_episode AND e.episode_status='RUNNING' AND e.expires_at>n)
              AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(COALESCE(t.task_payload->'depends_on','[]')) d JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=t.episode_id AND u.step_key=d.value WHERE u.task_status<>'COMPLETED')
              AND (SELECT count(*) FROM agent_checkpoint.workflow_task_checkpoint r WHERE r.episode_id=p_episode AND r.task_status='RUNNING' AND r.lease_expires_at>n)<lim
            ORDER BY t.step_key FOR UPDATE SKIP LOCKED LIMIT 1
          ) UPDATE agent_checkpoint.workflow_task_checkpoint t SET task_status='RUNNING',worker_id=p_worker,fencing_token=t.fencing_token+1,lease_expires_at=n+make_interval(secs=>p_lease_seconds),version=t.version+1 FROM candidate c WHERE t.task_id=c.task_id
          RETURNING t.task_id,t.version,t.fencing_token,t.task_payload || jsonb_build_object('input_artifacts',t.task_payload->'input_artifacts' || COALESCE((SELECT jsonb_agg(a.value ORDER BY d.ordinality,a.ordinality) FROM jsonb_array_elements_text(t.task_payload->'depends_on') WITH ORDINALITY d(value,ordinality) JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=t.episode_id AND u.step_key=d.value CROSS JOIN LATERAL jsonb_array_elements(u.result_payload->'artifacts') WITH ORDINALITY a(value,ordinality)),'[]'::jsonb));
        END $$"""
    )
    op.execute("RESET ROLE; SET ROLE fao_business_owner")
    # Replacing the legacy projector narrows all drift comparisons to the
    # journal's bound episode.  Independent episodes may legitimately share a
    # correlation ID and must never poison one another's rebuild.
    op.execute(
        """CREATE OR REPLACE FUNCTION fao.rebuild_decision_journal_projection(p_journal UUID,p_episode UUID,p_corr UUID,p_cutoff TIMESTAMPTZ,p_projected TIMESTAMPTZ) RETURNS INTEGER LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$ DECLARE added INT:=0; BEGIN
          IF p_projected<p_cutoff OR NOT EXISTS(SELECT 1 FROM fao.decision_episode WHERE episode_id=p_episode AND correlation_id=p_corr AND decision_cutoff_at=p_cutoff) THEN RAISE EXCEPTION 'invalid journal binding'; END IF;
          INSERT INTO fao.decision_journal(journal_id,projection_version,decision_episode_id,correlation_id,decision_cutoff_at) VALUES(p_journal,1,p_episode,p_corr,p_cutoff) ON CONFLICT DO NOTHING;
          INSERT INTO fao.decision_journal_binding(journal_id,episode_id,correlation_id,decision_cutoff_at) VALUES(p_journal,p_episode,p_corr,p_cutoff) ON CONFLICT DO NOTHING;
          IF NOT EXISTS(SELECT 1 FROM fao.decision_journal h JOIN fao.decision_journal_binding b USING(journal_id) WHERE h.journal_id=p_journal AND h.decision_episode_id=p_episode AND h.correlation_id=p_corr AND h.decision_cutoff_at=p_cutoff AND b.episode_id=p_episode AND b.correlation_id=p_corr AND b.decision_cutoff_at=p_cutoff) THEN RAISE EXCEPTION 'journal binding drift'; END IF;
          IF EXISTS(SELECT 1 FROM fao.workflow_episode_source es JOIN fao.domain_event d ON d.event_id=es.event_id JOIN fao.workflow_source_payload s ON s.event_id=d.event_id WHERE es.episode_id=p_episode AND (d.aggregate_type<>'autonomy_cycle' OR d.aggregate_id<>(SELECT cycle_id FROM fao.decision_episode WHERE episode_id=p_episode) OR d.schema_version<>'1.3' OR d.command_id IS NOT NULL OR d.causation_id IS NOT NULL OR d.correlation_id<>p_corr OR d.payload<>s.canonical_payload::jsonb OR d.payload_sha256<>s.payload_sha256 OR encode(public.digest(convert_to(s.canonical_payload,'UTF8'),'sha256'),'hex')<>d.payload_sha256)) THEN RAISE EXCEPTION 'source immutable fact mismatch'; END IF;
          INSERT INTO fao.source_event_identity(source_event_id,source_context,source_type,source_version,source_sha256,occurred_at,available_at,correlation_id) SELECT d.event_id,d.aggregate_type,d.event_type,d.aggregate_version,d.payload_sha256,d.occurred_at,d.recorded_at,d.correlation_id FROM fao.workflow_episode_source es JOIN fao.domain_event d ON d.event_id=es.event_id JOIN fao.workflow_source_payload s ON s.event_id=d.event_id WHERE es.episode_id=p_episode ON CONFLICT(source_event_id) DO NOTHING;
          IF EXISTS(SELECT 1 FROM fao.source_event_identity i JOIN fao.workflow_episode_source es ON es.event_id=i.source_event_id JOIN fao.domain_event d ON d.event_id=i.source_event_id WHERE es.episode_id=p_episode AND (i.source_context<>d.aggregate_type OR i.source_type<>d.event_type OR i.source_version<>d.aggregate_version OR i.source_sha256<>d.payload_sha256 OR i.occurred_at<>d.occurred_at OR i.available_at<>d.recorded_at OR i.correlation_id<>d.correlation_id)) THEN RAISE EXCEPTION 'source identity drift'; END IF;
          INSERT INTO fao.decision_journal_entry(entry_id,journal_id,source_event_id,projection_version,phase,source_context,source_type,source_version,source_sha256,observed_at,available_at,projected_at,decision_cutoff_at,correlation_id) SELECT gen_random_uuid(),p_journal,d.event_id,1,CASE WHEN d.recorded_at<=p_cutoff THEN 'DECISION_TIME' ELSE 'POST_HOC' END,d.aggregate_type,d.event_type,d.aggregate_version,d.payload_sha256,d.occurred_at,d.recorded_at,p_projected,p_cutoff,d.correlation_id FROM fao.workflow_episode_source es JOIN fao.domain_event d ON d.event_id=es.event_id WHERE es.episode_id=p_episode ON CONFLICT(journal_id,source_event_id,projection_version) DO NOTHING; GET DIAGNOSTICS added=ROW_COUNT;
          IF EXISTS(SELECT 1 FROM fao.decision_journal_entry j LEFT JOIN fao.workflow_episode_source es ON es.event_id=j.source_event_id AND es.episode_id=p_episode JOIN fao.domain_event d ON d.event_id=j.source_event_id WHERE j.journal_id=p_journal AND (es.event_id IS NULL OR j.source_context<>d.aggregate_type OR j.source_type<>d.event_type OR j.source_version<>d.aggregate_version OR j.source_sha256<>d.payload_sha256 OR j.observed_at<>d.occurred_at OR j.available_at<>d.recorded_at OR j.projected_at<j.available_at OR j.correlation_id<>p_corr OR j.decision_cutoff_at<>p_cutoff OR j.phase<>CASE WHEN d.recorded_at<=p_cutoff THEN 'DECISION_TIME' ELSE 'POST_HOC' END)) THEN RAISE EXCEPTION 'journal immutable fact mismatch'; END IF; RETURN added; END $$"""
    )
    # These are deliberately last: compatibility definitions above establish
    # objects for historical upgrades, while these definitions are authoritative
    # for every newly upgraded V1 database.
    op.execute("RESET ROLE; SET ROLE fao_checkpoint_owner")
    op.execute(
        """CREATE OR REPLACE FUNCTION agent_checkpoint.persist_workflow_execution(p_episode UUID,p_version BIGINT,p_plan JSONB,p_plan_text TEXT,p_plan_hash TEXT,p_tasks JSONB,p_tasks_text TEXT,p_tasks_hash TEXT) RETURNS BIGINT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$ DECLARE x agent_checkpoint.workflow_execution%ROWTYPE; inserted INT; BEGIN IF NOT fao.v1005_valid_canonical(p_plan,p_plan_text,p_plan_hash) OR NOT fao.v1005_valid_canonical(p_tasks,p_tasks_text,p_tasks_hash) OR NOT fao.v1005_valid_execution(p_episode,p_plan,p_tasks) OR NOT EXISTS(SELECT 1 FROM fao.decision_episode WHERE episode_id=p_episode AND episode_status='RUNNING' AND expires_at>clock_timestamp()) THEN RAISE EXCEPTION 'invalid typed workflow execution'; END IF; SELECT * INTO x FROM agent_checkpoint.workflow_execution WHERE episode_id=p_episode FOR UPDATE; IF FOUND THEN IF NOT agent_checkpoint.v1005_valid_materialized_execution(p_episode) THEN RAISE EXCEPTION 'checkpoint integrity drift'; END IF; IF x.plan_payload=p_plan AND x.plan_canonical=p_plan_text AND x.plan_sha256=p_plan_hash AND x.task_set_payload=p_tasks AND x.task_set_canonical=p_tasks_text AND x.task_set_sha256=p_tasks_hash THEN RETURN x.checkpoint_version; END IF; RAISE EXCEPTION 'checkpoint execution conflict'; END IF; IF p_version<>0 THEN RAISE EXCEPTION 'initial checkpoint version must be zero'; END IF; INSERT INTO agent_checkpoint.workflow_execution(episode_id,plan_payload,plan_canonical,plan_sha256,task_set_payload,task_set_canonical,task_set_sha256) VALUES(p_episode,p_plan,p_plan_text,p_plan_hash,p_tasks,p_tasks_text,p_tasks_hash) ON CONFLICT(episode_id) DO NOTHING; GET DIAGNOSTICS inserted=ROW_COUNT; IF inserted=0 THEN SELECT * INTO x FROM agent_checkpoint.workflow_execution WHERE episode_id=p_episode FOR UPDATE; IF NOT FOUND OR NOT agent_checkpoint.v1005_valid_materialized_execution(p_episode) THEN RAISE EXCEPTION 'checkpoint integrity drift'; END IF; IF x.plan_payload=p_plan AND x.plan_canonical=p_plan_text AND x.plan_sha256=p_plan_hash AND x.task_set_payload=p_tasks AND x.task_set_canonical=p_tasks_text AND x.task_set_sha256=p_tasks_hash THEN RETURN x.checkpoint_version; END IF; RAISE EXCEPTION 'checkpoint execution conflict'; END IF; INSERT INTO agent_checkpoint.workflow_task_checkpoint(task_id,episode_id,step_key,task_payload,task_canonical,task_sha256) SELECT (value->>'task_id')::uuid,p_episode,value->>'step_key',value,value::text,encode(public.digest(convert_to(value::text,'UTF8'),'sha256'),'hex') FROM jsonb_array_elements(p_tasks); RETURN 1; END $$"""
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION agent_checkpoint.complete_workflow_task(p_task UUID,p_version BIGINT,p_fencing BIGINT,p_result JSONB,p_result_text TEXT,p_result_hash TEXT) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$ DECLARE t agent_checkpoint.workflow_task_checkpoint%ROWTYPE; e fao.decision_episode%ROWTYPE; changed INT; n TIMESTAMPTZ:=clock_timestamp(); BEGIN SELECT * INTO t FROM agent_checkpoint.workflow_task_checkpoint WHERE task_id=p_task FOR UPDATE; IF NOT FOUND OR NOT fao.v1005_valid_canonical(p_result,p_result_text,p_result_hash) OR NOT fao.v1005_valid_task_result(t.task_payload,p_result) THEN RETURN FALSE; END IF; IF t.task_status IN ('COMPLETED','DEFERRED','FAILED') THEN RETURN t.version=p_version+1 AND t.fencing_token=p_fencing AND t.result_payload IS NOT NULL AND fao.v1005_valid_canonical(t.result_payload,t.result_canonical,t.result_sha256) AND fao.v1005_valid_task_result(t.task_payload,t.result_payload) AND t.result_payload=p_result AND t.result_canonical=p_result_text AND t.result_sha256=p_result_hash; END IF; SELECT * INTO e FROM fao.decision_episode WHERE episode_id=t.episode_id; IF t.task_status<>'RUNNING' OR t.version<>p_version OR t.fencing_token<>p_fencing OR t.lease_expires_at<=n OR COALESCE((t.task_payload->>'deadline_at')::timestamptz,n)<=n OR NOT FOUND OR e.episode_status<>'RUNNING' OR e.expires_at<=n THEN RETURN FALSE; END IF; UPDATE agent_checkpoint.workflow_task_checkpoint SET task_status=p_result->>'status',result_payload=p_result,result_canonical=p_result_text,result_sha256=p_result_hash,version=version+1,lease_expires_at=NULL WHERE task_id=p_task; LOOP UPDATE agent_checkpoint.workflow_task_checkpoint d SET task_status='SKIPPED',version=version+1 WHERE d.episode_id=t.episode_id AND d.task_status='PENDING' AND EXISTS(SELECT 1 FROM jsonb_array_elements_text(d.task_payload->'depends_on') x JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=d.episode_id AND u.step_key=x.value WHERE u.task_status IN ('DEFERRED','FAILED','TIMED_OUT','CANCELLED','SKIPPED')); GET DIAGNOSTICS changed=ROW_COUNT; EXIT WHEN changed=0; END LOOP; PERFORM fao.v1005_close_episode(t.episode_id); RETURN TRUE; END $$"""
    )
    op.execute("RESET ROLE; SET ROLE fao_business_owner")
    op.execute(
        """CREATE OR REPLACE FUNCTION fao.hydrate_workflow_episode(p_episode UUID) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$ DECLARE e fao.decision_episode%ROWTYPE; c fao.autonomy_cycle%ROWTYPE; x agent_checkpoint.workflow_execution%ROWTYPE; BEGIN SELECT * INTO e FROM fao.decision_episode WHERE episode_id=p_episode; IF NOT FOUND THEN RETURN NULL; END IF; SELECT * INTO c FROM fao.autonomy_cycle WHERE cycle_id=e.cycle_id; IF NOT FOUND OR c.correlation_id IS NULL OR e.correlation_id IS DISTINCT FROM c.correlation_id OR e.decision_cutoff_at IS DISTINCT FROM e.started_at OR NOT fao.v1005_valid_canonical(c.trigger_payload,c.trigger_canonical,c.trigger_sha256) OR NOT fao.v1005_valid_cycle_trigger(c.trigger_source,c.idempotency_key,c.trigger_payload) THEN RAISE EXCEPTION 'workflow creation integrity drift'; END IF; SELECT * INTO x FROM agent_checkpoint.workflow_execution WHERE episode_id=p_episode; IF x.episode_id IS NOT NULL AND (NOT fao.v1005_valid_canonical(x.plan_payload,x.plan_canonical,x.plan_sha256) OR NOT fao.v1005_valid_canonical(x.task_set_payload,x.task_set_canonical,x.task_set_sha256) OR NOT fao.v1005_valid_execution(p_episode,x.plan_payload,x.task_set_payload) OR EXISTS(SELECT 1 FROM agent_checkpoint.workflow_task_checkpoint t WHERE t.episode_id=p_episode AND (NOT fao.v1005_valid_canonical(t.task_payload,t.task_canonical,t.task_sha256) OR (t.result_payload IS NOT NULL AND (NOT fao.v1005_valid_canonical(t.result_payload,t.result_canonical,t.result_sha256) OR NOT fao.v1005_valid_task_result(t.task_payload,t.result_payload))) OR (t.result_payload IS NULL AND (t.result_canonical IS NOT NULL OR t.result_sha256 IS NOT NULL))))) THEN RAISE EXCEPTION 'checkpoint integrity drift'; END IF; RETURN jsonb_build_object('cycle',jsonb_build_object('cycle_id',c.cycle_id,'trigger',c.trigger_payload,'correlation_id',c.correlation_id,'started_at',c.started_at,'expires_at',c.expires_at,'status',c.cycle_status),'episode',jsonb_build_object('episode_id',e.episode_id,'candidate_key',e.candidate_key,'correlation_id',e.correlation_id,'started_at',e.started_at,'decision_cutoff_at',e.decision_cutoff_at,'expires_at',e.expires_at,'status',e.episode_status,'terminal_reason',e.terminal_reason),'execution',CASE WHEN x.episode_id IS NULL THEN NULL ELSE jsonb_build_object('plan',x.plan_payload,'version',x.checkpoint_version) END,'tasks',COALESCE((SELECT jsonb_agg(t.task_payload || jsonb_build_object('status',t.task_status,'result',t.result_payload) ORDER BY t.step_key) FROM agent_checkpoint.workflow_task_checkpoint t WHERE t.episode_id=p_episode),'[]'::jsonb)); END $$"""
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION fao.bind_workflow_source_episode(p_event UUID,p_episode UUID) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$ BEGIN INSERT INTO fao.workflow_episode_source(event_id,episode_id) SELECT p_event,p_episode FROM fao.workflow_source_payload s JOIN fao.domain_event d ON d.event_id=s.event_id JOIN fao.decision_episode e ON e.episode_id=p_episode WHERE s.event_id=p_event AND d.aggregate_type='autonomy_cycle' AND d.aggregate_id=e.cycle_id AND d.correlation_id=e.correlation_id AND d.schema_version='1.3' AND d.command_id IS NULL AND d.causation_id IS NULL AND d.payload=s.canonical_payload::jsonb AND d.payload_sha256=s.payload_sha256 ON CONFLICT(event_id) DO NOTHING; RETURN EXISTS(SELECT 1 FROM fao.workflow_episode_source WHERE event_id=p_event AND episode_id=p_episode); END $$"""
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION fao.append_workflow_domain_event(p_id UUID,p_aggregate UUID,p_version BIGINT,p_type TEXT,p_corr UUID,p_key TEXT,p_payload JSONB,p_canonical TEXT,p_hash TEXT,p_occurred TIMESTAMPTZ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$ DECLARE n TIMESTAMPTZ:=clock_timestamp(); BEGIN IF p_id IS NULL OR p_aggregate IS NULL OR p_version<1 OR p_type IS NULL OR p_type<>btrim(p_type) OR p_key IS NULL OR p_key<>btrim(p_key) OR p_occurred IS NULL OR p_occurred>n OR NOT fao.v1005_valid_canonical(p_payload,p_canonical,p_hash) THEN RETURN FALSE; END IF; INSERT INTO fao.domain_event(event_id,aggregate_type,aggregate_id,aggregate_version,event_type,schema_version,correlation_id,idempotency_key,actor_ref,payload,payload_sha256,occurred_at,recorded_at) VALUES(p_id,'autonomy_cycle',p_aggregate,p_version,p_type,'1.3',p_corr,p_key,'service:workflow',p_payload,p_hash,p_occurred,n); INSERT INTO fao.workflow_source_payload VALUES(p_id,p_canonical,p_hash); RETURN TRUE; EXCEPTION WHEN unique_violation THEN INSERT INTO fao.workflow_source_payload(event_id,canonical_payload,payload_sha256) SELECT p_id,p_canonical,p_hash WHERE EXISTS(SELECT 1 FROM fao.domain_event d WHERE d.event_id=p_id AND d.aggregate_type='autonomy_cycle' AND d.aggregate_id=p_aggregate AND d.aggregate_version=p_version AND d.event_type=p_type AND d.schema_version='1.3' AND d.command_id IS NULL AND d.causation_id IS NULL AND d.correlation_id=p_corr AND d.idempotency_key=p_key AND d.actor_ref='service:workflow' AND d.payload=p_payload AND d.payload_sha256=p_hash AND d.occurred_at=p_occurred AND d.recorded_at>=d.occurred_at) ON CONFLICT(event_id) DO NOTHING; RETURN EXISTS(SELECT 1 FROM fao.domain_event d JOIN fao.workflow_source_payload s USING(event_id) WHERE d.event_id=p_id AND d.aggregate_type='autonomy_cycle' AND d.aggregate_id=p_aggregate AND d.aggregate_version=p_version AND d.event_type=p_type AND d.schema_version='1.3' AND d.command_id IS NULL AND d.causation_id IS NULL AND d.correlation_id=p_corr AND d.idempotency_key=p_key AND d.actor_ref='service:workflow' AND d.payload=p_payload AND d.payload=s.canonical_payload::jsonb AND d.payload_sha256=p_hash AND d.occurred_at=p_occurred AND d.recorded_at>=d.occurred_at AND s.canonical_payload=p_canonical AND s.payload_sha256=p_hash); END $$"""
    )
    # append-only source data includes its byte representation as well as JSONB.
    op.execute(
        """CREATE FUNCTION fao.reject_v1005_mutation() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$ BEGIN RAISE EXCEPTION 'V1-008 source facts are append-only'; END $$"""
    )
    op.execute(
        """CREATE FUNCTION fao.reject_v1005_workflow_creation_mutation() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$ BEGIN
          IF TG_OP='DELETE' THEN RAISE EXCEPTION 'workflow creation facts are immutable'; END IF;
          IF TG_TABLE_NAME='autonomy_cycle' THEN IF OLD.cycle_id IS DISTINCT FROM NEW.cycle_id OR OLD.trigger_source IS DISTINCT FROM NEW.trigger_source OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key OR OLD.correlation_id IS DISTINCT FROM NEW.correlation_id OR OLD.trigger_payload IS DISTINCT FROM NEW.trigger_payload OR OLD.trigger_canonical IS DISTINCT FROM NEW.trigger_canonical OR OLD.trigger_sha256 IS DISTINCT FROM NEW.trigger_sha256 OR OLD.started_at IS DISTINCT FROM NEW.started_at OR OLD.expires_at IS DISTINCT FROM NEW.expires_at THEN RAISE EXCEPTION 'workflow creation facts are immutable'; END IF; END IF;
          IF TG_TABLE_NAME='decision_episode' THEN IF OLD.episode_id IS DISTINCT FROM NEW.episode_id OR OLD.cycle_id IS DISTINCT FROM NEW.cycle_id OR OLD.candidate_key IS DISTINCT FROM NEW.candidate_key OR OLD.correlation_id IS DISTINCT FROM NEW.correlation_id OR OLD.started_at IS DISTINCT FROM NEW.started_at OR OLD.decision_cutoff_at IS DISTINCT FROM NEW.decision_cutoff_at OR OLD.expires_at IS DISTINCT FROM NEW.expires_at THEN RAISE EXCEPTION 'workflow creation facts are immutable'; END IF; END IF;
          RETURN NEW;
        END $$"""
    )
    op.execute(
        "CREATE TRIGGER tr_v1005_source_payload_immutable BEFORE UPDATE OR DELETE ON fao.workflow_source_payload FOR EACH ROW EXECUTE FUNCTION fao.reject_v1005_mutation()"
    )
    op.execute(
        "CREATE TRIGGER tr_v1005_episode_source_immutable BEFORE UPDATE OR DELETE ON fao.workflow_episode_source FOR EACH ROW EXECUTE FUNCTION fao.reject_v1005_mutation()"
    )
    op.execute(
        "CREATE TRIGGER tr_v1005_journal_binding_immutable BEFORE UPDATE OR DELETE ON fao.decision_journal_binding FOR EACH ROW EXECUTE FUNCTION fao.reject_v1005_mutation()"
    )
    op.execute(
        "CREATE TRIGGER tr_v1005_cycle_creation_immutable BEFORE UPDATE OR DELETE ON fao.autonomy_cycle FOR EACH ROW EXECUTE FUNCTION fao.reject_v1005_workflow_creation_mutation()"
    )
    op.execute(
        "CREATE TRIGGER tr_v1005_episode_creation_immutable BEFORE UPDATE OR DELETE ON fao.decision_episode FOR EACH ROW EXECUTE FUNCTION fao.reject_v1005_workflow_creation_mutation()"
    )
    op.execute(
        """CREATE FUNCTION fao.reject_v1005_domain_event_mutation() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$ BEGIN IF OLD.actor_ref='service:workflow' THEN RAISE EXCEPTION 'V1-008 domain event is append-only'; END IF; RETURN OLD; END $$"""
    )
    op.execute(
        "CREATE TRIGGER tr_v1005_domain_event_immutable BEFORE UPDATE OR DELETE ON fao.domain_event FOR EACH ROW EXECUTE FUNCTION fao.reject_v1005_domain_event_mutation()"
    )
    op.execute("RESET ROLE; SET ROLE fao_checkpoint_owner")
    op.execute(
        "REVOKE ALL ON ALL TABLES IN SCHEMA agent_checkpoint FROM PUBLIC,fao_runtime,fao_agent_worker,fao_workflow_worker,fao_learning_projector"
    )
    op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA agent_checkpoint FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION agent_checkpoint.persist_workflow_execution(UUID,BIGINT,JSONB,TEXT,TEXT,JSONB,TEXT,TEXT),agent_checkpoint.claim_workflow_task(UUID,TEXT,INT),agent_checkpoint.complete_workflow_task(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT) TO fao_workflow_worker"
    )
    op.execute(
        """CREATE FUNCTION agent_checkpoint.reject_workflow_execution_mutation() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,agent_checkpoint,pg_temp AS $$ BEGIN IF OLD.plan_payload IS DISTINCT FROM NEW.plan_payload OR OLD.plan_canonical IS DISTINCT FROM NEW.plan_canonical OR OLD.plan_sha256 IS DISTINCT FROM NEW.plan_sha256 OR OLD.task_set_payload IS DISTINCT FROM NEW.task_set_payload OR OLD.task_set_canonical IS DISTINCT FROM NEW.task_set_canonical OR OLD.task_set_sha256 IS DISTINCT FROM NEW.task_set_sha256 THEN RAISE EXCEPTION 'workflow execution is immutable'; END IF; RETURN NEW; END $$"""
    )
    op.execute(
        """CREATE FUNCTION agent_checkpoint.reject_workflow_task_definition_mutation() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,agent_checkpoint,pg_temp AS $$ BEGIN IF TG_OP='DELETE' OR OLD.task_id IS DISTINCT FROM NEW.task_id OR OLD.episode_id IS DISTINCT FROM NEW.episode_id OR OLD.step_key IS DISTINCT FROM NEW.step_key OR OLD.task_payload IS DISTINCT FROM NEW.task_payload OR OLD.task_canonical IS DISTINCT FROM NEW.task_canonical OR OLD.task_sha256 IS DISTINCT FROM NEW.task_sha256 THEN RAISE EXCEPTION 'workflow task definition is immutable'; END IF; RETURN NEW; END $$"""
    )
    op.execute(
        "CREATE TRIGGER tr_v1005_workflow_execution_immutable BEFORE UPDATE ON agent_checkpoint.workflow_execution FOR EACH ROW EXECUTE FUNCTION agent_checkpoint.reject_workflow_execution_mutation()"
    )
    op.execute(
        "CREATE TRIGGER tr_v1005_workflow_task_definition_immutable BEFORE UPDATE OR DELETE ON agent_checkpoint.workflow_task_checkpoint FOR EACH ROW EXECUTE FUNCTION agent_checkpoint.reject_workflow_task_definition_mutation()"
    )
    op.execute("RESET ROLE; SET ROLE fao_business_owner")
    op.execute(
        "REVOKE ALL ON fao.autonomy_cycle,fao.decision_episode,fao.workflow_source_payload,fao.decision_journal_binding FROM PUBLIC,fao_runtime,fao_agent_worker,fao_workflow_worker,fao_learning_projector"
    )
    op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA fao FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION fao.start_autonomy_cycle(UUID,TEXT,TEXT,UUID,JSONB,TEXT,TEXT,TIMESTAMPTZ),fao.start_decision_episode(UUID,UUID,TEXT,TIMESTAMPTZ),fao.append_workflow_domain_event(UUID,UUID,BIGINT,TEXT,UUID,TEXT,JSONB,TEXT,TEXT,TIMESTAMPTZ),fao.bind_workflow_source_episode(UUID,UUID),fao.recoverable_workflow_cycles(),fao.recoverable_workflow_episodes(),fao.hydrate_workflow_episode(UUID),fao.cancel_decision_episode(UUID,TEXT) TO fao_workflow_worker"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION fao.rebuild_decision_journal_projection(UUID,UUID,UUID,TIMESTAMPTZ,TIMESTAMPTZ) TO fao_learning_projector"
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE fao_business_owner")
    op.execute("DROP TRIGGER IF EXISTS tr_v1005_domain_event_immutable ON fao.domain_event")
    op.execute("DROP TRIGGER IF EXISTS tr_v1005_cycle_creation_immutable ON fao.autonomy_cycle")
    op.execute("DROP TRIGGER IF EXISTS tr_v1005_episode_creation_immutable ON fao.decision_episode")
    op.execute("DROP TRIGGER IF EXISTS tr_v1005_source_payload_immutable ON fao.workflow_source_payload")
    op.execute("DROP TRIGGER IF EXISTS tr_v1005_episode_source_immutable ON fao.workflow_episode_source")
    op.execute("DROP TRIGGER IF EXISTS tr_v1005_journal_binding_immutable ON fao.decision_journal_binding")
    op.execute("RESET ROLE; SET ROLE fao_checkpoint_owner")
    op.execute("DROP TRIGGER IF EXISTS tr_v1005_workflow_execution_immutable ON agent_checkpoint.workflow_execution")
    op.execute(
        "DROP TRIGGER IF EXISTS tr_v1005_workflow_task_definition_immutable ON agent_checkpoint.workflow_task_checkpoint"
    )
    op.execute("DROP FUNCTION IF EXISTS agent_checkpoint.reject_workflow_execution_mutation()")
    op.execute("DROP FUNCTION IF EXISTS agent_checkpoint.reject_workflow_task_definition_mutation()")
    op.execute("RESET ROLE; SET ROLE fao_business_owner")
    op.execute(
        "DROP FUNCTION IF EXISTS fao.bind_workflow_source_episode(UUID,UUID),fao.reject_v1005_domain_event_mutation(),fao.reject_v1005_workflow_creation_mutation(),fao.reject_v1005_mutation(),fao.rebuild_decision_journal_projection(UUID,UUID,UUID,TIMESTAMPTZ,TIMESTAMPTZ),fao.v1005_close_episode(UUID),fao.cancel_decision_episode(UUID,TEXT),fao.hydrate_workflow_episode(UUID),fao.recoverable_workflow_episodes(),fao.recoverable_workflow_cycles(),fao.append_workflow_domain_event(UUID,UUID,BIGINT,TEXT,UUID,TEXT,JSONB,TEXT,TEXT,TIMESTAMPTZ),fao.start_decision_episode(UUID,UUID,TEXT,TIMESTAMPTZ),fao.start_autonomy_cycle(UUID,TEXT,TEXT,UUID,JSONB,TEXT,TEXT,TIMESTAMPTZ),fao.v1005_valid_task_result(JSONB,JSONB),fao.v1005_valid_execution(UUID,JSONB,JSONB),fao.v1005_valid_cycle_trigger(TEXT,TEXT,JSONB),fao.v1005_valid_artifact(JSONB),fao.v1005_valid_canonical(JSONB,TEXT,TEXT)"
    )
    op.execute("RESET ROLE; SET ROLE fao_checkpoint_owner")
    op.execute(
        "DROP FUNCTION IF EXISTS agent_checkpoint.complete_workflow_task(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT),agent_checkpoint.claim_workflow_task(UUID,TEXT,INT),agent_checkpoint.persist_workflow_execution(UUID,BIGINT,JSONB,TEXT,TEXT,JSONB,TEXT,TEXT),agent_checkpoint.v1005_valid_materialized_execution(UUID)"
    )
    op.execute("DROP TABLE IF EXISTS agent_checkpoint.workflow_task_checkpoint,agent_checkpoint.workflow_execution")
    op.execute("RESET ROLE; SET ROLE fao_business_owner")
    op.execute(
        "DROP TABLE IF EXISTS fao.decision_journal_binding,fao.workflow_episode_source,fao.workflow_source_payload,fao.decision_episode,fao.autonomy_cycle"
    )
    op.execute(
        "ALTER TABLE fao.decision_journal DROP COLUMN IF EXISTS decision_episode_id, DROP COLUMN IF EXISTS correlation_id, DROP COLUMN IF EXISTS decision_cutoff_at"
    )
    op.execute("RESET ROLE")
