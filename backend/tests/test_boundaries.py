from datetime import date

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.compatible import ProviderConfig
from app.main import create_app
from app.models import Source
from app.security.session import COOKIE_NAME, SessionManager
from tests.test_storage import put


def test_session_cookie_origin_and_csrf(browser_client):
    client = browser_client
    assert client.get("/api/session").status_code == 200
    cookie = client.post("/api/session").headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    client.headers["Origin"] = "https://evil.example.org"
    assert client.post("/api/session").status_code == 403
    assert client.get("/api/sources").status_code == 403
    client.headers["Origin"] = "http://127.0.0.1"
    client.headers["Sec-Fetch-Site"] = "same-site"
    assert client.post("/api/session").status_code == 403
    client.headers["Sec-Fetch-Site"] = "same-origin"
    client.headers.pop("X-CSRF-Token")
    assert client.post("/api/sources", json={"kind": "fixture", "display_name": "fake"}).status_code == 403
    client.headers.pop("Origin")
    assert client.post("/api/session").status_code == 403


def test_active_source_is_server_bound_and_foreign_ids_hidden(browser_client, store):
    client = browser_client
    db, a, b, outside = store
    with db.transaction() as session:
        mail, _ = put(session, a)
        session.get(Source, a.source_id).credential_ref = "test-secret-credential-reference"
        session.get(Source, a.source_id).safe_config = {"api_key": "test-do-not-echo"}
    assert client.get("/api/emails").status_code == 409
    assert client.post(f"/api/sources/{outside.source_id}/activate").status_code == 404
    assert outside.source_id not in client.get("/api/sources").text
    assert "test-do-not-echo" not in client.get("/api/sources").text
    assert "test-secret-credential-reference" not in client.get("/api/sources").text
    assert client.post(f"/api/sources/{a.source_id}/activate").status_code == 200
    client.headers["X-CampusFlow-Source"] = a.source_id
    assert len(client.get("/api/emails").json()) == 1
    assert client.post(f"/api/sources/{b.source_id}/activate").status_code == 200
    assert client.get("/api/emails").status_code == 409  # stale page/source header
    client.headers["X-CampusFlow-Source"] = b.source_id
    assert client.get("/api/emails").json() == []
    assert client.get(f"/api/emails/{mail.id}").status_code == 404
    assert client.get("/api/index-status").json()["jobs"] == {}
    assert client.get(f"/api/sources/{outside.source_id}/policy").status_code == 404


def test_policy_defaults_cas_and_error_redaction(browser_client, store):
    client = browser_client
    _, a, *_ = store
    policy = client.get(f"/api/sources/{a.source_id}/policy").json()
    assert not any(policy[key] for key in ["allow_remote_processing", "enable_qa_memory", "enable_implicit_profile"])
    response = client.patch(f"/api/sources/{a.source_id}/policy", json={"expected_version": 1, "enable_qa_memory": True})
    assert response.status_code == 200 and response.json()["version"] == 2
    assert client.patch(f"/api/sources/{a.source_id}/policy", json={"expected_version": 1, "retain_body": False}).status_code == 409
    assert client.patch(f"/api/sources/{a.source_id}/policy", json={"expected_version": 2, "allow_remote_processing": True}).status_code == 403
    response = client.post("/api/sources", json={"kind": "imap", "display_name": "fake", "password": "fixture-secret-never-echo"})
    assert response.status_code == 422 and "fixture-secret-never-echo" not in response.text
    assert client.post("/api/sources", content="x" * 262145).status_code == 413
    assert client.post(f"/api/sources/{a.source_id}/sync").status_code == 409  # explicit active-source selection required


def test_expanding_scope_revokes_provider_consent(browser_client, store):
    client = browser_client
    _, a, *_ = store
    config = ProviderConfig("cloud", "https://provider.example.org/v1", "fake-model", "fictional-key", True)
    client.app.state.provider_config = config
    response = client.patch(f"/api/sources/{a.source_id}/policy", json={"expected_version": 1, "allow_remote_processing": True, "consent_fingerprint": config.fingerprint})
    assert response.status_code == 200 and response.json()["allow_remote_processing"]
    response = client.patch(f"/api/sources/{a.source_id}/policy", json={"expected_version": 2, "scope": {"recent_days": 60, "max_messages": 400, "folders": []}})
    assert response.status_code == 200
    assert not response.json()["allow_remote_processing"] and response.json()["consent_fingerprint"] is None


def test_session_expiry_restart_and_revoke(browser_client):
    client = browser_client
    assert client.delete("/api/session").status_code == 204
    assert client.get("/api/sources").status_code == 401
    tick = [0]
    manager = SessionManager("test-workspace", ttl=10, clock=lambda: tick[0])
    token, _ = manager.create()
    tick[0] = 11
    import pytest
    from app.security.policies import BoundaryError
    with pytest.raises(BoundaryError):
        manager.get(token)
    fresh = SessionManager("test-workspace")
    with pytest.raises(BoundaryError):
        fresh.get(token)


def test_distinct_sessions_do_not_share_active_source(store, tmp_path):
    db, a, b, _ = store
    application = create_app(Settings("Asia/Shanghai", tmp_path / "unused", date(2026, 10, 12)), database=db, provider_config=ProviderConfig())
    with TestClient(application, base_url="http://127.0.0.1") as first:
        first.headers["Origin"] = "http://127.0.0.1"
        one = first.post("/api/session").json()
        first.headers["X-CSRF-Token"] = one["csrf_token"]
        assert first.post(f"/api/sources/{a.source_id}/activate").status_code == 200
        first.cookies.clear()
        two = first.post("/api/session").json()
        assert two["active_source_id"] is None
        assert two["csrf_token"] != one["csrf_token"]
