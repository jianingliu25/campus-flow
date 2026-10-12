import { useEffect, useRef, useState } from 'react'
import { activateSource, privateRequest } from './api/client'

interface Source { id: string; display_name: string; kind: string; timezone: string | null }
interface Preview { preview_id: string | null; mails: { id: number; subject: string; sender: string; date_status: string; warnings: string[] }[]; report: { duplicates_in_file: number; outside_date_range: number; unknown_dates: number; errors: { code: string }[] } }
interface Mail { id: string; subject: string; extraction_status: string; extraction_method: string | null }
interface Event { id: string; title: string; status: string; start_at_utc: string | null; event_date: string | null; source_email_id: string; source_changed: boolean }
interface MailDetail { subject: string; body_text: string | null; source_locator: string | null; import_warnings: string[]; extraction_warnings: string[] }

export default function LocalImport() {
  const [sources, setSources] = useState<Source[]>([])
  const [selectedSource, setSelectedSource] = useState('')
  const [label, setLabel] = useState('我的本地邮件')
  const [zone, setZone] = useState('Asia/Shanghai')
  const [scope, setScope] = useState({recent_days: 30, max_messages: 200})
  const [preview, setPreview] = useState<Preview | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [mode, setMode] = useState<'browse' | 'rules'>('browse')
  const [mails, setMails] = useState<Mail[]>([])
  const [events, setEvents] = useState<Event[]>([])
  const [detail, setDetail] = useState<MailDetail | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const generation = useRef(0)

  useEffect(() => {
    privateRequest<Source[]>('/api/sources').then(data => setSources(data.filter(source => source.kind === 'local_files')))
      .catch(() => setNotice('本地服务暂不可用，请刷新后再试。'))
  }, [])

  async function task(action: () => Promise<void>) {
    setBusy(true); setNotice('')
    try { await action() } catch (error) { setNotice(error instanceof Error ? error.message : '操作未完成') }
    finally { setBusy(false) }
  }

  async function loadData() {
    const mark = generation.current
    const [mailData, eventData] = await Promise.all([privateRequest<Mail[]>('/api/emails?limit=200'), privateRequest<Event[]>('/api/events?limit=200')])
    if (mark === generation.current) { setMails(mailData); setEvents(eventData.filter(event => event.status !== 'superseded')) }
  }

  async function selectSource(id: string) {
    if (preview?.preview_id) await privateRequest(`/api/imports/${preview.preview_id}`, { method: 'DELETE' }).catch(() => undefined)
    generation.current += 1
    setPreview(null); setSelected([]); setMails([]); setEvents([]); setDetail(null)
    await activateSource(id)
    setSelectedSource(id)
    const policy = await privateRequest<{scope: {recent_days: number; max_messages: number}}>(`/api/sources/${id}/policy`)
    setScope(policy.scope)
    await loadData()
  }

  async function create() {
    const source = await privateRequest<Source>('/api/sources', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'local_files', display_name: label, timezone: zone }) })
    setSources(previous => [...previous, source])
    await selectSource(source.id)
  }

  async function upload(file: File) {
    if (file.size > 10 * 1024 * 1024) throw new Error('文件超过 10 MiB，请缩小导出范围。')
    if (preview?.preview_id) await privateRequest(`/api/imports/${preview.preview_id}`, { method: 'DELETE' }).catch(() => undefined)
    setPreview(null); setDetail(null)
    const data = await privateRequest<Preview>('/api/imports/preview', { method: 'POST', headers: { 'X-Mail-Filename': encodeURIComponent(file.name), 'Content-Type': 'application/octet-stream' }, body: file })
    setPreview(data)
    // Unknown dates are visible but initially excluded, because the date range cannot be verified.
    setSelected(data.mails.filter(mail => mail.date_status !== 'unknown').map(mail => mail.id))
  }

  async function commit() {
    if (!preview?.preview_id) return
    const report = await privateRequest<{imported: number; updated: number; unchanged: number; events: number; errors: {code: string}[]}>(`/api/imports/${preview.preview_id}/commit`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ selected, mode }) })
    setPreview(null); setSelected([])
    await loadData()
    setNotice(`已导入 ${report.imported} 封，更新 ${report.updated} 封，重复 ${report.unchanged} 封；处理候选 ${report.events} 项。${report.errors.length ? ' 部分项目需检查，请查看邮件详情。' : ''}`)
  }

  async function reprocess(id: string, extractionMode: 'rules' | 'model') {
    await privateRequest(`/api/emails/${id}/reprocess`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: extractionMode }) })
    await loadData()
    setNotice(extractionMode === 'rules' ? '本地规则已重新处理；这不是模型推理。' : '模型候选已生成，请检查来源与时间。')
  }

  return <details className="local-import"><summary>导入我的本地邮件 <span>M3 · EML / MBOX</span></summary><div className="import-content">
    <p className="import-description">只读取你选择的文件。预览停留在内存中，确认后才写入本机数据库；下方三栏仍是独立的虚构演示。</p>
    <div className="import-toolbar"><label>本地来源<select aria-label="选择本地来源" disabled={busy} value={selectedSource} onChange={event => void task(() => selectSource(event.target.value))}><option value="" disabled>先创建或选择来源</option>{sources.map(source => <option key={source.id} value={source.id}>{source.display_name}</option>)}</select></label>
      <label>新来源名称<input aria-label="新来源名称" maxLength={80} value={label} disabled={busy} onChange={event => setLabel(event.target.value)} /></label>
      <label>邮件时区<select aria-label="邮件时区" value={zone} disabled={busy} onChange={event => setZone(event.target.value)}><option>Asia/Shanghai</option><option>UTC</option><option>America/New_York</option></select></label><button disabled={busy || !label.trim()} onClick={() => void task(create)}>创建来源</button></div>
    {selectedSource && <><p className="import-description">当前来源时区：{sources.find(source => source.id === selectedSource)?.timezone || '工作区时区'}。最近 {scope.recent_days} 天，本地导入最多 {Math.min(scope.max_messages, 200)} 封。日期未知的邮件需主动勾选。</p><div className="import-toolbar"><label className="file-pick">选择 EML / MBOX<input aria-label="选择邮件文件" type="file" accept=".eml,.mbox" disabled={busy} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void task(() => upload(file)) }} /></label><a href="/api/import-examples/sample.eml" download>下载虚构 EML</a><a href="/api/import-examples/sample.mbox" download>下载虚构 MBOX</a></div></>}
    {preview && <div className="import-preview"><h3>预览：{preview.mails.length} 封有效邮件</h3><p>文件内重复 {preview.report.duplicates_in_file} 封 · 范围外 {preview.report.outside_date_range} 封 · 无明确接收日期 {preview.report.unknown_dates} 封 · 无效邮件 {preview.report.errors.length} 封</p><div className="import-mail-scroll">{preview.mails.map(mail => <label className="preview-row" key={mail.id}><input type="checkbox" checked={selected.includes(mail.id)} disabled={busy} onChange={event => setSelected(previous => event.target.checked ? [...previous, mail.id] : previous.filter(id => id !== mail.id))} /><span><b>{mail.subject}</b><small>{mail.sender} · {mail.date_status === 'unknown' ? '接收日期未知' : '日期可用'}</small></span></label>)}</div>
      <label className="extraction-choice">保存后如何处理？<select aria-label="提取方式" value={mode} disabled={busy} onChange={event => setMode(event.target.value as 'browse' | 'rules')}><option value="browse">仅导入浏览（默认，不调用模型）</option><option value="rules">本地规则提取（不是 NLP 模型）</option></select></label>
      <div className="import-toolbar"><button disabled={busy || !preview.preview_id || !selected.length} onClick={() => void task(commit)}>确认保存 {selected.length} 封</button><button disabled={busy} onClick={() => void task(async () => { if (preview.preview_id) await privateRequest(`/api/imports/${preview.preview_id}`, { method: 'DELETE' }); setPreview(null) })}>取消预览</button></div></div>}
    {selectedSource && <div className="import-results"><div><h3>此来源邮件 · {mails.length}</h3>{mails.map(mail => <article key={mail.id}><button className="import-mail-title" disabled={busy} onClick={() => void task(async () => setDetail(await privateRequest<MailDetail>(`/api/emails/${mail.id}`)))}>{mail.subject}</button><small>{mail.extraction_method === 'rules' ? '规则处理' : mail.extraction_method === 'model' ? '模型候选' : '未提取'}</small><div className="import-toolbar"><button disabled={busy} onClick={() => void task(() => reprocess(mail.id, 'rules'))}>规则重处理</button><button disabled={busy} onClick={() => void task(() => reprocess(mail.id, 'model'))}>使用已配置模型</button></div></article>)}</div><div><h3>日程候选 · {events.length}</h3>{events.map(event => <article key={event.id}><b>{event.title}</b><small>{event.status === 'confirmed' ? '有明确时间/日期' : '待确认时间'}{event.source_changed ? ' · 原通知已更新' : ''}</small><p>{event.start_at_utc ? new Date(event.start_at_utc).toLocaleString('zh-CN', { timeZone: sources.find(source => source.id === selectedSource)?.timezone || 'Asia/Shanghai' }) : event.event_date || '未指定日期'}{!event.start_at_utc && event.event_date ? ' · 具体时刻未知' : ''}</p><button disabled={busy} onClick={() => void task(async () => setDetail(await privateRequest<MailDetail>(`/api/emails/${event.source_email_id}`)))}>查看来源邮件</button></article>)}</div></div>}
    {detail && <div className="import-detail"><h3>{detail.subject}</h3><small>{detail.source_locator}</small>{(detail.import_warnings.length > 0 || detail.extraction_warnings.length > 0) && <p>检查提示：{[...detail.import_warnings, ...detail.extraction_warnings].join(" · ")}</p>}<p>{detail.body_text ?? '当前策略未保留正文，无法离线查看或重处理。'}</p><button onClick={() => setDetail(null)}>关闭详情</button></div>}
    {busy && <p role="status">正在处理，请稍候…</p>}{notice && <p role="status" className="import-notice">{notice}</p>}
    <p className="import-description">模型提取只使用服务端已配置的 Provider，并遵守此来源的云端授权；没有模型时保留邮件可供浏览。语义索引任务仍等待后续本地模型接入。</p>
  </div></details>
}
