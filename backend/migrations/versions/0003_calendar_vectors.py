"""Local calendar membership and durable vector records, preserving original tables."""
from alembic import op
import sqlalchemy as sa

revision="0003"
down_revision="0002"
branch_labels=None
depends_on=None


def upgrade():
    op.add_column("events",sa.Column("revision",sa.Integer(),nullable=False,server_default="1"))
    op.create_index("ux_events_owner","events",["id","source_id","workspace_id"],unique=True)
    op.create_table("calendar_selections",sa.Column("id",sa.String(36),primary_key=True),sa.Column("event_id",sa.String(36),nullable=False),
        sa.Column("selected",sa.Boolean(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False),
        sa.Column("workspace_id",sa.String(36),nullable=False),sa.Column("source_id",sa.String(36),nullable=False),
        sa.ForeignKeyConstraint(["source_id","workspace_id"],["sources.id","sources.workspace_id"],ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id","source_id","workspace_id"],["events.id","events.source_id","events.workspace_id"],ondelete="CASCADE"),
        sa.UniqueConstraint("event_id"))
    op.create_table("local_vectors",sa.Column("id",sa.String(36),primary_key=True),sa.Column("document_id",sa.String(36),nullable=False),
        sa.Column("generation",sa.Integer(),nullable=False),sa.Column("document_version",sa.Integer(),nullable=False),
        sa.Column("embedding_version",sa.String(100),nullable=False),sa.Column("values",sa.JSON(),nullable=False),
        sa.Column("workspace_id",sa.String(36),nullable=False),sa.Column("source_id",sa.String(36),nullable=False),
        sa.ForeignKeyConstraint(["source_id","workspace_id"],["sources.id","sources.workspace_id"],ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id","source_id","workspace_id"],["vector_documents.id","vector_documents.source_id","vector_documents.workspace_id"],ondelete="CASCADE"),
        sa.UniqueConstraint("document_id"))
    for name in ["calendar_selections","local_vectors"]:
        op.create_index("ix_"+name+"_source_id",name,["source_id"])
        op.create_index("ix_"+name+"_workspace_id",name,["workspace_id"])


def downgrade():
    raise RuntimeError("Destructive downgrade from calendar/vector records is unsupported; restore a user-managed backup")
