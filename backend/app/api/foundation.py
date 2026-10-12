"""Configuration, scoped reads and local mail flags; no connector sync routes."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from app.models import CampusEvent, Email, IndexOutbox, Source, SourcePolicy, utcnow
from app.security.http import local_session, source_context
from app.security.policies import BoundaryError, SourceContext, scoped_policy, scoped_source
from app.security.session import COOKIE_NAME
from app.storage import create_source, list_emails, owned_query

router = APIRouter(prefix="/api")


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateSource(StrictBody):
    kind: Literal["fixture", "local_files", "imap", "mcp"]
    display_name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    timezone: str | None = Field(default=None, max_length=80)


class Scope(StrictBody):
    recent_days: int = Field(default=30, ge=1, le=365)
    max_messages: int = Field(default=200, ge=1, le=10000)
    folders: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=100)


class PolicyPatch(StrictBody):
    expected_version: int = Field(ge=1)
    scope: Scope | None = None
    allow_remote_processing: bool | None = None
    consent_fingerprint: str | None = Field(default=None, max_length=64)
    retain_body: bool | None = None
    enable_qa_memory: bool | None = None
    enable_implicit_profile: bool | None = None


def db(request):
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise BoundaryError("STORE_UNAVAILABLE", 503)
    return database


def session_info(request, session):
    config = request.app.state.provider_config
    return {"csrf_token": session.csrf_token, "workspace_id": session.workspace_id,
            "active_source_id": session.active_source_id, "ttl_seconds": int(max(0, session.expires_at - request.app.state.sessions.clock())),
            "provider_mode": config.mode, "provider_fingerprint": config.fingerprint,
            "remote_globally_enabled": config.global_remote, "workspace_timezone": request.app.state.timezone,
            "milestone": "M9-offline"}


@router.post("/session")
def bootstrap_session(request: Request, response: Response):
    manager = request.app.state.sessions
    token = request.cookies.get(COOKIE_NAME)
    try:
        session = manager.get(token)
    except BoundaryError:
        token, session = manager.create()
    response.set_cookie(COOKIE_NAME, token, max_age=int(max(0, session.expires_at - manager.clock())),
                        httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/api")
    response.headers["Cache-Control"] = "no-store"
    return session_info(request, session)


@router.get("/session")
def get_session(request: Request, response: Response, session=Depends(local_session)):
    response.headers["Cache-Control"] = "no-store"
    return session_info(request, session)


@router.delete("/session", status_code=204)
def logout(request: Request, response: Response, session=Depends(local_session)):
    request.app.state.credentials.clear_owner(session)
    request.app.state.previews.clear_owner(session)
    request.app.state.sessions.revoke(request.cookies[COOKIE_NAME])
    response.delete_cookie(COOKIE_NAME, path="/api")


@router.post("/sources/deactivate")
def deactivate_source(request: Request, session=Depends(local_session)):
    request.app.state.previews.clear_owner(session)
    session.active_source_id = None
    return {"active_source_id": None}


def source_view(source):
    # Do not serialize the ORM object, safe_config or credential_ref wholesale.
    return {"id": source.id, "kind": source.kind, "display_name": source.display_name,
            "status": source.status, "policy_version": source.policy_version, "connector_enabled": source.kind in {"imap","mcp"},
            "timezone": source.safe_config.get("timezone")}


def policy_view(policy):
    return {"source_id": policy.source_id, "version": policy.version, "scope": policy.scope,
            "allow_remote_processing": policy.allow_remote_processing, "consent_fingerprint": policy.consent_fingerprint,
            "retain_body": policy.retain_body, "enable_qa_memory": policy.enable_qa_memory,
            "enable_implicit_profile": policy.enable_implicit_profile}


@router.get("/sources")
def sources(request: Request, session=Depends(local_session)):
    with db(request).transaction() as transaction:
        return [source_view(source) for source in transaction.scalars(select(Source).where(Source.workspace_id == session.workspace_id, Source.status != "deleted").order_by(Source.created_at))]


@router.post("/sources", status_code=201)
def add_source(body: CreateSource, request: Request, session=Depends(local_session)):
    with db(request).transaction() as transaction:
        source = create_source(transaction, session.workspace_id, body.kind, body.display_name.strip())
        if body.timezone:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                ZoneInfo(body.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise BoundaryError("INVALID_TIMEZONE", 422) from None
            source.safe_config = {"timezone": body.timezone}
        return source_view(source)


@router.post("/sources/{source_id}/activate")
def activate_source(source_id: str, request: Request, session=Depends(local_session)):
    with db(request).transaction() as transaction:
        scoped_source(transaction, SourceContext(session.workspace_id, source_id))
    if session.active_source_id != source_id:
        request.app.state.previews.clear_owner(session)
    session.active_source_id = source_id
    return {"active_source_id": source_id}


@router.get("/sources/{source_id}/policy")
def get_policy(source_id: str, request: Request, session=Depends(local_session)):
    with db(request).transaction() as transaction:
        return policy_view(scoped_policy(transaction, SourceContext(session.workspace_id, source_id)))


@router.patch("/sources/{source_id}/policy")
def patch_policy(source_id: str, body: PolicyPatch, request: Request, session=Depends(local_session)):
    config = request.app.state.provider_config
    ctx = SourceContext(session.workspace_id, source_id)
    updates = body.model_dump(exclude_none=True, exclude={"expected_version", "consent_fingerprint"})
    if not updates:
        raise BoundaryError("EMPTY_POLICY_UPDATE", 422)
    with db(request).transaction() as transaction:
        policy = scoped_policy(transaction, ctx)
        if policy.version != body.expected_version:
            raise BoundaryError("POLICY_VERSION_CHANGED", 409)
        if "scope" in updates and updates["scope"] != policy.scope:
            updates.update(allow_remote_processing=False, consent_fingerprint=None)
        if body.allow_remote_processing is True:
            if not config.global_remote or config.mode != "cloud" or body.consent_fingerprint != config.fingerprint:
                raise BoundaryError("REMOTE_CONSENT_NOT_CONFIGURED")
            updates.update(allow_remote_processing=True, consent_fingerprint=config.fingerprint)
        elif body.allow_remote_processing is False:
            updates.update(allow_remote_processing=False, consent_fingerprint=None)
        updates.update(version=policy.version + 1, updated_at=utcnow())
        result = transaction.execute(update(SourcePolicy).where(SourcePolicy.id == policy.id, SourcePolicy.version == body.expected_version).values(**updates))
        if result.rowcount != 1:
            raise BoundaryError("POLICY_VERSION_CHANGED", 409)
        source = scoped_source(transaction, ctx)
        source.policy_version = body.expected_version + 1
        transaction.flush()
        transaction.refresh(policy)
        return policy_view(policy)


@router.get("/emails")
def emails(request: Request, limit: int = Query(default=50, ge=1, le=200), ctx=Depends(source_context)):
    with db(request).transaction() as transaction:
        return [{"id": mail.id, "source_id": mail.source_id, "subject": mail.subject, "summary": mail.summary,
                 "received_at": mail.received_at, "category": mail.category, "date_status": mail.date_status,
                 "extraction_status": mail.extraction_status, "extraction_method": mail.extraction_method} for mail in list_emails(transaction, ctx, limit)]


@router.get("/emails/{email_id}")
def email_detail(email_id: str, request: Request, ctx=Depends(source_context)):
    with db(request).transaction() as transaction:
        scoped_source(transaction, ctx)
        mail = transaction.scalar(owned_query(Email, ctx).where(Email.id == email_id))
        if mail is None:
            raise BoundaryError("EMAIL_NOT_FOUND", 404)
        return {"id": mail.id, "source_id": mail.source_id, "subject": mail.subject, "sender": mail.sender,
                "body_text": mail.body_text, "summary": mail.summary, "received_at": mail.received_at,
                "import_warnings": mail.import_warnings, "source_locator": mail.source_locator,
                "extraction_warnings": mail.extraction_warnings, "extraction_status": mail.extraction_status,
                "local_star": mail.local_star, "local_read": mail.local_read, "date_status": mail.date_status,
                "extraction_method": mail.extraction_method}


class MailFlags(StrictBody):
    local_star: bool | None = None
    local_read: bool | None = None


@router.patch("/emails/{email_id}/flags")
def update_flags(email_id: str, body: MailFlags, request: Request, ctx=Depends(source_context)):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise BoundaryError("EMPTY_FLAGS_UPDATE", 422)
    with db(request).transaction() as transaction:
        scoped_source(transaction, ctx)
        result = transaction.execute(update(Email).where(Email.id == email_id, Email.source_id == ctx.source_id,
                                                        Email.workspace_id == ctx.workspace_id).values(**changes))
        if result.rowcount != 1:
            raise BoundaryError("EMAIL_NOT_FOUND", 404)
        mail = transaction.get(Email, email_id)
        return {"id": mail.id, "local_star": mail.local_star, "local_read": mail.local_read}


@router.get("/events")
def events(request: Request, limit: int = Query(default=50, ge=1, le=200), ctx=Depends(source_context)):
    with db(request).transaction() as transaction:
        scoped_source(transaction, ctx)
        return [{"id": event.id, "source_id": event.source_id, "title": event.title, "status": event.status,
                 "start_at_utc": event.start_at_utc, "end_at_utc": event.end_at_utc, "deadline_date": event.deadline_date,
                 "event_date": event.event_date, "location": event.location, "type": event.type,
                 "source_email_id": event.source_email_id, "source_changed": event.source_changed,
                 "all_day": event.all_day}
                for event in transaction.scalars(owned_query(CampusEvent, ctx).order_by(CampusEvent.created_at).limit(limit))]


@router.get("/index-status")
def index_status(request: Request, ctx=Depends(source_context)):
    with db(request).transaction() as transaction:
        scoped_source(transaction, ctx)
        counts = transaction.execute(select(IndexOutbox.status, func.count()).where(
            IndexOutbox.workspace_id == ctx.workspace_id, IndexOutbox.source_id == ctx.source_id).group_by(IndexOutbox.status)).all()
        return {"source_id": ctx.source_id, "jobs": dict(counts), "worker_auto_start": False, "vector_search_enabled": True, "retrieval_mode":"local-lexical"}
