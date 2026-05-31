"""Add notifications table

Revision ID: 003
Revises:      002
Create Date:  2024-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision       = "003"
down_revision  = "002"
branch_labels  = None
depends_on     = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id",         sa.Integer,  primary_key=True, index=True),
        sa.Column("title",      sa.String,   nullable=False),
        sa.Column("body",       sa.Text,     nullable=True),
        sa.Column("kind",       sa.String,   nullable=False, server_default="info"),
        sa.Column("package",    sa.String,   nullable=True),
        sa.Column("source",     sa.String,   nullable=True),
        sa.Column("is_read",    sa.Boolean,  nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=True,  index=True),
    )


def downgrade():
    op.drop_table("notifications")