from sqlalchemy import select

from app.ingest.pipeline import import_one
from app.models import Email, IndexOutbox
from tests.test_local_import import parsed


def activate(client, ctx):
    assert client.post(f"/api/sources/{ctx.source_id}/activate").status_code == 200
    client.headers["X-CampusFlow-Source"] = ctx.source_id


def test_scoped_dashboard_unknown_dates_and_private_body_excluded(browser_client, store):
    db, a, b, _ = store
    import_one(db, a, parsed(), "rules", 1)
    from dataclasses import replace
    import_one(db, a, replace(parsed("活动的时间待定，private marker", False), external_id="unknown-date"), "rules", 1)
    activate(browser_client, a)
    response = browser_client.get("/api/dashboard")
    assert response.status_code == 200
    view = response.json()
    assert view["mail_total"] == view["event_total"] == 2
    assert view["stats"]["needs_confirmation"] == 1
    assert view["processing"]["account_connected"] is False
    assert all("body_text" not in mail for mail in view["emails"])
    assert view["source_id"] == a.source_id
    activate(browser_client, b)
    other = browser_client.get("/api/dashboard").json()
    assert other["mail_total"] == other["event_total"] == 0 and other["emails"] == []


def test_flags_persist_do_not_reindex_and_cross_source_ids_hidden(browser_client, store):
    db, a, b, _ = store
    result = import_one(db, a, parsed(), "browse", 1)
    mail_id = result["mail_id"]
    activate(browser_client, a)
    response = browser_client.patch(f"/api/emails/{mail_id}/flags", json={"local_star": True, "local_read": True})
    assert response.status_code == 200 and response.json()["local_star"]
    with db.transaction() as session:
        mail = session.get(Email, mail_id)
        assert mail.local_star and mail.local_read and mail.revision == 1
        assert len(list(session.scalars(select(IndexOutbox)))) == 1
    assert browser_client.get("/api/dashboard").json()["emails"][0]["local_star"]
    assert browser_client.patch(f"/api/emails/{mail_id}/flags", json={}).status_code == 422
    assert browser_client.patch(f"/api/emails/{mail_id}/flags", json={"body_text": "bad"}).status_code == 422
    activate(browser_client, b)
    assert browser_client.patch(f"/api/emails/{mail_id}/flags", json={"local_star": False}).status_code == 404
    browser_client.headers.pop("X-CSRF-Token")
    assert browser_client.patch(f"/api/emails/{mail_id}/flags", json={"local_star": False}).status_code == 403


def test_dashboard_pages_have_stable_totals_and_no_duplicates(browser_client, store):
    from dataclasses import replace
    db, a, *_ = store
    original = parsed()
    for index in range(53):
        import_one(db, a, replace(original, external_id=f"fiction-{index}", canonical_hash=f"hash-{index}"), "rules", 1)
    activate(browser_client, a)
    first = browser_client.get("/api/dashboard").json()
    next_page = browser_client.get("/api/dashboard?mail_offset=50&event_offset=50").json()
    assert first["mail_total"] == next_page["mail_total"] == first["event_total"] == 53
    assert len(first["emails"]) == 50 and len(next_page["emails"]) == 3
    assert len(first["events"]) == 50 and len(next_page["events"]) == 3
    assert not {mail["id"] for mail in first["emails"]} & {mail["id"] for mail in next_page["emails"]}
    assert browser_client.get("/api/dashboard?mail_offset=-1").status_code == 422


def test_deactivate_revokes_previews_and_clears_private_reads(browser_client, store):
    from tests.test_local_import import raw_mail
    _, a, *_ = store
    activate(browser_client, a)
    token = browser_client.post("/api/imports/preview", content=raw_mail(dated=False).as_bytes(), headers={"X-Mail-Filename": "fake.eml"}).json()["preview_id"]
    assert browser_client.post("/api/sources/deactivate").json()["active_source_id"] is None
    assert browser_client.get("/api/dashboard").status_code == 409
    activate(browser_client, a)
    assert browser_client.post(f"/api/imports/{token}/commit", json={"selected": [0]}).status_code == 404


def test_provider_status_omits_keys_and_unsafe_endpoint(browser_client):
    from app.llm.compatible import ProviderConfig
    browser_client.app.state.provider_config = ProviderConfig("cloud", "https://provider.example.org/v1", "fake-model", "fictional-secret", True)
    response = browser_client.get("/api/provider-status")
    assert response.json()["configured"] and response.json()["host"] == "provider.example.org"
    assert "fictional-secret" not in response.text and not response.json()["connection_tested"]
    browser_client.app.state.provider_config = ProviderConfig("local", "https://private:secret@example.org/v1?secret=one", "fake")
    response = browser_client.get("/api/provider-status")
    assert response.json()["host"] is None and not response.json()["configured"]
    assert "secret" not in response.text
