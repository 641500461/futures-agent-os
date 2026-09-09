"""V3-009 durable Mandate escalation and operational Mode pause.

Revision ID: 0010_v3_009
Revises: 0009_v3_002
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "0010_v3_009"
down_revision: str | Sequence[str] | None = "0009_v3_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE fao_business_owner")
    op.execute(
        "ALTER TABLE fao.simulation_autonomy_mandate "
        "ADD COLUMN escalation_mode TEXT NOT NULL DEFAULT 'SKIP_AND_NOTIFY' "
        "CHECK (escalation_mode IN ('SKIP_AND_NOTIFY','REQUEST_ONE_OFF'))"
    )
    op.execute(
        """CREATE FUNCTION fao.request_agent_plan_approval(
          p_approval UUID,p_plan UUID,p_plan_version BIGINT,p_plan_hash TEXT,p_account UUID,
          p_instrument TEXT,p_strategy TEXT,p_session TEXT,p_action TEXT,p_quantity NUMERIC,
          p_token UUID,p_scope_hash TEXT,p_approval_hash TEXT,p_expires TIMESTAMPTZ,
          p_mandate UUID,p_mandate_version BIGINT,p_binding UUID,p_binding_version BIGINT,
          p_environment_policy TEXT,p_requested_by TEXT,p_now TIMESTAMPTZ
        ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE m RECORD; b RECORD; scope_value JSONB; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          IF p_approval IS NULL OR p_plan IS NULL OR p_plan_version IS NULL OR p_plan_version<=0
             OR p_plan_hash IS NULL OR p_plan_hash !~ '^[0-9a-f]{64}$' OR p_account IS NULL
             OR NOT fao.v014_valid_execution_fields(p_instrument,p_strategy,p_session,p_action,p_quantity)
             OR p_token IS NULL OR p_scope_hash IS NULL OR p_scope_hash !~ '^[0-9a-f]{64}$'
             OR p_approval_hash IS NULL OR p_approval_hash !~ '^[0-9a-f]{64}$'
             OR p_expires IS NULL OR p_now IS NULL OR p_requested_by IS NULL
             OR p_environment_policy IS NULL OR p_environment_policy IS DISTINCT FROM btrim(p_environment_policy)
             OR p_environment_policy='' OR p_environment_policy ~ '[[:space:]]'
             OR p_requested_by IS DISTINCT FROM btrim(p_requested_by)
             OR p_requested_by !~ '^service:[^[:space:]]+$' THEN RETURN FALSE; END IF;
          SELECT * INTO m FROM fao.simulation_autonomy_mandate
            WHERE mandate_id=p_mandate AND version=p_mandate_version FOR SHARE;
          SELECT * INTO b FROM fao.autonomy_mode_binding
            WHERE binding_id=p_binding AND version=p_binding_version FOR SHARE;
          IF m IS NULL OR b IS NULL OR m.status IS DISTINCT FROM 'ACTIVE'
             OR m.expires_at<=authoritative_now OR m.simulation_account_id IS DISTINCT FROM p_account
             OR m.escalation_mode IS DISTINCT FROM 'REQUEST_ONE_OFF'
             OR b.binding_status IS DISTINCT FROM 'ACTIVE' OR b.mode IS DISTINCT FROM 'AUTONOMOUS_SIMULATION'
             OR b.expires_at<=authoritative_now OR b.account_id IS DISTINCT FROM p_account
             OR b.mandate_id IS DISTINCT FROM p_mandate OR b.mandate_version IS DISTINCT FROM p_mandate_version
             OR b.qualified_artifact_ref IS NULL OR p_expires<=authoritative_now
             OR p_expires>m.expires_at OR p_expires>b.expires_at
             OR NOT EXISTS (SELECT 1 FROM fao.autonomy_health_permit h
               WHERE h.account_id=p_account AND h.environment_policy_ref=p_environment_policy
                 AND h.permits IS TRUE AND h.valid_until_at>authoritative_now)
             OR fao.v014_scope_permits(m.scope,p_account,p_instrument,p_strategy,p_session,p_action,p_quantity,FALSE)
             THEN RETURN FALSE; END IF;
          scope_value := jsonb_build_object(
            'account_id',p_account::text,'instruments',jsonb_build_array(p_instrument),
            'strategies',jsonb_build_array(p_strategy),'sessions',jsonb_build_array(p_session),
            'actions',jsonb_build_array(p_action),'quantity_ceiling',p_quantity::text,
            'window_start_at',authoritative_now::text,'window_end_at',p_expires::text);
          IF EXISTS (SELECT 1 FROM fao.plan_approval WHERE approval_id=p_approval) THEN
            RETURN EXISTS (SELECT 1 FROM fao.plan_approval WHERE approval_id=p_approval AND version=1
              AND status='REQUESTED' AND plan_id=p_plan AND plan_version=p_plan_version
              AND plan_sha256=p_plan_hash AND scope_account_id=p_account AND approval_token=p_token
              AND scope_sha256=p_scope_hash AND approval_hash=p_approval_hash
              AND requested_by=p_requested_by AND expires_at=p_expires
              AND approval_scope->'instruments'=jsonb_build_array(p_instrument)
              AND approval_scope->'strategies'=jsonb_build_array(p_strategy)
              AND approval_scope->'sessions'=jsonb_build_array(p_session)
              AND approval_scope->'actions'=jsonb_build_array(p_action)
              AND quantity_ceiling=p_quantity);
          END IF;
          INSERT INTO fao.plan_approval
            (approval_id,version,status,plan_id,plan_version,plan_sha256,approval_scope,
             expires_at,requested_at,requested_by,approval_hash,approval_token,scope_sha256,
             scope_account_id,allowed_actions,quantity_ceiling,window_start_at,window_end_at)
          VALUES (p_approval,1,'REQUESTED',p_plan,p_plan_version,p_plan_hash,scope_value,
             p_expires,authoritative_now,p_requested_by,p_approval_hash,p_token,p_scope_hash,
             p_account,jsonb_build_array(p_action),p_quantity,authoritative_now,p_expires);
          RETURN TRUE;
        EXCEPTION WHEN unique_violation THEN RETURN FALSE;
        END $$"""
    )
    op.execute(
        """CREATE FUNCTION fao.pause_autonomy_mode(
          p_binding UUID,p_binding_version BIGINT,p_account UUID,p_now TIMESTAMPTZ,
          p_actor TEXT,p_reason TEXT,p_evidence TEXT,p_new_binding_hash TEXT
        ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE b RECORD; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          IF p_binding IS NULL OR p_binding_version IS NULL OR p_binding_version<=0 OR p_account IS NULL
             OR p_now IS NULL OR p_actor IS NULL OR p_actor IS DISTINCT FROM btrim(p_actor)
             OR p_actor !~ '^(service|system):[^[:space:]]+$'
             OR p_reason NOT IN ('HEALTH_DEGRADED','POLICY_OR_VERSION_QUARANTINE')
             OR p_evidence IS NULL OR p_evidence IS DISTINCT FROM btrim(p_evidence) OR p_evidence=''
             OR p_new_binding_hash IS NULL OR p_new_binding_hash !~ '^[0-9a-f]{64}$' THEN RETURN FALSE; END IF;
          SELECT * INTO b FROM fao.autonomy_mode_binding
            WHERE binding_id=p_binding AND version=p_binding_version FOR UPDATE;
          IF NOT FOUND OR b.binding_status IS DISTINCT FROM 'ACTIVE'
             OR b.mode IS DISTINCT FROM 'AUTONOMOUS_SIMULATION' OR b.account_id IS DISTINCT FROM p_account
             OR b.expires_at<=authoritative_now OR b.binding_sha256 IS NOT DISTINCT FROM p_new_binding_hash
             THEN RETURN FALSE; END IF;
          UPDATE fao.autonomy_mode_binding SET version=version+1,mode='PAUSED',
            previous_mode='AUTONOMOUS_SIMULATION',state_version=state_version+1,
            binding_sha256=p_new_binding_hash,transition_reason=p_reason,transition_actor=p_actor,
            evidence_ref=p_evidence,recorded_at=authoritative_now
            WHERE binding_id=p_binding AND version=p_binding_version;
          UPDATE fao.autonomy_gate_receipt SET receipt_status='STALE',state_version=state_version+1
            WHERE receipt_status='ISSUED' AND mode_binding_id=p_binding AND mode_binding_version=p_binding_version;
          UPDATE fao.authorization_basis SET basis_status='STALE',state_version=state_version+1
            WHERE basis_status='ACTIVE' AND basis_kind='MANDATE'
              AND source_mandate_id IS NOT DISTINCT FROM b.mandate_id
              AND source_mandate_version IS NOT DISTINCT FROM b.mandate_version
              AND account_id IS NOT DISTINCT FROM b.account_id;
          UPDATE fao.risk_budget_reservation r SET reservation_status='RELEASED',
            reservation_version=reservation_version+1,state_version=state_version+1,released_at=authoritative_now
            WHERE reservation_status='HELD' AND EXISTS (SELECT 1 FROM fao.authorization_basis z
              WHERE z.basis_id=r.basis_id AND z.basis_status='STALE' AND z.basis_kind='MANDATE'
                AND z.source_mandate_id IS NOT DISTINCT FROM b.mandate_id
                AND z.source_mandate_version IS NOT DISTINCT FROM b.mandate_version
                AND z.account_id IS NOT DISTINCT FROM b.account_id);
          RETURN TRUE;
        END $$"""
    )
    op.execute(
        "ALTER FUNCTION fao.request_agent_plan_approval(UUID,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,UUID,TEXT,TEXT,TIMESTAMPTZ,UUID,BIGINT,UUID,BIGINT,TEXT,TEXT,TIMESTAMPTZ) OWNER TO fao_business_owner"
    )
    op.execute(
        "ALTER FUNCTION fao.pause_autonomy_mode(UUID,BIGINT,UUID,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT) OWNER TO fao_business_owner"
    )
    op.execute(
        """CREATE FUNCTION fao.grant_plan_approval(
          p_approval UUID,p_approval_version BIGINT,p_plan UUID,p_plan_version BIGINT,
          p_plan_hash TEXT,p_actor TEXT,p_now TIMESTAMPTZ
        ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE a RECORD; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          IF p_approval IS NULL OR p_approval_version IS NULL OR p_approval_version<=0
             OR p_plan IS NULL OR p_plan_version IS NULL OR p_plan_version<=0
             OR p_plan_hash IS NULL OR p_plan_hash !~ '^[0-9a-f]{64}$'
             OR p_actor IS NULL OR p_actor IS DISTINCT FROM btrim(p_actor)
             OR p_actor !~ '^user:[^[:space:]]+$' OR p_now IS NULL THEN RETURN FALSE; END IF;
          SELECT * INTO a FROM fao.plan_approval
            WHERE approval_id=p_approval AND version=p_approval_version FOR UPDATE;
          IF NOT FOUND OR a.status IS DISTINCT FROM 'REQUESTED'
             OR a.plan_id IS DISTINCT FROM p_plan OR a.plan_version IS DISTINCT FROM p_plan_version
             OR a.plan_sha256 IS DISTINCT FROM p_plan_hash OR a.expires_at<=authoritative_now THEN RETURN FALSE; END IF;
          UPDATE fao.plan_approval SET version=version+1,status='GRANTED',state_version=state_version+1,
            decided_at=authoritative_now,decided_by=p_actor
            WHERE approval_id=p_approval AND version=p_approval_version;
          RETURN FOUND;
        EXCEPTION WHEN unique_violation THEN RETURN FALSE;
        END $$"""
    )
    op.execute(
        "ALTER FUNCTION fao.grant_plan_approval(UUID,BIGINT,UUID,BIGINT,TEXT,TEXT,TIMESTAMPTZ) OWNER TO fao_business_owner"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION fao.request_agent_plan_approval(UUID,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,UUID,TEXT,TEXT,TIMESTAMPTZ,UUID,BIGINT,UUID,BIGINT,TEXT,TEXT,TIMESTAMPTZ) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION fao.pause_autonomy_mode(UUID,BIGINT,UUID,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION fao.grant_plan_approval(UUID,BIGINT,UUID,BIGINT,TEXT,TEXT,TIMESTAMPTZ) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION fao.request_agent_plan_approval(UUID,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,UUID,TEXT,TEXT,TIMESTAMPTZ,UUID,BIGINT,UUID,BIGINT,TEXT,TEXT,TIMESTAMPTZ) TO fao_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION fao.pause_autonomy_mode(UUID,BIGINT,UUID,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT) TO fao_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION fao.grant_plan_approval(UUID,BIGINT,UUID,BIGINT,TEXT,TEXT,TIMESTAMPTZ) TO fao_supervisor"
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE fao_business_owner")
    op.execute("DROP FUNCTION IF EXISTS fao.grant_plan_approval(UUID,BIGINT,UUID,BIGINT,TEXT,TEXT,TIMESTAMPTZ)")
    op.execute("DROP FUNCTION IF EXISTS fao.pause_autonomy_mode(UUID,BIGINT,UUID,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT)")
    op.execute(
        "DROP FUNCTION IF EXISTS fao.request_agent_plan_approval(UUID,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,UUID,TEXT,TEXT,TIMESTAMPTZ,UUID,BIGINT,UUID,BIGINT,TEXT,TEXT,TIMESTAMPTZ)"
    )
    op.execute("ALTER TABLE fao.simulation_autonomy_mandate DROP COLUMN escalation_mode")
    op.execute("RESET ROLE")
