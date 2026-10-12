"""Durable leased outbox. No background model download or index run in M2."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from sqlalchemy import and_, or_, select, update

from app.models import IndexOutbox, Source, VectorDocument, new_id, utcnow


@dataclass(frozen=True)
class IndexChange:
    job_id: str
    lease_token: str
    source_id: str
    workspace_id: str
    document_id: str
    version: int
    generation: int
    operation: str
    text: str
    embedding_version: str


class IndexWriter(Protocol):
    def apply(self, change: IndexChange) -> None:
        """Durably idempotent by job_id; reject old (generation, version) writes."""
        ...


class IndexWorker:
    def __init__(self, database, writer: IndexWriter, lease_seconds=60, max_attempts=3, clock=utcnow):
        self.database, self.writer = database, writer
        self.lease_seconds, self.max_attempts, self.clock = lease_seconds, max_attempts, clock

    def claim(self):
        now, token = self.clock(), new_id()
        eligible = or_(and_(IndexOutbox.status == "pending", IndexOutbox.available_at <= now),
                       and_(IndexOutbox.status == "processing", IndexOutbox.lease_until <= now))
        candidate = select(IndexOutbox.id).where(eligible, IndexOutbox.attempts < self.max_attempts).order_by(IndexOutbox.created_at, IndexOutbox.id).limit(1).scalar_subquery()
        with self.database.transaction() as session:
            session.execute(update(IndexOutbox).where(IndexOutbox.status == "processing", IndexOutbox.lease_until <= now, IndexOutbox.attempts >= self.max_attempts).values(status="dead", error_code="LEASE_EXHAUSTED", lease_token=None, lease_until=None))
            id = session.scalar(update(IndexOutbox).where(IndexOutbox.id == candidate).values(
                status="processing", lease_token=token, lease_until=now + timedelta(seconds=self.lease_seconds), attempts=IndexOutbox.attempts + 1).returning(IndexOutbox.id))
            if id is None:
                return None
            job = session.get(IndexOutbox, id)
            document = session.get(VectorDocument, job.document_id)
            source = session.get(Source, job.source_id)
            if not self.current(job, document, source):
                job.status, job.lease_token, job.lease_until = "obsolete", None, None
                return None
            return IndexChange(job.id, token, job.source_id, job.workspace_id, job.document_id,
                               job.document_version, job.generation, job.operation, document.text, document.embedding_version)

    @staticmethod
    def current(job, document, source):
        return bool(source and document and source.workspace_id == job.workspace_id and
                    source.status not in {"deleting", "deleted", "disconnected"} and
                    source.index_generation == job.generation == document.generation and
                    document.version == job.document_version and
                    ((job.operation == "delete") == (document.deleted_at is not None)))

    def finish(self, change, *, error=False):
        now = self.clock()
        with self.database.transaction() as session:
            job = session.get(IndexOutbox, change.job_id)
            if job is None or job.status != "processing" or job.lease_token != change.lease_token or job.lease_until <= now:
                return False
            document, source = session.get(VectorDocument, job.document_id), session.get(Source, job.source_id)
            if not self.current(job, document, source):
                job.status = "obsolete"
            elif error:
                job.status = "dead" if job.attempts >= self.max_attempts else "pending"
                job.error_code = "INDEX_WRITE_FAILED"  # never persist exception text
                job.available_at = now + timedelta(seconds=min(2 ** job.attempts, 60))
            else:
                job.status, job.error_code = "done", None
                document.indexed_version = None if job.operation == "delete" else document.version
            job.lease_token, job.lease_until = None, None
            return job.status == "done"

    def process_one(self):
        change = self.claim()
        if change is None:
            return False
        try:
            self.writer.apply(change)
        except Exception:
            self.finish(change, error=True)
            return False
        return self.finish(change)


def searchable_documents(session, ctx):
    """Vector hits must always be filtered against these current SQL documents."""
    from app.security.policies import scoped_source
    source = scoped_source(session, ctx)
    return list(session.scalars(select(VectorDocument).where(
        VectorDocument.workspace_id == ctx.workspace_id, VectorDocument.source_id == ctx.source_id,
        VectorDocument.generation == source.index_generation, VectorDocument.deleted_at.is_(None),
        VectorDocument.indexed_version == VectorDocument.version)))
