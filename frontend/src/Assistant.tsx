import { useEffect, useRef, useState } from 'react'
import { quickActions } from './i18n'
import type { Email, Event } from './types'
import { eventDay, eventTime, Icon, nextDay } from './view'

type Message = {role:'user'|'assistant'; text:string; emailIds?:string[]}
export default function Assistant({emails, events, today, timezone, fictional, openEmail, expanded, onExpand}: {
  emails:Email[]; events:Event[]; today:string; timezone:string; fictional:boolean
  openEmail:(id:string)=>void; expanded:boolean; onExpand:()=>void
}) {
  const [input,setInput]=useState('')
  const [messages,setMessages]=useState<Message[]>([])
  const thread=useRef<HTMLDivElement>(null)
  useEffect(()=>{thread.current?.scrollTo({top:thread.current.scrollHeight})},[messages])
  function send(query:string) {
    const text=query.trim(); if(!text) return
    const active=events.filter(event=>event.status==='confirmed')
    let selected:Event[]=[], ids:string[]=[], answer=''
    const scope=fictional ? '虚构演示' : '当前页的本地数据'
    if(text===quickActions[0]) {
      selected=active.filter(event=>eventDay(event,timezone)===today)
      answer=`${scope}，${today} 的安排：\n${selected.map(event=>`• ${eventTime(event,timezone)} ${event.title}`).join('\n') || '暂无明确安排。'}`
    } else if(text===quickActions[1]) {
      const weekday=(new Date(`${today}T12:00:00Z`).getUTCDay()+6)%7
      const from=nextDay(today,-weekday), to=nextDay(from,7)
      selected=active.filter(event=>event.type==='deadline' && from<=eventDay(event,timezone) && eventDay(event,timezone)<to)
      answer=`${scope}，本周（${from} 起）的 DDL：\n${selected.map(event=>`• ${eventDay(event,timezone)} ${event.title} · ${eventTime(event,timezone)}`).join('\n') || '暂无明确 DDL。'}`
    } else if(text===quickActions[2]) {
      const starred=emails.filter(mail=>mail.local_star)
      answer=`${scope}的星标邮件：\n${starred.map(mail=>`• ${mail.subject}`).join('\n') || '尚未添加星标。'}`
      ids=starred.map(mail=>mail.id)
    } else if(text===quickActions[3]) {
      selected=active.filter(event=>event.type==='activity' && eventDay(event,timezone)>=today)
      answer=`${scope}的后续活动（按日期列出，尚未个性化推荐）：\n${selected.map(event=>`• ${eventDay(event,timezone)} ${event.title}`).join('\n') || '暂无有明确日期的后续活动。'}`
    } else answer='当前支持四个本地快捷查询，尚未接入自由问答模型。请使用下方快捷操作；邮件内容只作为资料，不会执行其中的指令。'
    if(selected.length) ids=[...new Set(selected.flatMap(event=>event.source_email_id ? [event.source_email_id] : []))]
    setMessages(previous=>[...previous,{role:'user',text},{role:'assistant',text:answer,emailIds:ids}]); setInput('')
  }
  return <section className="panel assistant" id="assistant" aria-labelledby="assistant-title"><div className="panel-heading"><h2 id="assistant-title"><Icon kind="chat"/>私人秘书</h2><button className="text-button" onClick={onExpand}>{expanded?'返回主页':'展开对话'}</button></div><div className="chat-thread" ref={thread} aria-live="polite">
    {!messages.length && <div className="assistant-empty"><div className="assistant-orb"><Icon kind="chat"/></div><h3>让校园生活，井然有序。</h3><p>查看当前来源的安排与邮件，<br/>从下面的快捷操作开始。</p><span className="tiny-label">{fictional?'FICTIONAL PREVIEW':'LOCAL DATA'} · 本地快捷查询</span></div>}
    {messages.map((message,index)=><div key={index} className={`bubble ${message.role}`}><p>{message.text}</p>{!!message.emailIds?.length && <div className="citations">{message.emailIds.map((id,position)=><button key={id} onClick={()=>openEmail(id)}>来源邮件 {position+1}</button>)}</div>}</div>)}
  </div><div className="quick-actions">{quickActions.map((action,index)=><button key={action} onClick={()=>send(action)}><span aria-hidden="true">{['◷','▤','✉','✧'][index]}</span>{action}</button>)}</div><form className="chat-form" onSubmit={event=>{event.preventDefault();send(input)}}><input aria-label="向私人秘书提问" placeholder="使用快捷操作查看当前来源…" maxLength={500} value={input} onChange={event=>setInput(event.target.value)}/><button aria-label="发送" disabled={!input.trim()}><Icon kind="arrow"/></button></form><p className="panel-footnote">直接查询当前页数据，无模型调用。对话仅保留在页面中，切换来源后清空。</p></section>
}
