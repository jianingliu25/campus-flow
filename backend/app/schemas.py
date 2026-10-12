"""Public fictional fixture contracts, not production storage models."""

from datetime import date as CalendarDate, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailFixture(FixtureModel):
    id: str
    source_id: Literal["demo"]
    subject: str
    sender_name: str
    sender: str
    body_text: str
    received_at: datetime
    category: Literal["academic", "admin", "activity"]
    summary: str
    local_star: bool
    local_read: bool
    tags: list[str]

    @model_validator(mode="after")
    def public_email(self):
        if self.sender.split("@")[-1] not in {"example.com", "example.org"}:
            raise ValueError("Fixture senders must use reserved example domains")
        if self.received_at.tzinfo is None:
            raise ValueError("Fixture received_at must have a timezone")
        return self


class EventFixture(FixtureModel):
    id: str
    source_id: Literal["demo"]
    source_email_id: str
    title: str
    type: Literal["course", "deadline", "activity", "personal"]
    start_at: datetime | None = None
    end_at: datetime | None = None
    date: CalendarDate | None = None
    all_day: bool = False
    location: str | None = None
    status: Literal["confirmed", "needs_confirmation", "superseded"]
    evidence: str
    capacity_remaining: int | None = Field(default=None, ge=0)
    supersedes_event_id: str | None = None

    @model_validator(mode="after")
    def coherent_time(self):
        for value in (self.start_at, self.end_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("Extracted fixture times must be timezone aware")
        if self.end_at is not None and (self.start_at is None or self.end_at <= self.start_at):
            raise ValueError("Event end must follow start")
        if self.status == "confirmed" and self.start_at is None and self.date is None:
            raise ValueError("Confirmed fixture events need a time or date")
        return self


class ProfileFixture(FixtureModel):
    source_id: Literal["demo"]
    fictional: Literal[True]
    display_name: str
    major: str
    grade: str
    preferences: list[str]


class QAFixture(FixtureModel):
    id: str
    query: str
    expected_intent: str
    expected_email_ids: list[str]
    expected_event_ids: list[str]
    expected_facts: list[str]


class FixtureBundle(FixtureModel):
    schema_version: Literal[1]
    fictional: Literal[True]
    reference_now: datetime
    timezone: Literal["Asia/Shanghai"]
    emails: list[EmailFixture]
    events: list[EventFixture]
    profile: ProfileFixture

    @model_validator(mode="after")
    def references(self):
        mail_ids = {mail.id for mail in self.emails}
        event_ids = {event.id for event in self.events}
        if len(mail_ids) != len(self.emails) or len(event_ids) != len(self.events):
            raise ValueError("Duplicate fixture IDs")
        mail_by_id = {mail.id: mail for mail in self.emails}
        for event in self.events:
            if event.source_email_id not in mail_ids:
                raise ValueError("Unknown source email")
            if event.evidence not in mail_by_id[event.source_email_id].body_text:
                raise ValueError("Evidence must be an exact source excerpt")
            if event.supersedes_event_id and event.supersedes_event_id not in event_ids:
                raise ValueError("Unknown superseded event")
        return self
