import { useEffect, useRef, useState } from 'react'
import { quickActions } from './i18n'
import type { Email } from './types'
import { Icon } from './view'
import { privateRequest } from './api/client'

interface AgentReply {answer:string;source_id:string;citations:{email_id:string;subject:string}[];template_id:string;verification_status:string;degraded:boolean;quality_score:number|null;trajectory:{stage:string;status:string;task?:string}[];tool_calls:number;processing_mode:string;retrieval_mode:string}
type Message = {role:'user'|'assistant'; text:string; emailIds?:string[];diagnostics?:AgentReply}
export default function Assistant({emails, fictional, openEmail, expanded, onExpand, sourceId, allowModel, onBusy}: {
  emails:Email[]; fictional:boolean
  openEmail:(id:string)=>void; expanded:boolean; onExpand:()=>void;sourceId:string;allowModel:boolean;onBusy:(value:boolean)=>void
}) {
  const [input,setInput]=useState('')
  const [messages,setMessages]=useState<Message[]>([])
  const thread=useRef<HTMLDivElement>(null)
  useEffect(()=>{thread.current?.scrollTo({top:thread.current.scrollHeight})},[messages])
  const [busy,setBusy]=useState(false),[modelRouting,setModelRouting]=useState(false)
  const active=useRef(true)
  useEffect(()=>{active.current=true;return()=>{active.current=false}},[])
  async function send(query:string) {
    const text=query.trim();if(!text||busy)return
    setBusy(true);onBusy(true);setInput('')
    setMessages(previous=>[...previous,{role:'user',text}])
    try {
      const response=await privateRequest<AgentReply>(fictional?'/api/chat-demo':'/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:text,model_routing:!fictional&&modelRouting,...(fictional?{starred_ids:emails.filter(mail=>mail.local_star).map(mail=>mail.id)}:{})})},fictional?null:sourceId)
      if(!active.current)return
      if(response.source_id!==sourceId)throw new Error('来源已变化，请重新提问。')
      setMessages(previous=>[...previous,{role:'assistant',text:response.answer,emailIds:response.citations.map(item=>item.email_id),diagnostics:response}])
    } catch(error) {if(active.current)setMessages(previous=>[...previous,{role:'assistant',text:error instanceof Error?error.message:'查询未完成，请稍后重试。'}])}
    finally{if(active.current)setBusy(false);onBusy(false)}
  }
  return <section className="panel assistant" id="assistant" aria-labelledby="assistant-title"><div className="panel-heading"><h2 id="assistant-title"><Icon kind="chat"/>私人秘书</h2><button className="text-button" onClick={onExpand}>{expanded?'返回主页':'展开对话'}</button></div><div className="chat-thread" ref={thread} aria-live="polite">
    {!messages.length && <div className="assistant-empty"><div className="assistant-orb"><Icon kind="chat"/></div><h3>让校园生活，井然有序。</h3><p>查看当前来源的安排与邮件，<br/>从下面的快捷操作开始。</p><span className="tiny-label">{fictional?'FICTIONAL PREVIEW':'LOCAL DATA'} · SMOA / SQL 事实核对</span></div>}
    {messages.map((message,index)=><div key={index} className={`bubble ${message.role}`}><p>{message.text}</p>{message.diagnostics&&<><small className="verification-label">{({passed:'已对照本地记录',partial:'部分结果，存在限制',needs_input:'需要补充输入',failed:'核对未通过',not_applicable:'无需工具核对'} as Record<string,string>)[message.diagnostics.verification_status]??message.diagnostics.verification_status}</small><details className="agent-trace"><summary>查看执行记录</summary><p>模板：{message.diagnostics.template_id} · 调用 {message.diagnostics.tool_calls} 次 · {message.diagnostics.processing_mode}</p>{message.diagnostics.trajectory.map((step,position)=><p key={position}>{step.stage} · {step.task??''} · {step.status}</p>)}</details></>}{!!message.emailIds?.length && <div className="citations">{message.emailIds.map((id,position)=><button key={id} onClick={()=>openEmail(id)}>来源邮件 {position+1}</button>)}</div>}</div>)}
  </div><div className="quick-actions">{quickActions.map((action,index)=><button key={action} disabled={busy} onClick={()=>void send(action)}><span aria-hidden="true">{['◷','▤','✉','✧'][index]}</span>{action}</button>)}</div><form className="chat-form" onSubmit={event=>{event.preventDefault();void send(input)}}><input aria-label="向私人秘书提问" placeholder="使用快捷操作查看当前来源…" maxLength={500} value={input} disabled={busy} onChange={event=>setInput(event.target.value)}/><button aria-label="发送" disabled={busy||!input.trim()}><Icon kind="arrow"/></button></form><p className="panel-footnote">查询当前来源，不受页面分页限制；超限会提示。默认规则理解，对话切换来源后清空。</p>{!fictional&&<label className="model-choice"><input type="checkbox" checked={modelRouting} disabled={busy||!allowModel} onChange={event=>setModelRouting(event.target.checked)}/>使用已配置模型理解任务（遵守此来源授权）</label>}{busy&&<p role="status">正在查询并核对本地记录…</p>}</section>
}
