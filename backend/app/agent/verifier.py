"""Hard source-record verification precedes diagnostic rule scores."""
from datetime import datetime
import re
from zoneinfo import ZoneInfo

from app.agent.tools import conflicts,free_slots


def verify(data,claims,results):
    events={event["id"]:event for event in data.events};mails={mail["id"]:mail for mail in data.emails}
    invalid=set()
    for claim in claims:
        if claim["kind"]=="event":
            event=events.get(claim["id"])
            if not event or event.get("source_id")!=data.source_id or any(event.get(key)!=claim.get(key) for key in ["title","start_at","end_at","date","location","source_email_id"]):invalid.add(claim["task"])
        elif claim["kind"]=="mail":
            mail=mails.get(claim["id"])
            if not mail or mail.get("source_id")!=data.source_id or mail["subject"]!=claim["subject"]:invalid.add(claim["task"])
    for id,result in results.items():
        if result["status"]!="done":continue
        if result["tool"]=="check_conflicts":
            parent=id.split(":")[0]+":events"
            if result["inputs"]!=results.get(parent,{}).get("data"):
                invalid.add(id)
            original=[events[event["id"]] for event in result["inputs"] if event["id"] in events]
            if conflicts(original,ZoneInfo(data.timezone))!=result["data"]:invalid.add(id)
        elif result["tool"]=="find_free_slots" and result["data"].get("window"):
            parent=id.split(":")[0]+":events"
            if result["inputs"]!=results.get(parent,{}).get("data"):
                invalid.add(id)
            original=[events[event["id"]] for event in result["inputs"] if event["id"] in events]
            if free_slots(original,result["data"]["window"],ZoneInfo(data.timezone),result["duration_minutes"])!=result["data"]:invalid.add(id)
    return invalid


def legacy_quality(query,answer,task_values=None):
    checks=[(1.0,len(answer)>10),(.8,not re.search(r"error|failed|失败|错误|无法",answer,re.I)),(.6,bool(answer))]
    if re.search("冲突|重叠",query):checks.append((.8,bool(re.search("有冲突|无冲突|没有冲突",answer))))
    if re.search("时间|几点|日程|安排",query):checks.append((.7,bool(re.search(r"\d{2}:\d{2}|\d{4}-\d{2}-\d{2}",answer))))
    if re.search("哪些|列表|所有",query):checks.append((.5,"•" in answer or "- " in answer))
    if re.search("总结|摘要|对比|计划",query):checks.append((.4,len(answer)>100))
    return sum(weight*passed for weight,passed in checks)/sum(weight for weight,_ in checks)


def event_text(event,timezone):
    zone=ZoneInfo(timezone)
    if event.get("start_at"):
        text=event["start_at"].astimezone(zone).strftime("%Y-%m-%d %H:%M")
        if event.get("end_at"):text+="–"+event["end_at"].astimezone(zone).strftime("%Y-%m-%d %H:%M")
    elif event.get("date"):text=str(event["date"])+( "（全天）" if event.get("all_day") else "（具体时刻未知）")
    else:text="日期与时间未知，待确认"
    return f"{event['title']} · {text}"+(f" · {event['location']}" if event.get("location") else "")
