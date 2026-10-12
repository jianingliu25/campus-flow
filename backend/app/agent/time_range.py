"""Source-zone half-open ranges; missing availability is clarified, never invented."""
from datetime import date,datetime,time,timedelta,timezone
import re
from zoneinfo import ZoneInfo

from app.security.policies import BoundaryError


def local_time(day,clock,zone):
    naive=datetime.combine(day,time.fromisoformat(clock))
    first=naive.replace(tzinfo=zone,fold=0);second=naive.replace(tzinfo=zone,fold=1)
    if first.utcoffset()!=second.utcoffset() or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=naive:
        raise BoundaryError("TIMEZONE_OFFSET_REQUIRED",422)
    return first.astimezone(timezone.utc)


def parse_range(query,now,timezone_name):
    zone=ZoneInfo(timezone_name);today=now.astimezone(zone).date()
    start=end=None
    dates=re.findall(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)",query)
    if len(dates)>2:raise BoundaryError("AMBIGUOUS_QUERY_DATES",422)
    if dates:
        start=date.fromisoformat(dates[0]);end=date.fromisoformat(dates[-1])+timedelta(days=1)
        if end<=start:raise BoundaryError("INVALID_QUERY_RANGE",422)
    elif "下周" in query or "本周" in query:
        start=today-timedelta(days=today.weekday())+timedelta(days=7 if "下周" in query else 0);end=start+timedelta(days=7)
    elif "后天" in query:start=today+timedelta(days=2);end=start+timedelta(days=1)
    elif "明天" in query:start=today+timedelta(days=1);end=start+timedelta(days=1)
    elif "今天" in query:start=today;end=start+timedelta(days=1)
    else:
        match=re.search("周([一二三四五六日天])",query)
        if match:
            offset="一二三四五六日".find("日" if match[1]=="天" else match[1])
            start=today-timedelta(days=today.weekday())+timedelta(days=offset);end=start+timedelta(days=1)
    if start and (end-start).days>366:raise BoundaryError("QUERY_RANGE_TOO_LARGE",422)
    clocks=re.findall(r"(?<!\d)([0-2]?\d:[0-5]\d)(?!\d)",query)
    window=None
    if start and end==start+timedelta(days=1) and len(clocks)==2:
        left,right=local_time(start,clocks[0],zone),local_time(start,clocks[1],zone)
        if right<=left:raise BoundaryError("INVALID_AVAILABILITY_WINDOW",422)
        window=(left,right)
    return {"start_day":start,"end_day":end,"window":window,"timezone":timezone_name}


def legacy_datetime(value):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}",value):value+="T00:00:00Z"
    stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
    return (stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp).astimezone(timezone.utc)
