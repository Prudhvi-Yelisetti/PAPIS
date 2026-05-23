"""
Initial schema — creates all tables from scratch.
This replaces the create_all() call in database.py for production use.
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # packages
    op.create_table(
        "packages",
        sa.Column("id",           sa.Integer,    primary_key=True, index=True),
        sa.Column("name",         sa.String,     nullable=False,   index=True),
        sa.Column("version",      sa.String,     nullable=False),
        sa.Column("source",       sa.String,     default="unknown"),
        sa.Column("install_type", sa.String,     default="unknown"),
        sa.Column("install_date", sa.DateTime,   nullable=True),
        sa.Column("last_updated", sa.DateTime,   nullable=True),
        sa.Column("size_bytes",   sa.BigInteger, nullable=True),
        sa.Column("description",  sa.Text,       nullable=True),
        sa.Column("depends_on",   sa.Text,       nullable=True),
        sa.Column("required_by",  sa.Text,       nullable=True),
        sa.Column("is_orphan",    sa.Boolean,    default=False),
        sa.Column("uv_mode",      sa.String,     nullable=True),
        sa.Column("last_used_at", sa.DateTime,   nullable=True),
        sa.Column("in_inbox",     sa.Boolean,    default=True),
        sa.Column("created_at",   sa.DateTime),
        sa.Column("updated_at",   sa.DateTime),
    )

    # projects
    op.create_table(
        "projects",
        sa.Column("id",          sa.Integer, primary_key=True, index=True),
        sa.Column("name",        sa.String,  nullable=False, unique=True, index=True),
        sa.Column("description", sa.Text,    nullable=True),
        sa.Column("directory",   sa.String,  nullable=True),
        sa.Column("tags",        sa.Text,    nullable=True),
        sa.Column("is_archived", sa.Boolean, default=False),
        sa.Column("created_at",  sa.DateTime),
        sa.Column("updated_at",  sa.DateTime),
    )

    # package_project (join table)
    op.create_table(
        "package_project",
        sa.Column("package_id",  sa.Integer, sa.ForeignKey("packages.id",  ondelete="CASCADE"), primary_key=True),
        sa.Column("project_id",  sa.Integer, sa.ForeignKey("projects.id",  ondelete="CASCADE"), primary_key=True),
        sa.Column("assigned_at", sa.DateTime),
        sa.Column("notes",       sa.Text, nullable=True),
    )

    # install_events
    op.create_table(
        "install_events",
        sa.Column("id",           sa.Integer, primary_key=True, index=True),
        sa.Column("package_id",   sa.Integer, sa.ForeignKey("packages.id", ondelete="CASCADE")),
        sa.Column("event_type",   sa.String,  nullable=False),
        sa.Column("version_old",  sa.String,  nullable=True),
        sa.Column("version_new",  sa.String,  nullable=True),
        sa.Column("triggered_by", sa.String,  nullable=True),
        sa.Column("metadata",     sa.Text,    nullable=True),
        sa.Column("occurred_at",  sa.DateTime, index=True),
    )

    # project_scans
    op.create_table(
        "project_scans",
        sa.Column("id",           sa.Integer, primary_key=True, index=True),
        sa.Column("project_id",   sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("scanned_path", sa.String,  nullable=False),
        sa.Column("manifest",     sa.String,  nullable=True),
        sa.Column("suggestions",  sa.Text,    nullable=True),
        sa.Column("scanned_at",   sa.DateTime),
    )


def downgrade():
    op.drop_table("project_scans")
    op.drop_table("install_events")
    op.drop_table("package_project")
    op.drop_table("projects")
    op.drop_table("packages")