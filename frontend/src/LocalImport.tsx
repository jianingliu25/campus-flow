import { useState } from 'react'
import { privateRequest } from './api/client'
import type { Policy, Source } from './types'

interface Preview { preview_id: string | null; mails: {id:number; subject:string; sender:string; date_status:string}[]; report: {duplicates_in_file:number; outside_date_range:number; unknown_dates:number; errors:{code:string}[]} }

export default function LocalImport({source, policy, busy, onBusy, onSaved, open, onOpen}: {
  source: Source; policy: Policy | null; busy:boolean; onBusy:(value:boolean)=>void
  onSaved:()=>Promise<void>; open:boolean; onOpen:(value:boolean)=>void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [mode, setMode] = useState<'browse'|'rules'>('browse')
  const [notice, setNotice] = useState('')
  const request = <T,>(path:string, options:RequestInit={}) => privateRequest<T>(path, options, source.id)
  async function task(action:()=>Promise<void>) {
    onBusy(true); setNotice('')
    try { await action() } catch(error) { setNotice(error instanceof Error ? error.message : '操作未完成') }
    finally { onBusy(false) }
  }
  async function upload(file:File) {
    if(file.size>10*1024*1024) throw new Error('文件超过 10 MiB，请缩小导出范围。')
    if(preview?.preview_id) await request(`/api/imports/${preview.preview_id}`, {method:'DELETE'}).catch(()=>undefined)
    setPreview(null)
    const data = await request<Preview>('/api/imports/preview', {method:'POST', headers:{'X-Mail-Filename':encodeURIComponent(file.name),'Content-Type':'application/octet-stream'},body:file})
    setPreview(data)
    setSelected(data.mails.filter(mail=>mail.date_status!=='unknown').map(mail=>mail.id))
  }
  async function cancel() {
    if(preview?.preview_id) await request(`/api/imports/${preview.preview_id}`, {method:'DELETE'})
    setPreview(null); setSelected([])
  }
  async function commit() {
    if(!preview?.preview_id) return
    const report = await request<{imported:number; updated:number; unchanged:number; events:number; errors:{code:string}[]}>(`/api/imports/${preview.preview_id}/commit`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selected,mode})})
    setPreview(null); setSelected([])
    await onSaved()
    setNotice(`已导入 ${report.imported} 封，更新 ${report.updated} 封，重复 ${report.unchanged} 封；处理候选 ${report.events} 项。${report.errors.length ? ' 提示：'+[...new Set(report.errors.map(error=>error.code))].join('、') : ''}`)
  }
  return <details className="local-import" open={open} onToggle={event=>onOpen(event.currentTarget.open)}><summary>导入本地邮件 <span>{source.display_name}</span></summary><div className="import-content">
    <p className="import-description">仅读取所选文件，确认后保存到本机。最近 {policy?.scope.recent_days ?? 30} 天，单次最多 {Math.min(policy?.scope.max_messages ?? 200,200)} 封；未知接收日期需主动勾选。切换来源会清除预览。</p>
    <div className="import-toolbar"><label className="file-pick">选择 EML / MBOX<input aria-label="选择邮件文件" type="file" accept=".eml,.mbox" disabled={busy} onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(file) void task(()=>upload(file))}} /></label><a href="/api/import-examples/sample.eml" download>下载虚构 EML</a><a href="/api/import-examples/sample.mbox" download>下载虚构 MBOX</a></div>
    {preview && <div className="import-preview"><h3>预览：{preview.mails.length} 封有效邮件</h3><p>文件内重复 {preview.report.duplicates_in_file} 封 · 范围外 {preview.report.outside_date_range} 封 · 日期未知 {preview.report.unknown_dates} 封 · 无效 {preview.report.errors.length} 封</p><div className="import-mail-scroll">{preview.mails.map(mail=><label className="preview-row" key={mail.id}><input type="checkbox" checked={selected.includes(mail.id)} disabled={busy} onChange={event=>setSelected(previous=>event.target.checked ? [...previous,mail.id] : previous.filter(id=>id!==mail.id))}/><span><b>{mail.subject}</b><small>{mail.sender} · {mail.date_status==='unknown' ? '接收日期未知' : '日期可用'}</small></span></label>)}</div><label className="extraction-choice">保存后如何处理？<select aria-label="提取方式" value={mode} disabled={busy} onChange={event=>setMode(event.target.value as 'browse'|'rules')}><option value="browse">仅导入浏览（默认）</option><option value="rules">本地规则提取（不是模型推理）</option></select></label><div className="import-toolbar"><button disabled={busy || !selected.length || !preview.preview_id} onClick={()=>void task(commit)}>确认保存 {selected.length} 封</button><button disabled={busy} onClick={()=>void task(cancel)}>取消预览</button></div></div>}
    {busy && <p role="status">正在处理所选邮件…</p>}{notice && <p role="status" className="import-notice">{notice}</p>}
  </div></details>
}
