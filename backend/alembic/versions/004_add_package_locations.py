"""Add package_locations table

Revision ID: 004
Revises:      003
Create Date:  2026-07-19 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision       = "004"
down_revision  = "003"
branch_labels  = None
depends_on     = None


def upgrade():
    op.create_table(
        "package_locations",
        sa.Column("id",            sa.Integer,  primary_key=True, index=True),
        sa.Column("package_id",    sa.Integer,  sa.ForeignKey("packages.id", ondelete="CASCADE"), index=True),
        sa.Column("file_path",     sa.String,   nullable=False),
        sa.Column("directory",     sa.String,   nullable=False, index=True),
        sa.Column("manifest_type", sa.String,   nullable=False),
        sa.Column("detected_at",   sa.DateTime, nullable=True),
        sa.UniqueConstraint("package_id", "file_path", name="uq_package_location"),
    )


def downgrade():
    op.drop_table("package_locations")
