"""
Example of how future migrations look.
This one adds the uv_mode column if upgrading from before it existed.
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("packages") as batch_op:
        batch_op.add_column(sa.Column("uv_mode", sa.String, nullable=True))


def downgrade():
    with op.batch_alter_table("packages") as batch_op:
        batch_op.drop_column("uv_mode")