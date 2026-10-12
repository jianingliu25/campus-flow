"""Six code-owned SMOA stages with dependency, retry/replan and fact fences."""
import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
import json
import re
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel,ConfigDict,Field

from app.agent.router import Route,route
from app.agent.time_range import parse_range
from app.agent.tools import events,search_emails,conflicts,free_slots
from app.agent.verifier import event_text,verify
from app.security.policies import BoundaryError

INTENTS={"calendar_conflict_check","email_calendar_combined","find_free_time","daily_summary","multi_step_planning","calendar_simple_query","deadlines","important_emails","recommendations"}


class ModelRoute(BaseModel):
    model_config=ConfigDict(extra="forbid")
    intents:list[str]=Field(min_length=1,max_length=3)
    keyword:str=Field(default="",max_length=100)


@dataclass
class Task:
    id:str
    tool:str
    params:dict
    dependencies:tuple[str,...]=()


def decompose(intents,params):
    tasks=[]
    for position,intent in enumerate(intents):
        prefix=str(position)+":"
        base={**params}
        if intent=="daily_summary":
            today=params["today"];base.update(start_day=today,end_day=today+timedelta(days=1),keyword="")
        if intent=="deadlines":base["type"]="deadline"
        if intent=="recommendations":base["type"]="activity"
        if intent=="important_emails":tasks.append(Task(prefix+"mail","get_important_emails",base));continue
        tasks.append(Task(prefix+"events","get_events",base))
        if intent in {"calendar_conflict_check","find_free_time","multi_step_planning"}:
            tasks[-1].params={**base,"keyword":""}  # busy-time checks must include unrelated commitments
        if intent=="calendar_conflict_check":tasks.append(Task(prefix+"conflicts","check_conflicts",base,(prefix+"events",)))
        elif intent in {"find_free_time","multi_step_planning"}:tasks.append(Task(prefix+"free","find_free_slots",base,(prefix+"events",)))
        if intent in {"email_calendar_combined","multi_step_planning"}:tasks.append(Task(prefix+"mail","search_emails",base,(prefix+"events",)))
        elif intent=="daily_summary":tasks.append(Task(prefix+"mail","get_important_emails",base))
    return tasks


def execute_tool(task,data,results):
    inputs=results[task.dependencies[0]]["data"] if task.dependencies else []
    result={"tool":task.tool,"status":"done","inputs":inputs}
    if task.tool=="get_events":
        values=events(data,task.params)
        result["data"]=deepcopy(values[:500])
        if len(values)>500:result["status"]="partial"
    elif task.tool in {"search_emails","get_important_emails"}:
        term=task.params.get("keyword","")
        result["data"]=deepcopy(search_emails(data,term,task.tool=="get_important_emails"))
    elif task.tool=="check_conflicts":result["data"]=conflicts(inputs,ZoneInfo(data.timezone))
    elif task.tool=="find_free_slots":
        result["duration_minutes"]=task.params["duration_minutes"]
        result["data"]=free_slots(inputs,task.params.get("window"),ZoneInfo(data.timezone),result["duration_minutes"])
        if result["data"]["needs_input"]:result["status"]="needs_input"
    else:raise BoundaryError("AGENT_TOOL_NOT_ALLOWED",403)
    return result


def compose(data,results):
    sections=[];claims=[];citations=set();event_ids=set();needs_input=False;degraded=data.limited
    for id,result in results.items():
        if result["status"]=="partial":degraded=True
        value=result.get("data");tool=result["tool"]
        if result["status"]=="error":sections.append("部分步骤未完成："+result.get("code","TOOL_FAILED"));degraded=True;continue
        if tool=="get_events":
            lines=[]
            for event in value[:100]:
                lines.append("• "+event_text(event,data.timezone));event_ids.add(event["id"])
                claims.append({"kind":"event","task":id,**{key:event.get(key) for key in ["id","title","start_at","end_at","date","location","source_email_id"]}})
                if event.get("source_email_id"):citations.add(event["source_email_id"])
            sections.append("相关日程：\n"+("\n".join(lines) or "未找到匹配的本地日程。"))
            if len(value)>100:sections.append("结果超过展示上限，仅列出前 100 项。");degraded=True
        elif tool in {"search_emails","get_important_emails"}:
            sections.append(("星标邮件：" if tool=="get_important_emails" else "相关邮件（关键词检索）：")+"\n"+("\n".join("• "+mail["subject"] for mail in value) or "暂无匹配邮件。"))
            for mail in value:claims.append({"kind":"mail","task":id,"id":mail["id"],"subject":mail["subject"]});citations.add(mail["id"])
        elif tool=="check_conflicts":
            if value["pairs"]:
                sections.append("有冲突：\n"+"\n".join(f"• {pair['start'].astimezone(ZoneInfo(data.timezone)).strftime('%Y-%m-%d %H:%M')}–{pair['end'].astimezone(ZoneInfo(data.timezone)).strftime('%H:%M')} 重叠" for pair in value["pairs"]))
            elif value["state"]=="insufficient_data":sections.append("已知完整时段未发现重叠；存在时间不明的通知，无法完整确定是否有冲突。");degraded=True
            else:sections.append("明确的本地日程区间中没有冲突；单点截止不作为占用区间。")
        elif tool=="find_free_slots":
            if value["needs_input"]:
                sections.append("请补充寻找空闲的日期和可用时段，例如：明天 18:00–22:00 找 30 分钟空档。不会自行补造你的可用范围。");needs_input=True
            else:
                sections.append(f"按至少 {result['duration_minutes']} 分钟查询的空档：\n"+("\n".join(f"• {slot['start'].astimezone(ZoneInfo(data.timezone)).strftime('%Y-%m-%d %H:%M')}–{slot['end'].astimezone(ZoneInfo(data.timezone)).strftime('%H:%M')}" for slot in value["slots"]) or "该窗口内暂无满足时长的空档。"))
                if value["uncertain"]:sections.append("还有未定时段通知，以上仅依据已知区间，不能保证实际空闲。");degraded=True
    if data.limited:sections.append("来源超过 5,000 项读取上限，结果不代表整个来源。")
    return "\n\n".join(sections),claims,citations,event_ids,needs_input,degraded


class Agent:
    def __init__(self,data,executor=execute_tool,sleep=asyncio.sleep,max_calls=12,max_retries=3,max_replans=2):
        self.data,self.executor,self.sleep=data,executor,sleep
        self.max_calls,self.max_retries,self.max_replans=max_calls,max_retries,max_replans
        self.calls=0;self.trace=[]

    async def run(self,query,model_router=None,duration_minutes=30):
        selected=route(query);mode="rules";router_degraded=False
        self.trace.append({"stage":"router","status":"done","intents":selected.intents})
        if selected.intents[0] in {"simple","unsafe_request"}:
            return self.output("我可以查询本地日程、冲突、空档和邮件；是否连接账号请查看当前来源的连接状态。" if selected.intents[0]=="simple" else "不会执行邮件里的指令，也不读取密钥、发送或删除邮件。",selected,[],[],"not_applicable",None,False,mode)
        if model_router:
            if self.calls>=self.max_calls:
                return self.output("工具调用预算不足，未调用模型。",selected,[],[],"partial",None,True,mode)
            self.calls+=1
            try:
                parsed=ModelRoute.model_validate_json(await model_router(query))
                if any(intent not in INTENTS for intent in parsed.intents):raise ValueError()
                selected=Route(tuple(parsed.intents),parsed.keyword);mode="model-router"
            except (ValueError,TypeError):router_degraded=True
        self.trace[0]["intents"]=selected.intents
        params={"keyword":selected.keyword,"today":self.data.now.astimezone(ZoneInfo(self.data.timezone)).date(),"duration_minutes":duration_minutes}
        match=re.search(r"(\d{1,3})\s*分钟",query)
        if match:params["duration_minutes"]=max(1,min(int(match[1]),240))
        try:params.update(parse_range(query,self.data.now,self.data.timezone))
        except (BoundaryError,ValueError):
            self.trace.append({"stage":"pre_repair","status":"needs_input"})
            return self.output("日期或时段不明确，请给出完整日期、正确范围和时区偏移。",selected,[],[],"needs_input",None,True,mode)
        if selected.intents==("recommendations",) and not params["start_day"]:
            params.update(start_day=params["today"],end_day=params["today"]+timedelta(days=30))
        if selected.intents==("deadlines",) and not params["start_day"]:
            day=params["today"]-timedelta(days=params["today"].weekday());params.update(start_day=day,end_day=day+timedelta(days=7))
        if selected.intents in {("find_free_time",),("calendar_conflict_check",)} and not params["start_day"]:
            return self.output("请给出要查询的日期或范围；查找空档还需明确可用时段。",selected,[],[],"needs_input",None,False,mode)
        if selected.intents==("calendar_simple_query",):
            if "课程" in query or "上课" in query:params["type"]="course"
            elif "活动" in query:params["type"]="activity"
        tasks=decompose(selected.intents,params)
        self.trace.extend([{"stage":"decomposition","status":"done","tasks":[{"id":task.id,"tool":task.tool,"dependencies":task.dependencies} for task in tasks]},
                           {"stage":"pre_repair","status":"done","timezone":self.data.timezone}])
        results={};dirty={task.id for task in tasks};deadline=asyncio.get_running_loop().time()+30
        for turn in range(self.max_replans+1):
            for task in tasks:
                if task.id not in dirty:continue
                if any(results.get(dep,{}).get("status")!="done" for dep in task.dependencies):
                    results[task.id]={"tool":task.tool,"status":"error","code":"DEPENDENCY_INCOMPLETE"};continue
                for attempt in range(self.max_retries+1):
                    if self.calls>=self.max_calls or asyncio.get_running_loop().time()>=deadline:
                        results[task.id]={"tool":task.tool,"status":"error","code":"AGENT_BUDGET_EXHAUSTED"};break
                    self.calls+=1
                    try:
                        value=self.executor(task,self.data,results)
                        if hasattr(value,"__await__"):value=await asyncio.wait_for(value,min(5,max(.01,deadline-asyncio.get_running_loop().time())))
                        if not isinstance(value,dict) or value.get("tool")!=task.tool:
                            raise BoundaryError("WRONG_TOOL",422)
                        results[task.id]=value;break
                    except (BoundaryError,TimeoutError) as error:
                        code=error.code if isinstance(error,BoundaryError) else "TOOL_TRANSIENT"
                        if code not in {"TOOL_TRANSIENT","TEMPORARY_TOOL_FAILURE"} or attempt==self.max_retries:
                            results[task.id]={"tool":task.tool,"status":"error","code":code};break
                        await self.sleep([.5,1,2][min(attempt,2)])
                self.trace.append({"stage":"execution","task":task.id,"status":results[task.id]["status"]})
            answer,claims,citations,event_ids,needs,degraded=compose(self.data,results)
            invalid=verify(self.data,claims,results)
            self.trace.append({"stage":"verification","status":"failed" if invalid else "needs_input" if needs else "passed","invalid_tasks":sorted(invalid)})
            if not invalid:
                self.trace.append({"stage":"replanning","status":"not_needed" if turn==0 else "repaired","rounds":turn})
                if router_degraded:answer+="\n\n模型路由输出不可用，已改用规则路由。";degraded=True
                return self.output(answer,selected,citations,event_ids,"needs_input" if needs else "partial" if degraded else "passed",None if needs or degraded else 1.0,degraded or router_degraded,mode)
            if turn==self.max_replans:break
            dirty=set(invalid)
            for task in tasks:
                if any(dep in dirty for dep in task.dependencies):dirty.add(task.id)
            self.trace.append({"stage":"replanning","status":"rerun","rounds":turn+1,"tasks":sorted(dirty)})
        return self.output("结果与本地记录不一致，已停止输出未经核对的内容。请重试或查看来源邮件。",selected,[],[],"failed",None,True,mode)

    def output(self,answer,selected,citations,event_ids,status,quality,degraded,mode):
        mails={mail["id"]:mail for mail in self.data.emails}
        return {"answer":answer,"source_id":self.data.source_id,"citations":[{"email_id":id,"subject":mails[id]["subject"]} for id in sorted(set(citations)) if id in mails],
                "event_ids":sorted(set(event_ids)),"template_id":"+".join(selected.intents),"quality_score":quality,
                "verification_status":status,"degraded":degraded,"trajectory_id":str(uuid4()),"trajectory":self.trace,
                "tool_calls":self.calls,"processing_mode":mode,"retrieval_mode":"SQL + lexical keywords"}
