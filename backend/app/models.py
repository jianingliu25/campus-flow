"""Source-bound storage. Composite foreign keys enforce ownership in SQLite."""

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def new_id():
    return str(uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Stored timestamps must have an explicit timezone")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), default="个人本地工作区")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        CheckConstraint("kind IN ('fixture','local_files','imap','mcp')"),
        CheckConstraint("status IN ('configured','active','disconnected','deleting','deleted')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    display_name: Mapped[str] = mapped_column(String(80))
    account_hint: Mapped[str | None] = mapped_column(String(120))
    safe_config: Mapped[dict] = mapped_column(JSON, default=dict)
    credential_ref: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="configured")
    policy_version: Mapped[int] = mapped_column(Integer, default=1)
    index_generation: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


def owned(*extra):
    return (ForeignKeyConstraint(["source_id", "workspace_id"], ["sources.id", "sources.workspace_id"], ondelete="CASCADE"), *extra)


class SourceOwned:
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    source_id: Mapped[str] = mapped_column(String(36), index=True)


class SourcePolicy(SourceOwned, Base):
    __tablename__ = "source_policies"
    __table_args__ = owned(UniqueConstraint("source_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version: Mapped[int] = mapped_column(Integer, default=1)
    scope: Mapped[dict] = mapped_column(JSON, default=lambda: {"recent_days": 30, "max_messages": 200, "folders": []})
    allow_remote_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_fingerprint: Mapped[str | None] = mapped_column(String(64))
    retain_body: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_qa_memory: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_implicit_profile: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class SyncRun(SourceOwned, Base):
    __tablename__ = "sync_runs"
    __table_args__ = owned()
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(40))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class SyncCursor(SourceOwned, Base):
    __tablename__ = "sync_cursors"
    __table_args__ = owned(UniqueConstraint("source_id", "folder"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    folder: Mapped[str] = mapped_column(String(120))
    cursor: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Email(SourceOwned, Base):
    __tablename__ = "emails"
    __table_args__ = owned(UniqueConstraint("source_id", "external_id"), UniqueConstraint("id", "source_id", "workspace_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    external_id: Mapped[str] = mapped_column(String(250))
    message_id: Mapped[str | None] = mapped_column(String(250))
    content_hash: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(Text)
    sender: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sorting_timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    canonical_hash: Mapped[str | None] = mapped_column(String(64))
    imported_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    date_status: Mapped[str] = mapped_column(String(30), default="known", server_default="known")
    import_warnings: Mapped[list] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    source_locator: Mapped[str | None] = mapped_column(String(160))
    extraction_status: Mapped[str] = mapped_column(String(30), default="not_processed", server_default="not_processed")
    extraction_method: Mapped[str | None] = mapped_column(String(30))
    extraction_warnings: Mapped[list] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    category: Mapped[str | None] = mapped_column(String(20))
    local_star: Mapped[bool] = mapped_column(Boolean, default=False)
    local_read: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class CampusEvent(SourceOwned, Base):
    __tablename__ = "events"
    __table_args__ = owned(ForeignKeyConstraint(["source_email_id", "source_id", "workspace_id"], ["emails.id", "emails.source_id", "emails.workspace_id"], ondelete="CASCADE"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(20))
    start_at_utc: Mapped[datetime | None] = mapped_column(UTCDateTime())
    end_at_utc: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_timezone: Mapped[str | None] = mapped_column(String(80))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    deadline_date: Mapped[date | None] = mapped_column(Date)
    event_date: Mapped[date | None] = mapped_column(Date)
    source_changed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    location: Mapped[str | None] = mapped_column(Text)
    source_email_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(30), default="needs_confirmation")
    evidence: Mapped[str | None] = mapped_column(Text)
    user_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Profile(SourceOwned, Base):
    __tablename__ = "profiles"
    __table_args__ = owned(UniqueConstraint("source_id"), UniqueConstraint("id", "source_id", "workspace_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    explicit_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    interest_vector: Mapped[list | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class EventLog(SourceOwned, Base):
    __tablename__ = "event_logs"
    __table_args__ = owned()
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str | None] = mapped_column(String(36))
    safe_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class QALog(SourceOwned, Base):
    __tablename__ = "qa_logs"
    __table_args__ = owned(UniqueConstraint("id", "source_id", "workspace_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    template_id: Mapped[str | None] = mapped_column(String(80))
    quality_score: Mapped[float | None] = mapped_column(Float)
    safe_trajectory: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class VectorDocument(SourceOwned, Base):
    __tablename__ = "vector_documents"
    __table_args__ = owned(
        UniqueConstraint("id", "source_id", "workspace_id"),
        UniqueConstraint("source_id", "kind", "foreign_key"),
        ForeignKeyConstraint(["email_id", "source_id", "workspace_id"], ["emails.id", "emails.source_id", "emails.workspace_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["qa_id", "source_id", "workspace_id"], ["qa_logs.id", "qa_logs.source_id", "qa_logs.workspace_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["profile_id", "source_id", "workspace_id"], ["profiles.id", "profiles.source_id", "profiles.workspace_id"], ondelete="CASCADE"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(20))
    foreign_key: Mapped[str] = mapped_column(String(36))
    email_id: Mapped[str | None] = mapped_column(String(36))
    qa_id: Mapped[str | None] = mapped_column(String(36))
    profile_id: Mapped[str | None] = mapped_column(String(36))
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding_version: Mapped[str] = mapped_column(String(100), default="pending-local-model")
    generation: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    indexed_version: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class IndexOutbox(SourceOwned, Base):
    __tablename__ = "index_outbox"
    __table_args__ = owned(
        ForeignKeyConstraint(["document_id", "source_id", "workspace_id"], ["vector_documents.id", "vector_documents.source_id", "vector_documents.workspace_id"], ondelete="CASCADE"),
        UniqueConstraint("document_id", "document_version", "generation", "operation"),
        CheckConstraint("status IN ('pending','processing','done','obsolete','dead')"),
        CheckConstraint("operation IN ('upsert','delete')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    document_version: Mapped[int] = mapped_column(Integer)
    generation: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(10), default="upsert")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
