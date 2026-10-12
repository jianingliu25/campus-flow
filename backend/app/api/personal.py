"""Owned calendar edits, transparent recommendations and opt-in local history."""
from datetime import date, datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import delete

from app.api.foundation import StrictBody, db
from app.agent.data import Snapshot
from app.agent.tools import conflicts, similarity
from app.agent.time_range import local_time
from app.calendar import selections, included
from app.ingest.pipeline import source_timezone
from app.models import CalendarSelection, CampusEvent, Profile, QALog, EventLog, utcnow
from app.profile.signals import suggestions
from app.security.http import source_context
from app.security.policies import BoundaryError, scoped_source, scoped_policy
from app.storage import owned_query

router = APIRouter(prefix="/api")


class Selection(StrictBody):
    selected: bool


class Edit(StrictBody):
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300, pattern=r"\S")
    type: Literal["course", "deadline", "activity", "personal"]
    start_at: str | None = Field(default=None, max_length=40)
    end_at: str | None = Field(default=None, max_length=40)
    date: str | None = Field(default=None, max_length=10)
    all_day: bool = False
    location: str | None = Field(default=None, max_length=300)
    status: Literal["confirmed", "needs_confirmation"] = "confirmed"


def stamp(value, zone):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return local_time(parsed.date(), parsed.time().isoformat(), ZoneInfo(zone))
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise BoundaryError("INVALID_EVENT_TIME", 422) from None


@router.put("/events/{event_id}/selection")
def select_event(event_id: str, body: Selection, request: Request, ctx=Depends(source_context)):
    with db(request).transaction() as session:
        scoped_source(session, ctx)
        event = session.scalar(owned_query(CampusEvent, ctx).where(CampusEvent.id == event_id))
        if not event or event.status == "superseded":
            raise BoundaryError("EVENT_NOT_FOUND", 404)
        row = session.scalar(owned_query(CalendarSelection, ctx).where(CalendarSelection.event_id == event_id))
        if row is None:
            row = CalendarSelection(workspace_id=ctx.workspace_id, source_id=ctx.source_id, event_id=event_id)
            session.add(row)
        row.selected, row.updated_at = body.selected, utcnow()
    return {"event_id": event_id, "in_calendar": body.selected, "remote_registration": False}


@router.patch("/events/{event_id}")
def edit_event(event_id: str, body: Edit, request: Request, ctx=Depends(source_context)):
    with db(request).transaction() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        scoped_source(session, ctx)
        event = session.scalar(owned_query(CampusEvent, ctx).where(CampusEvent.id == event_id))
        if not event or event.status == "superseded":
            raise BoundaryError("EVENT_NOT_FOUND", 404)
        if event.revision != body.expected_revision:
            raise BoundaryError("EVENT_REVISION_CHANGED", 409)
        zone = source_timezone(session, ctx)
        start, end = stamp(body.start_at, zone), stamp(body.end_at, zone)
        try:
            day = date.fromisoformat(body.date) if body.date else None
        except ValueError:
            raise BoundaryError("INVALID_EVENT_DATE", 422) from None
        if (end and (not start or end <= start)) or (body.all_day and (not day or start or end)):
            raise BoundaryError("INVALID_EVENT_INTERVAL", 422)
        if body.status == "confirmed" and not (start or day):
            raise BoundaryError("EVENT_TIME_REQUIRED", 422)
        event.title, event.type, event.location, event.status = body.title.strip(), body.type, body.location, body.status
        event.start_at_utc, event.end_at_utc, event.event_date = start, end, day
        event.deadline_date = day if body.type == "deadline" else None
        event.all_day, event.source_timezone = body.all_day, zone
        event.user_modified, event.source_changed = True, False
        event.revision += 1
        revision = event.revision
    return {"id": event_id, "revision": revision, "user_modified": True}


class Preferences(StrictBody):
    tags: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(max_length=20)


@router.get("/profile")
def profile(request: Request, ctx=Depends(source_context)):
    with db(request).transaction() as session:
        scoped_source(session, ctx)
        row = session.scalar(owned_query(Profile, ctx))
        return {"source_id": ctx.source_id, "tags": row.explicit_preferences.get("tags", []) if row else [],"suggestions": suggestions(session,ctx) if scoped_policy(session,ctx).enable_implicit_profile else []}


@router.put("/profile")
def put_profile(body: Preferences, request: Request, ctx=Depends(source_context)):
    with db(request).transaction() as session:
        scoped_source(session, ctx)
        row = session.scalar(owned_query(Profile, ctx))
        if row is None:
            row = Profile(workspace_id=ctx.workspace_id, source_id=ctx.source_id)
            session.add(row)
        row.explicit_preferences = {"tags": list(dict.fromkeys(tag.strip() for tag in body.tags if tag.strip()))}
        row.updated_at = utcnow()
    return {"saved": True}


@router.get("/recommendations")
def recommendations(request: Request, ctx=Depends(source_context)):
    data = Snapshot.sql(db(request), ctx)
    with db(request).transaction() as session:
        row = session.scalar(owned_query(Profile, ctx))
        tags = row.explicit_preferences.get("tags", []) if row else []
    zone = ZoneInfo(data.timezone)
    calendar = [event for event in data.events if event.get("in_calendar", True)]
    result = []
    for event in data.events:
        day = event["start_at"].astimezone(zone).date() if event["start_at"] else event["date"]
        if event["type"] != "activity" or event["status"] != "confirmed" or not day or day < data.now.astimezone(zone).date():
            continue
        rule = max((similarity(tag, event["title"] + " " + event["evidence"]) for tag in tags), default=0)
        freshness = 1 / (1 + (day - data.now.astimezone(zone).date()).days / 30)
        collision = conflicts([event] + [other for other in calendar if other["id"] != event["id"]], zone)
        result.append({**event, "score": round(.3 * rule + .2 * freshness, 6), "rule_score": rule,
                       "freshness": freshness, "semantic_score": None,
                       "conflicts": [pair for pair in collision["pairs"] if event["id"] in {pair["left"], pair["right"]}],
                       "reason": "兴趣关键词与时间距离" if tags else "尚未设置兴趣，按时间距离排序"})
    result.sort(key=lambda item: (-item["score"], item["id"]))
    return {"items": result[:20], "mode": "keyword-cold-start", "score_is_probability": False,
            "semantic_model_validated": False, "limited": data.limited, "remote_registration": False}


@router.get("/history")
def history(request: Request, ctx=Depends(source_context)):
    with db(request).transaction() as session:
        scoped_source(session, ctx)
        return {"items": [{"id": row.id, "question": row.question, "answer": row.answer, "created_at": row.created_at}
                          for row in session.scalars(owned_query(QALog, ctx).order_by(QALog.created_at.desc()).limit(100))]}


@router.delete("/history")
def clear_history(request: Request, ctx=Depends(source_context)):
    with db(request).transaction() as session:
        scoped_source(session, ctx)
        session.execute(delete(QALog).where(QALog.source_id == ctx.source_id, QALog.workspace_id == ctx.workspace_id))
    return {"cleared": True}


@router.delete("/profile/signals")
def clear_signals(request: Request,ctx=Depends(source_context)):
    with db(request).transaction() as session:
        scoped_source(session,ctx)
        session.execute(delete(EventLog).where(EventLog.source_id==ctx.source_id,EventLog.workspace_id==ctx.workspace_id,EventLog.action=="interest_signal"))
    return {"cleared":True}
