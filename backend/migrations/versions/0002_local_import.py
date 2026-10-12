"""Add local import metadata without rebuilding referenced SQLite tables."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("emails", "received_at", new_column_name="sorting_timestamp")
    op.add_column("emails", sa.Column("received_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE emails SET received_at = sorting_timestamp")
    op.add_column("emails", sa.Column("canonical_hash", sa.String(64), nullable=True))
    op.add_column("emails", sa.Column("imported_at", sa.DateTime(), nullable=True))
    op.add_column("emails", sa.Column("date_status", sa.String(30), nullable=False, server_default="known"))
    op.add_column("emails", sa.Column("import_warnings", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("emails", sa.Column("source_locator", sa.String(160), nullable=True))
    op.add_column("emails", sa.Column("extraction_status", sa.String(30), nullable=False, server_default="not_processed"))
    op.add_column("emails", sa.Column("extraction_method", sa.String(30), nullable=True))
    op.add_column("emails", sa.Column("extraction_warnings", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("events", sa.Column("event_date", sa.Date(), nullable=True))
    op.add_column("events", sa.Column("source_changed", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    raise RuntimeError("Migration 0002 contains nullable original dates; destructive downgrade is intentionally unsupported")
