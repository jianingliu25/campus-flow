import { useEffect, useRef, useState } from 'react'
import { privateRequest } from './api/client'
import type { Source } from './types'

interface Job {id:string;status:string;counts:Record<string,number>;error_code:string|null}
export default function ConnectorActions({source,busy,onBusy,onUpdated}:{source:Source;busy:boolean;onBusy:(value:boolean)=>void;onUpdated:()=>Promise<void>}) {
  const [job,setJob]=useState<Job|null>(null),[notice,setNotice]=useState(''),[mode,setMode]=useState('browse')
  const refresh=useRef(onUpdated);refresh.current=onUpdated
  useEffect(()=>{let active=true;privateRequest<Job|null>(`/api/sources/${source.id}/sync-status`,{},source.id).then(value=>{if(active)setJob(value)}).catch(()=>undefined);return()=>{active=false}},[source.id])
  useEffect(()=>{
    if(job?.status!=='running')return
    let active=true,timer:ReturnType<typeof setTimeout>
    async function poll(){try{const next=await privateRequest<Job>(`/api/sync/${job?.id}`,{},source.id);if(!active)return;setJob(next);if(next.status==='running')timer=setTimeout(()=>void poll(),1000);else await refresh.current()}catch{if(active)setNotice('同步状态暂不可用，请刷新此来源。')}}
    timer=setTimeout(()=>void poll(),500)
    return()=>{active=false;clearTimeout(timer)}
  },[job?.id,job?.status,source.id])
  async function action(path:string,body?:unknown){
    onBusy(true);setNotice('')
    try{const result=await privateRequest<{job_id?:string;account_verified?:boolean}>(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body??{})},source.id);if(result.job_id)setJob({id:result.job_id,status:'running',counts:{},error_code:null});else{await onUpdated();setNotice(path.endsWith('/test')?(result.account_verified?'TLS 与只读账号验证通过。':'MCP 协议已连通，账号身份与邮件字段尚需核验。'):path.endsWith('/disconnect')?'本地凭证已移除，邮件保留。第三方令牌需到服务方撤销。':'已请求暂停，正在进行的读取结束后不再保存。')}}catch(error){setNotice(error instanceof Error?error.message:'操作未完成')}finally{onBusy(false)}
  }
  return <div className="connector-actions"><div className="detail-actions"><button disabled={busy} onClick={()=>void action(`/api/sources/${source.id}/test`)}>测试只读连接</button><label>同步后处理<select aria-label="同步提取方式" value={mode} disabled={busy} onChange={event=>setMode(event.target.value)}><option value="browse">仅保存浏览</option><option value="rules">本地规则候选</option></select></label><button disabled={busy||job?.status==='running'} onClick={()=>void action(`/api/sources/${source.id}/sync`,{mode,resume:true})}>开始／继续同步</button><button disabled={busy} onClick={()=>void action(`/api/sources/${source.id}/pause`)}>暂停同步</button><button disabled={busy} onClick={()=>void action(`/api/sources/${source.id}/disconnect`)}>断开并移除凭证</button></div>{job&&<p role="status">同步：{({running:'读取中',completed:'本次读取结束',failed:'未完成',partial:'部分完成',cancelled:'已取消',interrupted:'已中断'} as Record<string,string>)[job.status]??job.status} · 读取 {job.counts.read??0} · 保存/更新 {job.counts.saved??0} · 跳过 {job.counts.skipped??0}{job.error_code?' · '+job.error_code:''}</p>}{notice&&<p role="status">{notice}</p>}</div>
}
