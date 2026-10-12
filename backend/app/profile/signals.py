"""Opt-in fixed campus topics, decayed locally; suggestions never silently become preferences."""
import math
import re
from datetime import timezone
from app.models import EventLog, utcnow
from app.storage import owned_query

TOPICS = {"NLP": r"\bnlp\b|自然语言", "机器学习": r"机器学习|machine learning", "开源": r"开源|open source",
          "运动": r"运动|篮球|足球", "职业发展": r"职业|招聘|实习"}


def safe_memory(query):
    return not re.search(r"密码|令牌|密钥|password|bearer|api.?key|token|sk-[A-Za-z0-9]|eyJ[A-Za-z0-9]|@[A-Za-z0-9.-]+|\b\d{7,}\b", query, re.I)


def record(session, ctx, query):
    for topic, pattern in TOPICS.items():
        if re.search(pattern, query, re.I):
            session.add(EventLog(workspace_id=ctx.workspace_id, source_id=ctx.source_id, action="interest_signal",
                                 safe_metadata={"topic": topic}))


def suggestions(session, ctx):
    now = utcnow(); totals = {}; counts = {}
    for row in session.scalars(owned_query(EventLog, ctx).where(EventLog.action == "interest_signal").order_by(EventLog.created_at.desc()).limit(1000)):
        topic = row.safe_metadata.get("topic")
        if topic not in TOPICS:
            continue
        age = max(0, (now - row.created_at.astimezone(timezone.utc)).total_seconds() / 86400)
        totals[topic] = totals.get(topic, 0) + math.exp(-age / 30)
        counts[topic] = counts.get(topic, 0) + 1
    return [{"tag": topic, "count": counts[topic], "weight": round(weight, 4), "requires_acceptance": True}
            for topic, weight in sorted(totals.items(), key=lambda pair: -pair[1]) if counts[topic] >= 5 and weight >= 3]
