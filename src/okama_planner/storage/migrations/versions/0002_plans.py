"""Add versioned planning snapshots without changing registry records."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("registry_id", sa.Integer, sa.ForeignKey("client_registry.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("source_digest", sa.String, nullable=False),
        sa.Column("note", sa.String),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("registry_id", "version"),
    )
    op.create_table(
        "plan_snapshot",
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), primary_key=True),
        sa.Column("request", sa.JSON, nullable=False),
    )
    for table in ("person", "asset", "liability", "budget_item", "goal", "portfolio"):
        op.create_table(
            table,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), nullable=False),
            sa.Column("position", sa.Integer, nullable=False),
            sa.Column("payload", sa.JSON, nullable=False),
            sa.UniqueConstraint("client_id", "position"),
        )
    op.create_table(
        "scenario",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), nullable=False),
        sa.Column("label", sa.String, nullable=False),
        sa.Column("request", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "plan_run",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scenario_id", sa.Integer, sa.ForeignKey("scenario.id"), nullable=False),
        sa.Column("request", sa.JSON, nullable=False),
        sa.Column("result", sa.JSON, nullable=False),
        sa.Column("source_digest", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Storage migrations are forward-only")
