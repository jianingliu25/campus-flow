import {useState} from 'react'
import {privateRequest} from './api/client'
import type {Event} from './types'

export default function PersonalTools({sourceId,onUpdated,onDeleted,onBusy}:{sourceId:string;onUpdated:()=>Promise<void>;onDeleted:()=>Promise<void>;onBusy:(busy:boolean)=>void}) {
  const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[tags,setTags]=useState('')
  const [items,setItems]=useState<(Event&{reason:string;score:number})[]>([])
  const [impact,setImpact]=useState<{counts:Record<string,number>;modified_events:string[]}|null>(null)
  const [confirm,setConfirm]=useState(false),[suggestions,setSuggestions]=useState<{tag:string;count:number}[]>([])
  const [query,setQuery]=useState(''),[hits,setHits]=useState<{email_id:string;excerpt:string;score:number}[]>([])
  async function run(action:()=>Promise<void>) {setBusy(true);onBusy(true);setMessage('');try{await action()}catch(e){setMessage(e instanceof Error?e.message:'操作未完成')}finally{setBusy(false);onBusy(false)}}
  const options=(body:unknown,method='POST')=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  return <details className="personal-tools"><summary>兴趣、推荐与本地数据管理</summary>
    <label>兴趣标签（逗号分隔）<input value={tags} onChange={e=>setTags(e.target.value)} placeholder="NLP, 开源, 机器学习"/></label>
    <button disabled={busy} onClick={()=>void run(async()=>{const p=await privateRequest<{tags:string[];suggestions:typeof suggestions}>('/api/profile',{},sourceId);setTags(p.tags.join(', '));setSuggestions(p.suggestions)})}>读取兴趣</button>
    <button disabled={busy} onClick={()=>void run(async()=>{await privateRequest('/api/profile',options({tags:tags.split(/[,，]/).map(t=>t.trim()).filter(Boolean)},'PUT'),sourceId);setMessage('兴趣已保存在此来源。')})}>保存兴趣</button>
    {suggestions.map(item=><p key={item.tag}>{item.tag} · {item.count} 次主题信号<button disabled={busy} onClick={()=>setTags(old=>old?`${old}, ${item.tag}`:item.tag)}>加入待保存兴趣</button></p>)}
    <button disabled={busy} onClick={()=>void run(async()=>{const r=await privateRequest<{items:typeof items}>('/api/recommendations',{},sourceId);setItems(r.items);setMessage('使用兴趣关键词与时间距离排序；未启用语义模型。')})}>查看推荐活动</button>
    {items.map(item=><p key={item.id}>{item.title} · {item.reason} · 排序分 {item.score.toFixed(3)}（非概率）<button disabled={busy} onClick={()=>void run(async()=>{await privateRequest(`/api/events/${item.id}/selection`,options({selected:true},'PUT'),sourceId);await onUpdated();setMessage('已加入私人日程。')})}>加入私人日程</button></p>)}
    <button disabled={busy} onClick={()=>void run(async()=>{const r=await privateRequest<{completed:number}>('/api/index/run',options({}),sourceId);setMessage(`本地关键词索引完成 ${r.completed} 项。`);await onUpdated()})}>更新本地检索索引</button>
    <label>本机邮件检索<input value={query} onChange={e=>setQuery(e.target.value)}/></label><button disabled={busy||!query.trim()} onClick={()=>void run(async()=>{const r=await privateRequest<{items:typeof hits}>('/api/search',options({query}),sourceId);setHits(r.items);setMessage('检索仅包含此来源已完成索引的邮件；未建索引时请先更新。')})}>检索本机邮件</button>
    {hits.map(item=><p key={item.email_id}>{item.excerpt} · 相似度 {item.score.toFixed(3)}（关键词向量）</p>)}
    <button disabled={busy} onClick={()=>void run(async()=>{await privateRequest('/api/profile/signals',{method:'DELETE'},sourceId);setSuggestions([]);setMessage('本机兴趣信号已清空。')})}>清空兴趣信号</button>
    <button disabled={busy} onClick={()=>void run(async()=>{const r=await privateRequest('/api/data/export' ,options({}),sourceId);const url=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='campus-flow-private-export.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);setMessage('已下载到本机，文件可能含私人邮件内容，请自行保管。')})}>导出此来源到本机</button>
    <button disabled={busy} onClick={()=>void run(async()=>{await privateRequest('/api/history',{method:'DELETE'},sourceId);setMessage('本机问答历史已清空。')})}>清空问答历史</button>
    <button disabled={busy} onClick={()=>void run(async()=>{setImpact(await privateRequest('/api/data/impact',{},sourceId));setConfirm(false)})}>查看删除影响</button>
    {impact&&<div className="dialog-note"><p>将删除此来源的邮件、日程、兴趣、问答和检索副本。邮箱原件保留。</p><p>{Object.entries(impact.counts).map(([key,value])=>`${key}: ${value}`).join(' · ')}</p><p>手工修改的日程也会删除：{impact.modified_events.join('、')||'无'}。需要保留时，请先导出。</p><label><input type="checkbox" checked={confirm} onChange={e=>setConfirm(e.target.checked)}/>我确认删除此来源及本机数据</label><button disabled={busy||!confirm} onClick={()=>void run(async()=>{await privateRequest('/api/data/delete',options({confirm_source_id:sourceId}),sourceId);await onDeleted()})}>确认删除</button><button onClick={()=>setImpact(null)}>取消</button></div>}
    {message&&<p role="status">{message}</p>}
  </details>
}
