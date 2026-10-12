"""Explicit source-local membership; joining an activity is never remote registration."""
from app.models import CalendarSelection
from app.storage import owned_query


def selections(session, ctx):
    return {row.event_id: row.selected for row in session.scalars(owned_query(CalendarSelection, ctx))}


def included(event, selected):
    return selected.get(event.id, event.type != "activity" or event.user_modified)
