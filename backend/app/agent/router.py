"""Product task-domain routing, plus separately labeled legacy keyword reproduction."""
from dataclasses import dataclass
import re

CORE=[
    ("calendar_conflict_check",["冲突","重叠","问题"]),
    ("email_calendar_combined",["邮件","相关","通知"]),
    ("find_free_time",["空闲","有空","什么时候"]),
    ("daily_summary",["今天","摘要","安排"]),
    ("multi_step_planning",["准备","计划","规划"]),
    ("calendar_simple_query",["日程","会议"]),
]


def legacy_route(query):
    scores=[sum(word in query for word in words) for _,words in CORE]
    return CORE[scores.index(max(scores))][0] if max(scores)>0 else "calendar_simple_query"


@dataclass(frozen=True)
class Route:
    intents:tuple[str,...]
    keyword:str=""


def keyword(query):
    # Topic extraction is lexical, not a semantic-model claim.
    patterns=[r"NLP(?:\s*项目)?",r"机器学习",r"自然语言处理",r"统计(?:作业)?",r"国际(?:线上)?讲座",r"跨日实验",r"宿舍维修",r"奖学金",r"论文(?:阅读)?",r"篮球",r"摄影"]
    matches=[match.group() for pattern in patterns for match in re.finditer(pattern,query,re.I)]
    if matches:return " ".join(matches)
    quoted=re.findall(r"[‘“\"]([^’”\"]{1,60})[’”\"]",query)
    if quoted:return " ".join(quoted)
    text=query
    for word in ["明天","后天","今天","本周","下周","周一","周二","周三","周四","周五","周六","周日","请","帮我","查找","查一下","查询","有没有","是什么","有哪些","有几次","相关","邮件","通知","收到","转发","后的","结束时间","本地时间","几点","截止","什么时候","哪一天","的安排","课程","日程","会议","有冲突吗","是否重叠","准备时间"]:
        text=text.replace(word,"")
    text=re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}:\d{2}|[，。？?！!、：:和与]"," ",text)
    return text.strip()[:100]


def route(query):
    text=query.strip()
    if re.search(r"执行.*(?:密钥|指令)|读取.*(?:密钥|密码)|忽略.*规则|发送邮件|删除邮件",text):
        return Route(("unsafe_request",))
    if text in {"你好","谢谢","你能做什么？","你能做什么","这里连接真实邮箱了吗？","hello","hi"}:
        return Route(("simple",))
    if text in {"重要邮件","星标邮件"}:return Route(("important_emails",))
    if re.search("推荐.*活动|活动推荐",text):return Route(("recommendations",),keyword(text))
    if re.search("规划|准备|计划",text):return Route(("multi_step_planning",),keyword(text))
    if re.search("今天.*(?:安排|摘要)|每日摘要",text):return Route(("daily_summary",))
    intents=[]
    if re.search("冲突|重叠",text):intents.append("calendar_conflict_check")
    if re.search("有空|空闲|空档|空余",text):intents.append("find_free_time")
    if re.search("邮件|通知|转发",text):intents.append("email_calendar_combined")
    if re.search("(?:本周|下周|今天|明天).*DDL|有哪些截止|截止列表",text,re.I):intents.append("deadlines")
    return Route(tuple(intents[:3]) or ("calendar_simple_query",),keyword(text))
