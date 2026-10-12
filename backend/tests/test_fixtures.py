import json
from collections import Counter
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import ROOT, Settings, get_settings
from app.demo import demo_payload, load_fixtures
from app.main import app
from app.schemas import FixtureBundle, QAFixture


def test_public_corpus_and_evidence():
    bundle = load_fixtures()
    assert len(bundle.emails) == 30
    assert Counter(email.category for email in bundle.emails) == {"academic": 10, "admin": 10, "activity": 10}
    tags = {tag for email in bundle.emails for tag in email.tags}
    assert {"no_date", "cross_midnight", "timezone", "deadline_update", "duplicate_content", "prompt_injection"} <= tags
    items = json.loads((ROOT / "eval/development/qa_set.json").read_text(encoding="utf-8"))
    assert len(items) == 20
    for item in items:
        qa = QAFixture.model_validate(item)
        assert set(qa.expected_email_ids) <= {mail.id for mail in bundle.emails}
        assert set(qa.expected_event_ids) <= {event.id for event in bundle.events}


def test_fixture_contract_rejects_nonpublic_sender_and_invented_evidence():
    data = load_fixtures().model_dump(mode="json")
    data["emails"][0]["sender"] = "someone@not-a-reserved-domain.invalid"
    with pytest.raises(ValidationError):
        FixtureBundle.model_validate(data)
    data = load_fixtures().model_dump(mode="json")
    data["events"][0]["evidence"] = "This does not appear in the source"
    with pytest.raises(ValidationError):
        FixtureBundle.model_validate(data)


def test_demo_rebase_keeps_source_and_dates_coherent(tmp_path):
    settings = Settings("Asia/Shanghai", tmp_path / "must-not-exist", date(2030, 1, 1))
    data = demo_payload(settings)
    assert data["meta"]["demo_date"] == "2030-01-01"
    assert data["meta"]["evaluation_reference_now"].startswith("2026-10-12")
    assert data["stats"]["today_events"] > 0
    assert data["stats"]["upcoming_deadlines"] > 0
    assert not settings.data_dir.exists()
    by_id = {email["id"]: email for email in data["emails"]}
    for event in data["events"]:
        assert event["evidence"] in by_id[event["source_email_id"]]["body_text"]


def test_demo_ignores_cloud_credentials_and_is_read_only(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("LLM_MODE", "cloud")
    monkeypatch.setenv("ALLOW_REMOTE_PROCESSING", "true")
    monkeypatch.setenv("DEMO_REFERENCE_DATE", "2026-10-12")
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/api/health").json()["live_account_validated"] is False
    payload = client.get("/api/demo").json()
    assert payload["meta"]["provider"] == "FixtureProvider"
    assert payload["meta"]["remote_processing"] is False
    assert client.post("/api/demo").status_code == 405
    assert client.get("/api/sources").status_code == 401
    assert client.get("/api/demo", headers={"host": "evil.example.org"}).status_code == 400
    assert not (tmp_path / "private").exists()


def test_settings_does_not_use_repository_for_runtime(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "")
    assert not get_settings().data_dir.is_relative_to(ROOT)
