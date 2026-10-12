"""Code-owned read tools; mathematical dependencies consume prior structured outputs."""
from datetime import datetime,time,timedelta,timezone
import math
import re
from zoneinfo import ZoneInfo


def tokens(text):
    output=set(re.findall(r"[A-Za-z0-9]+",text.lower()))
    for chunk in re.findall(r"[\u4e00-\u9fff]+",text):
        output.update(chunk[index:index+2] for index in range(len(chunk)-1))
        if len(chunk)==1:output.add(chunk)
    return output


def similarity(query,text):
    a,b=tokens(query),tokens(text)
    return len(a&b)/math.sqrt(len(a)*len(b)) if a and b else 0.0


def day_of(event,zone):
    return event["start_at"].astimezone(zone).date() if event.get("start_at") else event.get("date")


def interval(event,zone):
    if event.get("all_day") and event.get("date"):
        start=datetime.combine(event["date"],time.min,tzinfo=zone).astimezone(timezone.utc)
        end=datetime.combine(event["date"]+timedelta(days=1),time.min,tzinfo=zone).astimezone(timezone.utc)
        return start,end
    if event.get("start_at") and event.get("end_at") and event["end_at"]>event["start_at"]:
        return event["start_at"],event["end_at"]
    return None


def events(data,params):
    zone=ZoneInfo(data.timezone);start,end=params.get("start_day"),params.get("end_day")
    result=[]
    for event in data.events:
        if params.get("type") and event["type"]!=params["type"]:continue
        if params.get("keyword") and similarity(params["keyword"],event["title"]+" "+event.get("evidence",""))<=0:continue
        day=day_of(event,zone)
        span=interval(event,zone)
        if start and day and not start<=day<end:
            if not (span and span[0].astimezone(zone).date()<end and span[1].astimezone(zone).date()>=start):continue
        result.append(event)
    return sorted(result,key=lambda event:(day_of(event,zone) is None,day_of(event,zone) or __import__('datetime').date.max,event["id"]))


def search_emails(data,keyword="",starred=False):
    candidates=[mail for mail in data.emails if not starred or mail["local_star"]]
    if keyword:
        candidates=[mail for mail in candidates if similarity(keyword,mail["subject"]+" "+mail.get("summary","")+" "+mail.get("body_excerpt",""))>0]
        candidates.sort(key=lambda mail:(-similarity(keyword,mail["subject"]+" "+mail.get("summary","")),mail["id"]))
    return candidates[:20]


def conflicts(values,zone):
    pairs=[];uncertain=[]
    for index,event in enumerate(values):
        if event["type"]=="deadline":continue  # date-only/point deadlines are not occupied intervals
        left=interval(event,zone)
        if left is None or event["status"]!="confirmed":uncertain.append(event["id"]);continue
        for other in values[index+1:]:
            right=interval(other,zone)
            if other["type"]=="deadline" or other["status"]!="confirmed" or right is None:continue
            start,end=max(left[0],right[0]),min(left[1],right[1])
            if start<end:pairs.append({"left":event["id"],"right":other["id"],"start":start,"end":end})
    return {"state":"conflict" if pairs else "insufficient_data" if uncertain else "no_conflict","pairs":pairs,"uncertain":uncertain}


def free_slots(values,window,zone,duration_minutes=30):
    if window is None:return {"needs_input":True,"slots":[],"uncertain":[]}
    start,end=window;busy=[];uncertain=[]
    for event in values:
        if event["type"]=="deadline":continue
        span=interval(event,zone)
        if not span or event["status"]!="confirmed":uncertain.append(event["id"]);continue
        left,right=max(start,span[0]),min(end,span[1])
        if left<right:busy.append((left,right))
    merged=[]
    for left,right in sorted(busy):
        if merged and left<=merged[-1][1]:merged[-1]=(merged[-1][0],max(right,merged[-1][1]))
        else:merged.append((left,right))
    slots=[];cursor=start
    for left,right in merged+[(end,end)]:
        if left-cursor>=timedelta(minutes=duration_minutes):slots.append({"start":cursor,"end":left})
        cursor=max(cursor,right)
    return {"needs_input":False,"slots":slots,"uncertain":uncertain,"window":window}
