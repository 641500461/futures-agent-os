"""V1-009: add the research Critic to durable observe workflow fan-in."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision = "0006_v1_009"
down_revision: str | Sequence[str] | None = "0005_v1_008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE fao_business_owner")
    # Preserve the released 0005 validators byte-for-byte under private legacy
    # names.  The new public validators are additive OR-wrappers, so an already
    # persisted Catalog 1.3 execution continues to use its original semantics.
    op.execute("ALTER FUNCTION fao.v1005_valid_artifact(JSONB) RENAME TO v1005_valid_artifact_legacy")
    op.execute("ALTER FUNCTION fao.v1005_valid_execution(UUID,JSONB,JSONB) RENAME TO v1005_valid_execution_legacy")
    op.execute(
        """CREATE FUNCTION fao.v1006_valid_critique_artifact(p JSONB) RETURNS BOOLEAN
        LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,pg_temp AS $$
          SELECT jsonb_typeof(p)='object'
            AND p ?& ARRAY['id','namespace','kind','schema','hash','created_at','as_of']
            AND (SELECT count(*) FROM jsonb_object_keys(p))=7
            AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(p) k WHERE k NOT IN ('id','namespace','kind','schema','hash','created_at','as_of'))
            AND jsonb_typeof(p->'id')='string' AND jsonb_typeof(p->'namespace')='string'
            AND jsonb_typeof(p->'kind')='string' AND jsonb_typeof(p->'schema')='string'
            AND jsonb_typeof(p->'hash')='string' AND jsonb_typeof(p->'created_at')='string'
            AND jsonb_typeof(p->'as_of')='string'
            AND p->>'id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            AND substring(p->>'id' from 15 for 1)='7' AND substring(p->>'id' from 20 for 1)~'^[89ab]$'
            AND p->>'namespace'='critique' AND p->>'kind'='critique'
            AND p->>'schema' ~ '^[0-9]+\\.[0-9]+$' AND p->>'hash' ~ '^sha256:[0-9a-f]{64}$'
            AND (p->>'created_at')::timestamptz >= (p->>'as_of')::timestamptz
        $$"""
    )
    op.execute(
        """CREATE FUNCTION fao.v1005_valid_artifact(p JSONB) RETURNS BOOLEAN
        LANGUAGE sql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$
          SELECT fao.v1005_valid_artifact_legacy(p) OR fao.v1006_valid_critique_artifact(p)
        $$"""
    )
    op.execute(
        """CREATE FUNCTION fao.v1006_valid_critic_execution(p_episode UUID,p_plan JSONB,p_tasks JSONB)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$
        DECLARE
          critic JSONB;
          critic_task JSONB;
          upstream JSONB;
          legacy_plan JSONB;
          legacy_tasks JSONB;
          critic_key TEXT;
          upstream_key TEXT;
        BEGIN
          IF jsonb_typeof(p_plan)<>'object' OR jsonb_typeof(p_plan->'steps')<>'array'
             OR jsonb_typeof(p_tasks)<>'array'
             OR (SELECT count(*) FROM jsonb_array_elements(p_plan->'steps') s WHERE s.value->>'role_id'='pre_trade_critic')<>1
             OR jsonb_array_length(p_plan->'steps')<>jsonb_array_length(p_tasks)
             OR jsonb_array_length(p_plan->'steps')<>(SELECT count(DISTINCT s.value->>'step_key') FROM jsonb_array_elements(p_plan->'steps') s)
             OR jsonb_array_length(p_tasks)<>(SELECT count(DISTINCT t.value->>'task_id') FROM jsonb_array_elements(p_tasks) t)
          THEN RETURN FALSE; END IF;

          SELECT value INTO critic FROM jsonb_array_elements(p_plan->'steps')
            WHERE value->>'role_id'='pre_trade_critic';
          critic_key:=critic->>'step_key';
          IF jsonb_typeof(critic)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(critic))<>6
             OR EXISTS(SELECT 1 FROM jsonb_object_keys(critic) k WHERE k NOT IN ('step_key','role_id','input_artifacts','required_outputs','budget','depends_on'))
             OR jsonb_typeof(critic->'step_key')<>'string' OR critic_key IS NULL OR critic_key='' OR critic_key<>btrim(critic_key)
             OR critic->'input_artifacts'<>'[]'::jsonb
             OR critic->'required_outputs'<>jsonb_build_array('critique')
             OR jsonb_typeof(critic->'depends_on')<>'array' OR jsonb_array_length(critic->'depends_on')<>1
             OR jsonb_typeof(critic->'depends_on'->0)<>'string'
             OR jsonb_typeof(critic->'budget')<>'object' OR (SELECT count(*) FROM jsonb_object_keys(critic->'budget'))<>5
             OR EXISTS(SELECT 1 FROM jsonb_object_keys(critic->'budget') k WHERE k NOT IN ('max_turns','max_tool_calls','max_tokens','timeout_seconds','max_parallel_tasks'))
             OR EXISTS(SELECT 1 FROM jsonb_each(critic->'budget') b WHERE jsonb_typeof(b.value)<>'number' OR (b.value#>>'{}')::numeric<=0 OR (b.value#>>'{}')::numeric<>trunc((b.value#>>'{}')::numeric))
             OR (critic->'budget'->>'max_turns')::int>4
             OR (critic->'budget'->>'max_tool_calls')::int>16
             OR (critic->'budget'->>'max_tokens')::int>12000
             OR (critic->'budget'->>'timeout_seconds')::int>120
             OR (critic->'budget'->>'max_parallel_tasks')::int>1
          THEN RETURN FALSE; END IF;
          IF EXISTS(
            SELECT 1 FROM (
              SELECT SUM((value->'budget'->>'max_turns')::bigint) turns,
                     SUM((value->'budget'->>'max_tool_calls')::bigint) calls,
                     SUM((value->'budget'->>'max_tokens')::bigint) tokens,
                     SUM((value->'budget'->>'timeout_seconds')::bigint) seconds,
                     MAX((value->'budget'->>'max_parallel_tasks')::bigint) parallel
              FROM jsonb_array_elements(p_plan->'steps')
            ) totals
            WHERE totals.turns>(p_plan->'cycle_budget'->>'max_turns')::bigint
               OR totals.calls>(p_plan->'cycle_budget'->>'max_tool_calls')::bigint
               OR totals.tokens>(p_plan->'cycle_budget'->>'max_tokens')::bigint
               OR totals.seconds>(p_plan->'cycle_budget'->>'timeout_seconds')::bigint
               OR totals.parallel>(p_plan->'cycle_budget'->>'max_parallel_tasks')::bigint
          ) THEN RETURN FALSE; END IF;

          upstream_key:=critic->'depends_on'->>0;
          SELECT value INTO upstream FROM jsonb_array_elements(p_plan->'steps')
            WHERE value->>'step_key'=upstream_key;
          IF upstream IS NULL OR upstream->>'role_id'<>'research'
             OR upstream->'required_outputs'<>jsonb_build_array('hypothesis','evidence_synthesis','experiment_request')
          THEN RETURN FALSE; END IF;

          SELECT value INTO critic_task FROM jsonb_array_elements(p_tasks)
            WHERE value->>'step_key'=critic_key;
          IF critic_task IS NULL OR (SELECT count(*) FROM jsonb_array_elements(p_tasks) t WHERE t.value->>'step_key'=critic_key)<>1
             OR jsonb_typeof(critic_task)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(critic_task))<>9
             OR EXISTS(SELECT 1 FROM jsonb_object_keys(critic_task) k WHERE k NOT IN ('task_id','episode_id','step_key','role_id','deadline_at','depends_on','required_outputs','input_artifacts','budget'))
             OR critic_task->>'task_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
             OR substring(critic_task->>'task_id' from 15 for 1)<>'7' OR substring(critic_task->>'task_id' from 20 for 1)!~'^[89ab]$'
             OR critic_task->>'episode_id'<>p_episode::text OR critic_task->>'role_id'<>'pre_trade_critic'
             OR critic_task->'depends_on'<>critic->'depends_on'
             OR critic_task->'required_outputs'<>critic->'required_outputs'
             OR critic_task->'input_artifacts'<>critic->'input_artifacts'
             OR critic_task->'budget'<>critic->'budget'
             OR jsonb_typeof(critic_task->'deadline_at')<>'string'
             OR (critic_task->>'deadline_at')::timestamptz>(p_plan->>'expires_at')::timestamptz
          THEN RETURN FALSE; END IF;

          legacy_plan:=jsonb_set(
            p_plan,'{steps}',
            COALESCE((SELECT jsonb_agg(s.value ORDER BY s.ordinality)
              FROM jsonb_array_elements(p_plan->'steps') WITH ORDINALITY s(value,ordinality)
              WHERE s.value->>'role_id'<>'pre_trade_critic'),'[]'::jsonb)
          );
          legacy_tasks:=COALESCE((SELECT jsonb_agg(t.value ORDER BY t.ordinality)
            FROM jsonb_array_elements(p_tasks) WITH ORDINALITY t(value,ordinality)
            WHERE t.value->>'role_id'<>'pre_trade_critic'),'[]'::jsonb);
          RETURN fao.v1005_valid_execution_legacy(p_episode,legacy_plan,legacy_tasks);
        EXCEPTION WHEN others THEN RETURN FALSE; END $$"""
    )
    op.execute(
        """CREATE FUNCTION fao.v1005_valid_execution(p_episode UUID,p_plan JSONB,p_tasks JSONB)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,pg_temp AS $$
        BEGIN
          RETURN fao.v1005_valid_execution_legacy(p_episode,p_plan,p_tasks)
                 OR fao.v1006_valid_critic_execution(p_episode,p_plan,p_tasks);
        EXCEPTION WHEN others THEN RETURN FALSE; END $$"""
    )
    op.execute(
        """CREATE FUNCTION fao.v1006_canonical_json(p JSONB) RETURNS TEXT
        LANGUAGE plpgsql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        DECLARE result TEXT;
        BEGIN
          CASE jsonb_typeof(p)
          WHEN 'object' THEN SELECT '{'||COALESCE(string_agg(to_jsonb(key)::text||':'||fao.v1006_canonical_json(value),',' ORDER BY key),'')||'}' INTO result FROM jsonb_each(p);
          WHEN 'array' THEN SELECT '['||COALESCE(string_agg(fao.v1006_canonical_json(value),',' ORDER BY ordinality),'')||']' INTO result FROM jsonb_array_elements(p) WITH ORDINALITY items(value,ordinality);
          ELSE result:=p::text;
          END CASE;
          RETURN result;
        END $$"""
    )
    op.execute(
        """CREATE FUNCTION fao.v1006_valid_canonical_text_set(p JSONB,p_required BOOLEAN) RETURNS BOOLEAN
        LANGUAGE plpgsql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        DECLARE normalized JSONB;
        BEGIN
          IF jsonb_typeof(p)<>'array' OR (p_required AND jsonb_array_length(p)=0)
             OR EXISTS(SELECT 1 FROM jsonb_array_elements(p) x WHERE jsonb_typeof(x.value)<>'string' OR x.value#>>'{}'='' OR x.value#>>'{}'<>btrim(x.value#>>'{}'))
          THEN RETURN FALSE; END IF;
          SELECT COALESCE(jsonb_agg(to_jsonb(v) ORDER BY v COLLATE "C"),'[]'::jsonb) INTO normalized
          FROM (SELECT DISTINCT x.value#>>'{}' AS v FROM jsonb_array_elements(p) x) valueset;
          RETURN p=normalized;
        EXCEPTION WHEN others THEN RETURN FALSE; END $$"""
    )
    op.execute(
        """CREATE FUNCTION fao.v1006_valid_entity_id(p JSONB,p_namespace TEXT) RETURNS BOOLEAN
        LANGUAGE plpgsql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        DECLARE serialized TEXT; identifier TEXT;
        BEGIN
          IF jsonb_typeof(p)<>'string' OR p_namespace='' THEN RETURN FALSE; END IF;
          serialized:=p#>>'{}';
          IF left(serialized,char_length(p_namespace)+1)<>p_namespace||'_' THEN RETURN FALSE; END IF;
          identifier:=substring(serialized from char_length(p_namespace)+2);
          RETURN identifier~'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                 AND substring(identifier from 15 for 1)='7'
                 AND substring(identifier from 20 for 1)~'^[89ab]$';
        EXCEPTION WHEN others THEN RETURN FALSE; END $$"""
    )
    op.execute(
        """CREATE FUNCTION fao.v1006_valid_canonical_evidence_gaps(p JSONB) RETURNS BOOLEAN
        LANGUAGE plpgsql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        DECLARE normalized JSONB;
        BEGIN
          IF jsonb_typeof(p)<>'array' OR EXISTS(
            SELECT 1 FROM jsonb_array_elements(p) x
            WHERE jsonb_typeof(x.value)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(x.value))<>2
               OR EXISTS(SELECT 1 FROM jsonb_object_keys(x.value) k WHERE k NOT IN ('code','description'))
               OR jsonb_typeof(x.value->'code')<>'string' OR (x.value->>'code')!~'^[a-z][a-z0-9_]*$'
               OR jsonb_typeof(x.value->'description')<>'string' OR btrim(x.value->>'description')=''
          ) THEN RETURN FALSE; END IF;
          SELECT COALESCE(jsonb_agg(value ORDER BY value->>'code' COLLATE "C",value->>'description' COLLATE "C"),'[]'::jsonb) INTO normalized
          FROM (SELECT DISTINCT x.value FROM jsonb_array_elements(p) x) gapset;
          RETURN p=normalized;
        EXCEPTION WHEN others THEN RETURN FALSE; END $$"""
    )
    op.execute(
        "REVOKE ALL ON FUNCTION fao.v1005_valid_artifact(JSONB),fao.v1006_valid_critique_artifact(JSONB),fao.v1005_valid_execution(UUID,JSONB,JSONB),fao.v1006_valid_critic_execution(UUID,JSONB,JSONB),fao.v1006_canonical_json(JSONB),fao.v1006_valid_canonical_text_set(JSONB,BOOLEAN),fao.v1006_valid_entity_id(JSONB,TEXT),fao.v1006_valid_canonical_evidence_gaps(JSONB),fao.v1005_valid_artifact_legacy(JSONB),fao.v1005_valid_execution_legacy(UUID,JSONB,JSONB) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION fao.v1005_valid_artifact(JSONB),fao.v1006_valid_critique_artifact(JSONB),fao.v1005_valid_execution(UUID,JSONB,JSONB),fao.v1006_canonical_json(JSONB),fao.v1006_valid_canonical_text_set(JSONB,BOOLEAN),fao.v1006_valid_entity_id(JSONB,TEXT),fao.v1006_valid_canonical_evidence_gaps(JSONB) TO fao_checkpoint_owner"
    )
    op.execute("RESET ROLE; SET ROLE fao_checkpoint_owner")
    op.execute(
        """CREATE TABLE agent_checkpoint.critique_revision(
          episode_id UUID NOT NULL REFERENCES fao.decision_episode(episode_id),
          hypothesis_sha256 TEXT NOT NULL CHECK(hypothesis_sha256~'^[0-9a-f]{64}$'),
          policy_id UUID NOT NULL, policy_version INT NOT NULL CHECK(policy_version>0), policy_schema TEXT NOT NULL CHECK(policy_schema~'^[0-9]+\\.[0-9]+$'), policy_max INT NOT NULL CHECK(policy_max BETWEEN 1 AND 20),
          evaluation_sha256 TEXT NOT NULL CHECK(evaluation_sha256~'^[0-9a-f]{64}$'),
          iteration INT NOT NULL CHECK(iteration>0), created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          PRIMARY KEY(episode_id,policy_id,policy_version,policy_schema,iteration),
          UNIQUE(episode_id,policy_id,policy_version,policy_schema,evaluation_sha256)
        )"""
    )
    op.execute(
        """CREATE FUNCTION agent_checkpoint.reserve_critique_revision(
          p_episode UUID,p_hypothesis TEXT,p_policy UUID,p_policy_version INT,p_policy_schema TEXT,p_max INT,p_evaluation TEXT
        ) RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,agent_checkpoint,pg_temp AS $$
        DECLARE prior INT; allocated INT;
        BEGIN
          IF p_episode IS NULL OR p_hypothesis !~ '^[0-9a-f]{64}$' OR p_evaluation !~ '^[0-9a-f]{64}$'
             OR p_policy<>'019034dd-0000-7000-8000-000000000009'::uuid OR p_policy_version<>1 OR p_policy_schema<>'1.4' OR p_max<>1 THEN RAISE EXCEPTION 'invalid pinned V1-009 critique policy'; END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended(p_episode::text||p_policy::text||p_policy_version::text||p_policy_schema,0));
          SELECT iteration INTO prior FROM agent_checkpoint.critique_revision WHERE episode_id=p_episode AND policy_id=p_policy AND policy_version=p_policy_version AND policy_schema=p_policy_schema AND evaluation_sha256=p_evaluation;
          IF FOUND THEN
            IF (SELECT hypothesis_sha256 FROM agent_checkpoint.critique_revision WHERE episode_id=p_episode AND policy_id=p_policy AND policy_version=p_policy_version AND policy_schema=p_policy_schema AND evaluation_sha256=p_evaluation) IS DISTINCT FROM p_hypothesis THEN
              RAISE EXCEPTION 'critique evaluation retry has a different hypothesis';
            END IF;
            RETURN prior;
          END IF;
          SELECT COALESCE(max(iteration),0) INTO prior FROM agent_checkpoint.critique_revision WHERE episode_id=p_episode AND policy_id=p_policy AND policy_version=p_policy_version AND policy_schema=p_policy_schema;
          IF prior>=p_max THEN RAISE EXCEPTION 'critique iteration limit is exhausted'; END IF;
          allocated:=prior+1;
          INSERT INTO agent_checkpoint.critique_revision(episode_id,hypothesis_sha256,policy_id,policy_version,policy_schema,policy_max,evaluation_sha256,iteration) VALUES(p_episode,p_hypothesis,p_policy,p_policy_version,p_policy_schema,p_max,p_evaluation,allocated);
          RETURN allocated;
        END $$"""
    )
    op.execute(
        "REVOKE ALL ON TABLE agent_checkpoint.critique_revision FROM PUBLIC; REVOKE ALL ON FUNCTION agent_checkpoint.reserve_critique_revision(UUID,TEXT,UUID,INT,TEXT,INT,TEXT) FROM PUBLIC; GRANT EXECUTE ON FUNCTION agent_checkpoint.reserve_critique_revision(UUID,TEXT,UUID,INT,TEXT,INT,TEXT) TO fao_workflow_worker"
    )
    # Keep the complete canonical Critique beside the generic task result.  The
    # generic result schema intentionally remains frozen for Catalog 1.3 replay;
    # Critic completion is a separate, typed command rather than an optional
    # worker-controlled JSON field.
    op.execute(
        """CREATE TABLE agent_checkpoint.critique_completion(
          task_id UUID PRIMARY KEY REFERENCES agent_checkpoint.workflow_task_checkpoint(task_id),
          artifact_payload JSONB NOT NULL, critique_payload JSONB NOT NULL,
          critique_canonical TEXT NOT NULL, critique_sha256 TEXT NOT NULL CHECK(critique_sha256~'^[0-9a-f]{64}$'),
          critique_status TEXT NOT NULL CHECK(critique_status IN ('PASS','REVISE','REJECT','DEFER')),
          created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        )"""
    )
    op.execute(
        "ALTER FUNCTION agent_checkpoint.complete_workflow_task(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT) RENAME TO complete_workflow_task_legacy"
    )
    # The legacy implementation is an internal subroutine for the two fenced
    # commands below.  Renaming must not preserve the worker's old grant.
    op.execute(
        "REVOKE ALL ON FUNCTION agent_checkpoint.complete_workflow_task_legacy(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT) FROM PUBLIC,fao_workflow_worker,fao_business_owner"
    )
    op.execute(
        """CREATE FUNCTION agent_checkpoint.complete_workflow_task(p_task UUID,p_version BIGINT,p_fencing BIGINT,p_result JSONB,p_result_text TEXT,p_result_hash TEXT) RETURNS BOOLEAN
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$
        BEGIN
          IF EXISTS(SELECT 1 FROM agent_checkpoint.workflow_task_checkpoint WHERE task_id=p_task AND task_payload->>'role_id'='pre_trade_critic') THEN RETURN FALSE; END IF;
          RETURN agent_checkpoint.complete_workflow_task_legacy(p_task,p_version,p_fencing,p_result,p_result_text,p_result_hash);
        END $$"""
    )
    op.execute(
        """CREATE FUNCTION agent_checkpoint.complete_critic_workflow_task(
          p_task UUID,p_version BIGINT,p_fencing BIGINT,p_artifact JSONB,p_critique JSONB,p_critique_text TEXT,p_critique_hash TEXT
        ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$
        DECLARE t agent_checkpoint.workflow_task_checkpoint%ROWTYPE; e fao.decision_episode%ROWTYPE; upstream JSONB; identity JSONB; finding JSONB; diagnostic JSONB; category TEXT;
          expected_status TEXT; mapped_status TEXT; base_result JSONB; base_text TEXT; base_hash TEXT; unresolved BOOLEAN:=FALSE; high_unresolved BOOLEAN:=FALSE; conclusive BOOLEAN:=FALSE; expected_resolution TEXT;
        BEGIN
          SELECT * INTO t FROM agent_checkpoint.workflow_task_checkpoint WHERE task_id=p_task FOR UPDATE;
          IF NOT FOUND OR t.task_payload->>'role_id'<>'pre_trade_critic' OR NOT fao.v1005_valid_canonical(p_critique,p_critique_text,p_critique_hash) OR NOT fao.v1006_valid_critique_artifact(p_artifact) OR p_artifact->>'hash'<>'sha256:'||p_critique_hash THEN RETURN FALSE; END IF;
          IF jsonb_typeof(p_critique)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p_critique))<>12 OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_critique) k WHERE k NOT IN ('policy','hypothesis','evidence_synthesis','experiment_request','evaluated_at','expires_at','iteration','source_snapshots','diagnostics','findings','status','required_validations'))
             OR p_critique->'policy'<>jsonb_build_object('policy_id','019034dd-0000-7000-8000-000000000009','version',1,'schema_version','1.4','max_iterations',1)
             OR jsonb_typeof(p_critique->'iteration')<>'number' OR (p_critique->>'iteration')::numeric<>1
             OR p_critique->>'status'<>'DEFER' OR p_critique->'diagnostics'<>'[]'::jsonb
             OR p_critique->'required_validations'<>jsonb_build_array('DIAGNOSTIC_REQUIRED:CONCENTRATION','DIAGNOSTIC_REQUIRED:CONCLUSION_STRENGTH','DIAGNOSTIC_REQUIRED:COST_COVERAGE','DIAGNOSTIC_REQUIRED:COUNTER_EVIDENCE','DIAGNOSTIC_REQUIRED:DATA_LEAKAGE','DIAGNOSTIC_REQUIRED:HISTORICAL_FAILURE','DIAGNOSTIC_REQUIRED:PARAMETER_STABILITY','DIAGNOSTIC_REQUIRED:SAMPLE_APPLICABILITY')
             OR jsonb_typeof(p_critique->'findings')<>'array' OR jsonb_array_length(p_critique->'findings')<>8
             OR jsonb_typeof(p_critique->'source_snapshots')<>'object'
          THEN RETURN FALSE; END IF;
          IF p_artifact->>'schema'<>'1.4' OR p_artifact->>'created_at' IS DISTINCT FROM p_critique->>'evaluated_at' OR p_artifact->>'as_of' IS DISTINCT FROM p_critique->'hypothesis'->>'as_of'
             OR jsonb_typeof(p_critique->'evaluated_at')<>'string' OR jsonb_typeof(p_critique->'expires_at')<>'string'
             OR (p_critique->>'evaluated_at')::timestamptz>clock_timestamp()
             OR (p_critique->>'expires_at')::timestamptz<=clock_timestamp()
             OR (p_critique->>'evaluated_at')::timestamptz>(t.task_payload->>'deadline_at')::timestamptz
             OR (p_critique->>'expires_at')::timestamptz<=(p_critique->>'evaluated_at')::timestamptz
             OR (p_critique->>'expires_at')::timestamptz>(t.task_payload->>'deadline_at')::timestamptz
          THEN RETURN FALSE; END IF;
          SELECT jsonb_agg(a.value ORDER BY a.ordinality) INTO upstream FROM jsonb_array_elements_text(t.task_payload->'depends_on') d(value) JOIN agent_checkpoint.workflow_task_checkpoint u ON u.episode_id=t.episode_id AND u.step_key=d.value CROSS JOIN LATERAL jsonb_array_elements(u.result_payload->'artifacts') WITH ORDINALITY a(value,ordinality);
          IF upstream IS NULL OR jsonb_array_length(upstream)<>3 THEN RETURN FALSE; END IF;
          IF (SELECT count(*) FROM jsonb_object_keys(p_critique->'source_snapshots'))<>3
             OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_critique->'source_snapshots') k WHERE k NOT IN ('hypothesis','evidence_synthesis','experiment_request'))
             OR (SELECT count(*) FROM jsonb_object_keys(p_critique->'source_snapshots'->'hypothesis'))<>11
             OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_critique->'source_snapshots'->'hypothesis') k WHERE k NOT IN ('spec','market_state_assessment','as_of','valid_until','lifecycle','statement','applicable_markets','observable_outcome','falsification_criterion','required_data','proposal_source'))
             OR (SELECT count(*) FROM jsonb_object_keys(p_critique->'source_snapshots'->'evidence_synthesis'))<>8
             OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_critique->'source_snapshots'->'evidence_synthesis') k WHERE k NOT IN ('hypothesis_content_sha256','as_of','valid_until','knowns','unknowns','conflicts','next_steps','evidence_gaps'))
             OR (SELECT count(*) FROM jsonb_object_keys(p_critique->'source_snapshots'->'experiment_request'))<>12
             OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_critique->'source_snapshots'->'experiment_request') k WHERE k NOT IN ('spec','hypothesis_content_sha256','as_of','valid_until','data_requirements','control','evaluation_window','method','metrics','expected_diagnostics','stop_condition','potential_biases'))
          THEN RETURN FALSE; END IF;
          FOREACH category IN ARRAY ARRAY['hypothesis','evidence_synthesis','experiment_request'] LOOP
            identity:=p_critique->category;
            IF jsonb_typeof(identity)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(identity))<>6 OR EXISTS(SELECT 1 FROM jsonb_object_keys(identity) k WHERE k NOT IN ('artifact_id','artifact_kind','schema_version','content_sha256','as_of','valid_until'))
               OR jsonb_typeof(identity->'artifact_id')<>'string' OR jsonb_typeof(identity->'artifact_kind')<>'string' OR jsonb_typeof(identity->'schema_version')<>'string' OR jsonb_typeof(identity->'content_sha256')<>'string' OR jsonb_typeof(identity->'as_of')<>'string' OR jsonb_typeof(identity->'valid_until')<>'string'
               OR identity->>'artifact_kind' IS DISTINCT FROM category OR identity->>'artifact_id' !~ ('^'||category||'_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') OR substring(identity->>'artifact_id' from char_length(category)+16 for 1)<>'7' OR substring(identity->>'artifact_id' from char_length(category)+21 for 1)!~'^[89ab]$' OR identity->>'schema_version'<>'1.4' OR identity->>'content_sha256' !~ '^[0-9a-f]{64}$' OR (identity->>'valid_until')::timestamptz <= (identity->>'as_of')::timestamptz
               OR (p_critique->>'evaluated_at')::timestamptz<(identity->>'as_of')::timestamptz OR (p_critique->>'expires_at')::timestamptz>(identity->>'valid_until')::timestamptz
               OR jsonb_typeof(p_critique->'source_snapshots'->category)<>'object' OR p_critique->'source_snapshots'->category->>'as_of' IS DISTINCT FROM identity->>'as_of' OR p_critique->'source_snapshots'->category->>'valid_until' IS DISTINCT FROM identity->>'valid_until' OR encode(public.digest(convert_to(fao.v1006_canonical_json(p_critique->'source_snapshots'->category),'UTF8'),'sha256'),'hex') IS DISTINCT FROM identity->>'content_sha256' OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(upstream) a WHERE a.value->>'id' IS NOT DISTINCT FROM substring(identity->>'artifact_id' from char_length(category)+2) AND a.value->>'namespace' IS NOT DISTINCT FROM category AND a.value->>'kind' IS NOT DISTINCT FROM identity->>'artifact_kind' AND a.value->>'schema' IS NOT DISTINCT FROM identity->>'schema_version' AND a.value->>'hash' IS NOT DISTINCT FROM 'sha256:'||(identity->>'content_sha256') AND a.value->>'as_of' IS NOT DISTINCT FROM identity->>'as_of') THEN RETURN FALSE; END IF;
          END LOOP;
          IF jsonb_typeof(p_critique->'source_snapshots'->'hypothesis'->'spec')<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p_critique->'source_snapshots'->'hypothesis'->'spec'))<>3 OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_critique->'source_snapshots'->'hypothesis'->'spec') k WHERE k NOT IN ('spec_id','version','schema_version'))
             OR NOT fao.v1006_valid_entity_id(p_critique->'source_snapshots'->'hypothesis'->'spec'->'spec_id','hypothesis_spec') OR jsonb_typeof(p_critique->'source_snapshots'->'hypothesis'->'spec'->'version')<>'number' OR (p_critique->'source_snapshots'->'hypothesis'->'spec'->>'version')::numeric<1 OR (p_critique->'source_snapshots'->'hypothesis'->'spec'->>'version')::numeric<>trunc((p_critique->'source_snapshots'->'hypothesis'->'spec'->>'version')::numeric) OR jsonb_typeof(p_critique->'source_snapshots'->'hypothesis'->'spec'->'schema_version')<>'string' OR p_critique->'source_snapshots'->'hypothesis'->'spec'->>'schema_version'<>'1.4'
             OR jsonb_typeof(p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment')<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment'))<>5 OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment') k WHERE k NOT IN ('assessment_id','content_sha256','schema_version','as_of','valid_until'))
             OR NOT fao.v1006_valid_entity_id(p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment'->'assessment_id','market_state_assessment') OR jsonb_typeof(p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment'->'content_sha256')<>'string' OR p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment'->>'content_sha256' !~ '^[0-9a-f]{64}$' OR jsonb_typeof(p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment'->'schema_version')<>'string' OR p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment'->>'schema_version'<>'1.4' OR jsonb_typeof(p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment'->'as_of')<>'string' OR jsonb_typeof(p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment'->'valid_until')<>'string' OR p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment'->>'as_of' IS DISTINCT FROM p_critique->'hypothesis'->>'as_of' OR (p_critique->'source_snapshots'->'hypothesis'->'market_state_assessment'->>'valid_until')::timestamptz<(p_critique->'hypothesis'->>'valid_until')::timestamptz
             OR p_critique->'source_snapshots'->'hypothesis'->>'lifecycle'<>'DRAFT' OR p_critique->'source_snapshots'->'hypothesis'->>'proposal_source'<>'MARKET_STATE_ASSESSMENT'
             OR NOT fao.v1006_valid_canonical_text_set(p_critique->'source_snapshots'->'hypothesis'->'applicable_markets',TRUE)
             OR NOT fao.v1006_valid_canonical_text_set(p_critique->'source_snapshots'->'hypothesis'->'required_data',TRUE)
             OR EXISTS(SELECT 1 FROM jsonb_each(p_critique->'source_snapshots'->'hypothesis') x WHERE x.key IN ('statement','observable_outcome','falsification_criterion') AND (jsonb_typeof(x.value)<>'string' OR x.value#>>'{}'='' OR x.value#>>'{}'<>btrim(x.value#>>'{}')))
          THEN RETURN FALSE; END IF;
          IF jsonb_typeof(p_critique->'source_snapshots'->'evidence_synthesis'->'hypothesis_content_sha256')<>'string' OR jsonb_typeof(p_critique->'source_snapshots'->'evidence_synthesis'->'as_of')<>'string' OR jsonb_typeof(p_critique->'source_snapshots'->'evidence_synthesis'->'valid_until')<>'string' OR p_critique->'source_snapshots'->'evidence_synthesis'->>'as_of' IS DISTINCT FROM p_critique->'hypothesis'->>'as_of' OR p_critique->'source_snapshots'->'evidence_synthesis'->>'valid_until' IS DISTINCT FROM p_critique->'hypothesis'->>'valid_until' OR NOT fao.v1006_valid_canonical_text_set(p_critique->'source_snapshots'->'evidence_synthesis'->'knowns',FALSE) OR NOT fao.v1006_valid_canonical_text_set(p_critique->'source_snapshots'->'evidence_synthesis'->'unknowns',FALSE) OR NOT fao.v1006_valid_canonical_text_set(p_critique->'source_snapshots'->'evidence_synthesis'->'conflicts',FALSE) OR NOT fao.v1006_valid_canonical_text_set(p_critique->'source_snapshots'->'evidence_synthesis'->'next_steps',TRUE) OR NOT fao.v1006_valid_canonical_evidence_gaps(p_critique->'source_snapshots'->'evidence_synthesis'->'evidence_gaps') THEN RETURN FALSE; END IF;
          IF jsonb_typeof(p_critique->'source_snapshots'->'experiment_request'->'spec')<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p_critique->'source_snapshots'->'experiment_request'->'spec'))<>3 OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_critique->'source_snapshots'->'experiment_request'->'spec') k WHERE k NOT IN ('spec_id','version','schema_version')) OR NOT fao.v1006_valid_entity_id(p_critique->'source_snapshots'->'experiment_request'->'spec'->'spec_id','experiment_request_spec') OR jsonb_typeof(p_critique->'source_snapshots'->'experiment_request'->'spec'->'version')<>'number' OR (p_critique->'source_snapshots'->'experiment_request'->'spec'->>'version')::numeric<1 OR (p_critique->'source_snapshots'->'experiment_request'->'spec'->>'version')::numeric<>trunc((p_critique->'source_snapshots'->'experiment_request'->'spec'->>'version')::numeric) OR jsonb_typeof(p_critique->'source_snapshots'->'experiment_request'->'spec'->'schema_version')<>'string' OR p_critique->'source_snapshots'->'experiment_request'->'spec'->>'schema_version'<>'1.4' OR jsonb_typeof(p_critique->'source_snapshots'->'experiment_request'->'hypothesis_content_sha256')<>'string' OR jsonb_typeof(p_critique->'source_snapshots'->'experiment_request'->'as_of')<>'string' OR jsonb_typeof(p_critique->'source_snapshots'->'experiment_request'->'valid_until')<>'string' OR p_critique->'source_snapshots'->'experiment_request'->>'as_of' IS DISTINCT FROM p_critique->'hypothesis'->>'as_of' OR p_critique->'source_snapshots'->'experiment_request'->>'valid_until' IS DISTINCT FROM p_critique->'hypothesis'->>'valid_until' OR p_critique->'source_snapshots'->'experiment_request'->'data_requirements' IS DISTINCT FROM p_critique->'source_snapshots'->'hypothesis'->'required_data' OR EXISTS(SELECT 1 FROM jsonb_each(p_critique->'source_snapshots'->'experiment_request') x WHERE x.key IN ('control','evaluation_window','method','stop_condition') AND (jsonb_typeof(x.value)<>'string' OR x.value#>>'{}'='' OR x.value#>>'{}'<>btrim(x.value#>>'{}'))) OR NOT fao.v1006_valid_canonical_text_set(p_critique->'source_snapshots'->'experiment_request'->'data_requirements',TRUE) OR NOT fao.v1006_valid_canonical_text_set(p_critique->'source_snapshots'->'experiment_request'->'metrics',TRUE) OR NOT fao.v1006_valid_canonical_text_set(p_critique->'source_snapshots'->'experiment_request'->'expected_diagnostics',TRUE) OR NOT fao.v1006_valid_canonical_text_set(p_critique->'source_snapshots'->'experiment_request'->'potential_biases',FALSE) THEN RETURN FALSE; END IF;
          IF (p_critique->'evidence_synthesis'->>'content_sha256') IS NULL OR (p_critique->'experiment_request'->>'content_sha256') IS NULL
             OR p_critique->'source_snapshots'->'evidence_synthesis'->>'hypothesis_content_sha256'<>p_critique->'hypothesis'->>'content_sha256'
             OR p_critique->'source_snapshots'->'experiment_request'->>'hypothesis_content_sha256'<>p_critique->'hypothesis'->>'content_sha256'
             OR NOT EXISTS(SELECT 1 FROM agent_checkpoint.critique_revision r WHERE r.episode_id=t.episode_id AND r.hypothesis_sha256=p_critique->'hypothesis'->>'content_sha256' AND r.policy_id=(p_critique->'policy'->>'policy_id')::uuid AND r.policy_version=(p_critique->'policy'->>'version')::int AND r.policy_schema=p_critique->'policy'->>'schema_version' AND r.policy_max=(p_critique->'policy'->>'max_iterations')::int AND r.evaluation_sha256=p_critique_hash AND r.iteration=1)
          THEN RETURN FALSE; END IF;
          IF EXISTS(
            SELECT 1 FROM jsonb_array_elements(p_critique->'findings') WITH ORDINALITY f(value,ordinality)
            WHERE jsonb_typeof(f.value)<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(f.value))<>6
               OR EXISTS(SELECT 1 FROM jsonb_object_keys(f.value) k WHERE k NOT IN ('category','state','severity','resolution','summary','evidence_hashes'))
               OR jsonb_typeof(f.value->'category')<>'string'
               OR jsonb_typeof(f.value->'state')<>'string'
               OR jsonb_typeof(f.value->'severity')<>'string'
               OR jsonb_typeof(f.value->'resolution')<>'string'
               OR jsonb_typeof(f.value->'summary')<>'string'
               OR jsonb_typeof(f.value->'evidence_hashes')<>'array'
               OR f.value->>'category' IS DISTINCT FROM (ARRAY['CONCENTRATION','CONCLUSION_STRENGTH','COST_COVERAGE','COUNTER_EVIDENCE','DATA_LEAKAGE','HISTORICAL_FAILURE','PARAMETER_STABILITY','SAMPLE_APPLICABILITY'])[f.ordinality]
          ) THEN RETURN FALSE; END IF;
          FOREACH category IN ARRAY ARRAY['COUNTER_EVIDENCE','DATA_LEAKAGE','COST_COVERAGE','SAMPLE_APPLICABILITY','CONCENTRATION','PARAMETER_STABILITY','HISTORICAL_FAILURE','CONCLUSION_STRENGTH'] LOOP
            SELECT value INTO finding FROM jsonb_array_elements(p_critique->'findings') WHERE value->>'category'=category;
            IF finding IS NULL OR (SELECT count(*) FROM jsonb_array_elements(p_critique->'findings') WHERE value->>'category'=category)<>1 THEN RETURN FALSE; END IF;
            IF finding->>'state'<>'GAP' OR finding->>'severity'<>(CASE WHEN category='DATA_LEAKAGE' THEN 'HIGH' ELSE 'MEDIUM' END) OR finding->>'resolution'<>'UNRESOLVED' OR finding->>'summary'<>('No typed diagnostic evidence was supplied for '||category||'.') OR finding->'evidence_hashes'<>'[]'::jsonb THEN RETURN FALSE; END IF;
          END LOOP;
          expected_status:='DEFER';
          mapped_status:='DEFERRED';
          base_result:=jsonb_build_object('task_id',p_task::text,'status',mapped_status,'artifacts',CASE WHEN mapped_status='COMPLETED' THEN jsonb_build_array(p_artifact) ELSE '[]'::jsonb END,'unknowns',CASE WHEN mapped_status='COMPLETED' THEN '[]'::jsonb ELSE jsonb_build_array('critique:'||expected_status) END,'warnings','[]'::jsonb);
          base_text:=base_result::text; base_hash:=encode(public.digest(convert_to(base_text,'UTF8'),'sha256'),'hex');
          IF NOT agent_checkpoint.complete_workflow_task_legacy(p_task,p_version,p_fencing,base_result,base_text,base_hash) THEN RETURN FALSE; END IF;
          INSERT INTO agent_checkpoint.critique_completion(task_id,artifact_payload,critique_payload,critique_canonical,critique_sha256,critique_status) VALUES(p_task,p_artifact,p_critique,p_critique_text,p_critique_hash,expected_status) ON CONFLICT(task_id) DO UPDATE SET task_id=EXCLUDED.task_id WHERE agent_checkpoint.critique_completion.artifact_payload=EXCLUDED.artifact_payload AND agent_checkpoint.critique_completion.critique_payload=EXCLUDED.critique_payload AND agent_checkpoint.critique_completion.critique_canonical=EXCLUDED.critique_canonical AND agent_checkpoint.critique_completion.critique_sha256=EXCLUDED.critique_sha256 AND agent_checkpoint.critique_completion.critique_status=EXCLUDED.critique_status;
          IF NOT FOUND THEN RETURN FALSE; END IF;
          RETURN TRUE;
        EXCEPTION WHEN others THEN RETURN FALSE; END $$"""
    )
    op.execute(
        "REVOKE ALL ON TABLE agent_checkpoint.critique_completion FROM PUBLIC; REVOKE ALL ON FUNCTION agent_checkpoint.complete_workflow_task(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT),agent_checkpoint.complete_critic_workflow_task(UUID,BIGINT,BIGINT,JSONB,JSONB,TEXT,TEXT),agent_checkpoint.complete_workflow_task_legacy(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT) FROM PUBLIC,fao_business_owner; REVOKE ALL ON FUNCTION agent_checkpoint.complete_workflow_task_legacy(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT) FROM fao_workflow_worker; GRANT EXECUTE ON FUNCTION agent_checkpoint.complete_workflow_task(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT),agent_checkpoint.complete_critic_workflow_task(UUID,BIGINT,BIGINT,JSONB,JSONB,TEXT,TEXT) TO fao_workflow_worker"
    )
    op.execute(
        """CREATE FUNCTION agent_checkpoint.hydrate_critic_completion(p_task UUID,p_episode UUID) RETURNS JSONB
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,fao,agent_checkpoint,pg_temp AS $$
        DECLARE t agent_checkpoint.workflow_task_checkpoint%ROWTYPE; c agent_checkpoint.critique_completion%ROWTYPE;
        BEGIN
          SELECT * INTO t FROM agent_checkpoint.workflow_task_checkpoint WHERE task_id=p_task AND episode_id=p_episode;
          IF NOT FOUND OR t.task_payload->>'role_id'<>'pre_trade_critic' THEN RETURN NULL; END IF;
          SELECT * INTO c FROM agent_checkpoint.critique_completion WHERE task_id=p_task;
          IF NOT FOUND THEN RETURN NULL; END IF;
          IF c.critique_status<>'DEFER' OR c.critique_payload->>'status' IS DISTINCT FROM c.critique_status
             OR NOT fao.v1005_valid_canonical(c.critique_payload,c.critique_canonical,c.critique_sha256)
             OR NOT fao.v1006_valid_critique_artifact(c.artifact_payload)
             OR c.artifact_payload->>'hash' IS DISTINCT FROM 'sha256:'||c.critique_sha256
             OR c.artifact_payload->>'schema' IS DISTINCT FROM c.critique_payload->'policy'->>'schema_version'
             OR c.artifact_payload->>'created_at' IS DISTINCT FROM c.critique_payload->>'evaluated_at'
             OR c.artifact_payload->>'as_of' IS DISTINCT FROM c.critique_payload->'hypothesis'->>'as_of'
          THEN RAISE EXCEPTION 'critic completion integrity drift'; END IF;
          RETURN jsonb_build_object('artifact',c.artifact_payload,'critique',c.critique_payload,'canonical',c.critique_canonical,'hash',c.critique_sha256,'status',c.critique_status);
        END $$"""
    )
    op.execute(
        "REVOKE ALL ON FUNCTION agent_checkpoint.hydrate_critic_completion(UUID,UUID) FROM PUBLIC,fao_business_owner; GRANT EXECUTE ON FUNCTION agent_checkpoint.hydrate_critic_completion(UUID,UUID) TO fao_workflow_worker"
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    # A 0005 runtime cannot interpret Critic tasks.  Never make that fact a
    # silent data-loss operation: a populated downgrade must be explicitly
    # refused until the durable Critique facts have been archived by a future
    # compatible release.
    op.execute("SET ROLE fao_checkpoint_owner")
    op.execute(
        """DO $$ BEGIN IF EXISTS(
          SELECT 1 FROM agent_checkpoint.workflow_execution x WHERE EXISTS(
          SELECT 1 FROM jsonb_array_elements(x.plan_payload->'steps') s
          WHERE s.value->>'role_id'='pre_trade_critic')
        ) OR EXISTS(SELECT 1 FROM agent_checkpoint.critique_revision)
        THEN RAISE EXCEPTION 'cannot downgrade V1-009 while durable Critique workflow facts exist'; END IF; END $$"""
    )
    op.execute("RESET ROLE; SET ROLE fao_business_owner")
    op.execute("DROP FUNCTION fao.v1005_valid_execution(UUID,JSONB,JSONB)")
    op.execute("DROP FUNCTION fao.v1006_valid_critic_execution(UUID,JSONB,JSONB)")
    op.execute("ALTER FUNCTION fao.v1005_valid_execution_legacy(UUID,JSONB,JSONB) RENAME TO v1005_valid_execution")
    op.execute("DROP FUNCTION fao.v1005_valid_artifact(JSONB)")
    op.execute("DROP FUNCTION fao.v1006_valid_critique_artifact(JSONB)")
    op.execute("ALTER FUNCTION fao.v1005_valid_artifact_legacy(JSONB) RENAME TO v1005_valid_artifact")
    op.execute(
        "GRANT EXECUTE ON FUNCTION fao.v1005_valid_artifact(JSONB),fao.v1005_valid_execution(UUID,JSONB,JSONB) TO fao_checkpoint_owner"
    )
    op.execute("RESET ROLE; SET ROLE fao_checkpoint_owner")
    op.execute("DROP FUNCTION agent_checkpoint.hydrate_critic_completion(UUID,UUID)")
    op.execute("DROP FUNCTION agent_checkpoint.complete_critic_workflow_task(UUID,BIGINT,BIGINT,JSONB,JSONB,TEXT,TEXT)")
    op.execute("RESET ROLE; SET ROLE fao_business_owner")
    op.execute("DROP FUNCTION fao.v1006_valid_canonical_evidence_gaps(JSONB)")
    op.execute("DROP FUNCTION fao.v1006_valid_entity_id(JSONB,TEXT)")
    op.execute("DROP FUNCTION fao.v1006_valid_canonical_text_set(JSONB,BOOLEAN)")
    op.execute("DROP FUNCTION fao.v1006_canonical_json(JSONB)")
    op.execute("RESET ROLE; SET ROLE fao_checkpoint_owner")
    op.execute("DROP FUNCTION agent_checkpoint.complete_workflow_task(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT)")
    op.execute(
        "ALTER FUNCTION agent_checkpoint.complete_workflow_task_legacy(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT) RENAME TO complete_workflow_task"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION agent_checkpoint.complete_workflow_task(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT) FROM PUBLIC,fao_business_owner; GRANT EXECUTE ON FUNCTION agent_checkpoint.complete_workflow_task(UUID,BIGINT,BIGINT,JSONB,TEXT,TEXT) TO fao_workflow_worker"
    )
    op.execute("DROP TABLE agent_checkpoint.critique_completion")
    op.execute("DROP FUNCTION agent_checkpoint.reserve_critique_revision(UUID,TEXT,UUID,INT,TEXT,INT,TEXT)")
    op.execute("DROP TABLE agent_checkpoint.critique_revision")
    op.execute("RESET ROLE")
