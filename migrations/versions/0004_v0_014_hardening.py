"""Add V0-014 SECURITY DEFINER commands and append-only enforcement."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "0004_v0_014_hardening"
down_revision: str | Sequence[str] | None = "0003_v0_014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute(statements: tuple[str, ...]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _execute(
        (
            # Human supervision is a database authority boundary, not an
            # application-supplied ``user:*`` string.  A deployment grants
            # this NOLOGIN role only to its authenticated supervisor ingress.
            "RESET ROLE",
            "DO $$ BEGIN CREATE ROLE fao_supervisor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
            "SET ROLE fao_business_owner",
            # Old revisions admitted REPLACED despite having no safe command
            # which could create it.  Preserve the terminal time while
            # normalising such legacy rows to the only equivalent terminal
            # state before tightening the enum.
            "UPDATE fao.risk_budget_reservation SET reservation_status='RELEASED', reservation_version=reservation_version+1, state_version=state_version+1, released_at=COALESCE(released_at, clock_timestamp()) WHERE reservation_status='REPLACED'",
            "ALTER TABLE fao.risk_budget_reservation DROP CONSTRAINT IF EXISTS ck_v014_reservation_status, DROP CONSTRAINT IF EXISTS risk_budget_reservation_reservation_status_check",
            "ALTER TABLE fao.risk_budget_reservation ADD CONSTRAINT ck_v014_reservation_status CHECK (reservation_status IN ('HELD','CONSUMED','RELEASED','EXPIRED','RECONCILED'))",
            # Canonical references are authority identifiers, not display text.
            # Bad legacy authorities are deliberately untrusted; dependent held
            # reservations/receipts are closed before ref checks are tightened.
            "UPDATE fao.risk_budget_authority SET constitution_ref='legacy://untrusted-risk-constitution', ceiling=0, state_version=state_version+1, updated_at=clock_timestamp() WHERE constitution_ref IS DISTINCT FROM btrim(constitution_ref) OR constitution_ref ~ '[[:space:]]' OR constitution_ref=''",
            "UPDATE fao.risk_budget_reservation SET risk_constitution_ref='legacy://untrusted-risk-constitution', reservation_status=CASE WHEN reservation_status='HELD' THEN 'RELEASED' ELSE reservation_status END, reservation_version=reservation_version+1, state_version=state_version+1, released_at=CASE WHEN reservation_status='HELD' THEN COALESCE(released_at,clock_timestamp()) ELSE released_at END WHERE risk_constitution_ref IS DISTINCT FROM btrim(risk_constitution_ref) OR risk_constitution_ref ~ '[[:space:]]' OR risk_constitution_ref=''",
            "UPDATE fao.autonomy_gate_receipt x SET risk_constitution_ref='legacy://untrusted-risk-constitution', receipt_status=CASE WHEN x.receipt_status='ISSUED' THEN 'STALE' ELSE x.receipt_status END, state_version=x.state_version+1 WHERE x.risk_constitution_ref IS DISTINCT FROM btrim(x.risk_constitution_ref) OR x.risk_constitution_ref ~ '[[:space:]]' OR x.risk_constitution_ref='' OR EXISTS (SELECT 1 FROM fao.risk_budget_reservation r WHERE r.reservation_id=x.reservation_id AND r.risk_constitution_ref='legacy://untrusted-risk-constitution')",
            "UPDATE fao.simulation_autonomy_mandate SET status='EXPIRED', risk_policy_ref=CASE WHEN risk_policy_ref IS DISTINCT FROM btrim(risk_policy_ref) OR risk_policy_ref ~ '[[:space:]]' OR risk_policy_ref='' THEN 'legacy://untrusted-risk-policy' ELSE risk_policy_ref END, notification_policy_ref=CASE WHEN notification_policy_ref IS DISTINCT FROM btrim(notification_policy_ref) OR notification_policy_ref ~ '[[:space:]]' OR notification_policy_ref='' THEN 'legacy://expired-notification' ELSE notification_policy_ref END, escalation_policy_ref=CASE WHEN escalation_policy_ref IS DISTINCT FROM btrim(escalation_policy_ref) OR escalation_policy_ref ~ '[[:space:]]' OR escalation_policy_ref='' THEN 'legacy://expired-escalation' ELSE escalation_policy_ref END WHERE risk_policy_ref IS DISTINCT FROM btrim(risk_policy_ref) OR risk_policy_ref ~ '[[:space:]]' OR risk_policy_ref='' OR notification_policy_ref IS DISTINCT FROM btrim(notification_policy_ref) OR notification_policy_ref ~ '[[:space:]]' OR notification_policy_ref='' OR escalation_policy_ref IS DISTINCT FROM btrim(escalation_policy_ref) OR escalation_policy_ref ~ '[[:space:]]' OR escalation_policy_ref=''",
            "ALTER TABLE fao.risk_budget_authority DROP CONSTRAINT IF EXISTS risk_budget_authority_constitution_ref_check, ADD CONSTRAINT ck_v014_authority_constitution_ref CHECK (constitution_ref=btrim(constitution_ref) AND constitution_ref !~ '[[:space:]]' AND constitution_ref<>'')",
            "ALTER TABLE fao.risk_budget_reservation DROP CONSTRAINT IF EXISTS risk_budget_reservation_risk_constitution_ref_check, ADD CONSTRAINT ck_v014_reservation_constitution_ref CHECK (risk_constitution_ref=btrim(risk_constitution_ref) AND risk_constitution_ref !~ '[[:space:]]' AND risk_constitution_ref<>'')",
            "ALTER TABLE fao.autonomy_gate_receipt DROP CONSTRAINT IF EXISTS autonomy_gate_receipt_risk_constitution_ref_check, ADD CONSTRAINT ck_v014_receipt_constitution_ref CHECK (risk_constitution_ref=btrim(risk_constitution_ref) AND risk_constitution_ref !~ '[[:space:]]' AND risk_constitution_ref<>'')",
            "ALTER TABLE fao.simulation_autonomy_mandate DROP CONSTRAINT IF EXISTS ck_v014_mandate_risk_ref, DROP CONSTRAINT IF EXISTS ck_v014_mandate_notification_ref, DROP CONSTRAINT IF EXISTS ck_v014_mandate_escalation_ref, ADD CONSTRAINT ck_v014_mandate_risk_ref CHECK (risk_policy_ref=btrim(risk_policy_ref) AND risk_policy_ref !~ '[[:space:]]' AND risk_policy_ref<>''), ADD CONSTRAINT ck_v014_mandate_notification_ref CHECK (notification_policy_ref=btrim(notification_policy_ref) AND notification_policy_ref !~ '[[:space:]]' AND notification_policy_ref<>''), ADD CONSTRAINT ck_v014_mandate_escalation_ref CHECK (escalation_policy_ref=btrim(escalation_policy_ref) AND escalation_policy_ref !~ '[[:space:]]' AND escalation_policy_ref<>'')",
            "UPDATE fao.autonomy_mode_binding SET binding_status=CASE WHEN binding_status='ACTIVE' THEN 'EXPIRED' ELSE binding_status END, expires_at=CASE WHEN binding_status='ACTIVE' THEN recorded_at ELSE expires_at END, qualified_artifact_ref='legacy://untrusted-qualified-artifact', state_version=state_version+1 WHERE qualified_artifact_ref IS NOT NULL AND (qualified_artifact_ref IS DISTINCT FROM btrim(qualified_artifact_ref) OR qualified_artifact_ref ~ '[[:space:]]' OR qualified_artifact_ref='')",
            "UPDATE fao.autonomy_gate_receipt x SET receipt_status=CASE WHEN x.receipt_status='ISSUED' THEN 'STALE' ELSE x.receipt_status END, state_version=x.state_version+1 WHERE EXISTS (SELECT 1 FROM fao.autonomy_mode_binding b WHERE b.binding_id=x.mode_binding_id AND b.version=x.mode_binding_version AND b.qualified_artifact_ref='legacy://untrusted-qualified-artifact')",
            "UPDATE fao.risk_budget_reservation r SET reservation_status='RELEASED', reservation_version=reservation_version+1, state_version=state_version+1, released_at=COALESCE(released_at,clock_timestamp()) WHERE r.reservation_status='HELD' AND EXISTS (SELECT 1 FROM fao.autonomy_gate_receipt x JOIN fao.autonomy_mode_binding b ON b.binding_id=x.mode_binding_id AND b.version=x.mode_binding_version WHERE x.reservation_id=r.reservation_id AND b.qualified_artifact_ref='legacy://untrusted-qualified-artifact')",
            "ALTER TABLE fao.autonomy_mode_binding DROP CONSTRAINT IF EXISTS ck_v014_binding_qualified_artifact_ref, ADD CONSTRAINT ck_v014_binding_qualified_artifact_ref CHECK (qualified_artifact_ref IS NULL OR (qualified_artifact_ref=btrim(qualified_artifact_ref) AND qualified_artifact_ref !~ '[[:space:]]' AND qualified_artifact_ref<>''))",
            # Scope is a canonical, non-expandable range schema.  Do not use
            # JSON `->>` comparisons directly: missing/null keys yield NULL,
            # which can turn an `IF ... THEN reject` predicate into a bypass.
            """CREATE FUNCTION fao.v014_valid_scope(p_scope JSONB,p_account UUID,p_require_window BOOLEAN)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE ceiling NUMERIC; starts_at TIMESTAMPTZ; ends_at TIMESTAMPTZ;
        BEGIN
          IF p_scope IS NULL OR p_account IS NULL OR jsonb_typeof(p_scope) IS DISTINCT FROM 'object'
             OR p_scope ?| ARRAY['instrument','strategy','session']
             OR jsonb_typeof(p_scope->'account_id') IS DISTINCT FROM 'string'
             OR p_scope->>'account_id' IS DISTINCT FROM p_account::text
             OR jsonb_typeof(p_scope->'instruments') IS DISTINCT FROM 'array'
             OR jsonb_typeof(p_scope->'strategies') IS DISTINCT FROM 'array'
             OR jsonb_typeof(p_scope->'sessions') IS DISTINCT FROM 'array'
             OR jsonb_typeof(p_scope->'actions') IS DISTINCT FROM 'array'
             OR jsonb_typeof(p_scope->'quantity_ceiling') IS DISTINCT FROM 'string'
             OR jsonb_array_length(p_scope->'instruments') = 0
             OR jsonb_array_length(p_scope->'strategies') = 0
             OR jsonb_array_length(p_scope->'sessions') = 0
             OR jsonb_array_length(p_scope->'actions') = 0 THEN RETURN FALSE; END IF;
          IF (p_require_window AND EXISTS (SELECT 1 FROM jsonb_object_keys(p_scope) AS x(key) WHERE x.key NOT IN ('account_id','instruments','strategies','sessions','actions','quantity_ceiling','window_start_at','window_end_at')))
             OR (NOT p_require_window AND EXISTS (SELECT 1 FROM jsonb_object_keys(p_scope) AS x(key) WHERE x.key NOT IN ('account_id','instruments','strategies','sessions','actions','quantity_ceiling'))) THEN RETURN FALSE; END IF;
          IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_scope->'instruments') AS x(value) WHERE jsonb_typeof(x.value) IS DISTINCT FROM 'string' OR btrim(x.value #>> '{}') = '' OR x.value #>> '{}' ~ '[[:space:]]')
             OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_scope->'strategies') AS x(value) WHERE jsonb_typeof(x.value) IS DISTINCT FROM 'string' OR btrim(x.value #>> '{}') = '' OR x.value #>> '{}' ~ '[[:space:]]')
             OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_scope->'sessions') AS x(value) WHERE jsonb_typeof(x.value) IS DISTINCT FROM 'string' OR btrim(x.value #>> '{}') = '' OR x.value #>> '{}' ~ '[[:space:]]')
             OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_scope->'actions') AS x(value) WHERE jsonb_typeof(x.value) IS DISTINCT FROM 'string' OR x.value #>> '{}' NOT IN ('OPEN','REDUCE','CLOSE')) THEN RETURN FALSE; END IF;
          IF (SELECT count(*) FROM jsonb_array_elements_text(p_scope->'instruments')) IS DISTINCT FROM (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p_scope->'instruments') AS x(value))
             OR (SELECT count(*) FROM jsonb_array_elements_text(p_scope->'strategies')) IS DISTINCT FROM (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p_scope->'strategies') AS x(value))
             OR (SELECT count(*) FROM jsonb_array_elements_text(p_scope->'sessions')) IS DISTINCT FROM (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p_scope->'sessions') AS x(value))
             OR (SELECT count(*) FROM jsonb_array_elements_text(p_scope->'actions')) IS DISTINCT FROM (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p_scope->'actions') AS x(value)) THEN RETURN FALSE; END IF;
          IF (SELECT array_agg(value) FROM jsonb_array_elements_text(p_scope->'instruments') AS x(value)) IS DISTINCT FROM (SELECT array_agg(value ORDER BY value) FROM jsonb_array_elements_text(p_scope->'instruments') AS x(value))
             OR (SELECT array_agg(value) FROM jsonb_array_elements_text(p_scope->'strategies') AS x(value)) IS DISTINCT FROM (SELECT array_agg(value ORDER BY value) FROM jsonb_array_elements_text(p_scope->'strategies') AS x(value))
             OR (SELECT array_agg(value) FROM jsonb_array_elements_text(p_scope->'sessions') AS x(value)) IS DISTINCT FROM (SELECT array_agg(value ORDER BY value) FROM jsonb_array_elements_text(p_scope->'sessions') AS x(value))
             OR (SELECT array_agg(value) FROM jsonb_array_elements_text(p_scope->'actions') AS x(value)) IS DISTINCT FROM (SELECT array_agg(value ORDER BY value) FROM jsonb_array_elements_text(p_scope->'actions') AS x(value)) THEN RETURN FALSE; END IF;
          ceiling := (p_scope->>'quantity_ceiling')::numeric;
          IF ceiling <= 0 OR ceiling IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric) THEN RETURN FALSE; END IF;
          IF p_require_window THEN
            IF jsonb_typeof(p_scope->'window_start_at') IS DISTINCT FROM 'string' OR jsonb_typeof(p_scope->'window_end_at') IS DISTINCT FROM 'string' THEN RETURN FALSE; END IF;
            starts_at := (p_scope->>'window_start_at')::timestamptz;
            ends_at := (p_scope->>'window_end_at')::timestamptz;
            IF ends_at <= starts_at THEN RETURN FALSE; END IF;
          END IF;
          RETURN TRUE;
        EXCEPTION WHEN others THEN RETURN FALSE;
        END $$""",
            """CREATE FUNCTION fao.v014_valid_execution_fields(p_instrument TEXT,p_strategy TEXT,p_session TEXT,p_action TEXT,p_quantity NUMERIC)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        BEGIN
          IF p_instrument IS NULL OR p_instrument='' OR p_instrument ~ '[[:space:]]' OR p_strategy IS NULL OR p_strategy='' OR p_strategy ~ '[[:space:]]' OR p_session IS NULL OR p_session='' OR p_session ~ '[[:space:]]' OR p_action IS NULL OR p_action NOT IN ('OPEN','REDUCE','CLOSE') OR p_quantity IS NULL OR p_quantity <= 0 OR p_quantity IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric) THEN RETURN FALSE; END IF;
          RETURN TRUE;
        END $$""",
            """CREATE FUNCTION fao.v014_valid_risk_dimensions(p_dimensions JSONB)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        BEGIN
          IF p_dimensions IS NULL OR jsonb_typeof(p_dimensions) IS DISTINCT FROM 'object' OR EXISTS (SELECT 1 FROM jsonb_each(p_dimensions) AS x(key,value) WHERE x.key='' OR x.key IS DISTINCT FROM btrim(x.key) OR x.key ~ '(^[[:space:]]|[[:space:]]$)' OR jsonb_typeof(x.value) IS DISTINCT FROM 'string' OR x.value #>> '{}'='') THEN RETURN FALSE; END IF;
          RETURN TRUE;
        END $$""",
            """CREATE FUNCTION fao.v014_valid_snapshot_refs(p_snapshots JSONB,p_now TIMESTAMPTZ)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE as_of_at TIMESTAMPTZ; expires_at TIMESTAMPTZ;
        BEGIN
          IF p_snapshots IS NULL OR jsonb_typeof(p_snapshots) IS DISTINCT FROM 'object' OR p_now IS NULL
             OR jsonb_typeof(p_snapshots->'as_of') IS DISTINCT FROM 'string' OR jsonb_typeof(p_snapshots->'expires_at') IS DISTINCT FROM 'string'
             OR EXISTS (SELECT 1 FROM jsonb_each(p_snapshots) AS x(key,value) WHERE btrim(x.key)='' OR jsonb_typeof(x.value) IS DISTINCT FROM 'string' OR btrim(x.value #>> '{}')='') THEN RETURN FALSE; END IF;
          as_of_at := (p_snapshots->>'as_of')::timestamptz;
          expires_at := (p_snapshots->>'expires_at')::timestamptz;
          RETURN as_of_at <= p_now AND expires_at > as_of_at AND expires_at > p_now;
        EXCEPTION WHEN others THEN RETURN FALSE;
        END $$""",
            """CREATE FUNCTION fao.v014_scope_permits(p_scope JSONB,p_account UUID,p_instrument TEXT,p_strategy TEXT,p_session TEXT,p_action TEXT,p_quantity NUMERIC,p_require_window BOOLEAN)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        BEGIN
          IF NOT fao.v014_valid_scope(p_scope,p_account,p_require_window) OR NOT fao.v014_valid_execution_fields(p_instrument,p_strategy,p_session,p_action,p_quantity) THEN RETURN FALSE; END IF;
          IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(p_scope->'instruments') AS x(value) WHERE x.value IS NOT DISTINCT FROM p_instrument)
             OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(p_scope->'strategies') AS x(value) WHERE x.value IS NOT DISTINCT FROM p_strategy)
             OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(p_scope->'sessions') AS x(value) WHERE x.value IS NOT DISTINCT FROM p_session)
             OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(p_scope->'actions') AS x(value) WHERE x.value IS NOT DISTINCT FROM p_action)
             OR p_quantity > (p_scope->>'quantity_ceiling')::numeric THEN RETURN FALSE; END IF;
          RETURN TRUE;
        EXCEPTION WHEN others THEN RETURN FALSE;
        END $$""",
            # A GRANTED approval is transformed in-place from version n to n+1.
            # Its basis records n; the consumed approval at n+1 is therefore a
            # durable, unambiguous manual authorization chain.
            """CREATE FUNCTION fao.consume_plan_approval(
            p_approval UUID, p_approval_version BIGINT, p_plan UUID, p_plan_version BIGINT, p_plan_hash TEXT,
            p_account UUID, p_instrument TEXT, p_strategy TEXT, p_session TEXT, p_action TEXT, p_quantity NUMERIC, p_token UUID, p_approval_hash TEXT,
            p_scope_hash TEXT, p_basis UUID, p_basis_hash TEXT, p_expires TIMESTAMPTZ, p_now TIMESTAMPTZ, p_actor TEXT
        ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE a RECORD; existing UUID; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          SELECT * INTO a FROM fao.plan_approval WHERE approval_id=p_approval AND version IN (p_approval_version, p_approval_version+1) ORDER BY version DESC FOR UPDATE;
          IF NOT FOUND THEN RETURN NULL; END IF;
          IF a.version=p_approval_version+1 AND a.status='CONSUMED' AND a.consumed_basis_id IS NOT NULL THEN
            SELECT basis_id INTO existing FROM fao.authorization_basis WHERE basis_id=a.consumed_basis_id AND basis_kind='PLAN_APPROVAL' AND plan_id IS NOT DISTINCT FROM p_plan AND plan_version IS NOT DISTINCT FROM p_plan_version AND plan_sha256 IS NOT DISTINCT FROM p_plan_hash AND account_id IS NOT DISTINCT FROM p_account AND instrument_id IS NOT DISTINCT FROM p_instrument AND strategy_id IS NOT DISTINCT FROM p_strategy AND session_id IS NOT DISTINCT FROM p_session AND authorized_action IS NOT DISTINCT FROM p_action AND authorized_quantity IS NOT DISTINCT FROM p_quantity AND approval_token IS NOT DISTINCT FROM p_token AND source_approval_id IS NOT DISTINCT FROM p_approval AND source_approval_version IS NOT DISTINCT FROM p_approval_version AND source_sha256 IS NOT DISTINCT FROM p_approval_hash AND scope_sha256 IS NOT DISTINCT FROM p_scope_hash AND basis_sha256 IS NOT DISTINCT FROM p_basis_hash AND expires_at IS NOT DISTINCT FROM p_expires AND issued_by IS NOT DISTINCT FROM p_actor AND actor_audit_ref IS NOT DISTINCT FROM p_actor AND fao.v014_scope_permits(scope_snapshot,p_account,p_instrument,p_strategy,p_session,p_action,p_quantity,TRUE);
            RETURN existing;
          END IF;
          IF a.version IS DISTINCT FROM p_approval_version OR a.status IS DISTINCT FROM 'GRANTED' OR a.expires_at<=authoritative_now OR p_expires IS NULL OR p_expires<=authoritative_now OR p_expires>a.expires_at OR p_expires>a.window_end_at
             OR a.plan_id IS DISTINCT FROM p_plan OR a.plan_version IS DISTINCT FROM p_plan_version OR a.plan_sha256 IS DISTINCT FROM p_plan_hash OR a.scope_account_id IS DISTINCT FROM p_account
             OR p_quantity IS NULL OR p_quantity>a.quantity_ceiling OR a.approval_token IS DISTINCT FROM p_token
             OR a.approval_hash IS DISTINCT FROM p_approval_hash OR a.scope_sha256 IS DISTINCT FROM p_scope_hash OR authoritative_now<a.window_start_at OR authoritative_now>=a.window_end_at
             OR a.decided_by IS DISTINCT FROM p_actor OR p_actor IS NULL OR p_actor IS DISTINCT FROM btrim(p_actor) OR p_actor !~ '^user:[^[:space:]]+$' OR NOT fao.v014_scope_permits(a.approval_scope,p_account,p_instrument,p_strategy,p_session,p_action,p_quantity,TRUE) OR p_basis_hash !~ '^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
          INSERT INTO fao.authorization_basis (basis_id,basis_kind,basis_status,basis_sha256,plan_id,plan_version,plan_sha256,account_id,instrument_id,strategy_id,session_id,authorized_action,authorized_quantity,window_start_at,window_end_at,approval_token,source_approval_id,source_approval_version,source_sha256,scope_snapshot,scope_sha256,issued_by,actor_audit_ref,expires_at)
          VALUES (p_basis,'PLAN_APPROVAL','ACTIVE',p_basis_hash,p_plan,p_plan_version,p_plan_hash,p_account,p_instrument,p_strategy,p_session,p_action,p_quantity,a.window_start_at,a.window_end_at,p_token,p_approval,p_approval_version,a.approval_hash,a.approval_scope,a.scope_sha256,p_actor,p_actor,p_expires);
          UPDATE fao.plan_approval SET version=version+1,status='CONSUMED',state_version=state_version+1,consumed_basis_id=p_basis,consumed_at=authoritative_now WHERE approval_id=p_approval AND version=p_approval_version;
          RETURN p_basis;
        EXCEPTION WHEN unique_violation THEN RETURN NULL;
        END $$""",
            """CREATE FUNCTION fao.issue_mandate_basis(
            p_basis UUID, p_mandate UUID, p_mandate_version BIGINT, p_plan UUID, p_plan_version BIGINT, p_plan_hash TEXT,
            p_account UUID, p_instrument TEXT, p_strategy TEXT, p_session TEXT, p_action TEXT, p_quantity NUMERIC, p_mandate_hash TEXT, p_scope_hash TEXT, p_basis_hash TEXT,
            p_expires TIMESTAMPTZ, p_now TIMESTAMPTZ, p_actor TEXT
        ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE m RECORD; existing UUID; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          SELECT * INTO m FROM fao.simulation_autonomy_mandate WHERE mandate_id=p_mandate AND version=p_mandate_version FOR UPDATE;
          IF NOT FOUND OR m.status IS DISTINCT FROM 'ACTIVE' OR m.expires_at<=authoritative_now OR m.simulation_account_id IS DISTINCT FROM p_account OR m.authority_sha256 IS DISTINCT FROM p_mandate_hash OR m.scope_sha256 IS DISTINCT FROM p_scope_hash OR p_expires IS NULL OR p_expires<=authoritative_now OR p_expires>m.expires_at OR p_actor IS NULL OR p_actor IS DISTINCT FROM btrim(p_actor) OR p_actor !~ '^service:[^[:space:]]+$' OR NOT fao.v014_scope_permits(m.scope,p_account,p_instrument,p_strategy,p_session,p_action,p_quantity,FALSE) OR p_basis_hash !~ '^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
          SELECT basis_id INTO existing FROM fao.authorization_basis WHERE basis_kind='MANDATE' AND source_mandate_id=p_mandate AND source_mandate_version=p_mandate_version AND plan_id=p_plan AND plan_version=p_plan_version;
          IF FOUND THEN
            IF EXISTS (SELECT 1 FROM fao.authorization_basis WHERE basis_id=existing AND plan_sha256=p_plan_hash AND account_id=p_account AND instrument_id=p_instrument AND strategy_id=p_strategy AND session_id=p_session AND authorized_action=p_action AND authorized_quantity=p_quantity AND source_sha256=p_mandate_hash AND scope_sha256=p_scope_hash AND basis_sha256=p_basis_hash AND expires_at=p_expires AND issued_by=p_actor) THEN RETURN existing; END IF;
            RETURN NULL;
          END IF;
          INSERT INTO fao.authorization_basis (basis_id,basis_kind,basis_status,basis_sha256,plan_id,plan_version,plan_sha256,account_id,instrument_id,strategy_id,session_id,authorized_action,authorized_quantity,source_mandate_id,source_mandate_version,source_sha256,scope_snapshot,scope_sha256,issued_by,actor_audit_ref,expires_at)
          VALUES (p_basis,'MANDATE','ACTIVE',p_basis_hash,p_plan,p_plan_version,p_plan_hash,p_account,p_instrument,p_strategy,p_session,p_action,p_quantity,p_mandate,p_mandate_version,m.authority_sha256,m.scope,m.scope_sha256,p_actor,p_actor,p_expires);
          RETURN p_basis;
        EXCEPTION WHEN unique_violation THEN RETURN NULL;
        END $$""",
            """CREATE FUNCTION fao.reserve_risk_budget(
            p_reservation UUID, p_reservation_hash TEXT, p_account UUID, p_plan UUID, p_plan_version BIGINT, p_plan_hash TEXT, p_instrument TEXT, p_strategy TEXT, p_session TEXT,
            p_basis UUID, p_basis_hash TEXT, p_constitution_ref TEXT, p_constitution_version BIGINT, p_constitution_hash TEXT,
            p_dimensions JSONB, p_quantity NUMERIC, p_loss NUMERIC, p_margin NUMERIC, p_expires TIMESTAMPTZ, p_now TIMESTAMPTZ
        ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE au RECORD; b RECORD; held NUMERIC; source_record_ref UUID; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          SELECT * INTO au FROM fao.risk_budget_authority WHERE account_id=p_account AND constitution_ref=p_constitution_ref AND constitution_version=p_constitution_version AND constitution_sha256=p_constitution_hash FOR UPDATE;
          IF NOT FOUND OR p_constitution_ref IS NULL OR p_constitution_ref IS DISTINCT FROM btrim(p_constitution_ref) OR p_constitution_ref ~ '[[:space:]]' OR p_constitution_ref='' OR au.constitution_ref LIKE 'legacy://untrusted-%' OR au.ceiling IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric) OR p_loss IS NULL OR p_loss<0 OR p_loss>au.ceiling OR p_loss IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric) OR p_quantity IS NULL OR p_quantity<=0 OR p_quantity IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric) OR p_margin IS NULL OR p_margin<0 OR p_margin IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric) OR NOT fao.v014_valid_risk_dimensions(p_dimensions) OR p_reservation_hash !~ '^[0-9a-f]{64}$' THEN RETURN FALSE; END IF;
          SELECT * INTO b FROM fao.authorization_basis WHERE basis_id=p_basis FOR UPDATE;
          IF NOT FOUND OR b.basis_status IS DISTINCT FROM 'ACTIVE' OR b.expires_at<=authoritative_now OR b.account_id IS DISTINCT FROM p_account OR b.plan_id IS DISTINCT FROM p_plan OR b.plan_version IS DISTINCT FROM p_plan_version OR b.plan_sha256 IS DISTINCT FROM p_plan_hash OR b.instrument_id IS DISTINCT FROM p_instrument OR b.strategy_id IS DISTINCT FROM p_strategy OR b.session_id IS DISTINCT FROM p_session OR b.basis_sha256 IS DISTINCT FROM p_basis_hash OR p_quantity IS DISTINCT FROM b.authorized_quantity OR p_expires IS NULL OR p_expires<=authoritative_now OR p_expires>b.expires_at OR (b.basis_kind='PLAN_APPROVAL' AND (b.window_start_at IS NULL OR b.window_end_at IS NULL OR authoritative_now<b.window_start_at OR authoritative_now>=b.window_end_at OR p_expires>b.window_end_at)) OR NOT fao.v014_valid_execution_fields(p_instrument,p_strategy,p_session,b.authorized_action,p_quantity) OR NOT fao.v014_scope_permits(b.scope_snapshot,p_account,p_instrument,p_strategy,p_session,b.authorized_action,p_quantity,b.basis_kind='PLAN_APPROVAL') THEN RETURN FALSE; END IF;
          IF b.basis_kind='MANDATE' THEN
            IF NOT EXISTS (SELECT 1 FROM fao.simulation_autonomy_mandate m WHERE m.mandate_id=b.source_mandate_id AND m.version=b.source_mandate_version AND m.status='ACTIVE' AND m.expires_at>authoritative_now AND m.simulation_account_id=p_account AND m.authority_sha256=b.source_sha256 AND m.scope_sha256=b.scope_sha256) THEN RETURN FALSE; END IF;
            source_record_ref:=b.source_mandate_id;
          ELSE
            IF NOT EXISTS (SELECT 1 FROM fao.plan_approval a WHERE a.approval_id=b.source_approval_id AND a.version=b.source_approval_version+1 AND a.status='CONSUMED' AND a.consumed_basis_id=b.basis_id AND a.scope_account_id=p_account AND a.approval_hash=b.source_sha256 AND a.scope_sha256=b.scope_sha256 AND a.approval_token=b.approval_token AND a.allowed_actions @> jsonb_build_array(to_jsonb(b.authorized_action)) AND a.quantity_ceiling>=b.authorized_quantity) THEN RETURN FALSE; END IF;
            source_record_ref:=b.source_approval_id;
          END IF;
          IF EXISTS (SELECT 1 FROM fao.risk_budget_reservation WHERE plan_id=p_plan AND plan_version=p_plan_version AND basis_id=p_basis) THEN
            RETURN EXISTS (SELECT 1 FROM fao.risk_budget_reservation WHERE plan_id=p_plan AND plan_version=p_plan_version AND basis_id=p_basis AND reservation_status='HELD' AND reservation_sha256=p_reservation_hash AND account_id=p_account AND plan_sha256=p_plan_hash AND basis_sha256=p_basis_hash AND risk_constitution_ref=p_constitution_ref AND risk_constitution_version=p_constitution_version AND risk_constitution_sha256=p_constitution_hash AND instrument_id=p_instrument AND strategy_id=p_strategy AND session_id=p_session AND risk_dimensions IS NOT DISTINCT FROM p_dimensions AND quantity=p_quantity AND worst_case_loss=p_loss AND margin=p_margin AND source_kind=b.basis_kind AND source_ref=source_record_ref AND source_sha256=b.source_sha256 AND expires_at=p_expires);
          END IF;
          SELECT COALESCE(sum(worst_case_loss),0) INTO held FROM fao.risk_budget_reservation WHERE account_id=p_account AND reservation_status='HELD' AND expires_at>authoritative_now;
          IF held+p_loss>au.ceiling THEN RETURN FALSE; END IF;
          INSERT INTO fao.risk_budget_reservation (reservation_id,reservation_version,reservation_status,reservation_sha256,account_id,plan_id,plan_version,plan_sha256,basis_id,basis_sha256,risk_constitution_ref,risk_constitution_version,risk_constitution_sha256,instrument_id,strategy_id,session_id,risk_dimensions,quantity,worst_case_loss,margin,source_kind,source_ref,source_sha256,expires_at)
          VALUES (p_reservation,1,'HELD',p_reservation_hash,p_account,p_plan,p_plan_version,p_plan_hash,p_basis,p_basis_hash,p_constitution_ref,p_constitution_version,p_constitution_hash,p_instrument,p_strategy,p_session,p_dimensions,p_quantity,p_loss,p_margin,b.basis_kind,source_record_ref,b.source_sha256,p_expires);
          RETURN TRUE;
        EXCEPTION WHEN unique_violation THEN
          RETURN EXISTS (SELECT 1 FROM fao.risk_budget_reservation WHERE plan_id=p_plan AND plan_version=p_plan_version AND basis_id=p_basis AND reservation_status='HELD' AND reservation_sha256=p_reservation_hash AND account_id=p_account AND plan_sha256=p_plan_hash AND basis_sha256=p_basis_hash AND risk_constitution_ref=p_constitution_ref AND risk_constitution_version=p_constitution_version AND risk_constitution_sha256=p_constitution_hash AND instrument_id=p_instrument AND strategy_id=p_strategy AND session_id=p_session AND risk_dimensions IS NOT DISTINCT FROM p_dimensions AND quantity=p_quantity AND worst_case_loss=p_loss AND margin=p_margin AND expires_at=p_expires);
        END $$""",
            """CREATE FUNCTION fao.issue_autonomy_gate_receipt(
            p_receipt UUID,p_nonce UUID,p_basis UUID,p_basis_hash TEXT,p_reservation UUID,p_reservation_hash TEXT,
            p_plan UUID,p_plan_version BIGINT,p_plan_hash TEXT,p_account UUID,p_instrument TEXT,p_strategy TEXT,p_session TEXT,p_action TEXT,p_origin TEXT,p_source_hash TEXT,p_scope_hash TEXT,
            p_snapshot_refs JSONB,p_snapshot_hash TEXT,p_run_hash TEXT,p_binding UUID,p_binding_version BIGINT,p_binding_hash TEXT,
            p_constitution_ref TEXT,p_constitution_version BIGINT,p_constitution_hash TEXT,p_expires TIMESTAMPTZ,p_now TIMESTAMPTZ,p_actor TEXT,p_manual_actor TEXT,p_environment_policy TEXT
        ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE b RECORD; r RECORD; au RECORD; m RECORD; bind RECORD; existing UUID; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          SELECT * INTO b FROM fao.authorization_basis WHERE basis_id=p_basis FOR UPDATE;
          SELECT * INTO r FROM fao.risk_budget_reservation WHERE reservation_id=p_reservation FOR UPDATE;
          SELECT * INTO au FROM fao.risk_budget_authority WHERE account_id=p_account AND constitution_ref=p_constitution_ref AND constitution_version=p_constitution_version AND constitution_sha256=p_constitution_hash FOR UPDATE;
          IF NOT FOUND OR b IS NULL OR b.basis_status IS DISTINCT FROM 'ACTIVE' OR b.expires_at<=authoritative_now OR r.reservation_status IS DISTINCT FROM 'HELD' OR r.expires_at<=authoritative_now
             OR b.basis_sha256 IS DISTINCT FROM p_basis_hash OR b.plan_id IS DISTINCT FROM p_plan OR b.plan_version IS DISTINCT FROM p_plan_version OR b.plan_sha256 IS DISTINCT FROM p_plan_hash OR b.account_id IS DISTINCT FROM p_account OR b.instrument_id IS DISTINCT FROM p_instrument OR b.strategy_id IS DISTINCT FROM p_strategy OR b.session_id IS DISTINCT FROM p_session OR b.authorized_action IS DISTINCT FROM p_action OR b.source_sha256 IS DISTINCT FROM p_source_hash OR b.scope_sha256 IS DISTINCT FROM p_scope_hash
             OR r.reservation_sha256 IS DISTINCT FROM p_reservation_hash OR r.account_id IS DISTINCT FROM p_account OR r.plan_id IS DISTINCT FROM p_plan OR r.plan_version IS DISTINCT FROM p_plan_version OR r.plan_sha256 IS DISTINCT FROM p_plan_hash OR r.instrument_id IS DISTINCT FROM p_instrument OR r.strategy_id IS DISTINCT FROM p_strategy OR r.session_id IS DISTINCT FROM p_session OR r.basis_id IS DISTINCT FROM p_basis OR r.basis_sha256 IS DISTINCT FROM p_basis_hash OR r.quantity IS DISTINCT FROM b.authorized_quantity OR r.source_kind IS DISTINCT FROM b.basis_kind OR r.source_ref IS DISTINCT FROM COALESCE(b.source_mandate_id,b.source_approval_id) OR r.source_sha256 IS DISTINCT FROM p_source_hash
             OR r.risk_constitution_ref IS DISTINCT FROM p_constitution_ref OR r.risk_constitution_version IS DISTINCT FROM p_constitution_version OR r.risk_constitution_sha256 IS DISTINCT FROM p_constitution_hash OR p_constitution_ref IS NULL OR p_constitution_ref IS DISTINCT FROM btrim(p_constitution_ref) OR p_constitution_ref ~ '[[:space:]]' OR p_constitution_ref='' OR au IS NULL OR au.constitution_ref LIKE 'legacy://untrusted-%' OR p_expires IS NULL OR p_expires<=authoritative_now OR p_expires>b.expires_at OR p_expires>r.expires_at OR (b.basis_kind='PLAN_APPROVAL' AND (b.window_start_at IS NULL OR b.window_end_at IS NULL OR authoritative_now<b.window_start_at OR authoritative_now>=b.window_end_at OR p_expires>b.window_end_at)) OR NOT fao.v014_valid_snapshot_refs(p_snapshot_refs,authoritative_now) OR p_expires>(p_snapshot_refs->>'expires_at')::timestamptz OR NOT fao.v014_scope_permits(b.scope_snapshot,p_account,p_instrument,p_strategy,p_session,p_action,b.authorized_quantity,b.basis_kind='PLAN_APPROVAL') THEN RETURN NULL; END IF;
          IF p_origin='AUTONOMOUS_AGENT' THEN
            IF b.basis_kind<>'MANDATE' OR p_manual_actor IS NOT NULL OR p_actor<>btrim(p_actor) OR p_actor !~ '^service:[^[:space:]]+$' THEN RETURN NULL; END IF;
            SELECT * INTO m FROM fao.simulation_autonomy_mandate WHERE mandate_id=b.source_mandate_id AND version=b.source_mandate_version AND status='ACTIVE' AND expires_at>authoritative_now AND simulation_account_id=p_account AND authority_sha256=b.source_sha256 AND scope_sha256=b.scope_sha256 FOR UPDATE;
            SELECT * INTO bind FROM fao.autonomy_mode_binding WHERE binding_id=p_binding AND version=p_binding_version AND binding_status='ACTIVE' AND mode='AUTONOMOUS_SIMULATION' AND expires_at>authoritative_now AND qualified_artifact_ref IS NOT NULL AND qualified_artifact_ref= btrim(qualified_artifact_ref) AND qualified_artifact_ref !~ '[[:space:]]' AND qualified_artifact_ref<>'' FOR UPDATE;
            IF m IS NULL OR bind IS NULL OR bind.account_id IS DISTINCT FROM p_account OR bind.mandate_id IS DISTINCT FROM b.source_mandate_id OR bind.mandate_version IS DISTINCT FROM b.source_mandate_version OR bind.run_versions_sha256 IS DISTINCT FROM p_run_hash OR bind.binding_sha256 IS DISTINCT FROM p_binding_hash OR bind.scope_sha256 IS DISTINCT FROM p_scope_hash OR p_expires>bind.expires_at OR NOT EXISTS (SELECT 1 FROM fao.autonomy_health_permit h WHERE h.account_id=p_account AND h.permits IS TRUE AND h.environment_policy_ref=p_environment_policy AND h.valid_until_at>=p_expires) THEN RETURN NULL; END IF;
          ELSIF p_origin='MANUAL_TEST' THEN
            IF b.basis_kind IS DISTINCT FROM 'PLAN_APPROVAL' OR p_binding IS NOT NULL OR p_binding_version IS NOT NULL OR p_binding_hash IS NOT NULL OR p_manual_actor IS NULL OR p_manual_actor IS DISTINCT FROM p_actor OR p_actor IS NULL OR p_actor IS DISTINCT FROM btrim(p_actor) OR p_actor !~ '^user:[^[:space:]]+$' OR NOT EXISTS (SELECT 1 FROM fao.plan_approval a WHERE a.approval_id IS NOT DISTINCT FROM b.source_approval_id AND a.version IS NOT DISTINCT FROM b.source_approval_version+1 AND a.status IS NOT DISTINCT FROM 'CONSUMED' AND a.consumed_basis_id IS NOT DISTINCT FROM b.basis_id AND a.scope_account_id IS NOT DISTINCT FROM p_account AND a.approval_hash IS NOT DISTINCT FROM b.source_sha256 AND a.scope_sha256 IS NOT DISTINCT FROM b.scope_sha256 AND a.approval_token IS NOT DISTINCT FROM b.approval_token AND a.allowed_actions @> jsonb_build_array(to_jsonb(p_action)) AND a.quantity_ceiling>=b.authorized_quantity AND a.decided_by IS NOT DISTINCT FROM p_manual_actor) OR NOT EXISTS (SELECT 1 FROM fao.autonomy_health_permit h WHERE h.account_id=p_account AND h.environment_policy_ref=p_environment_policy AND h.permits IS TRUE AND h.valid_until_at>=p_expires) THEN RETURN NULL; END IF;
          ELSE RETURN NULL; END IF;
          INSERT INTO fao.autonomy_gate_receipt (receipt_id,receipt_status,nonce,basis_id,basis_sha256,plan_id,plan_version,plan_sha256,account_id,instrument_id,strategy_id,session_id,action,execution_origin,source_sha256,scope_sha256,reservation_id,reservation_sha256,risk_constitution_ref,risk_constitution_version,risk_constitution_sha256,snapshot_refs,snapshot_sha256,run_versions_sha256,mode_binding_id,mode_binding_version,mode_binding_sha256,issued_at,expires_at,issued_by,manual_actor_ref,environment_policy_ref)
          VALUES (p_receipt,'ISSUED',p_nonce,p_basis,p_basis_hash,p_plan,p_plan_version,p_plan_hash,p_account,p_instrument,p_strategy,p_session,p_action,p_origin,p_source_hash,p_scope_hash,p_reservation,p_reservation_hash,p_constitution_ref,p_constitution_version,p_constitution_hash,p_snapshot_refs,p_snapshot_hash,p_run_hash,p_binding,p_binding_version,p_binding_hash,authoritative_now,p_expires,p_actor,p_manual_actor,p_environment_policy);
          RETURN p_receipt;
        EXCEPTION WHEN unique_violation THEN
          SELECT receipt_id INTO existing FROM fao.autonomy_gate_receipt x WHERE x.basis_id IS NOT DISTINCT FROM p_basis AND x.basis_sha256 IS NOT DISTINCT FROM p_basis_hash AND x.reservation_id IS NOT DISTINCT FROM p_reservation AND x.reservation_sha256 IS NOT DISTINCT FROM p_reservation_hash AND x.plan_id IS NOT DISTINCT FROM p_plan AND x.plan_version IS NOT DISTINCT FROM p_plan_version AND x.plan_sha256 IS NOT DISTINCT FROM p_plan_hash AND x.account_id IS NOT DISTINCT FROM p_account AND x.instrument_id IS NOT DISTINCT FROM p_instrument AND x.strategy_id IS NOT DISTINCT FROM p_strategy AND x.session_id IS NOT DISTINCT FROM p_session AND x.action IS NOT DISTINCT FROM p_action AND x.execution_origin IS NOT DISTINCT FROM p_origin AND x.source_sha256 IS NOT DISTINCT FROM p_source_hash AND x.scope_sha256 IS NOT DISTINCT FROM p_scope_hash AND x.snapshot_refs IS NOT DISTINCT FROM p_snapshot_refs AND x.snapshot_sha256 IS NOT DISTINCT FROM p_snapshot_hash AND x.run_versions_sha256 IS NOT DISTINCT FROM p_run_hash AND x.mode_binding_id IS NOT DISTINCT FROM p_binding AND x.mode_binding_version IS NOT DISTINCT FROM p_binding_version AND x.mode_binding_sha256 IS NOT DISTINCT FROM p_binding_hash AND x.risk_constitution_ref IS NOT DISTINCT FROM p_constitution_ref AND x.risk_constitution_version IS NOT DISTINCT FROM p_constitution_version AND x.risk_constitution_sha256 IS NOT DISTINCT FROM p_constitution_hash AND x.expires_at IS NOT DISTINCT FROM p_expires AND x.issued_by IS NOT DISTINCT FROM p_actor AND x.manual_actor_ref IS NOT DISTINCT FROM p_manual_actor AND x.environment_policy_ref IS NOT DISTINCT FROM p_environment_policy;
          RETURN existing;
        END $$""",
            """CREATE FUNCTION fao.consume_autonomy_gate_receipt(p_receipt UUID,p_nonce UUID,p_now TIMESTAMPTZ)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE x RECORD; b RECORD; r RECORD; au RECORD; m RECORD; bind RECORD; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          SELECT * INTO x FROM fao.autonomy_gate_receipt WHERE receipt_id=p_receipt AND nonce=p_nonce FOR UPDATE;
          IF NOT FOUND OR x.receipt_status<>'ISSUED' OR x.expires_at<=authoritative_now THEN RETURN FALSE; END IF;
          SELECT * INTO b FROM fao.authorization_basis WHERE basis_id=x.basis_id FOR UPDATE;
          SELECT * INTO r FROM fao.risk_budget_reservation WHERE reservation_id=x.reservation_id FOR UPDATE;
          SELECT * INTO au FROM fao.risk_budget_authority WHERE account_id=x.account_id AND constitution_ref=x.risk_constitution_ref AND constitution_version=x.risk_constitution_version AND constitution_sha256=x.risk_constitution_sha256 FOR UPDATE;
          IF b IS NULL OR r IS NULL OR b.basis_status<>'ACTIVE' OR b.expires_at<=authoritative_now OR r.reservation_status<>'HELD' OR r.expires_at<=authoritative_now OR NOT fao.v014_valid_snapshot_refs(x.snapshot_refs,authoritative_now) OR x.expires_at>(x.snapshot_refs->>'expires_at')::timestamptz OR (b.basis_kind='PLAN_APPROVAL' AND (b.window_start_at IS NULL OR b.window_end_at IS NULL OR authoritative_now<b.window_start_at OR authoritative_now>=b.window_end_at OR x.expires_at>b.window_end_at OR r.expires_at>b.window_end_at))
             OR x.basis_sha256<>b.basis_sha256 OR x.plan_id<>b.plan_id OR x.plan_version<>b.plan_version OR x.plan_sha256<>b.plan_sha256 OR x.account_id<>b.account_id OR x.instrument_id<>b.instrument_id OR x.strategy_id<>b.strategy_id OR x.session_id<>b.session_id OR x.action<>b.authorized_action OR x.source_sha256<>b.source_sha256 OR x.scope_sha256<>b.scope_sha256
             OR x.reservation_sha256<>r.reservation_sha256 OR r.account_id<>x.account_id OR r.plan_id<>x.plan_id OR r.plan_version<>x.plan_version OR r.plan_sha256<>x.plan_sha256 OR r.instrument_id<>x.instrument_id OR r.strategy_id<>x.strategy_id OR r.session_id<>x.session_id OR r.basis_id<>x.basis_id OR r.basis_sha256<>x.basis_sha256 OR r.quantity<>b.authorized_quantity OR r.source_kind<>b.basis_kind OR r.source_ref<>COALESCE(b.source_mandate_id,b.source_approval_id) OR r.source_sha256<>x.source_sha256
             OR x.risk_constitution_ref<>r.risk_constitution_ref OR x.risk_constitution_version<>r.risk_constitution_version OR x.risk_constitution_sha256<>r.risk_constitution_sha256 OR au IS NULL OR au.constitution_ref LIKE 'legacy://untrusted-%' THEN RETURN FALSE; END IF;
          IF x.execution_origin='AUTONOMOUS_AGENT' THEN
            SELECT * INTO m FROM fao.simulation_autonomy_mandate WHERE mandate_id=b.source_mandate_id AND version=b.source_mandate_version AND status='ACTIVE' AND expires_at>authoritative_now AND simulation_account_id=x.account_id AND authority_sha256=b.source_sha256 AND scope_sha256=b.scope_sha256 FOR UPDATE;
            SELECT * INTO bind FROM fao.autonomy_mode_binding WHERE binding_id=x.mode_binding_id AND version=x.mode_binding_version AND binding_status='ACTIVE' AND mode='AUTONOMOUS_SIMULATION' AND expires_at>authoritative_now AND qualified_artifact_ref IS NOT NULL AND qualified_artifact_ref=btrim(qualified_artifact_ref) AND qualified_artifact_ref !~ '[[:space:]]' AND qualified_artifact_ref<>'' FOR UPDATE;
            IF b.basis_kind<>'MANDATE' OR m IS NULL OR bind IS NULL OR bind.account_id<>x.account_id OR bind.mandate_id<>b.source_mandate_id OR bind.mandate_version<>b.source_mandate_version OR bind.run_versions_sha256<>x.run_versions_sha256 OR bind.binding_sha256<>x.mode_binding_sha256 OR bind.scope_sha256<>x.scope_sha256 OR x.expires_at>bind.expires_at OR NOT EXISTS (SELECT 1 FROM fao.autonomy_health_permit h WHERE h.account_id=x.account_id AND h.permits IS TRUE AND h.environment_policy_ref=x.environment_policy_ref AND h.valid_until_at>=x.expires_at) THEN RETURN FALSE; END IF;
          ELSIF x.execution_origin='MANUAL_TEST' THEN
            IF b.basis_kind<>'PLAN_APPROVAL' OR x.manual_actor_ref IS NULL OR x.mode_binding_id IS NOT NULL OR NOT EXISTS (SELECT 1 FROM fao.plan_approval a WHERE a.approval_id=b.source_approval_id AND a.version=b.source_approval_version+1 AND a.status='CONSUMED' AND a.consumed_basis_id=b.basis_id AND a.scope_account_id=x.account_id AND a.approval_hash=b.source_sha256 AND a.scope_sha256=b.scope_sha256 AND a.approval_token=b.approval_token AND a.allowed_actions @> jsonb_build_array(to_jsonb(x.action)) AND a.quantity_ceiling>=b.authorized_quantity AND a.decided_by=x.manual_actor_ref) OR NOT EXISTS (SELECT 1 FROM fao.autonomy_health_permit h WHERE h.account_id=x.account_id AND h.environment_policy_ref=x.environment_policy_ref AND h.permits IS TRUE AND h.valid_until_at>=x.expires_at) THEN RETURN FALSE; END IF;
          ELSE RETURN FALSE; END IF;
          UPDATE fao.autonomy_gate_receipt SET receipt_status='CONSUMED',state_version=state_version+1,consumed_at=authoritative_now WHERE receipt_id=p_receipt AND receipt_status='ISSUED';
          RETURN FOUND;
        END $$""",
            """CREATE FUNCTION fao.consume_risk_budget_reservation(p_reservation UUID,p_receipt UUID,p_now TIMESTAMPTZ)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        BEGIN
          UPDATE fao.risk_budget_reservation r SET reservation_status='CONSUMED',reservation_version=r.reservation_version+1,state_version=r.state_version+1,consumed_at=clock_timestamp()
          FROM fao.autonomy_gate_receipt x WHERE r.reservation_id=p_reservation AND x.receipt_id=p_receipt AND x.reservation_id=r.reservation_id AND x.receipt_status='CONSUMED' AND r.reservation_status='HELD';
          RETURN FOUND;
        END $$""",
            """CREATE FUNCTION fao.transition_simulation_autonomy_mandate(p_mandate UUID,p_version BIGINT,p_target TEXT,p_actor TEXT,p_evidence TEXT,p_reason TEXT,p_new_hash TEXT)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE m RECORD; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          IF p_mandate IS NULL OR p_version IS NULL OR p_version<=0 OR p_target IS NULL OR p_target NOT IN ('VALIDATED','APPROVED','ACTIVE','SUSPENDED','HALTED','RECOVERING','REVOKED') OR p_actor IS NULL OR p_actor IS DISTINCT FROM btrim(p_actor) OR p_actor !~ '^(user|service|system):[^[:space:]]+$' OR p_evidence IS NULL OR btrim(p_evidence)='' OR p_new_hash IS NULL OR p_new_hash !~ '^[0-9a-f]{64}$' OR p_reason IS NULL OR btrim(p_reason)='' THEN RETURN FALSE; END IF;
          SELECT * INTO m FROM fao.simulation_autonomy_mandate WHERE mandate_id=p_mandate AND version=p_version FOR UPDATE;
          IF NOT FOUND OR m.status IN ('EXPIRED','REVOKED') OR m.authority_sha256=p_new_hash OR (m.status<>'DRAFT' AND m.expires_at<=authoritative_now)
             OR NOT ((m.status='DRAFT' AND p_target='VALIDATED') OR (m.status='VALIDATED' AND p_target='APPROVED') OR (m.status='APPROVED' AND p_target IN ('ACTIVE','REVOKED')) OR (m.status='ACTIVE' AND p_target IN ('SUSPENDED','HALTED','REVOKED')) OR (m.status='SUSPENDED' AND p_target IN ('ACTIVE','REVOKED')) OR (m.status='HALTED' AND p_target IN ('RECOVERING','REVOKED')) OR (m.status='RECOVERING' AND p_target IN ('ACTIVE','HALTED','REVOKED'))) OR (p_target IN ('ACTIVE','RECOVERING','REVOKED') AND p_actor !~ '^user:') THEN RETURN FALSE; END IF;
          UPDATE fao.simulation_autonomy_mandate SET version=version+1,status=p_target,state_version=state_version+1,authority_sha256=p_new_hash,revocation_reason=CASE WHEN p_target='REVOKED' THEN p_reason ELSE NULL END,recorded_by=p_actor,last_transition_reason=p_reason,evidence_ref=p_evidence,transitioned_at=authoritative_now WHERE mandate_id=p_mandate AND version=p_version;
          IF p_target IN ('SUSPENDED','HALTED','REVOKED') THEN
            UPDATE fao.authorization_basis SET basis_status='STALE',state_version=state_version+1 WHERE basis_kind='MANDATE' AND source_mandate_id=p_mandate AND source_mandate_version=p_version AND basis_status='ACTIVE';
            UPDATE fao.autonomy_gate_receipt x SET receipt_status='STALE',state_version=state_version+1 WHERE receipt_status='ISSUED' AND EXISTS (SELECT 1 FROM fao.authorization_basis b WHERE b.basis_id=x.basis_id AND b.basis_kind='MANDATE' AND b.source_mandate_id=p_mandate AND b.source_mandate_version=p_version);
            UPDATE fao.risk_budget_reservation r SET reservation_status='RELEASED',reservation_version=reservation_version+1,state_version=state_version+1,released_at=authoritative_now WHERE reservation_status='HELD' AND EXISTS (SELECT 1 FROM fao.authorization_basis b WHERE b.basis_id=r.basis_id AND b.basis_kind='MANDATE' AND b.source_mandate_id=p_mandate AND b.source_mandate_version=p_version);
          END IF;
          RETURN TRUE;
        END $$""",
            """CREATE FUNCTION fao.expire_simulation_autonomy_mandate(p_mandate UUID,p_version BIGINT,p_actor TEXT,p_reason TEXT,p_new_hash TEXT)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE m RECORD; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          IF p_mandate IS NULL OR p_version IS NULL OR p_version<=0 OR p_actor IS NULL OR p_actor !~ '^(service|system):[^[:space:]]+$' OR p_reason IS NULL OR btrim(p_reason)='' OR p_new_hash IS NULL OR p_new_hash !~ '^[0-9a-f]{64}$' THEN RETURN FALSE; END IF;
          SELECT * INTO m FROM fao.simulation_autonomy_mandate WHERE mandate_id=p_mandate AND version=p_version FOR UPDATE;
          IF NOT FOUND OR m.status IN ('DRAFT','EXPIRED','REVOKED') OR authoritative_now<m.expires_at OR m.authority_sha256=p_new_hash THEN RETURN FALSE; END IF;
          UPDATE fao.simulation_autonomy_mandate SET version=version+1,status='EXPIRED',state_version=state_version+1,authority_sha256=p_new_hash,recorded_by=p_actor,last_transition_reason=p_reason,evidence_ref='evidence://system-expiry',transitioned_at=authoritative_now WHERE mandate_id=p_mandate AND version=p_version;
          UPDATE fao.authorization_basis SET basis_status='STALE',state_version=state_version+1 WHERE basis_kind='MANDATE' AND source_mandate_id=p_mandate AND source_mandate_version=p_version AND basis_status='ACTIVE';
          UPDATE fao.autonomy_gate_receipt x SET receipt_status='STALE',state_version=state_version+1 WHERE receipt_status='ISSUED' AND EXISTS (SELECT 1 FROM fao.authorization_basis b WHERE b.basis_id=x.basis_id AND b.basis_kind='MANDATE' AND b.source_mandate_id=p_mandate AND b.source_mandate_version=p_version);
          UPDATE fao.risk_budget_reservation r SET reservation_status='RELEASED',reservation_version=reservation_version+1,state_version=state_version+1,released_at=authoritative_now WHERE reservation_status='HELD' AND EXISTS (SELECT 1 FROM fao.authorization_basis b WHERE b.basis_id=r.basis_id AND b.basis_kind='MANDATE' AND b.source_mandate_id=p_mandate AND b.source_mandate_version=p_version);
          RETURN TRUE;
        END $$""",
            """CREATE FUNCTION fao.composite_pause(p_mandate UUID,p_mandate_version BIGINT,p_binding UUID,p_binding_version BIGINT,p_account UUID,p_now TIMESTAMPTZ,p_actor TEXT,p_evidence TEXT,p_new_mandate_hash TEXT,p_new_binding_hash TEXT)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE m RECORD; b RECORD; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          IF p_mandate IS NULL OR p_mandate_version IS NULL OR p_mandate_version<=0 OR p_binding IS NULL OR p_binding_version IS NULL OR p_binding_version<=0 OR p_account IS NULL OR p_now IS NULL OR p_actor IS NULL OR p_actor IS DISTINCT FROM btrim(p_actor) OR p_actor !~ '^user:[^[:space:]]+$' OR p_evidence IS NULL OR p_evidence IS DISTINCT FROM btrim(p_evidence) OR length(p_evidence)=0 OR p_new_mandate_hash IS NULL OR p_new_mandate_hash !~ '^[0-9a-f]{64}$' OR p_new_binding_hash IS NULL OR p_new_binding_hash !~ '^[0-9a-f]{64}$' THEN RETURN FALSE; END IF;
          SELECT * INTO m FROM fao.simulation_autonomy_mandate WHERE mandate_id=p_mandate AND version=p_mandate_version AND simulation_account_id=p_account FOR UPDATE;
          SELECT * INTO b FROM fao.autonomy_mode_binding WHERE binding_id=p_binding AND version=p_binding_version AND account_id=p_account FOR UPDATE;
          IF m IS NULL OR b IS NULL OR m.status IS DISTINCT FROM 'ACTIVE' OR m.expires_at<=authoritative_now OR b.binding_status IS DISTINCT FROM 'ACTIVE' OR b.mode IS DISTINCT FROM 'AUTONOMOUS_SIMULATION' OR b.expires_at<=authoritative_now OR b.mandate_id IS DISTINCT FROM p_mandate OR b.mandate_version IS DISTINCT FROM p_mandate_version OR p_new_mandate_hash IS NOT DISTINCT FROM m.authority_sha256 OR p_new_binding_hash IS NOT DISTINCT FROM b.binding_sha256 THEN RETURN FALSE; END IF;
          UPDATE fao.simulation_autonomy_mandate SET version=version+1,status='SUSPENDED',state_version=state_version+1,authority_sha256=p_new_mandate_hash,recorded_by=p_actor,last_transition_reason='USER_PAUSE',evidence_ref=p_evidence,transitioned_at=authoritative_now WHERE mandate_id=p_mandate AND version=p_mandate_version;
          UPDATE fao.autonomy_mode_binding SET version=version+1,mode='PAUSED',previous_mode='AUTONOMOUS_SIMULATION',mandate_version=p_mandate_version+1,state_version=state_version+1,binding_sha256=p_new_binding_hash,transition_reason='USER_PAUSE',transition_actor=p_actor,evidence_ref=p_evidence,recorded_at=authoritative_now WHERE binding_id=p_binding AND version=p_binding_version;
          UPDATE fao.authorization_basis SET basis_status='STALE',state_version=state_version+1 WHERE basis_kind='MANDATE' AND source_mandate_id=p_mandate AND source_mandate_version=p_mandate_version AND account_id=p_account AND basis_status='ACTIVE';
          UPDATE fao.autonomy_gate_receipt x SET receipt_status='STALE',state_version=state_version+1 WHERE x.receipt_status='ISSUED' AND EXISTS (SELECT 1 FROM fao.authorization_basis z WHERE z.basis_id=x.basis_id AND z.basis_kind='MANDATE' AND z.source_mandate_id=p_mandate AND z.source_mandate_version=p_mandate_version AND z.account_id=p_account);
          UPDATE fao.risk_budget_reservation r SET reservation_status='RELEASED',reservation_version=reservation_version+1,state_version=state_version+1,released_at=authoritative_now WHERE r.reservation_status='HELD' AND EXISTS (SELECT 1 FROM fao.authorization_basis z WHERE z.basis_id=r.basis_id AND z.basis_kind='MANDATE' AND z.source_mandate_id=p_mandate AND z.source_mandate_version=p_mandate_version AND z.account_id=p_account);
          RETURN TRUE;
        END $$""",
            """CREATE FUNCTION fao.composite_resume(p_mandate UUID,p_mandate_version BIGINT,p_binding UUID,p_binding_version BIGINT,p_account UUID,p_run_hash TEXT,p_qualified BOOLEAN,p_health BOOLEAN,p_environment_policy TEXT,p_now TIMESTAMPTZ,p_actor TEXT,p_evidence TEXT,p_new_mandate_hash TEXT,p_new_binding_hash TEXT)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE m RECORD; b RECORD; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          IF p_mandate IS NULL OR p_mandate_version IS NULL OR p_mandate_version<=0 OR p_binding IS NULL OR p_binding_version IS NULL OR p_binding_version<=0 OR p_account IS NULL OR p_run_hash IS NULL OR p_run_hash !~ '^[0-9a-f]{64}$' OR p_environment_policy IS NULL OR p_environment_policy IS DISTINCT FROM btrim(p_environment_policy) OR p_environment_policy='' OR p_now IS NULL OR p_actor IS NULL OR p_actor IS DISTINCT FROM btrim(p_actor) OR p_actor !~ '^user:[^[:space:]]+$' OR p_evidence IS NULL OR p_evidence IS DISTINCT FROM btrim(p_evidence) OR length(p_evidence)=0 OR p_new_mandate_hash IS NULL OR p_new_mandate_hash !~ '^[0-9a-f]{64}$' OR p_new_binding_hash IS NULL OR p_new_binding_hash !~ '^[0-9a-f]{64}$' THEN RETURN FALSE; END IF;
          SELECT * INTO m FROM fao.simulation_autonomy_mandate WHERE mandate_id=p_mandate AND version=p_mandate_version AND simulation_account_id=p_account FOR UPDATE;
          SELECT * INTO b FROM fao.autonomy_mode_binding WHERE binding_id=p_binding AND version=p_binding_version AND account_id=p_account FOR UPDATE;
          IF m IS NULL OR b IS NULL OR m.status IS DISTINCT FROM 'SUSPENDED' OR m.expires_at<=authoritative_now OR b.binding_status IS DISTINCT FROM 'ACTIVE' OR b.mode IS DISTINCT FROM 'PAUSED' OR b.previous_mode IS DISTINCT FROM 'AUTONOMOUS_SIMULATION' OR b.expires_at<=authoritative_now OR b.mandate_id IS DISTINCT FROM p_mandate OR b.mandate_version IS DISTINCT FROM p_mandate_version OR b.run_versions_sha256 IS DISTINCT FROM p_run_hash OR b.qualified_artifact_ref IS NULL OR b.qualified_artifact_ref IS DISTINCT FROM btrim(b.qualified_artifact_ref) OR b.qualified_artifact_ref ~ '[[:space:]]' OR b.qualified_artifact_ref='' OR NOT EXISTS (SELECT 1 FROM fao.autonomy_health_permit h WHERE h.account_id=p_account AND h.environment_policy_ref=p_environment_policy AND h.permits IS TRUE AND h.valid_until_at>authoritative_now) OR p_new_mandate_hash IS NOT DISTINCT FROM m.authority_sha256 OR p_new_binding_hash IS NOT DISTINCT FROM b.binding_sha256 THEN RETURN FALSE; END IF;
          UPDATE fao.simulation_autonomy_mandate SET version=version+1,status='ACTIVE',state_version=state_version+1,authority_sha256=p_new_mandate_hash,recorded_by=p_actor,last_transition_reason='USER_RESUME',evidence_ref=p_evidence,transitioned_at=authoritative_now WHERE mandate_id=p_mandate AND version=p_mandate_version;
          UPDATE fao.autonomy_mode_binding SET version=version+1,mode='AUTONOMOUS_SIMULATION',previous_mode=NULL,mandate_version=p_mandate_version+1,state_version=state_version+1,binding_sha256=p_new_binding_hash,transition_reason='USER_RESUME',transition_actor=p_actor,evidence_ref=p_evidence,recorded_at=authoritative_now WHERE binding_id=p_binding AND version=p_binding_version;
          RETURN TRUE;
        END $$""",
            """CREATE FUNCTION fao.retire_autonomy_mode_binding(p_binding UUID,p_binding_version BIGINT,p_account UUID,p_status TEXT,p_now TIMESTAMPTZ,p_actor TEXT,p_reason TEXT,p_new_binding_hash TEXT)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE b RECORD; authoritative_now TIMESTAMPTZ := clock_timestamp();
        BEGIN
          IF p_binding IS NULL OR p_binding_version IS NULL OR p_binding_version<=0 OR p_now IS NULL OR p_status IS NULL OR p_status NOT IN ('EXPIRED','SUPERSEDED') OR p_actor IS NULL OR p_actor IS DISTINCT FROM btrim(p_actor) OR p_actor !~ '^service:[^[:space:]]+$' OR p_reason IS NULL OR p_reason IS DISTINCT FROM btrim(p_reason) OR length(p_reason)=0 OR p_new_binding_hash IS NULL OR p_new_binding_hash !~ '^[0-9a-f]{64}$' THEN RETURN FALSE; END IF;
          SELECT * INTO b FROM fao.autonomy_mode_binding WHERE binding_id=p_binding AND version=p_binding_version FOR UPDATE;
          IF NOT FOUND OR b.binding_status IS DISTINCT FROM 'ACTIVE' OR b.account_id IS DISTINCT FROM p_account OR b.binding_sha256 IS NOT DISTINCT FROM p_new_binding_hash OR (p_status='EXPIRED' AND authoritative_now<b.expires_at) THEN RETURN FALSE; END IF;
          UPDATE fao.autonomy_mode_binding SET version=version+1,binding_status=p_status,state_version=state_version+1,binding_sha256=p_new_binding_hash,transition_reason=p_reason,transition_actor=p_actor,recorded_at=authoritative_now WHERE binding_id=p_binding AND version=p_binding_version;
          UPDATE fao.autonomy_gate_receipt SET receipt_status='STALE',state_version=state_version+1 WHERE receipt_status='ISSUED' AND mode_binding_id=p_binding AND mode_binding_version=p_binding_version;
          UPDATE fao.authorization_basis SET basis_status='STALE',state_version=state_version+1 WHERE basis_status='ACTIVE' AND basis_kind='MANDATE' AND source_mandate_id IS NOT DISTINCT FROM b.mandate_id AND source_mandate_version IS NOT DISTINCT FROM b.mandate_version AND account_id IS NOT DISTINCT FROM b.account_id;
          UPDATE fao.risk_budget_reservation r SET reservation_status='RELEASED',reservation_version=reservation_version+1,state_version=state_version+1,released_at=authoritative_now WHERE reservation_status='HELD' AND EXISTS (SELECT 1 FROM fao.authorization_basis z WHERE z.basis_id=r.basis_id AND z.basis_status='STALE' AND z.basis_kind='MANDATE' AND z.source_mandate_id IS NOT DISTINCT FROM b.mandate_id AND z.source_mandate_version IS NOT DISTINCT FROM b.mandate_version AND z.account_id IS NOT DISTINCT FROM b.account_id);
          RETURN TRUE;
        END $$""",
            """CREATE FUNCTION fao.claim_v014_source_event_identity(p_source UUID,p_context TEXT,p_type TEXT,p_version BIGINT,p_hash TEXT,p_occurred TIMESTAMPTZ,p_available TIMESTAMPTZ,p_correlation UUID)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE known RECORD;
        BEGIN
          IF p_source IS NULL OR p_context IS NULL OR btrim(p_context)='' OR p_type IS NULL OR btrim(p_type)='' OR p_version IS NULL OR p_version<=0 OR p_hash IS NULL OR p_hash !~ '^[0-9a-f]{64}$' OR p_occurred IS NULL OR p_available IS NULL OR p_available<p_occurred OR p_correlation IS NULL OR NOT EXISTS (SELECT 1 FROM fao.domain_event e WHERE e.event_id=p_source AND e.aggregate_type=p_context AND e.event_type=p_type AND e.aggregate_version=p_version AND e.payload_sha256=p_hash AND e.occurred_at=p_occurred AND e.recorded_at=p_available AND e.correlation_id=p_correlation) THEN RETURN FALSE; END IF;
          INSERT INTO fao.source_event_identity (source_event_id,source_context,source_type,source_version,source_sha256,occurred_at,available_at,correlation_id) VALUES (p_source,p_context,p_type,p_version,p_hash,p_occurred,p_available,p_correlation) ON CONFLICT (source_event_id) DO NOTHING;
          SELECT * INTO known FROM fao.source_event_identity WHERE source_event_id=p_source;
          RETURN known.source_context IS NOT DISTINCT FROM p_context AND known.source_type IS NOT DISTINCT FROM p_type AND known.source_version IS NOT DISTINCT FROM p_version AND known.source_sha256 IS NOT DISTINCT FROM p_hash AND known.occurred_at IS NOT DISTINCT FROM p_occurred AND known.available_at IS NOT DISTINCT FROM p_available AND known.correlation_id IS NOT DISTINCT FROM p_correlation;
        END $$""",
            """CREATE FUNCTION fao.append_decision_journal(p_journal UUID,p_journal_version BIGINT,p_entry UUID,p_source UUID,p_projection_version BIGINT,p_phase TEXT,p_context TEXT,p_type TEXT,p_source_version BIGINT,p_source_hash TEXT,p_observed TIMESTAMPTZ,p_available TIMESTAMPTZ,p_projected TIMESTAMPTZ,p_cutoff TIMESTAMPTZ,p_correlation UUID)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE header_version BIGINT;
        BEGIN
          IF p_journal IS NULL OR p_journal_version IS NULL OR p_journal_version<=0 OR p_entry IS NULL OR p_source IS NULL OR p_projection_version IS NULL OR p_projection_version IS DISTINCT FROM p_journal_version OR p_phase IS NULL OR p_phase NOT IN ('DECISION_TIME','POST_HOC') OR p_context IS NULL OR btrim(p_context)='' OR p_type IS NULL OR btrim(p_type)='' OR p_source_version IS NULL OR p_source_version<=0 OR p_source_hash IS NULL OR p_source_hash !~ '^[0-9a-f]{64}$' OR p_observed IS NULL OR p_available IS NULL OR p_projected IS NULL OR p_observed>p_available OR p_projected<p_available OR p_correlation IS NULL OR (p_phase='DECISION_TIME' AND (p_cutoff IS NULL OR p_available>p_cutoff)) THEN RETURN FALSE; END IF;
          IF NOT fao.claim_v014_source_event_identity(p_source,p_context,p_type,p_source_version,p_source_hash,p_observed,p_available,p_correlation) THEN RETURN FALSE; END IF;
          SELECT projection_version INTO header_version FROM fao.decision_journal WHERE journal_id=p_journal FOR UPDATE;
          IF NOT FOUND THEN INSERT INTO fao.decision_journal (journal_id,projection_version) VALUES (p_journal,p_journal_version); ELSIF header_version IS DISTINCT FROM p_journal_version THEN RETURN FALSE; END IF;
          INSERT INTO fao.decision_journal_entry (entry_id,journal_id,source_event_id,projection_version,phase,source_context,source_type,source_version,source_sha256,observed_at,available_at,projected_at,decision_cutoff_at,correlation_id) VALUES (p_entry,p_journal,p_source,p_projection_version,p_phase,p_context,p_type,p_source_version,p_source_hash,p_observed,p_available,p_projected,p_cutoff,p_correlation);
          RETURN TRUE;
        EXCEPTION WHEN unique_violation THEN
          RETURN EXISTS (SELECT 1 FROM fao.decision_journal_entry WHERE journal_id=p_journal AND source_event_id=p_source AND projection_version=p_projection_version AND phase=p_phase AND source_context=p_context AND source_type=p_type AND source_version=p_source_version AND source_sha256=p_source_hash AND observed_at=p_observed AND available_at=p_available AND projected_at=p_projected AND decision_cutoff_at IS NOT DISTINCT FROM p_cutoff AND correlation_id=p_correlation);
        END $$""",
            """CREATE FUNCTION fao.append_trade_episode_projection(p_episode UUID,p_projection_version BIGINT,p_decision UUID,p_source UUID,p_context TEXT,p_type TEXT,p_source_version BIGINT,p_occurred TIMESTAMPTZ,p_available TIMESTAMPTZ,p_correlation UUID,p_source_hash TEXT,p_projection_hash TEXT)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        BEGIN
          IF p_episode IS NULL OR p_projection_version IS NULL OR p_projection_version<=0 OR p_decision IS NULL OR p_source IS NULL OR p_context IS NULL OR btrim(p_context)='' OR p_type IS NULL OR btrim(p_type)='' OR p_source_version IS NULL OR p_source_version<=0 OR p_occurred IS NULL OR p_available IS NULL OR p_correlation IS NULL OR p_source_hash IS NULL OR p_source_hash !~ '^[0-9a-f]{64}$' OR p_projection_hash IS NULL OR p_projection_hash !~ '^[0-9a-f]{64}$' OR NOT fao.claim_v014_source_event_identity(p_source,p_context,p_type,p_source_version,p_source_hash,p_occurred,p_available,p_correlation) THEN RETURN FALSE; END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended(p_episode::text || ':' || p_projection_version::text, 0));
          IF EXISTS (SELECT 1 FROM fao.trade_episode_projection WHERE episode_id=p_episode AND projection_version=p_projection_version AND (decision_episode_id IS DISTINCT FROM p_decision OR projection_sha256 IS DISTINCT FROM p_projection_hash)) THEN RETURN FALSE; END IF;
          INSERT INTO fao.trade_episode_projection (episode_id,projection_version,decision_episode_id,source_event_id,source_context,source_type,source_time,correlation_id,source_sha256,projection_sha256) VALUES (p_episode,p_projection_version,p_decision,p_source,p_context,p_type,p_occurred,p_correlation,p_source_hash,p_projection_hash);
          RETURN TRUE;
        EXCEPTION WHEN unique_violation THEN
          RETURN EXISTS (SELECT 1 FROM fao.trade_episode_projection WHERE episode_id=p_episode AND projection_version=p_projection_version AND source_event_id=p_source AND decision_episode_id=p_decision AND source_context=p_context AND source_type=p_type AND source_time=p_occurred AND correlation_id=p_correlation AND source_sha256=p_source_hash AND projection_sha256=p_projection_hash);
        END $$""",
            """CREATE FUNCTION fao.reject_v014_projection_mutation() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$ BEGIN RAISE EXCEPTION 'V0-014 projections are append-only'; END $$""",
            """CREATE FUNCTION fao.assert_v014_reservation_binding() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE b RECORD; au RECORD;
        BEGIN
          SELECT * INTO b FROM fao.authorization_basis WHERE basis_id=NEW.basis_id;
          SELECT * INTO au FROM fao.risk_budget_authority WHERE account_id=NEW.account_id AND constitution_ref=NEW.risk_constitution_ref AND constitution_version=NEW.risk_constitution_version AND constitution_sha256=NEW.risk_constitution_sha256;
          IF NOT FOUND OR au IS NULL OR NEW.risk_constitution_ref IS DISTINCT FROM btrim(NEW.risk_constitution_ref) OR NEW.risk_constitution_ref ~ '[[:space:]]' OR NEW.risk_constitution_ref='' OR au.constitution_ref LIKE 'legacy://untrusted-%' OR NOT fao.v014_valid_risk_dimensions(NEW.risk_dimensions) OR NEW.basis_sha256 IS DISTINCT FROM b.basis_sha256 OR NEW.account_id IS DISTINCT FROM b.account_id OR NEW.plan_id IS DISTINCT FROM b.plan_id OR NEW.plan_version IS DISTINCT FROM b.plan_version OR NEW.plan_sha256 IS DISTINCT FROM b.plan_sha256 OR NEW.instrument_id IS DISTINCT FROM b.instrument_id OR NEW.strategy_id IS DISTINCT FROM b.strategy_id OR NEW.session_id IS DISTINCT FROM b.session_id OR NEW.quantity IS DISTINCT FROM b.authorized_quantity OR NEW.source_kind IS DISTINCT FROM b.basis_kind OR NEW.source_ref IS DISTINCT FROM COALESCE(b.source_mandate_id,b.source_approval_id) OR NEW.source_sha256 IS DISTINCT FROM b.source_sha256 THEN RAISE EXCEPTION 'reservation does not bind its authorization basis'; END IF;
          RETURN NEW;
        END $$""",
            """CREATE FUNCTION fao.assert_v014_receipt_binding() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE b RECORD; r RECORD;
        BEGIN
          SELECT * INTO b FROM fao.authorization_basis WHERE basis_id=NEW.basis_id;
          SELECT * INTO r FROM fao.risk_budget_reservation WHERE reservation_id=NEW.reservation_id;
          IF NOT FOUND OR b IS NULL OR NEW.basis_sha256 IS DISTINCT FROM b.basis_sha256 OR NEW.plan_id IS DISTINCT FROM b.plan_id OR NEW.plan_version IS DISTINCT FROM b.plan_version OR NEW.plan_sha256 IS DISTINCT FROM b.plan_sha256 OR NEW.account_id IS DISTINCT FROM b.account_id OR NEW.instrument_id IS DISTINCT FROM b.instrument_id OR NEW.strategy_id IS DISTINCT FROM b.strategy_id OR NEW.session_id IS DISTINCT FROM b.session_id OR NEW.action IS DISTINCT FROM b.authorized_action OR NEW.source_sha256 IS DISTINCT FROM b.source_sha256 OR NEW.scope_sha256 IS DISTINCT FROM b.scope_sha256 OR NEW.reservation_sha256 IS DISTINCT FROM r.reservation_sha256 OR r.account_id IS DISTINCT FROM NEW.account_id OR r.plan_id IS DISTINCT FROM NEW.plan_id OR r.plan_version IS DISTINCT FROM NEW.plan_version OR r.plan_sha256 IS DISTINCT FROM NEW.plan_sha256 OR r.instrument_id IS DISTINCT FROM NEW.instrument_id OR r.strategy_id IS DISTINCT FROM NEW.strategy_id OR r.session_id IS DISTINCT FROM NEW.session_id OR r.basis_id IS DISTINCT FROM NEW.basis_id OR r.basis_sha256 IS DISTINCT FROM NEW.basis_sha256 OR r.source_kind IS DISTINCT FROM b.basis_kind OR r.source_ref IS DISTINCT FROM COALESCE(b.source_mandate_id,b.source_approval_id) OR r.source_sha256 IS DISTINCT FROM NEW.source_sha256 OR NEW.risk_constitution_ref IS DISTINCT FROM r.risk_constitution_ref OR NEW.risk_constitution_version IS DISTINCT FROM r.risk_constitution_version OR NEW.risk_constitution_sha256 IS DISTINCT FROM r.risk_constitution_sha256 THEN RAISE EXCEPTION 'receipt does not bind basis and reservation'; END IF;
          RETURN NEW;
        END $$""",
            """CREATE FUNCTION fao.assert_v014_approval_scope() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        BEGIN
          IF NOT fao.v014_valid_scope(NEW.approval_scope,NEW.scope_account_id,TRUE) OR NEW.allowed_actions IS DISTINCT FROM NEW.approval_scope->'actions' OR (NEW.approval_scope->>'quantity_ceiling')::numeric IS DISTINCT FROM NEW.quantity_ceiling OR (NEW.approval_scope->>'window_start_at')::timestamptz IS DISTINCT FROM NEW.window_start_at OR (NEW.approval_scope->>'window_end_at')::timestamptz IS DISTINCT FROM NEW.window_end_at THEN RAISE EXCEPTION 'approval scope is not consistent with typed authority'; END IF;
          RETURN NEW;
        END $$""",
            """CREATE FUNCTION fao.assert_v014_mandate_scope() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        BEGIN
          IF NOT fao.v014_valid_scope(NEW.scope,NEW.simulation_account_id,FALSE) THEN RAISE EXCEPTION 'mandate scope is not a canonical authorization range'; END IF;
          RETURN NEW;
        END $$""",
            """CREATE FUNCTION fao.assert_v014_basis_scope() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE m RECORD; a RECORD;
        BEGIN
          IF NOT fao.v014_scope_permits(NEW.scope_snapshot,NEW.account_id,NEW.instrument_id,NEW.strategy_id,NEW.session_id,NEW.authorized_action,NEW.authorized_quantity,NEW.basis_kind='PLAN_APPROVAL') THEN RAISE EXCEPTION 'basis scope is not a canonical non-expandable authorization range'; END IF;
          IF TG_OP='INSERT' AND NEW.basis_kind='MANDATE' THEN
            SELECT * INTO m FROM fao.simulation_autonomy_mandate WHERE mandate_id=NEW.source_mandate_id AND version=NEW.source_mandate_version;
            IF NOT FOUND OR NEW.scope_snapshot IS DISTINCT FROM m.scope OR NEW.scope_sha256 IS DISTINCT FROM m.scope_sha256 OR NEW.account_id IS DISTINCT FROM m.simulation_account_id THEN RAISE EXCEPTION 'basis does not bind its mandate scope'; END IF;
          ELSIF TG_OP='INSERT' THEN
            SELECT * INTO a FROM fao.plan_approval WHERE approval_id=NEW.source_approval_id AND version IN (NEW.source_approval_version,NEW.source_approval_version+1) ORDER BY version DESC;
            IF NOT FOUND OR NEW.scope_snapshot IS DISTINCT FROM a.approval_scope OR NEW.scope_sha256 IS DISTINCT FROM a.scope_sha256 OR NEW.account_id IS DISTINCT FROM a.scope_account_id THEN RAISE EXCEPTION 'basis does not bind its approval scope'; END IF;
          END IF;
          RETURN NEW;
        END $$""",
            """CREATE FUNCTION fao.assert_v014_binding_scope() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, fao, pg_temp AS $$
        DECLARE m RECORD;
        BEGIN
          IF NEW.mode='AUTONOMOUS_SIMULATION' OR (NEW.mode='PAUSED' AND NEW.previous_mode='AUTONOMOUS_SIMULATION') THEN
            SELECT * INTO m FROM fao.simulation_autonomy_mandate WHERE mandate_id=NEW.mandate_id AND version=NEW.mandate_version;
            IF NOT FOUND OR NOT fao.v014_valid_scope(NEW.scope_snapshot,NEW.account_id,FALSE) OR NEW.scope_snapshot IS DISTINCT FROM m.scope OR NEW.scope_sha256 IS DISTINCT FROM m.scope_sha256 OR NEW.account_id IS DISTINCT FROM m.simulation_account_id THEN RAISE EXCEPTION 'binding does not bind its mandate scope'; END IF;
          END IF;
          RETURN NEW;
        END $$""",
            "CREATE TRIGGER tr_v014_journal_immutable BEFORE UPDATE OR DELETE ON fao.decision_journal FOR EACH ROW EXECUTE FUNCTION fao.reject_v014_projection_mutation()",
            "CREATE TRIGGER tr_v014_journal_entry_immutable BEFORE UPDATE OR DELETE ON fao.decision_journal_entry FOR EACH ROW EXECUTE FUNCTION fao.reject_v014_projection_mutation()",
            "CREATE TRIGGER tr_v014_episode_immutable BEFORE UPDATE OR DELETE ON fao.trade_episode_projection FOR EACH ROW EXECUTE FUNCTION fao.reject_v014_projection_mutation()",
            "CREATE TRIGGER tr_v014_reservation_binding BEFORE INSERT OR UPDATE ON fao.risk_budget_reservation FOR EACH ROW EXECUTE FUNCTION fao.assert_v014_reservation_binding()",
            "CREATE TRIGGER tr_v014_receipt_binding BEFORE INSERT OR UPDATE ON fao.autonomy_gate_receipt FOR EACH ROW EXECUTE FUNCTION fao.assert_v014_receipt_binding()",
            "CREATE TRIGGER tr_v014_approval_scope BEFORE INSERT OR UPDATE ON fao.plan_approval FOR EACH ROW EXECUTE FUNCTION fao.assert_v014_approval_scope()",
            "CREATE TRIGGER tr_v014_mandate_scope BEFORE INSERT OR UPDATE ON fao.simulation_autonomy_mandate FOR EACH ROW EXECUTE FUNCTION fao.assert_v014_mandate_scope()",
            "CREATE TRIGGER tr_v014_basis_scope BEFORE INSERT OR UPDATE ON fao.authorization_basis FOR EACH ROW EXECUTE FUNCTION fao.assert_v014_basis_scope()",
            "CREATE TRIGGER tr_v014_binding_scope BEFORE INSERT OR UPDATE ON fao.autonomy_mode_binding FOR EACH ROW EXECUTE FUNCTION fao.assert_v014_binding_scope()",
            "ALTER FUNCTION fao.consume_plan_approval(UUID,BIGINT,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,UUID,TEXT,TEXT,UUID,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.issue_mandate_basis(UUID,UUID,BIGINT,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,TEXT,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.reserve_risk_budget(UUID,TEXT,UUID,UUID,BIGINT,TEXT,TEXT,TEXT,TEXT,UUID,TEXT,TEXT,BIGINT,TEXT,JSONB,NUMERIC,NUMERIC,NUMERIC,TIMESTAMPTZ,TIMESTAMPTZ) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.issue_autonomy_gate_receipt(UUID,UUID,UUID,TEXT,UUID,TEXT,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT,UUID,BIGINT,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT,TEXT,TEXT) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.consume_autonomy_gate_receipt(UUID,UUID,TIMESTAMPTZ) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.consume_risk_budget_reservation(UUID,UUID,TIMESTAMPTZ) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.transition_simulation_autonomy_mandate(UUID,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.expire_simulation_autonomy_mandate(UUID,BIGINT,TEXT,TEXT,TEXT) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.composite_pause(UUID,BIGINT,UUID,BIGINT,UUID,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.composite_resume(UUID,BIGINT,UUID,BIGINT,UUID,TEXT,BOOLEAN,BOOLEAN,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.retire_autonomy_mode_binding(UUID,BIGINT,UUID,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.append_decision_journal(UUID,BIGINT,UUID,UUID,BIGINT,TEXT,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TIMESTAMPTZ,TIMESTAMPTZ,UUID) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.append_trade_episode_projection(UUID,BIGINT,UUID,UUID,TEXT,TEXT,BIGINT,TIMESTAMPTZ,TIMESTAMPTZ,UUID,TEXT,TEXT) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.assert_v014_reservation_binding() OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.assert_v014_receipt_binding() OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.assert_v014_approval_scope() OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.assert_v014_mandate_scope() OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.assert_v014_basis_scope() OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.assert_v014_binding_scope() OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.v014_valid_scope(JSONB,UUID,BOOLEAN) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.v014_valid_execution_fields(TEXT,TEXT,TEXT,TEXT,NUMERIC) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.v014_scope_permits(JSONB,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,BOOLEAN) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.v014_valid_risk_dimensions(JSONB) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.v014_valid_snapshot_refs(JSONB,TIMESTAMPTZ) OWNER TO fao_business_owner",
            "ALTER FUNCTION fao.claim_v014_source_event_identity(UUID,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,UUID) OWNER TO fao_business_owner",
            "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA fao FROM PUBLIC, fao_agent_worker",
            "GRANT USAGE ON SCHEMA fao TO fao_supervisor",
            "REVOKE ALL ON fao.authorization_basis, fao.risk_budget_authority, fao.risk_budget_reservation, fao.autonomy_mode_binding, fao.autonomy_health_permit, fao.autonomy_gate_receipt, fao.decision_journal, fao.decision_journal_entry, fao.trade_episode_projection, fao.source_event_identity FROM PUBLIC, fao_runtime, fao_agent_worker, fao_supervisor",
            "GRANT SELECT ON fao.authorization_basis, fao.risk_budget_authority, fao.risk_budget_reservation, fao.autonomy_mode_binding, fao.autonomy_health_permit, fao.autonomy_gate_receipt, fao.decision_journal, fao.decision_journal_entry, fao.trade_episode_projection, fao.source_event_identity TO fao_runtime",
            "GRANT EXECUTE ON FUNCTION fao.consume_autonomy_gate_receipt(UUID,UUID,TIMESTAMPTZ), fao.consume_risk_budget_reservation(UUID,UUID,TIMESTAMPTZ), fao.retire_autonomy_mode_binding(UUID,BIGINT,UUID,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT), fao.expire_simulation_autonomy_mandate(UUID,BIGINT,TEXT,TEXT,TEXT), fao.append_decision_journal(UUID,BIGINT,UUID,UUID,BIGINT,TEXT,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TIMESTAMPTZ,TIMESTAMPTZ,UUID), fao.append_trade_episode_projection(UUID,BIGINT,UUID,UUID,TEXT,TEXT,BIGINT,TIMESTAMPTZ,TIMESTAMPTZ,UUID,TEXT,TEXT) TO fao_runtime",
            "GRANT EXECUTE ON FUNCTION fao.issue_mandate_basis(UUID,UUID,BIGINT,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,TEXT,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT), fao.reserve_risk_budget(UUID,TEXT,UUID,UUID,BIGINT,TEXT,TEXT,TEXT,TEXT,UUID,TEXT,TEXT,BIGINT,TEXT,JSONB,NUMERIC,NUMERIC,NUMERIC,TIMESTAMPTZ,TIMESTAMPTZ), fao.issue_autonomy_gate_receipt(UUID,UUID,UUID,TEXT,UUID,TEXT,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT,UUID,BIGINT,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT,TEXT,TEXT) TO fao_runtime",
            "GRANT EXECUTE ON FUNCTION fao.consume_plan_approval(UUID,BIGINT,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,UUID,TEXT,TEXT,UUID,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT), fao.composite_pause(UUID,BIGINT,UUID,BIGINT,UUID,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT), fao.composite_resume(UUID,BIGINT,UUID,BIGINT,UUID,TEXT,BOOLEAN,BOOLEAN,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT), fao.transition_simulation_autonomy_mandate(UUID,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT) TO fao_supervisor",
            "GRANT EXECUTE ON FUNCTION fao.issue_mandate_basis(UUID,UUID,BIGINT,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,TEXT,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT), fao.consume_autonomy_gate_receipt(UUID,UUID,TIMESTAMPTZ), fao.consume_risk_budget_reservation(UUID,UUID,TIMESTAMPTZ) TO fao_supervisor",
            "RESET ROLE",
        )
    )


def downgrade() -> None:
    _execute(
        (
            "SET ROLE fao_business_owner",
            "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA fao FROM fao_runtime",
            "REVOKE SELECT ON fao.authorization_basis, fao.risk_budget_authority, fao.risk_budget_reservation, fao.autonomy_mode_binding, fao.autonomy_health_permit, fao.autonomy_gate_receipt, fao.decision_journal, fao.decision_journal_entry, fao.trade_episode_projection, fao.source_event_identity FROM fao_runtime",
            "ALTER TABLE fao.risk_budget_authority DROP CONSTRAINT IF EXISTS ck_v014_authority_constitution_ref, ADD CONSTRAINT risk_budget_authority_constitution_ref_check CHECK (constitution_ref=btrim(constitution_ref) AND constitution_ref !~ '[[:space:]]' AND constitution_ref<>'')",
            "ALTER TABLE fao.risk_budget_reservation DROP CONSTRAINT IF EXISTS ck_v014_reservation_constitution_ref, ADD CONSTRAINT risk_budget_reservation_risk_constitution_ref_check CHECK (risk_constitution_ref=btrim(risk_constitution_ref) AND risk_constitution_ref !~ '[[:space:]]' AND risk_constitution_ref<>'')",
            "ALTER TABLE fao.autonomy_gate_receipt DROP CONSTRAINT IF EXISTS ck_v014_receipt_constitution_ref, ADD CONSTRAINT autonomy_gate_receipt_risk_constitution_ref_check CHECK (risk_constitution_ref=btrim(risk_constitution_ref) AND risk_constitution_ref !~ '[[:space:]]' AND risk_constitution_ref<>'')",
            # Restore the preceding revision's accepted union so a downgrade
            # is a faithful schema snapshot.  All rows written by this
            # revision have already been canonicalised to RELEASED.
            "ALTER TABLE fao.risk_budget_reservation DROP CONSTRAINT IF EXISTS ck_v014_reservation_status",
            "ALTER TABLE fao.risk_budget_reservation ADD CONSTRAINT ck_v014_reservation_status CHECK (reservation_status IN ('HELD','CONSUMED','RELEASED','EXPIRED','REPLACED','RECONCILED'))",
            "DROP TRIGGER IF EXISTS tr_v014_binding_scope ON fao.autonomy_mode_binding",
            "DROP TRIGGER IF EXISTS tr_v014_basis_scope ON fao.authorization_basis",
            "DROP TRIGGER IF EXISTS tr_v014_mandate_scope ON fao.simulation_autonomy_mandate",
            "DROP TRIGGER IF EXISTS tr_v014_receipt_binding ON fao.autonomy_gate_receipt",
            "DROP TRIGGER IF EXISTS tr_v014_approval_scope ON fao.plan_approval",
            "DROP TRIGGER IF EXISTS tr_v014_reservation_binding ON fao.risk_budget_reservation",
            "DROP TRIGGER IF EXISTS tr_v014_episode_immutable ON fao.trade_episode_projection",
            "DROP TRIGGER IF EXISTS tr_v014_journal_entry_immutable ON fao.decision_journal_entry",
            "DROP TRIGGER IF EXISTS tr_v014_journal_immutable ON fao.decision_journal",
            "DROP FUNCTION IF EXISTS fao.reject_v014_projection_mutation()",
            "DROP FUNCTION IF EXISTS fao.assert_v014_receipt_binding()",
            "DROP FUNCTION IF EXISTS fao.assert_v014_reservation_binding()",
            "DROP FUNCTION IF EXISTS fao.assert_v014_approval_scope()",
            "DROP FUNCTION IF EXISTS fao.assert_v014_binding_scope()",
            "DROP FUNCTION IF EXISTS fao.assert_v014_basis_scope()",
            "DROP FUNCTION IF EXISTS fao.assert_v014_mandate_scope()",
            "DROP FUNCTION IF EXISTS fao.v014_scope_permits(JSONB,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,BOOLEAN)",
            "DROP FUNCTION IF EXISTS fao.v014_valid_risk_dimensions(JSONB)",
            "DROP FUNCTION IF EXISTS fao.v014_valid_snapshot_refs(JSONB,TIMESTAMPTZ)",
            "DROP FUNCTION IF EXISTS fao.v014_valid_execution_fields(TEXT,TEXT,TEXT,TEXT,NUMERIC)",
            "DROP FUNCTION IF EXISTS fao.v014_valid_scope(JSONB,UUID,BOOLEAN)",
            "DROP FUNCTION IF EXISTS fao.append_trade_episode_projection(UUID,BIGINT,UUID,UUID,TEXT,TEXT,BIGINT,TIMESTAMPTZ,TIMESTAMPTZ,UUID,TEXT,TEXT)",
            "DROP FUNCTION IF EXISTS fao.append_decision_journal(UUID,BIGINT,UUID,UUID,BIGINT,TEXT,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TIMESTAMPTZ,TIMESTAMPTZ,UUID)",
            "DROP FUNCTION IF EXISTS fao.claim_v014_source_event_identity(UUID,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,UUID)",
            "DROP FUNCTION IF EXISTS fao.expire_simulation_autonomy_mandate(UUID,BIGINT,TEXT,TEXT,TEXT)",
            "DROP FUNCTION IF EXISTS fao.transition_simulation_autonomy_mandate(UUID,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT)",
            "DROP FUNCTION IF EXISTS fao.composite_resume(UUID,BIGINT,UUID,BIGINT,UUID,TEXT,BOOLEAN,BOOLEAN,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT)",
            "DROP FUNCTION IF EXISTS fao.retire_autonomy_mode_binding(UUID,BIGINT,UUID,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT)",
            "DROP FUNCTION IF EXISTS fao.composite_pause(UUID,BIGINT,UUID,BIGINT,UUID,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT)",
            "DROP FUNCTION IF EXISTS fao.consume_risk_budget_reservation(UUID,UUID,TIMESTAMPTZ)",
            "DROP FUNCTION IF EXISTS fao.consume_autonomy_gate_receipt(UUID,UUID,TIMESTAMPTZ)",
            "DROP FUNCTION IF EXISTS fao.issue_autonomy_gate_receipt(UUID,UUID,UUID,TEXT,UUID,TEXT,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT,UUID,BIGINT,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT,TEXT,TEXT)",
            "DROP FUNCTION IF EXISTS fao.reserve_risk_budget(UUID,TEXT,UUID,UUID,BIGINT,TEXT,TEXT,TEXT,TEXT,UUID,TEXT,TEXT,BIGINT,TEXT,JSONB,NUMERIC,NUMERIC,NUMERIC,TIMESTAMPTZ,TIMESTAMPTZ)",
            "DROP FUNCTION IF EXISTS fao.issue_mandate_basis(UUID,UUID,BIGINT,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,TEXT,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT)",
            "DROP FUNCTION IF EXISTS fao.consume_plan_approval(UUID,BIGINT,UUID,BIGINT,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,NUMERIC,UUID,TEXT,TEXT,UUID,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT)",
            "RESET ROLE",
        )
    )
