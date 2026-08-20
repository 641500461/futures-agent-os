"""Create V0-014 durable autonomy facts with fail-closed SQL unions."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "0003_v0_014"
down_revision: str | Sequence[str] | None = "0002_v0_010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HASH = "^[0-9a-f]{64}$"


def _execute(statements: tuple[str, ...]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    # V0-007 rows do not carry typed authorization.  Preserve the audit row,
    # but expire it rather than inventing an account, token or human decision.
    _execute(
        (
            "SET ROLE fao_business_owner",
            "ALTER TABLE fao.simulation_autonomy_mandate ADD COLUMN IF NOT EXISTS state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version > 0), ADD COLUMN IF NOT EXISTS authority_sha256 TEXT, ADD COLUMN IF NOT EXISTS revocation_reason TEXT, ADD COLUMN IF NOT EXISTS notification_policy_ref TEXT, ADD COLUMN IF NOT EXISTS escalation_policy_ref TEXT, ADD COLUMN IF NOT EXISTS last_transition_reason TEXT, ADD COLUMN IF NOT EXISTS evidence_ref TEXT, ADD COLUMN IF NOT EXISTS transitioned_at TIMESTAMPTZ",
            "UPDATE fao.simulation_autonomy_mandate SET status='EXPIRED' WHERE status NOT IN ('DRAFT','VALIDATED','APPROVED','ACTIVE','SUSPENDED','EXPIRED','REVOKED','HALTED','RECOVERING') OR authority_sha256 IS NULL",
            "UPDATE fao.simulation_autonomy_mandate SET status='EXPIRED', expires_at=created_at + INTERVAL '1 microsecond' WHERE expires_at<=created_at",
            "UPDATE fao.simulation_autonomy_mandate SET authority_sha256=lower(md5(mandate_id::text || '_legacy-a') || md5(mandate_id::text || '_legacy-b')) WHERE authority_sha256 IS NULL",
            "UPDATE fao.simulation_autonomy_mandate SET status='EXPIRED', risk_policy_ref=CASE WHEN risk_policy_ref IS NULL OR risk_policy_ref IS DISTINCT FROM btrim(risk_policy_ref) OR risk_policy_ref ~ '[[:space:]]' OR risk_policy_ref='' THEN 'legacy://untrusted-risk-policy' ELSE risk_policy_ref END, notification_policy_ref=CASE WHEN notification_policy_ref IS NULL OR notification_policy_ref IS DISTINCT FROM btrim(notification_policy_ref) OR notification_policy_ref ~ '[[:space:]]' OR notification_policy_ref='' THEN 'legacy://expired-notification' ELSE notification_policy_ref END, escalation_policy_ref=CASE WHEN escalation_policy_ref IS NULL OR escalation_policy_ref IS DISTINCT FROM btrim(escalation_policy_ref) OR escalation_policy_ref ~ '[[:space:]]' OR escalation_policy_ref='' THEN 'legacy://expired-escalation' ELSE escalation_policy_ref END WHERE risk_policy_ref IS NULL OR risk_policy_ref IS DISTINCT FROM btrim(risk_policy_ref) OR risk_policy_ref ~ '[[:space:]]' OR risk_policy_ref='' OR notification_policy_ref IS NULL OR notification_policy_ref IS DISTINCT FROM btrim(notification_policy_ref) OR notification_policy_ref ~ '[[:space:]]' OR notification_policy_ref='' OR escalation_policy_ref IS NULL OR escalation_policy_ref IS DISTINCT FROM btrim(escalation_policy_ref) OR escalation_policy_ref ~ '[[:space:]]' OR escalation_policy_ref=''",
            "UPDATE fao.simulation_autonomy_mandate SET last_transition_reason=COALESCE(last_transition_reason, 'LEGACY_FAIL_CLOSED'), evidence_ref=COALESCE(evidence_ref, 'evidence://legacy-migration'), transitioned_at=COALESCE(transitioned_at, created_at)",
            "ALTER TABLE fao.simulation_autonomy_mandate ALTER COLUMN last_transition_reason SET DEFAULT 'INITIAL_RECORD', ALTER COLUMN evidence_ref SET DEFAULT 'evidence://initial-record', ALTER COLUMN transitioned_at SET DEFAULT CURRENT_TIMESTAMP",
            f"ALTER TABLE fao.simulation_autonomy_mandate ADD CONSTRAINT ck_v014_mandate_status CHECK (status IN ('DRAFT','VALIDATED','APPROVED','ACTIVE','SUSPENDED','EXPIRED','REVOKED','HALTED','RECOVERING')), ADD CONSTRAINT ck_v014_mandate_hash CHECK (authority_sha256 ~ '{_HASH}'), ADD CONSTRAINT ck_v014_mandate_expiry CHECK (expires_at > created_at), ADD CONSTRAINT ck_v014_mandate_revocation CHECK (status <> 'REVOKED' OR revocation_reason IS NOT NULL), ADD CONSTRAINT ck_v014_mandate_risk_ref CHECK (risk_policy_ref=btrim(risk_policy_ref) AND risk_policy_ref !~ '[[:space:]]' AND risk_policy_ref<>''), ADD CONSTRAINT ck_v014_mandate_transition_audit CHECK (btrim(last_transition_reason)<>'' AND btrim(evidence_ref)<>'' AND transitioned_at IS NOT NULL), ADD CONSTRAINT ck_v014_mandate_notification_ref CHECK (notification_policy_ref=btrim(notification_policy_ref) AND notification_policy_ref !~ '[[:space:]]' AND notification_policy_ref<>''), ADD CONSTRAINT ck_v014_mandate_escalation_ref CHECK (escalation_policy_ref=btrim(escalation_policy_ref) AND escalation_policy_ref !~ '[[:space:]]' AND escalation_policy_ref<>''), ADD CONSTRAINT ck_v014_mandate_active_refs CHECK (status IN ('DRAFT','EXPIRED') OR (notification_policy_ref NOT LIKE 'legacy://%' AND escalation_policy_ref NOT LIKE 'legacy://%'))",
            "ALTER TABLE fao.simulation_autonomy_mandate ALTER COLUMN authority_sha256 SET NOT NULL, ALTER COLUMN notification_policy_ref SET NOT NULL, ALTER COLUMN escalation_policy_ref SET NOT NULL, ALTER COLUMN last_transition_reason SET NOT NULL, ALTER COLUMN evidence_ref SET NOT NULL, ALTER COLUMN transitioned_at SET NOT NULL",
            "ALTER TABLE fao.plan_approval ADD COLUMN IF NOT EXISTS requested_by TEXT, ADD COLUMN IF NOT EXISTS consumed_basis_id UUID, ADD COLUMN IF NOT EXISTS consumed_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS approval_hash TEXT, ADD COLUMN IF NOT EXISTS state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version > 0), ADD COLUMN IF NOT EXISTS approval_token UUID, ADD COLUMN IF NOT EXISTS scope_sha256 TEXT, ADD COLUMN IF NOT EXISTS scope_account_id UUID, ADD COLUMN IF NOT EXISTS allowed_actions JSONB, ADD COLUMN IF NOT EXISTS quantity_ceiling NUMERIC, ADD COLUMN IF NOT EXISTS window_start_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS window_end_at TIMESTAMPTZ",
            "UPDATE fao.plan_approval SET status='EXPIRED' WHERE status NOT IN ('REQUESTED','GRANTED','REJECTED','EXPIRED','CONSUMED') OR status IN ('REQUESTED','GRANTED','CONSUMED')",
            "UPDATE fao.plan_approval SET status='EXPIRED', expires_at=requested_at + INTERVAL '1 microsecond' WHERE expires_at<=requested_at",
            "UPDATE fao.plan_approval SET status='EXPIRED' WHERE status='REJECTED' AND (decided_at IS NULL OR decided_by IS NULL)",
            "UPDATE fao.plan_approval SET requested_by=COALESCE(requested_by, decided_by, 'legacy_migration'), approval_hash=COALESCE(approval_hash, lower(md5(approval_id::text || '_legacy-a') || md5(approval_id::text || '_legacy-b'))), scope_sha256=COALESCE(scope_sha256, lower(md5(approval_id::text || '_scope-a') || md5(approval_id::text || '_scope-b'))), scope_account_id=COALESCE(scope_account_id, '00000000-0000-0000-0000-000000000000'::uuid), allowed_actions=COALESCE(allowed_actions, jsonb_build_array('OPEN')), quantity_ceiling=COALESCE(quantity_ceiling, 1), window_start_at=COALESCE(window_start_at, requested_at), window_end_at=COALESCE(window_end_at, expires_at), approval_token=COALESCE(approval_token, (substr(md5(approval_id::text || '_token'),1,8)||'-'||substr(md5(approval_id::text || '_token'),9,4)||'-'||substr(md5(approval_id::text || '_token'),13,4)||'-'||substr(md5(approval_id::text || '_token'),17,4)||'-'||substr(md5(approval_id::text || '_token'),21,12))::uuid)",
            "UPDATE fao.plan_approval SET quantity_ceiling=1 WHERE quantity_ceiling IS NULL OR quantity_ceiling <= 0 OR quantity_ceiling IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
            "ALTER TABLE fao.plan_approval ALTER COLUMN requested_by SET NOT NULL, ALTER COLUMN approval_hash SET NOT NULL, ALTER COLUMN approval_token SET NOT NULL, ALTER COLUMN scope_sha256 SET NOT NULL, ALTER COLUMN scope_account_id SET NOT NULL, ALTER COLUMN allowed_actions SET NOT NULL, ALTER COLUMN quantity_ceiling SET NOT NULL, ALTER COLUMN window_start_at SET NOT NULL, ALTER COLUMN window_end_at SET NOT NULL",
            f"ALTER TABLE fao.plan_approval ADD CONSTRAINT ck_v014_approval_status CHECK (status IN ('REQUESTED','GRANTED','REJECTED','EXPIRED','CONSUMED')), ADD CONSTRAINT ck_v014_approval_hash CHECK (approval_hash ~ '{_HASH}' AND scope_sha256 ~ '{_HASH}'), ADD CONSTRAINT ck_v014_approval_actions CHECK (jsonb_typeof(allowed_actions)='array' AND jsonb_array_length(allowed_actions)>0), ADD CONSTRAINT ck_v014_approval_quantity CHECK (quantity_ceiling > 0 AND quantity_ceiling NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)), ADD CONSTRAINT ck_v014_approval_window CHECK (window_end_at > window_start_at), ADD CONSTRAINT ck_v014_approval_decision CHECK ((status IN ('GRANTED','REJECTED','CONSUMED') AND decided_at IS NOT NULL AND decided_by IS NOT NULL) OR status IN ('REQUESTED','EXPIRED')), ADD CONSTRAINT ck_v014_approval_consumption CHECK ((status='CONSUMED' AND consumed_basis_id IS NOT NULL AND consumed_at IS NOT NULL) OR (status <> 'CONSUMED' AND consumed_basis_id IS NULL AND consumed_at IS NULL)), ADD CONSTRAINT uq_v014_approval_consumed_basis UNIQUE (consumed_basis_id), ADD CONSTRAINT uq_v014_approval_token UNIQUE (approval_token)",
            """CREATE TABLE fao.authorization_basis (
            basis_id UUID PRIMARY KEY, state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version > 0),
            basis_kind TEXT NOT NULL CHECK (basis_kind IN ('MANDATE','PLAN_APPROVAL')),
            basis_status TEXT NOT NULL CHECK (basis_status IN ('ACTIVE','STALE','EXPIRED','CONSUMED')),
            basis_sha256 TEXT NOT NULL CHECK (basis_sha256 ~ '^[0-9a-f]{64}$'),
            plan_id UUID NOT NULL, plan_version BIGINT NOT NULL CHECK (plan_version > 0), plan_sha256 TEXT NOT NULL CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'), account_id UUID NOT NULL,
            instrument_id TEXT NOT NULL CHECK (btrim(instrument_id)<>''), strategy_id TEXT NOT NULL CHECK (btrim(strategy_id)<>''), session_id TEXT NOT NULL CHECK (btrim(session_id)<>''),
            authorized_action TEXT NOT NULL CHECK (authorized_action IN ('OPEN','REDUCE','CLOSE')), authorized_quantity NUMERIC NOT NULL CHECK (authorized_quantity > 0 AND authorized_quantity NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)), window_start_at TIMESTAMPTZ, window_end_at TIMESTAMPTZ, approval_token UUID,
            source_mandate_id UUID, source_mandate_version BIGINT, source_approval_id UUID, source_approval_version BIGINT,
            source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'), scope_snapshot JSONB NOT NULL CHECK (jsonb_typeof(scope_snapshot)='object'), scope_sha256 TEXT NOT NULL CHECK (scope_sha256 ~ '^[0-9a-f]{64}$'),
            issued_by TEXT NOT NULL, actor_audit_ref TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (source_approval_id), UNIQUE (source_mandate_id, source_mandate_version, plan_id, plan_version, basis_kind), CHECK (expires_at > created_at),
            CHECK ((basis_kind='MANDATE' AND source_mandate_id IS NOT NULL AND source_mandate_version > 0 AND source_approval_id IS NULL AND source_approval_version IS NULL AND approval_token IS NULL AND window_start_at IS NULL AND window_end_at IS NULL)
                OR (basis_kind='PLAN_APPROVAL' AND source_approval_id IS NOT NULL AND source_approval_version > 0 AND source_mandate_id IS NULL AND source_mandate_version IS NULL AND approval_token IS NOT NULL AND window_start_at IS NOT NULL AND window_end_at IS NOT NULL AND window_end_at > window_start_at))
        )""",
            """CREATE TABLE fao.risk_budget_authority (
            account_id UUID PRIMARY KEY, constitution_ref TEXT NOT NULL CHECK (constitution_ref=btrim(constitution_ref) AND constitution_ref !~ '[[:space:]]' AND constitution_ref<>''), constitution_version BIGINT NOT NULL CHECK (constitution_version > 0),
            constitution_sha256 TEXT NOT NULL CHECK (constitution_sha256 ~ '^[0-9a-f]{64}$'), ceiling NUMERIC NOT NULL CHECK (ceiling >= 0 AND ceiling NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)),
            state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version > 0), updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (account_id, constitution_ref, constitution_version, constitution_sha256)
        )""",
            """CREATE TABLE fao.risk_budget_reservation (
            reservation_id UUID PRIMARY KEY, reservation_version BIGINT NOT NULL CHECK (reservation_version > 0), state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version > 0),
            reservation_status TEXT NOT NULL CONSTRAINT ck_v014_reservation_status CHECK (reservation_status IN ('HELD','CONSUMED','RELEASED','EXPIRED','RECONCILED')),
            reservation_sha256 TEXT NOT NULL CHECK (reservation_sha256 ~ '^[0-9a-f]{64}$'), account_id UUID NOT NULL, plan_id UUID NOT NULL, plan_version BIGINT NOT NULL CHECK (plan_version > 0), plan_sha256 TEXT NOT NULL CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
            basis_id UUID NOT NULL REFERENCES fao.authorization_basis(basis_id), basis_sha256 TEXT NOT NULL CHECK (basis_sha256 ~ '^[0-9a-f]{64}$'),
            risk_constitution_ref TEXT NOT NULL CHECK (risk_constitution_ref=btrim(risk_constitution_ref) AND risk_constitution_ref !~ '[[:space:]]' AND risk_constitution_ref<>''), risk_constitution_version BIGINT NOT NULL CHECK (risk_constitution_version > 0), risk_constitution_sha256 TEXT NOT NULL CHECK (risk_constitution_sha256 ~ '^[0-9a-f]{64}$'),
            instrument_id TEXT NOT NULL CHECK (btrim(instrument_id)<>''), strategy_id TEXT NOT NULL CHECK (btrim(strategy_id)<>''), session_id TEXT NOT NULL CHECK (btrim(session_id)<>''),
            risk_dimensions JSONB NOT NULL CHECK (jsonb_typeof(risk_dimensions)='object'), quantity NUMERIC NOT NULL CHECK (quantity > 0 AND quantity NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)), worst_case_loss NUMERIC NOT NULL CHECK (worst_case_loss >= 0 AND worst_case_loss NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)), margin NUMERIC NOT NULL CHECK (margin >= 0 AND margin NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)),
            source_kind TEXT NOT NULL CHECK (source_kind IN ('MANDATE','PLAN_APPROVAL')), source_ref UUID NOT NULL, source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
            expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, released_at TIMESTAMPTZ, consumed_at TIMESTAMPTZ,
            UNIQUE (plan_id, plan_version, basis_id), CHECK (expires_at > created_at), CHECK ((reservation_status='RELEASED' AND released_at IS NOT NULL) OR reservation_status <> 'RELEASED'), CHECK ((reservation_status='CONSUMED' AND consumed_at IS NOT NULL) OR reservation_status <> 'CONSUMED')
        )""",
            """CREATE TABLE fao.autonomy_mode_binding (
            binding_id UUID NOT NULL, version BIGINT NOT NULL CHECK (version > 0), state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version > 0),
            mode TEXT NOT NULL CHECK (mode IN ('OBSERVE','SHADOW','AUTONOMOUS_SIMULATION','PAUSED')), binding_status TEXT NOT NULL CHECK (binding_status IN ('ACTIVE','EXPIRED','SUPERSEDED')),
            account_id UUID, mandate_id UUID, mandate_version BIGINT, run_versions_sha256 TEXT NOT NULL CHECK (run_versions_sha256 ~ '^[0-9a-f]{64}$'), binding_sha256 TEXT NOT NULL CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
            scope_snapshot JSONB NOT NULL CHECK (jsonb_typeof(scope_snapshot)='object'), scope_sha256 TEXT NOT NULL CHECK (scope_sha256 ~ '^[0-9a-f]{64}$'), qualified_artifact_ref TEXT,
            previous_mode TEXT, transition_reason TEXT NOT NULL DEFAULT 'INITIAL_BINDING', transition_actor TEXT NOT NULL DEFAULT 'service:binding-bootstrap', evidence_ref TEXT NOT NULL DEFAULT 'evidence://binding-bootstrap', expires_at TIMESTAMPTZ NOT NULL, recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            scan_policy_ref TEXT NOT NULL DEFAULT 'policy://scan/bootstrap', universe_policy_ref TEXT NOT NULL DEFAULT 'policy://universe/bootstrap',
            PRIMARY KEY (binding_id, version), CONSTRAINT ck_v014_binding_temporal CHECK ((binding_status='ACTIVE' AND expires_at>recorded_at) OR (binding_status='EXPIRED' AND recorded_at>=expires_at) OR (binding_status='SUPERSEDED' AND recorded_at<expires_at)),
            CONSTRAINT ck_v014_binding_refs CHECK (btrim(scan_policy_ref)<>'' AND btrim(universe_policy_ref)<>'' AND btrim(transition_reason)<>'' AND transition_actor ~ '^(user|service|system):[^[:space:]]+$' AND btrim(evidence_ref)<>''),
            CONSTRAINT ck_v014_binding_qualified_artifact_ref CHECK (qualified_artifact_ref IS NULL OR (qualified_artifact_ref=btrim(qualified_artifact_ref) AND qualified_artifact_ref !~ '[[:space:]]' AND qualified_artifact_ref<>'')),
            CHECK ((mode='OBSERVE' AND mandate_id IS NULL AND mandate_version IS NULL AND previous_mode IS NULL)
                OR (mode='SHADOW' AND account_id IS NOT NULL AND mandate_id IS NULL AND mandate_version IS NULL AND previous_mode IS NULL)
                OR (mode='AUTONOMOUS_SIMULATION' AND account_id IS NOT NULL AND mandate_id IS NOT NULL AND mandate_version > 0 AND previous_mode IS NULL AND qualified_artifact_ref IS NOT NULL)
                OR (mode='PAUSED' AND previous_mode IN ('OBSERVE','SHADOW','AUTONOMOUS_SIMULATION') AND ((previous_mode='OBSERVE' AND mandate_id IS NULL AND mandate_version IS NULL) OR (previous_mode='SHADOW' AND account_id IS NOT NULL AND mandate_id IS NULL AND mandate_version IS NULL) OR (previous_mode='AUTONOMOUS_SIMULATION' AND account_id IS NOT NULL AND mandate_id IS NOT NULL AND mandate_version > 0))))
        )""",
            "ALTER TABLE fao.autonomy_mode_binding ALTER COLUMN scan_policy_ref SET DEFAULT 'policy://scan/bootstrap', ALTER COLUMN universe_policy_ref SET DEFAULT 'policy://universe/bootstrap', ALTER COLUMN transition_reason SET DEFAULT 'INITIAL_BINDING', ALTER COLUMN transition_actor SET DEFAULT 'service:binding-bootstrap', ALTER COLUMN evidence_ref SET DEFAULT 'evidence://binding-bootstrap'",
            """CREATE TABLE fao.autonomy_health_permit (
            account_id UUID PRIMARY KEY, environment_policy_ref TEXT NOT NULL CHECK (btrim(environment_policy_ref)<>''), permits BOOLEAN NOT NULL,
            valid_until_at TIMESTAMPTZ NOT NULL, state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version > 0), recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (valid_until_at > recorded_at)
        )""",
            """CREATE TABLE fao.autonomy_gate_receipt (
            receipt_id UUID PRIMARY KEY, state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version > 0), receipt_status TEXT NOT NULL CHECK (receipt_status IN ('ISSUED','CONSUMED','STALE','EXPIRED')),
            nonce UUID NOT NULL UNIQUE, basis_id UUID NOT NULL UNIQUE REFERENCES fao.authorization_basis(basis_id), basis_sha256 TEXT NOT NULL CHECK (basis_sha256 ~ '^[0-9a-f]{64}$'),
            plan_id UUID NOT NULL, plan_version BIGINT NOT NULL CHECK (plan_version > 0), plan_sha256 TEXT NOT NULL CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'), account_id UUID NOT NULL, instrument_id TEXT NOT NULL CHECK (btrim(instrument_id)<>''), strategy_id TEXT NOT NULL CHECK (btrim(strategy_id)<>''), session_id TEXT NOT NULL CHECK (btrim(session_id)<>''), action TEXT NOT NULL CHECK (action IN ('OPEN','REDUCE','CLOSE')), execution_origin TEXT NOT NULL CHECK (execution_origin IN ('AUTONOMOUS_AGENT','MANUAL_TEST')),
            source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'), scope_sha256 TEXT NOT NULL CHECK (scope_sha256 ~ '^[0-9a-f]{64}$'), reservation_id UUID NOT NULL REFERENCES fao.risk_budget_reservation(reservation_id), reservation_sha256 TEXT NOT NULL CHECK (reservation_sha256 ~ '^[0-9a-f]{64}$'),
            risk_constitution_ref TEXT NOT NULL CHECK (risk_constitution_ref=btrim(risk_constitution_ref) AND risk_constitution_ref !~ '[[:space:]]' AND risk_constitution_ref<>''), risk_constitution_version BIGINT NOT NULL CHECK (risk_constitution_version > 0), risk_constitution_sha256 TEXT NOT NULL CHECK (risk_constitution_sha256 ~ '^[0-9a-f]{64}$'),
            snapshot_refs JSONB NOT NULL CHECK (jsonb_typeof(snapshot_refs)='object'), snapshot_sha256 TEXT NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'), run_versions_sha256 TEXT NOT NULL CHECK (run_versions_sha256 ~ '^[0-9a-f]{64}$'),
            mode_binding_id UUID, mode_binding_version BIGINT, mode_binding_sha256 TEXT, issued_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, expires_at TIMESTAMPTZ NOT NULL, issued_by TEXT NOT NULL, manual_actor_ref TEXT, environment_policy_ref TEXT NOT NULL, consumed_at TIMESTAMPTZ,
            CHECK (expires_at > issued_at), CHECK ((execution_origin='AUTONOMOUS_AGENT' AND mode_binding_id IS NOT NULL AND mode_binding_version > 0 AND mode_binding_sha256 ~ '^[0-9a-f]{64}$' AND manual_actor_ref IS NULL) OR (execution_origin='MANUAL_TEST' AND mode_binding_id IS NULL AND mode_binding_version IS NULL AND mode_binding_sha256 IS NULL AND manual_actor_ref IS NOT NULL))
        )""",
            """CREATE TABLE fao.decision_journal (journal_id UUID PRIMARY KEY, projection_version BIGINT NOT NULL CHECK (projection_version > 0), created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE fao.source_event_identity (
            source_event_id UUID PRIMARY KEY, source_context TEXT NOT NULL, source_type TEXT NOT NULL, source_version BIGINT NOT NULL CHECK (source_version > 0), source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'), occurred_at TIMESTAMPTZ NOT NULL, available_at TIMESTAMPTZ NOT NULL, correlation_id UUID NOT NULL, first_claimed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (available_at >= occurred_at)
        )""",
            """CREATE TABLE fao.decision_journal_entry (
            entry_id UUID PRIMARY KEY, journal_id UUID NOT NULL REFERENCES fao.decision_journal(journal_id), source_event_id UUID NOT NULL, projection_version BIGINT NOT NULL CHECK (projection_version > 0), phase TEXT NOT NULL CHECK (phase IN ('DECISION_TIME','POST_HOC')),
            source_context TEXT NOT NULL, source_type TEXT NOT NULL, source_version BIGINT NOT NULL CHECK (source_version > 0), source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'), observed_at TIMESTAMPTZ NOT NULL, available_at TIMESTAMPTZ NOT NULL, projected_at TIMESTAMPTZ NOT NULL, decision_cutoff_at TIMESTAMPTZ, correlation_id UUID NOT NULL,
            UNIQUE (journal_id, source_event_id, projection_version), CHECK (projected_at >= available_at), CHECK ((phase='DECISION_TIME' AND decision_cutoff_at IS NOT NULL AND available_at <= decision_cutoff_at) OR phase='POST_HOC')
        )""",
            """CREATE TABLE fao.trade_episode_projection (
            episode_id UUID NOT NULL, projection_version BIGINT NOT NULL CHECK (projection_version > 0), decision_episode_id UUID NOT NULL, source_event_id UUID NOT NULL, source_context TEXT NOT NULL, source_type TEXT NOT NULL, source_time TIMESTAMPTZ NOT NULL, correlation_id UUID NOT NULL, source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'), projection_sha256 TEXT NOT NULL CHECK (projection_sha256 ~ '^[0-9a-f]{64}$'), PRIMARY KEY (episode_id, projection_version, source_event_id)
        )""",
            "CREATE INDEX ix_v014_receipt_active ON fao.autonomy_gate_receipt (receipt_status, expires_at)",
            "CREATE INDEX ix_v014_reservation_active ON fao.risk_budget_reservation (reservation_status, expires_at)",
            "REVOKE ALL ON fao.authorization_basis, fao.risk_budget_authority, fao.risk_budget_reservation, fao.autonomy_mode_binding, fao.autonomy_health_permit, fao.autonomy_gate_receipt, fao.decision_journal, fao.decision_journal_entry, fao.trade_episode_projection, fao.source_event_identity FROM PUBLIC, fao_runtime, fao_agent_worker",
            "RESET ROLE",
        )
    )


def downgrade() -> None:
    _execute(
        (
            "SET ROLE fao_business_owner",
            "DROP TABLE IF EXISTS fao.trade_episode_projection",
            "DROP TABLE IF EXISTS fao.decision_journal_entry",
            "DROP TABLE IF EXISTS fao.decision_journal",
            "DROP TABLE IF EXISTS fao.autonomy_gate_receipt",
            "DROP TABLE IF EXISTS fao.autonomy_mode_binding",
            "DROP TABLE IF EXISTS fao.risk_budget_reservation",
            "DROP TABLE IF EXISTS fao.risk_budget_authority",
            "DROP TABLE IF EXISTS fao.authorization_basis",
            "DROP TABLE IF EXISTS fao.source_event_identity",
            "DROP TABLE IF EXISTS fao.autonomy_health_permit",
            "ALTER TABLE fao.simulation_autonomy_mandate DROP CONSTRAINT IF EXISTS ck_v014_mandate_status, DROP CONSTRAINT IF EXISTS ck_v014_mandate_hash, DROP CONSTRAINT IF EXISTS ck_v014_mandate_expiry, DROP CONSTRAINT IF EXISTS ck_v014_mandate_revocation, DROP CONSTRAINT IF EXISTS ck_v014_mandate_risk_ref, DROP CONSTRAINT IF EXISTS ck_v014_mandate_transition_audit, DROP CONSTRAINT IF EXISTS ck_v014_mandate_notification_ref, DROP CONSTRAINT IF EXISTS ck_v014_mandate_escalation_ref, DROP CONSTRAINT IF EXISTS ck_v014_mandate_active_refs, DROP COLUMN IF EXISTS authority_sha256, DROP COLUMN IF EXISTS revocation_reason, DROP COLUMN IF EXISTS notification_policy_ref, DROP COLUMN IF EXISTS escalation_policy_ref, DROP COLUMN IF EXISTS last_transition_reason, DROP COLUMN IF EXISTS evidence_ref, DROP COLUMN IF EXISTS transitioned_at, DROP COLUMN IF EXISTS state_version",
            "ALTER TABLE fao.plan_approval DROP CONSTRAINT IF EXISTS ck_v014_approval_status, DROP CONSTRAINT IF EXISTS ck_v014_approval_hash, DROP CONSTRAINT IF EXISTS ck_v014_approval_actions, DROP CONSTRAINT IF EXISTS ck_v014_approval_quantity, DROP CONSTRAINT IF EXISTS ck_v014_approval_window, DROP CONSTRAINT IF EXISTS ck_v014_approval_decision, DROP CONSTRAINT IF EXISTS ck_v014_approval_consumption, DROP CONSTRAINT IF EXISTS uq_v014_approval_consumed_basis, DROP CONSTRAINT IF EXISTS uq_v014_approval_token, DROP COLUMN IF EXISTS requested_by, DROP COLUMN IF EXISTS consumed_basis_id, DROP COLUMN IF EXISTS consumed_at, DROP COLUMN IF EXISTS approval_hash, DROP COLUMN IF EXISTS state_version, DROP COLUMN IF EXISTS approval_token, DROP COLUMN IF EXISTS scope_sha256, DROP COLUMN IF EXISTS scope_account_id, DROP COLUMN IF EXISTS allowed_actions, DROP COLUMN IF EXISTS quantity_ceiling, DROP COLUMN IF EXISTS window_start_at, DROP COLUMN IF EXISTS window_end_at",
            "RESET ROLE",
        )
    )
