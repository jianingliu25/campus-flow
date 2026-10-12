from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.memory.index_worker import IndexWorker, searchable_documents
from app.models import IndexOutbox, Source
from tests.test_storage import put


class TestWriter:
    __test__ = False

    def __init__(self):
        self.jobs, self.writes = set(), {}

    def apply(self, change):
        if change.job_id in self.jobs:
            return
        previous = self.writes.get(change.document_id)
        if previous is None or (change.generation, change.version) > (previous.generation, previous.version):
            self.writes[change.document_id] = change
        self.jobs.add(change.job_id)


def clock():
    tick = [datetime.now(timezone.utc)]
    return tick, lambda: tick[0]


def test_claim_is_atomic_across_workers(store):
    db, a, *_ = store
    with db.transaction() as session:
        put(session, a)
    writers = [IndexWorker(db, TestWriter()), IndexWorker(db, TestWriter())]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda worker: worker.claim(), writers))
    assert sum(result is not None for result in results) == 1


def test_expired_lease_replays_same_job_and_fences_old_owner(store):
    db, a, *_ = store
    with db.transaction() as session:
        put(session, a)
    tick, now = clock()
    writer = TestWriter()
    worker = IndexWorker(db, writer, lease_seconds=10, clock=now)
    first = worker.claim()
    writer.apply(first)  # crash after durable index write, before SQL acknowledgement
    tick[0] += timedelta(seconds=11)
    replay = worker.claim()
    assert replay.job_id == first.job_id and replay.lease_token != first.lease_token
    writer.apply(replay)
    assert len(writer.jobs) == 1
    assert not worker.finish(first)
    assert worker.finish(replay)
    with db.transaction() as session:
        assert len(searchable_documents(session, a)) == 1


def test_stale_document_version_cannot_become_searchable(store):
    db, a, *_ = store
    with db.transaction() as session:
        put(session, a)
    writer, tick_and_clock = TestWriter(), clock()
    worker = IndexWorker(db, writer, clock=tick_and_clock[1])
    old = worker.claim()
    with db.transaction() as session:
        put(session, a, "changed before acknowledgement")
    writer.apply(old)
    assert not worker.finish(old)
    with db.transaction() as session:
        assert searchable_documents(session, a) == []
    tick_and_clock[0][0] += timedelta(seconds=1)
    assert worker.process_one()
    with db.transaction() as session:
        assert searchable_documents(session, a)[0].version == 2


def test_source_deleting_and_generation_change_block_reappearance(store):
    db, a, b, _ = store
    with db.transaction() as session:
        put(session, a)
        put(session, b)
    worker = IndexWorker(db, TestWriter())
    change = worker.claim()
    with db.transaction() as session:
        source = session.get(Source, change.source_id)
        source.status = "deleting"
        source.index_generation += 1
    assert not worker.finish(change)
    with db.transaction() as session:
        job = session.get(IndexOutbox, change.job_id)
        assert job.status == "obsolete"
    assert worker.process_one()  # independent source still progresses


def test_error_backoff_is_bounded_and_never_persists_exception_text(store):
    db, a, *_ = store
    with db.transaction() as session:
        put(session, a)
    tick, now = clock()

    class BrokenWriter:
        def apply(self, change):
            raise RuntimeError("fake-private-mail-and-key")

    worker = IndexWorker(db, BrokenWriter(), max_attempts=3, clock=now)
    for attempt in range(1, 4):
        assert not worker.process_one()
        with db.transaction() as session:
            job = session.scalar(select(IndexOutbox))
            assert job.attempts == attempt
            assert job.error_code == "INDEX_WRITE_FAILED"
            assert job.status == ("dead" if attempt == 3 else "pending")
        tick[0] += timedelta(seconds=2 ** attempt + 1)
    assert worker.claim() is None


def test_crashing_worker_cannot_retry_forever(store):
    db, a, *_ = store
    with db.transaction() as session:
        put(session, a)
    tick, now = clock()
    worker = IndexWorker(db, TestWriter(), lease_seconds=1, max_attempts=2, clock=now)
    assert worker.claim() is not None
    tick[0] += timedelta(seconds=2)
    assert worker.claim() is not None
    tick[0] += timedelta(seconds=2)
    assert worker.claim() is None
    with db.transaction() as session:
        assert session.scalar(select(IndexOutbox)).status == "dead"


def test_pending_lease_survives_database_reopen(store):
    from app.db import Database
    db, a, *_ = store
    with db.transaction() as session:
        put(session, a)
    tick, now = clock()
    old = IndexWorker(db, TestWriter(), lease_seconds=1, clock=now).claim()
    directory = db.path.parent
    db.close()
    reopened = Database(directory)
    try:
        reopened.migrate()
        tick[0] += timedelta(seconds=2)
        worker = IndexWorker(reopened, TestWriter(), lease_seconds=1, clock=now)
        recovered = worker.claim()
        assert recovered.job_id == old.job_id and recovered.lease_token != old.lease_token
        worker.writer.apply(recovered)
        assert worker.finish(recovered)
    finally:
        reopened.close()
