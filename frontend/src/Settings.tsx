import { useState } from 'react'
import type { Policy, Provider, Source } from './types'

export default function Settings({source, policy, provider, busy, onCreate, onSave}: {
  source:Source | null; policy:Policy | null; provider:Provider | null; busy:boolean
  onCreate:(label:string,zone:string)=>Promise<void>; onSave:(body:Record<string,unknown>)=>Promise<void>
}) {
  const [tab,setTab]=useState('sources')
  const [label,setLabel]=useState('我的本地邮件'), [zone,setZone]=useState('Asia/Shanghai')
  const [days,setDays]=useState(policy?.scope.recent_days ?? 30), [maximum,setMaximum]=useState(Math.min(policy?.scope.max_messages ?? 200,200))
  const [retain,setRetain]=useState(policy?.retain_body ?? true)
  const cloudCurrent=!!(provider?.configured && provider.mode==='cloud' && provider.remote_globally_enabled)
  const [remote,setRemote]=useState(!!(policy?.allow_remote_processing && policy.consent_fingerprint===provider?.fingerprint && cloudCurrent))
  const [notice,setNotice]=useState('')
  async function action(fn:()=>Promise<void>) { setNotice(''); try {await fn();setNotice('设置已保存。')} catch(error) {setNotice(error instanceof Error?error.message:'保存未完成')} }
  return <div className="dialog-content settings-content"><div className="tabs" aria-label="设置分类">{[['sources','来源与范围'],['models','模型'],['privacy','隐私']].map(([key,name])=><button key={key} aria-pressed={tab===key} className={tab===key?'selected':''} onClick={()=>setTab(key)}>{name}</button>)}</div>
    {tab==='sources' && <><h3>本地邮件来源</h3><p>在顶部选择来源后，主页、日程、邮件和对话一起切换。</p><form className="settings-form" onSubmit={event=>{event.preventDefault();void action(()=>onCreate(label,zone))}}><label>新来源名称<input aria-label="新来源名称" maxLength={80} required value={label} disabled={busy} onChange={event=>setLabel(event.target.value)}/></label><label>邮件时区<select aria-label="邮件时区" value={zone} disabled={busy} onChange={event=>setZone(event.target.value)}>{['Asia/Shanghai','UTC','America/New_York','Europe/London'].map(value=><option key={value}>{value}</option>)}</select></label><button className="primary-button" disabled={busy || !label.trim()}>创建并切换来源</button></form>
      <p className="dialog-note">EML/MBOX 文件导入可用。IMAP 和 MCP 账号连接将在 M5 接入；当前没有自动邮箱同步。</p>
      {source && policy && <form className="settings-form" onSubmit={event=>{event.preventDefault();void action(()=>onSave({expected_version:policy.version,scope:{recent_days:days,max_messages:maximum,folders:policy.scope.folders}}))}}><h3>{source.display_name} · 读取范围</h3><label>最近天数<input aria-label="最近天数" type="number" min={1} max={365} required value={days} disabled={busy} onChange={event=>setDays(Number(event.target.value))}/></label><label>单次最多邮件<input aria-label="单次最多邮件" type="number" min={1} max={200} required value={maximum} disabled={busy} onChange={event=>setMaximum(Number(event.target.value))}/></label><button disabled={busy}>保存读取范围</button><p>改变范围会撤销此来源的云端授权，只影响后续导入，不删除已保存的邮件。</p></form>}</>}
    {tab==='models' && <><h3>处理方式</h3><dl><dt>当前配置</dt><dd>{provider?.configured ? `${provider.mode==='local'?'本地模型':'云端模型'} · ${provider.model}` : '尚未配置实际模型'}</dd><dt>处理位置</dt><dd>{provider?.host ?? '本机规则，不发送到模型服务'}</dd><dt>连接状态</dt><dd>{provider?.configured ? '已配置，尚未验证实际连接' : '可使用规则提取及邮件浏览'}</dd><dt>自由问答</dt><dd>当前为本地快捷查询；SMOA 与检索问答待后续接入。</dd></dl><p className="dialog-note">模型地址和密钥由本地服务配置，页面不保存密钥。模型重处理需要主动点击；云端还需此来源单独授权。</p></>}
    {tab==='privacy' && <><h3>此来源的隐私</h3>{source && policy ? <form className="settings-form" onSubmit={event=>{event.preventDefault();void action(()=>onSave({expected_version:policy.version,retain_body:retain,allow_remote_processing:remote, ...(remote?{consent_fingerprint:provider?.fingerprint}:{})}))}}><label className="check-label"><input type="checkbox" aria-label="保留邮件正文" checked={retain} disabled={busy} onChange={event=>setRetain(event.target.checked)}/>保留邮件正文，供离线查看与重处理</label><p>关闭只影响后续保存，不清除已有正文；摘要、日程证据仍可能保留邮件内容。完整数据清理将在后续阶段提供。</p><label className="check-label"><input type="checkbox" aria-label="允许此来源云端处理" checked={remote} disabled={busy || !cloudCurrent} onChange={event=>setRemote(event.target.checked)}/>允许把此来源邮件发送到 {cloudCurrent?`${provider?.host} / ${provider?.model}`:'已配置的云端模型（当前不可用）'}</label><p>仅供主动请求的模型处理。默认关闭；更换模型服务或改变范围需重新授权。</p><button disabled={busy}>保存隐私设置</button><dl><dt>问答记忆</dt><dd>{policy.enable_qa_memory?'授权已开启，功能尚未接入':'关闭，功能待后续接入'}</dd><dt>隐式画像</dt><dd>{policy.enable_implicit_profile?'授权已开启，功能尚未接入':'关闭，功能待后续接入'}</dd></dl></form> : <p>先在顶部选择或创建一个本地来源，再调整隐私设置。</p>}<p className="dialog-note">数据库仅存于本机私有目录。页面不缓存正文到浏览器存储；退出到演示或切换来源会清除当前对话和邮件详情。</p></>}
    {notice && <p role="status">{notice}</p>}
  </div>
}
