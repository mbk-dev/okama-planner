"""Create the neutral registry, independently of the current ORM models."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_registry",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String, nullable=False, unique=True),
        sa.Column("full_name", sa.String, nullable=False),
        sa.Column("sex", sa.String),
        sa.Column("birth_year", sa.Integer),
        *[
            sa.Column(name, sa.String)
            for name in ("email", "phone", "telegram", "whatsapp", "max_messenger", "primary_channel", "note")
        ],
        sa.Column("telegram_id", sa.Integer),
        sa.Column("brokers", sa.JSON(none_as_null=True)),
        sa.Column("ips_sent_at", sa.Date),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "tax_residency",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("registry_id", sa.Integer, sa.ForeignKey("client_registry.id"), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("note", sa.String),
        sa.UniqueConstraint("registry_id", "year"),
    )


def downgrade() -> None:
    raise RuntimeError("Storage migrations are forward-only")
