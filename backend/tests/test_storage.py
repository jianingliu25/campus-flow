from datetime import datetime, timezone

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.models import Base, CampusEvent, Email, IndexOutbox, SourcePolicy, VectorDocument
from app.security.policies import BoundaryError, SourceContext
from app.storage import list_emails, upsert_email


def put(session, ctx, body="fictional body", external="one"):
    return upsert_email(session, ctx, external_id=external, subject="虚构通知", sender="fiction@example.org", body_text=body,
                        received_at=datetime(2026, 10, 12, 9, tzinfo=timezone.utc), summary="虚构摘要")


def test_migration_matches_models_and_repeats(store):
    db, *_ = store
    db.migrate()
    with db.engine.connect() as connection:
        assert len(inspect(connection).get_table_names()) == len(Base.metadata.tables) + 1
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"


def test_email_document_outbox_are_atomic_and_idempotent(store):
    db, a, _, _ = store
    with pytest.raises(RuntimeError):
        with db.transaction() as session:
            put(session, a)
            raise RuntimeError("simulate interrupted transaction")
    with db.transaction() as session:
        for model in [Email, VectorDocument, IndexOutbox]:
            assert session.scalar(select(func.count()).select_from(model)) == 0
        first, document = put(session, a)
        id = first.id
    with db.transaction() as session:
        again, document = put(session, a)
        assert again.id == id and document.version == 1
        assert session.scalar(select(func.count()).select_from(IndexOutbox)) == 1
    with db.transaction() as session:
        changed, document = put(session, a, "updated fictional body")
        assert changed.id == id and changed.revision == document.version == 2
        assert session.scalar(select(func.count()).select_from(IndexOutbox)) == 2


def test_cross_source_reads_and_database_foreign_keys(store):
    db, a, b, outside = store
    with db.transaction() as session:
        mail, _ = put(session, a)
    with db.transaction() as session:
        assert list_emails(session, b) == []
        with pytest.raises(BoundaryError):
            list_emails(session, SourceContext(a.workspace_id, outside.source_id))
    with pytest.raises(IntegrityError):
        with db.transaction() as session:
            session.add(CampusEvent(workspace_id=b.workspace_id, source_id=b.source_id, source_email_id=mail.id, title="cross-source", type="course"))
    with pytest.raises(IntegrityError):
        with db.transaction() as session:
            session.add(Email(workspace_id=outside.workspace_id, source_id=a.source_id, external_id="bad", content_hash="bad", subject="bad", sender="fake@example.org", received_at=datetime.now(timezone.utc)))


def test_no_body_policy_and_utc_storage(store):
    db, a, *_ = store
    with db.transaction() as session:
        session.scalar(select(SourcePolicy).where(SourcePolicy.source_id == a.source_id)).retain_body = False
        mail, document = put(session, a, body="body must not persist")
        assert mail.body_text is None
        assert "body must not persist" not in document.text
    with db.transaction() as session:
        mail = list_emails(session, a)[0]
        assert mail.received_at.tzinfo == timezone.utc
    with pytest.raises(StatementError):
        with db.transaction() as session:
            upsert_email(session, a, external_id="naive", subject="bad", sender="fake@example.org", body_text="fake", received_at=datetime(2026, 1, 1))


def test_initial_migration_round_trip(tmp_path):
    from app.db import Database
    db = Database(tmp_path / "migration-roundtrip")
    db.migrate()
    with db.engine.begin() as connection:
        command.downgrade(db.migration_config(connection), "base")
        assert inspect(connection).get_table_names() == ["alembic_version"]
    db.migrate()
    assert set(inspect(db.engine).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    db.close()
