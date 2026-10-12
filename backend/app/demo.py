"""Read public fixtures only. No LLM, mailbox, embedding, or database access."""

import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import ROOT, Settings
from app.schemas import FixtureBundle


def load_fixtures() -> FixtureBundle:
    directory = ROOT / "fixtures"
    load = lambda filename: json.loads((directory / filename).read_text(encoding="utf-8"))
    return FixtureBundle.model_validate({
        **load("manifest.json"),
        "emails": load("emails.json"),
        "events": load("extractions.json"),
        "profile": load("profile.json"),
    })


def demo_payload(settings: Settings) -> dict:
    fixture = load_fixtures()
    shift = settings.demo_date - fixture.reference_now.date()

    def rebase(value):
        # Only public fixture strings are rebased. This is never an ingest parser.
        if isinstance(value, str):
            return re.sub(r"\b2026-\d{2}-\d{2}\b", lambda match: (date.fromisoformat(match[0]) + shift).isoformat(), value)
        if isinstance(value, list):
            return [rebase(item) for item in value]
        if isinstance(value, dict):
            return {key: rebase(item) for key, item in value.items()}
        return value

    data = rebase(fixture.model_dump(mode="json"))
    day = settings.demo_date.isoformat()
    week_end = (settings.demo_date + timedelta(days=7)).isoformat()
    active = [event for event in data["events"] if event["status"] == "confirmed"]
    def event_day(event):
        if event["start_at"]:
            return datetime.fromisoformat(event["start_at"].replace("Z", "+00:00")).astimezone(ZoneInfo(settings.timezone)).date().isoformat()
        return event["date"] or ""
    data["meta"] = {
        "milestone": "M2", "source_id": "demo", "source_name": "虚构校园邮箱",
        "provider": "FixtureProvider", "retrieval": "预置样例（无向量检索）",
        "fictional": True, "remote_processing": False, "connected_accounts": 0,
        "timezone": settings.timezone, "demo_date": day,
        "evaluation_reference_now": fixture.reference_now.isoformat(),
    }
    data["stats"] = {
        "today_events": sum(event_day(event) == day for event in active),
        "upcoming_deadlines": sum(event["type"] == "deadline" and day <= event_day(event) < week_end for event in active),
        "unread_emails": sum(not mail["local_read"] for mail in data["emails"]),
        "needs_confirmation": sum(event["status"] == "needs_confirmation" for event in data["events"]),
    }
    data["recommendations"] = [event for event in active if event["type"] == "activity" and event_day(event) >= day][:5]
    return data
