"""
Adds the uv_mode column if upgrading from before it existed.

Idempotent: migration 001's initial schema already includes uv_mode for
anyone installing fresh (it was added there after this migration already
existed), so this checks the actual table first rather than assuming the
column is missing — prevents a "duplicate column" error on a genuinely
fresh install, while still correctly adding it for anyone upgrading from
an install that went through the original 001 before uv_mode was folded
into it.
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    if not _has_column("packages", "uv_mode"):
        with op.batch_alter_table("packages") as batch_op:
            batch_op.add_column(sa.Column("uv_mode", sa.String, nullable=True))


def downgrade():
    if _has_column("packages", "uv_mode"):
        with op.batch_alter_table("packages") as batch_op:
            batch_op.drop_column("uv_mode")
