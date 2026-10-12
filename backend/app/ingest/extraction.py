"""Conservative candidate validation and an explicitly labeled rule fallback."""

from datetime import date, datetime, timedelta, timezone
import re
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    type: Literal["course", "deadline", "activity", "personal"]
    start_time: str | None = None
    end_time: str | None = None
    date: str | None = None
    all_day: bool = False
    location: str | None = Field(default=None, max_length=300)
    evidence: str = Field(min_length=1, max_length=4000)


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["academic", "admin", "activity"]
    summary: str = Field(max_length=2000)
    events: list[dict] = Field(default_factory=list, max_length=20)


DATES = re.compile(r"(?<!\d)(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?(?!\d)")
STAMPS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?")
TIMES = re.compile(r"(?<!\d)([0-2]?\d):([0-5]\d)(?!\d)")


def evidence_dates(text, received, zone):
    dates = {date(int(y), int(m), int(d)) for y, m, d in DATES.findall(text)}
    if received:
        reference = received.astimezone(zone).date()
        for word, offset in [("今天", 0), ("明天", 1), ("后天", 2)]:
            if word in text:
                dates.add(reference + timedelta(days=offset))
    return dates


def timestamp(value, zone):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value and " " not in value:
        raise ValueError("A date is not a timestamp")
    return (stamp.replace(tzinfo=zone) if stamp.tzinfo is None else stamp).astimezone(timezone.utc)


def validate_candidates(extraction, body, received, timezone_name):
    zone = ZoneInfo(timezone_name)
    accepted, warnings = [], []
    for raw in extraction.events:
        try:
            candidate = Candidate.model_validate(raw)
            if candidate.evidence not in body or (candidate.location and candidate.location not in candidate.evidence):
                raise ValueError("Ungrounded evidence/location")
            dates = evidence_dates(candidate.evidence, received, zone)
            day = date.fromisoformat(candidate.date) if candidate.date else None
            start = timestamp(candidate.start_time, zone) if candidate.start_time else None
            end = timestamp(candidate.end_time, zone) if candidate.end_time else None
            if day and day not in dates:
                raise ValueError("Ungrounded date")
            if day and start and day != start.astimezone(zone).date():
                raise ValueError("Conflicting event date")
            raw_stamps = {timestamp(stamp, zone) for stamp in STAMPS.findall(candidate.evidence)}
            for value in [start, end]:
                if value is None or value in raw_stamps:
                    continue
                if value.astimezone(zone).date() not in dates or value.astimezone(zone).strftime("%H:%M") not in {f"{int(h):02}:{m}" for h, m in TIMES.findall(candidate.evidence)}:
                    raise ValueError("Ungrounded timestamp")
            if end and (start is None or end <= start):
                raise ValueError("Invalid interval")
            status = "confirmed" if start or (day and (candidate.type == "deadline" or candidate.all_day)) else "needs_confirmation"
            # Multiple dates without a grounded instant are ambiguous (including amendments).
            if len(dates) > 1 and not start:
                status = "needs_confirmation"
            accepted.append({"title": candidate.title, "type": candidate.type, "start_at_utc": start,
                             "end_at_utc": end, "deadline_date": day if candidate.type == "deadline" else None,
                             "event_date": day, "all_day": candidate.all_day, "location": candidate.location,
                             "source_timezone": timezone_name, "status": status, "evidence": candidate.evidence})
        except (ValueError, TypeError, OverflowError):
            warnings.append("INVALID_EVENT_DROPPED")
    return accepted, warnings


def rule_extract(subject, body, received, timezone_name):
    text = subject + "\n" + body
    category = "admin" if re.search("缴费|宿舍|奖学金|选课|行政|学费", text) else "activity" if re.search("活动|招新|篮球|音乐|志愿", text) else "academic"
    result = Extraction(category=category, summary=body[:160], events=[])
    if not body or not re.search("截止|DDL|提交|课程|上课|讲座|组会|活动|招新|比赛|预约|安排|时间|讨论", text, re.I):
        return result
    kind = "deadline" if re.search("截止|DDL|提交", text, re.I) else "course" if re.search("课程|上课|讲座|组会", text) else "activity" if category == "activity" else "personal"
    evidence = body[:4000]
    values = {"title": subject[:200], "type": kind, "evidence": evidence}
    try:
        dates = sorted(evidence_dates(evidence, received, ZoneInfo(timezone_name)))
        stamps = STAMPS.findall(evidence)
        if stamps:
            values["start_time"] = stamps[0]
            if len(stamps) == 2:
                values["end_time"] = stamps[1]
            elif len(stamps) == 1 and len(dates) == 1:
                # A full dated start may be followed by a clock-only end.
                remaining = evidence.replace(stamps[0], "", 1)
                clocks = TIMES.findall(remaining)
                first = timestamp(stamps[0], ZoneInfo(timezone_name)).astimezone(ZoneInfo(timezone_name))
                if len(clocks) == 1 and tuple(map(int, clocks[0])) > (first.hour, first.minute):
                    values["end_time"] = f"{first.date()}T{int(clocks[0][0]):02}:{clocks[0][1]}:00"
            elif len(stamps) > 2:
                values.pop("start_time")  # one email may contain multiple separate events
        elif len(dates) == 1:
            values["date"] = dates[0].isoformat()
            times = TIMES.findall(evidence)
            if len(times) == 1:
                values["start_time"] = f"{dates[0]}T{int(times[0][0]):02}:{times[0][1]}:00"
            elif len(times) > 1:
                # A clock-only range is not allowed to silently cross midnight.
                if len(times) == 2 and tuple(map(int, times[1])) > tuple(map(int, times[0])):
                    values["start_time"] = f"{dates[0]}T{int(times[0][0]):02}:{times[0][1]}:00"
                    values["end_time"] = f"{dates[0]}T{int(times[1][0]):02}:{times[1][1]}:00"
            values["all_day"] = "全天" in evidence
    except (ValueError, OverflowError):
        pass
    result.events = [values]
    return result
