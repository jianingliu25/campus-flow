"""Consistent, bounded snapshot of one explicitly selected private source."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.api.foundation import db
from app.ingest.pipeline import source_timezone
from app.models import CampusEvent, Email, IndexOutbox, utcnow
from app.security.http import local_session, source_context
from app.security.policies import scoped_source
from app.storage import owned_query

router = APIRouter(prefix="/api")


@router.get("/provider-status")
def provider_status(request: Request, session=Depends(local_session)):
    from urllib.parse import urlsplit
    from app.llm.compatible import normalize_endpoint
    from app.security.policies import BoundaryError
    config = request.app.state.provider_config
    endpoint, valid = "", False
    if config.mode in {"local", "cloud"}:
        try:
            endpoint = normalize_endpoint(config)
            valid = bool(config.model and (config.mode == "local" or config.api_key))
        except BoundaryError:
            pass
    return {"mode": config.mode, "model": config.model if valid else None,
            "host": urlsplit(endpoint).hostname if endpoint else None, "configured": valid,
            "remote_globally_enabled": config.global_remote, "fingerprint": config.fingerprint,
            "connection_tested": False}


@router.get("/dashboard")
def dashboard(request: Request, mail_offset: int = Query(default=0, ge=0, le=1000000),
              event_offset: int = Query(default=0, ge=0, le=1000000), ctx=Depends(source_context)):
    with db(request).transaction() as transaction:
        transaction.connection().exec_driver_sql("BEGIN")  # SQLite snapshot spans every read below.
        source = scoped_source(transaction, ctx)
        zone = source_timezone(transaction, ctx)
        today = utcnow().astimezone(ZoneInfo(zone)).date()
        page_size = 50
        mails = list(transaction.scalars(owned_query(Email, ctx).order_by(Email.sorting_timestamp.desc(), Email.id)
                                         .offset(mail_offset).limit(page_size)))
        event_query = owned_query(CampusEvent, ctx).where(CampusEvent.status != "superseded")
        events = list(transaction.scalars(event_query.order_by(CampusEvent.start_at_utc.asc().nullslast(),
                                                               CampusEvent.event_date.asc().nullslast(), CampusEvent.id)
                                          .offset(event_offset).limit(page_size)))
        mail_total = transaction.scalar(select(func.count()).select_from(owned_query(Email, ctx).subquery()))
        event_total = transaction.scalar(select(func.count()).select_from(event_query.subquery()))
        today_count = deadlines = pending = 0
        # Totals read scalar fields only; the response omits body_text (excerpts may contain mail content).
        for status, kind, stamp, day in transaction.execute(event_query.with_only_columns(
                CampusEvent.status, CampusEvent.type, CampusEvent.start_at_utc, CampusEvent.event_date)):
            if status == "needs_confirmation":
                pending += 1
            local_day = stamp.astimezone(ZoneInfo(zone)).date() if stamp else day
            if status == "confirmed" and local_day:
                today_count += int(local_day == today)
                deadlines += int(kind == "deadline" and today <= local_day < today + timedelta(days=7))
        counts = dict(transaction.execute(select(IndexOutbox.status, func.count()).where(
            IndexOutbox.workspace_id == ctx.workspace_id, IndexOutbox.source_id == ctx.source_id).group_by(IndexOutbox.status)).all())
        last_import = transaction.scalar(select(func.max(Email.imported_at)).where(
            Email.workspace_id == ctx.workspace_id, Email.source_id == ctx.source_id))
        return {
            "source_id": source.id, "timezone": zone, "today": today, "page_size": page_size,
            "mail_total": mail_total, "event_total": event_total, "mail_offset": mail_offset, "event_offset": event_offset,
            "stats": {"today_events": today_count, "upcoming_deadlines": deadlines, "needs_confirmation": pending},
            "processing": {"last_import_at": last_import, "index_jobs": counts, "vector_search_enabled": False,
                           "account_connected":bool(source.safe_config.get("connection_tested")),
                           "sync_paused":bool(source.safe_config.get("paused"))},
            "emails": [{"id": mail.id, "source_id": mail.source_id, "subject": mail.subject, "sender": mail.sender,
                        "summary": mail.summary, "received_at": mail.received_at, "category": mail.category,
                        "local_star": mail.local_star, "local_read": mail.local_read, "date_status": mail.date_status,
                        "extraction_status": mail.extraction_status, "extraction_method": mail.extraction_method} for mail in mails],
            "events": [{"id": event.id, "source_id": event.source_id, "source_email_id": event.source_email_id,
                        "title": event.title, "type": event.type, "start_at": event.start_at_utc,
                        "end_at": event.end_at_utc, "date": event.event_date or event.deadline_date,
                        "all_day": event.all_day, "location": event.location, "status": event.status,
                        "source_changed": event.source_changed, "evidence": event.evidence,
                        "user_modified": event.user_modified} for event in events],
        }
