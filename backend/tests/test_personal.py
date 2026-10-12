from datetime import datetime, timezone
from sqlalchemy import select
import pytest

from app.agent.data import Snapshot
from app.agent.tools import events
from app.ingest.pipeline import import_one
from app.memory.index_worker import IndexWorker
from app.memory.vector_store import VectorStore
from app.models import CampusEvent, Email, LocalVector, Source
from app.security.policies import BoundaryError
from tests.test_local_import import parsed


def active(client, ctx):
    client.post(f"/api/sources/{ctx.source_id}/activate")
    client.headers["X-CampusFlow-Source"] = ctx.source_id


def event(store, ctx):
    db = store[0]
    with db.transaction() as session:
        row = CampusEvent(workspace_id=ctx.workspace_id, source_id=ctx.source_id, title="虚构开源活动", type="activity",
                          status="confirmed", start_at_utc=datetime(2026, 10, 15, 9, tzinfo=timezone.utc),
                          end_at_utc=datetime(2026, 10, 15, 10, tzinfo=timezone.utc), evidence="虚构时间证据")
        session.add(row); session.flush()
        return row.id


def test_membership_owned_idempotent_and_calendar_only(store, browser_client):
    db, a, b, _ = store; client = browser_client
    id = event(store, a); active(client, a)
    assert events(Snapshot.sql(db, a), {}) == []
    for _ in range(2):
        assert client.put(f"/api/events/{id}/selection", json={"selected": True}).status_code == 200
    assert [item["id"] for item in events(Snapshot.sql(db, a), {})] == [id]
    active(client, b)
    assert client.put(f"/api/events/{id}/selection", json={"selected": True}).status_code == 404


def test_edit_revision_date_only_and_invalid_interval(store, browser_client):
    _, a, *_ = store; client = browser_client; id = event(store, a); active(client, a)
    payload = {"expected_revision": 1, "title": "虚构截止", "type": "deadline", "date": "2026-10-20"}
    result = client.patch(f"/api/events/{id}", json=payload)
    assert result.status_code == 200 and result.json()["revision"] == 2
    assert client.patch(f"/api/events/{id}", json=payload).status_code == 409
    data = client.get('/api/dashboard').json()['events'][0]
    assert data['start_at'] is None and data['date'] == '2026-10-20' and data['user_modified']
    payload.update(expected_revision=2, start_at="2026-10-20T11:00:00", end_at="2026-10-20T10:00:00")
    assert client.patch(f"/api/events/{id}", json=payload).status_code == 422


def test_local_index_durable_scoped_and_old_generation_rejected(store):
    db, a, b, _ = store
    import_one(db, a, parsed(), 'rules', 1)
    store1 = VectorStore(db)
    worker = IndexWorker(db, store1, ctx=a)
    assert worker.process_one()
    assert VectorStore(db).search(a, '课程')  # newly created store sees persisted vectors
    assert store1.search(b, '课程') == []
    store1.rebuild(a)
    assert store1.search(a, '课程') == []
    change = worker.claim()
    store1.rebuild(a)
    with pytest.raises(BoundaryError):
        store1.apply(change)


def test_export_delete_cascades_and_blocks_late_worker(store, browser_client):
    db, a, b, _ = store; client = browser_client
    import_one(db, a, parsed(), 'rules', 1); import_one(db, b, parsed(), 'rules', 1)
    vectors = VectorStore(db); worker = IndexWorker(db, vectors, ctx=a); change = worker.claim()
    active(client, a)
    assert client.put('/api/profile', json={"tags": ["NLP"]}).status_code == 200
    exported = client.post('/api/data/export', json={}).json()
    assert exported['private_data'] and 'credential' not in str(exported)
    assert client.post('/api/data/delete', json={"confirm_source_id": b.source_id}).status_code == 422
    result = client.post('/api/data/delete', json={"confirm_source_id": a.source_id})
    assert result.status_code == 200, result.text
    assert result.json()['remaining_owned_rows'] == 0 and not result.json()['remote_mail_deleted']
    with pytest.raises(BoundaryError):
        vectors.apply(change)
    with db.transaction() as session:
        assert session.get(Source, a.source_id) is None
        assert session.scalar(select(Email).where(Email.source_id == b.source_id))
        assert not session.scalar(select(LocalVector).where(LocalVector.source_id == a.source_id))


def test_profile_and_recommendations_do_not_cross_sources(store, browser_client):
    _, a, b, _ = store; client = browser_client; event(store, a)
    active(client, a)
    assert client.put('/api/profile', json={"tags": ["开源"]}).status_code == 200
    assert client.get('/api/profile').json()['tags'] == ['开源']
    result = client.get('/api/recommendations').json()
    assert not result['score_is_probability'] and not result['semantic_model_validated']
    active(client, b)
    assert client.get('/api/profile').json()['tags'] == []
    assert client.get('/api/recommendations').json()['items'] == []


def test_implicit_topics_are_opt_in_and_suggestions_need_acceptance(store):
    from app.profile.signals import record, suggestions, safe_memory
    from app.models import EventLog
    db, a, b, _ = store
    with db.transaction() as session:
        for _ in range(5):
            record(session, a, "NLP 项目准备")
        session.flush()
        assert suggestions(session, a)[0]['requires_acceptance']
        assert suggestions(session, b) == []
        assert all('NLP 项目准备' not in str(row.safe_metadata) for row in session.scalars(select(EventLog)))
    assert not safe_memory('password=fictional') and not safe_memory('联系 fictional@example.org')


def test_contact_redaction_restores_valid_json_without_sending_originals():
    import json
    from app.security.redaction import mask, restore
    messages = [{"role": "user", "content": "虚构邮箱 fictional@example.org，电话 12345678901"}]
    prepared, mapping = mask(messages)
    assert 'fictional@example.org' not in prepared[0]['content'] and '12345678901' not in prepared[0]['content']
    response = restore(json.dumps({'evidence': prepared[0]['content']}), mapping)
    assert json.loads(response)['evidence'] == messages[0]['content']
