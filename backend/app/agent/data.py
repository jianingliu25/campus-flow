"""One bounded SQL/fixture snapshot; original source records, never old assistant answers."""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select,func

from app.ingest.pipeline import source_timezone
from app.models import CampusEvent,Email
from app.security.policies import scoped_policy,scoped_source
from app.storage import owned_query


@dataclass
class Snapshot:
    source_id:str
    timezone:str
    now:datetime
    emails:list[dict]
    events:list[dict]
    policy_version:int=1
    generation:int=1
    limited:bool=False

    @classmethod
    def sql(cls,database,ctx,now=None):
        with database.transaction() as session:
            session.connection().exec_driver_sql("BEGIN")
            source,policy=scoped_source(session,ctx),scoped_policy(session,ctx)
            zone=source_timezone(session,ctx)
            rows=session.execute(owned_query(Email,ctx).with_only_columns(Email.id,Email.source_id,Email.subject,Email.sender,
                Email.summary,func.substr(Email.body_text,1,2000),Email.local_star,Email.category,Email.received_at).order_by(Email.sorting_timestamp.desc(),Email.id).limit(5001)).all()
            emails=[{"id":row[0],"source_id":row[1],"subject":row[2],"sender":row[3],"summary":row[4] or "",
                     "body_excerpt":row[5] or "","local_star":row[6],"category":row[7],"received_at":row[8]} for row in rows[:5000]]
            values=list(session.scalars(owned_query(CampusEvent,ctx).where(CampusEvent.status!="superseded").order_by(CampusEvent.created_at,CampusEvent.id).limit(5001)))
            events=[{"id":item.id,"source_id":item.source_id,"source_email_id":item.source_email_id,"title":item.title,
                     "type":item.type,"start_at":item.start_at_utc,"end_at":item.end_at_utc,"date":item.event_date or item.deadline_date,
                     "all_day":item.all_day,"location":item.location,"status":item.status,"evidence":item.evidence or ""} for item in values[:5000]]
            return cls(source.id,zone,now or datetime.now(timezone.utc),emails,events,policy.version,source.index_generation,len(rows)>5000 or len(values)>5000)

    @classmethod
    def fixtures(cls,bundle,stars=None):
        data=bundle.model_dump() if hasattr(bundle,"model_dump") else bundle
        now=data.get("reference_now") or datetime.fromisoformat(data["meta"]["demo_date"]+"T09:00:00+08:00")
        emails=[{**mail,"body_excerpt":mail.get("body_text","")[:2000],"local_star":mail["id"] in stars if stars is not None else mail["local_star"]} for mail in data["emails"]]
        events=[event for event in data["events"] if event["status"]!="superseded"]
        for event in events:
            for key in ["start_at","end_at"]:
                if isinstance(event.get(key),str):event[key]=datetime.fromisoformat(event[key].replace("Z","+00:00"))
            if isinstance(event.get("date"),str):event["date"]=__import__('datetime').date.fromisoformat(event["date"])
        return cls("demo",data.get("timezone",data.get("meta",{}).get("timezone","Asia/Shanghai")),now,emails,events)
