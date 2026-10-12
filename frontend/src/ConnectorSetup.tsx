import { useEffect, useState } from 'react'
import { privateRequest } from './api/client'
import type { Policy, Source } from './types'

export default function ConnectorSetup({source,policy,busy,onBusy,onSaved}:{source:Source;policy:Policy;busy:boolean;onBusy:(value:boolean)=>void;onSaved:()=>Promise<void>}) {
  const [host,setHost]=useState(''),[username,setUsername]=useState(''),[folder,setFolder]=useState('INBOX')
  const [endpoint,setEndpoint]=useState(''),[account,setAccount]=useState(''),[secret,setSecret]=useState('')
  const [persistent,setPersistent]=useState(false),[available,setAvailable]=useState(false),[unknown,setUnknown]=useState(false),[tokenConfirmed,setTokenConfirmed]=useState(false)
  const [notice,setNotice]=useState(''),[configured,setConfigured]=useState(false)
  useEffect(()=>{
    let active=true
    Promise.all([privateRequest<{config:Record<string,string|boolean>}>('/api/sources/'+source.id+'/connector',{},source.id),privateRequest<{persistent_available:boolean}>('/api/credential-status')])
      .then(([info,status])=>{if(!active)return;const c=info.config;setConfigured(!!c.connector);setHost(String(c.host??''));setUsername(String(c.username??''));setFolder(String(c.folder??'INBOX'));setEndpoint(String(c.endpoint??''));setAccount(String(c.account_id??''));setUnknown(!!c.include_unknown_dates);setAvailable(status.persistent_available)})
      .catch(()=>{if(active)setNotice('配置暂不可用，请重新打开设置。')})
    return()=>{active=false}
  },[source.id])
  async function save(){
    onBusy(true);setNotice('')
    try{await privateRequest('/api/sources/'+source.id+'/connector',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:policy.version,secret,persistent,include_unknown_dates:unknown,...(source.kind==='imap'?{host,username,folder}:{endpoint,account_id:account,token_for_this_server:tokenConfirmed})})},source.id);await onSaved();setNotice('配置已保存，可在主页测试连接并开始只读同步。')}
    catch(error){setNotice(error instanceof Error?error.message:'配置未完成')}
    finally{setSecret('');onBusy(false)}
  }
  return <form className="settings-form" onSubmit={event=>{event.preventDefault();void save()}}><h3>{source.kind==='imap'?'IMAP 账号':'MCP 邮件服务'} · {source.display_name}</h3>
    {source.kind==='imap'?<><label>IMAPS 服务器<input aria-label="IMAP服务器" required placeholder="imap.example.org" value={host} disabled={busy||configured} onChange={event=>setHost(event.target.value)}/></label><label>邮箱账号<input aria-label="邮箱账号" required value={username} disabled={busy||configured} onChange={event=>setUsername(event.target.value)}/></label><label>邮箱文件夹<input aria-label="邮箱文件夹" required value={folder} disabled={busy} onChange={event=>setFolder(event.target.value)}/></label><p>使用经过校验的 TLS（端口 993）与只读读取。需要服务商允许的应用密码；当前不支持 OAuth 登录刷新。</p></>:<><label>MCP 服务地址<input aria-label="MCP服务地址" required placeholder="http://127.0.0.1:8990/mcp" value={endpoint} disabled={busy||configured} onChange={event=>setEndpoint(event.target.value)}/></label><label>此服务的账号标识<input aria-label="MCP账号标识" required value={account} disabled={busy||configured} onChange={event=>setAccount(event.target.value)}/></label><label className="check-label"><input type="checkbox" required aria-label="令牌属于此MCP服务" checked={tokenConfirmed} disabled={busy} onChange={event=>setTokenConfirmed(event.target.checked)}/>令牌由此 MCP 服务签发，不是上游 Gmail/Graph 令牌；我了解该服务可能读取和记录邮件。</label><p>当前要求 campusflow-mail-v1 邮件字段契约；只调用 list_emails / read_email。第三方供应商通常需要适配，协议连通不代表账号或邮件字段已验证。</p></>}
    <label>{source.kind==='imap'?'应用专用密码':'MCP服务令牌'}<input type="password" aria-label="接入凭证" autoComplete="off" required maxLength={2400} value={secret} disabled={busy} onChange={event=>setSecret(event.target.value)}/></label><label className="check-label"><input type="checkbox" checked={persistent} disabled={busy||!available} onChange={event=>setPersistent(event.target.checked)}/>保存到 Windows 系统凭证管理器（默认仅本机会话）</label><label className="check-label"><input type="checkbox" aria-label="同步日期未知的邮件" checked={unknown} disabled={busy} onChange={event=>setUnknown(event.target.checked)}/>同步无明确 Date 的邮件，保留“日期未知”标记</label><button disabled={busy||!secret||(source.kind==='mcp'&&!tokenConfirmed)}>保存接入配置</button>{notice&&<p role="status">{notice}</p>}
  </form>
}
