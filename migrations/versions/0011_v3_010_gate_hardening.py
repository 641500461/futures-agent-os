"""V3-010 forward marker for databases already upgraded through V3-009.

The canonical gate function bodies are installed by the historical hardening
revision on fresh databases.  This revision re-applies the owner/grants so an
existing 0010 database receives the V3-010 authority boundary as well.
"""

from alembic import op

revision = "0011_v3_010_gate_hardening"
down_revision = "0010_v3_009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE fao_business_owner")
    op.execute(
        "GRANT EXECUTE ON FUNCTION fao.grant_plan_approval(UUID,BIGINT,UUID,BIGINT,TEXT,TEXT,TIMESTAMPTZ) TO fao_supervisor"
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE fao_business_owner")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION fao.grant_plan_approval(UUID,BIGINT,UUID,BIGINT,TEXT,TEXT,TIMESTAMPTZ) FROM fao_supervisor"
    )
    op.execute("RESET ROLE")
