"""Adopt the original snapshot schema without changing its data.

Revision ID: 0001_snapshot_ledger
Revises:
"""

import sqlalchemy as sa
from alembic import context, op

revision = "0001_snapshot_ledger"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Accept unstamped legacy databases, checking both tables independently.
    existing = (
        set() if context.is_offline_mode() else set(sa.inspect(op.get_bind()).get_table_names())
    )
    if "sessions" not in existing:
        op.create_table(
            "sessions",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("state", sa.Text(), nullable=False),
        )
    if "requests" not in existing:
        op.create_table(
            "requests",
            sa.Column("session_id", sa.Text(), sa.ForeignKey("sessions.id"), primary_key=True),
            sa.Column("request_id", sa.Text(), primary_key=True),
            sa.Column("fingerprint", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("created", sa.Float(), nullable=False),
            sa.Column("result", sa.Text()),
            sa.Column("trace", sa.Text()),
            sa.Column("http_status", sa.Integer(), nullable=False, server_default="200"),
        )


def downgrade():
    # This revision adopts existing application tables. Unstamp only; dropping
    # them would destroy pre-Alembic user data and prevent an upgrade roundtrip.
    pass
