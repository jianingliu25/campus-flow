from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.ingest.extraction import Extraction, rule_extract, validate_candidates
from app.ingest.pipeline import import_one
from app.ingest.previews import PreviewStore, filter_scope
from app.models import CampusEvent, Email, IndexOutbox, SourcePolicy
from app.security.policies import BoundaryError
from app.sources.local_files import MAX_UPLOAD, decode_message, parse_upload, selected_files


def raw_mail(body="课程时间：2026-10-15 09:00–10:00", dated=True):
    message = EmailMessage()
    message["From"] = "虚构老师 <teacher@example.org>"
    message["Subject"] = "虚构课程安排"
    message["Message-ID"] = "<test-course@example.org>"
    if dated:
        message["Date"] = "Mon, 12 Oct 2026 08:00:00 +0800"
    message.set_content(body)
    return message


def parsed(body="课程时间：2026-10-15 09:00–10:00", dated=True):
    return decode_message(raw_mail(body, dated).as_bytes(), "Asia/Shanghai", "fiction.eml#1")


def test_mime_text_only_and_html_never_executes():
    message = raw_mail()
    message.add_alternative('<p>课程</p><script>secret()</script><img src="https://example.org/tracker"><p>正文</p>', subtype="html")
    message.add_attachment(b"attachment secret", maintype="application", subtype="octet-stream", filename="fake.bin")
    mail = decode_message(message.as_bytes(), "Asia/Shanghai", "fiction.eml#1")
    assert mail.subject == "虚构课程安排" and mail.sender == "teacher@example.org"
    assert "attachment secret" not in mail.body_text and "secret()" not in mail.body_text
    html = raw_mail()
    html.set_content('<p>课程</p><script>secret()</script><img src="https://example.org/tracker"><p>正文</p>', subtype="html")
    assert decode_message(html.as_bytes(), "UTC", "html.eml#1").body_text == "课程\n\n正文"


def test_missing_date_is_never_today_and_naive_date_is_labeled():
    assert parsed(dated=False).received_at is None
    assert parsed(dated=False).date_status == "unknown"
    message = raw_mail()
    message.replace_header("Date", "Mon, 12 Oct 2026 08:00:00 -0000")
    mail = decode_message(message.as_bytes(), "Asia/Shanghai", "fiction.eml#1")
    assert mail.received_at == datetime(2026, 10, 12, tzinfo=timezone.utc)
    assert "HEADER_TIMEZONE_ASSUMED" in mail.warnings


def test_upload_limits_invalid_names_and_mbox_duplicates():
    for name in ["../mail.eml", "mail.txt", ""]:
        with pytest.raises(BoundaryError):
            parse_upload(b"fake", name, "UTC")
    with pytest.raises(BoundaryError, match="UPLOAD_TOO_LARGE"):
        parse_upload(b"x" * (MAX_UPLOAD + 1), "mail.eml", "UTC")
    mails, report = parse_upload((Path(__file__).parents[2] / "fixtures/mail/sample.mbox").read_bytes(), "sample.mbox", "Asia/Shanghai")
    assert len(mails) == 3 and report["duplicates_in_file"] == 1
    assert report["errors"] == []
    with pytest.raises(BoundaryError):
        parse_upload(b"not an mbox", "bad.mbox", "UTC")


@pytest.mark.parametrize("body,dated,start,end,day,status", [
    ("课程时间：2026-10-15 09:00–10:00", True, "2026-10-15T01:00:00+00:00", "2026-10-15T02:00:00+00:00", None, "confirmed"),
    ("提交截止：2026-10-16", True, None, None, "2026-10-16", "confirmed"),
    ("课程时间：明天 09:00", True, "2026-10-13T01:00:00+00:00", None, "2026-10-13", "confirmed"),
    ("课程时间：明天 09:00", False, None, None, None, "needs_confirmation"),
    ("课程时间：10月15日 09:00", True, None, None, None, "needs_confirmation"),
    ("提交截止：2026-10-15，另一个截止2026-10-16", True, None, None, None, "needs_confirmation"),
])
def test_rules_ground_dates_without_guessing(body, dated, start, end, day, status):
    mail = parsed(body, dated)
    extraction = rule_extract(mail.subject, body, mail.received_at, "Asia/Shanghai")
    values, warnings = validate_candidates(extraction, body, mail.received_at, "Asia/Shanghai")
    assert warnings == [] and len(values) == 1
    event = values[0]
    assert (event["start_at_utc"].isoformat() if event["start_at_utc"] else None) == start
    assert (event["end_at_utc"].isoformat() if event["end_at_utc"] else None) == end
    assert (event["event_date"].isoformat() if event["event_date"] else None) == day
    assert event["status"] == status


def test_model_candidates_cannot_invent_evidence_dates_or_location():
    body = "课程时间：2026-10-15 09:00"
    for change in [{"evidence": "made up"}, {"start_time": "2026-10-16T09:00:00"}, {"location": "invented room"}, {"date": "2026-10-16"}]:
        event = {"title": "课程", "type": "course", "evidence": body, **change}
        values, warnings = validate_candidates(Extraction(category="academic", summary="", events=[event]), body, None, "Asia/Shanghai")
        assert values == [] and warnings == ["INVALID_EVENT_DROPPED"]


def test_preview_ownership_expiry_and_scope(store):
    _, a, b, _ = store
    now = [0]
    previews = PreviewStore(clock=lambda: now[0], ttl=10)
    first, other = SimpleNamespace(csrf_token="one"), SimpleNamespace(csrf_token="two")
    token = previews.add(first, a, 1, [parsed()], {})
    for owner, ctx in [(other, a), (first, b)]:
        with pytest.raises(BoundaryError):
            previews.take(token, owner, ctx)
    now[0] = 11
    with pytest.raises(BoundaryError):
        previews.take(token, first, a)
    mails, report = filter_scope([parsed(), parsed(dated=False)], {"recent_days": 1, "max_messages": 20}, datetime(2026, 10, 20, tzinfo=timezone.utc))
    assert len(mails) == 1 and mails[0].received_at is None
    assert report["unknown_dates"] == report["outside_date_range"] == 1


def test_import_idempotence_ownership_manual_edits_and_policy(store):
    db, a, b, _ = store
    mail = parsed()
    first = import_one(db, a, mail, "rules", 1)
    assert first["action"] == "imported" and first["events"] == 1
    assert import_one(db, a, mail, "rules", 1)["action"] == "unchanged"
    second = import_one(db, b, mail, "browse", 1)
    assert first["mail_id"] != second["mail_id"]
    with db.transaction() as session:
        event = session.scalar(select(CampusEvent).where(CampusEvent.source_id == a.source_id))
        event.user_modified = True
        event.title = "用户保留的标题"
    changed = parsed("课程时间：2026-10-16 11:00–12:00")
    assert import_one(db, a, changed, "rules", 1)["action"] == "updated"
    with db.transaction() as session:
        event = session.scalar(select(CampusEvent).where(CampusEvent.source_id == a.source_id))
        assert event.title == "用户保留的标题" and event.source_changed
        assert session.scalar(select(func.count()).select_from(Email)) == 2
        assert session.scalar(select(func.count()).select_from(IndexOutbox)) == 3
        session.scalar(select(SourcePolicy).where(SourcePolicy.source_id == a.source_id)).version = 2
    with pytest.raises(BoundaryError, match="POLICY_VERSION_CHANGED"):
        import_one(db, a, mail, "browse", 1)


def test_explicit_directory_rejects_outside_and_links(tmp_path):
    scope = tmp_path / "scope"
    scope.mkdir()
    outside = tmp_path / "outside.eml"
    outside.write_bytes(raw_mail().as_bytes())
    with pytest.raises(BoundaryError, match="PATH_OUTSIDE_SCOPE"):
        selected_files(scope, [outside])
    nested = scope / "nested"
    nested.mkdir()
    (nested / "ignored.eml").write_bytes(raw_mail().as_bytes())
    assert selected_files(scope) == []
    link = scope / "linked.eml"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Host does not permit test symlinks")
    with pytest.raises(BoundaryError, match="LINKED_PATH_REJECTED"):
        selected_files(scope)


def test_preview_commit_default_is_browse_and_tokens_are_one_use(browser_client, store):
    client = browser_client
    _, a, b, _ = store
    response = client.post(f"/api/sources/{a.source_id}/activate")
    assert response.status_code == 200
    client.headers["X-CampusFlow-Source"] = a.source_id
    response = client.post("/api/imports/preview", content=raw_mail(dated=False).as_bytes(), headers={"X-Mail-Filename": "fake.eml"})
    assert response.status_code == 200
    preview = response.json()
    assert preview["mails"][0]["received_at"] is None
    token = preview["preview_id"]
    result = client.post(f"/api/imports/{token}/commit", json={"selected": [0]})
    assert result.status_code == 200 and result.json()["events"] == 0
    assert client.post(f"/api/imports/{token}/commit", json={"selected": [0]}).status_code == 404
    assert client.get("/api/emails").json()[0]["extraction_status"] == "not_processed"
    assert client.get("/api/emails?limit=200").status_code == 200
    assert client.get("/api/events?limit=200").status_code == 200


def test_preview_source_switch_policy_change_and_csrf(browser_client, store):
    client = browser_client
    _, a, b, _ = store
    client.post(f"/api/sources/{a.source_id}/activate")
    client.headers["X-CampusFlow-Source"] = a.source_id
    token = client.post("/api/imports/preview", content=raw_mail(dated=False).as_bytes(), headers={"X-Mail-Filename": "fake.eml"}).json()["preview_id"]
    client.post(f"/api/sources/{b.source_id}/activate")
    client.headers["X-CampusFlow-Source"] = b.source_id
    assert client.post(f"/api/imports/{token}/commit", json={"selected": [0]}).status_code == 404
    client.post(f"/api/sources/{a.source_id}/activate")
    client.headers["X-CampusFlow-Source"] = a.source_id
    client.patch(f"/api/sources/{a.source_id}/policy", json={"expected_version": 1, "retain_body": False})
    response = client.post(f"/api/imports/{token}/commit", json={"selected": [0]})
    assert response.json()["processed"] == 0
    assert response.json()["errors"][0]["code"] == "POLICY_VERSION_CHANGED"
    client.headers.pop("X-CSRF-Token")
    assert client.post("/api/imports/preview", content=raw_mail().as_bytes(), headers={"X-Mail-Filename": "fake.eml"}).status_code == 403


def test_nonretained_body_blocks_reprocessing(store):
    import asyncio
    from app.ingest.pipeline import reprocess
    from app.llm.compatible import ProviderConfig
    db, a, *_ = store
    with db.transaction() as session:
        session.scalar(select(SourcePolicy).where(SourcePolicy.source_id == a.source_id)).retain_body = False
    result = import_one(db, a, parsed(), "rules", 1)
    with db.transaction() as session:
        assert session.get(Email, result["mail_id"]).body_text is None
    with pytest.raises(BoundaryError, match="BODY_NOT_RETAINED"):
        asyncio.run(reprocess(db, a, result["mail_id"], "rules", ProviderConfig()))


def test_cli_dry_run_creates_no_database(tmp_path, monkeypatch, capsys):
    from app.ingest.cli import main
    file = tmp_path / "fake.eml"
    file.write_bytes(raw_mail().as_bytes())
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "private"))
    monkeypatch.setattr("sys.argv", ["import", "--file", str(file), "--dry-run"])
    main()
    assert not (tmp_path / "private").exists()
    assert "dry_run" in capsys.readouterr().out


def test_invalid_model_output_preserves_original_and_events(store, monkeypatch):
    import asyncio
    from app.ingest.pipeline import reprocess
    from app.llm.compatible import ProviderConfig
    db, a, *_ = store
    result = import_one(db, a, parsed(), "rules", 1)
    async def malformed(*args, **kwargs):
        return '{"category":"invented","events":"bad"}'
    monkeypatch.setattr("app.ingest.pipeline.ProcessingGateway.process", malformed)
    with pytest.raises(BoundaryError, match="EXTRACTION_OUTPUT_INVALID"):
        asyncio.run(reprocess(db, a, result["mail_id"], "model", ProviderConfig()))
    with db.transaction() as session:
        mail = session.get(Email, result["mail_id"])
        assert mail.body_text == parsed().body_text and mail.extraction_method == "rules"
        assert session.scalar(select(func.count()).select_from(CampusEvent)) == 1
