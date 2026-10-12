import { useEffect, useRef, useState } from 'react'
import { establishSession, getDemo } from './api/client'
import { labels, quickActions } from './i18n'
import type { Category, Demo, Email, Event, EventType } from './types'

function Icon({ kind }: { kind: 'calendar' | 'mail' | 'chat' | 'book' | 'settings' | 'arrow' }) {
  const paths = {
    calendar: 'M7 3v4m10-4v4M4 10h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Z',
    mail: 'M3 5h18v14H3V5Zm0 1 9 7 9-7',
    chat: 'M4 4h16v12H9l-5 4V4Zm4 5h8m-8 3h5',
    book: 'M12 5v16M3 4h5l4 2 4-2h5v15h-5l-4 2-4-2H3V4Z',
    settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-5v2m0 14v2M3 12h2m14 0h2M6 6l1 1m10 10 1 1M6 18l1-1M17 7l1-1',
    arrow: 'M4 12h16m-6-6 6 6-6 6',
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true" className="icon"><path d={paths[kind]} /></svg>
}

function eventDay(event: Event, timezone: string) {
  if (!event.start_at) return event.date ?? ''
  const parts = new Intl.DateTimeFormat('en', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(event.start_at))
  const part = (name: string) => parts.find(item => item.type === name)?.value
  return `${part('year')}-${part('month')}-${part('day')}`
}

function eventTime(event: Event, timezone: string) {
  if (!event.start_at) return event.all_day ? '全天' : '具体时刻未知'
  return new Intl.DateTimeFormat('zh-CN', { timeZone: timezone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(event.start_at))
}

type Message = { role: 'user' | 'assistant'; text: string; emailIds?: string[] }

function Assistant({ demo, openEmail }: { demo: Demo; openEmail: (id: string) => void }) {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const thread = useRef<HTMLDivElement>(null)
  useEffect(() => { thread.current?.scrollTo({ top: thread.current.scrollHeight }) }, [messages])

  function send(query: string) {
    const text = query.trim()
    if (!text) return
    const today = demo.meta.demo_date
    const active = demo.events.filter(event => event.status === 'confirmed')
    let selected: Event[] = []
    let answer = ''
    let emailIds: string[] = []
    if (text === quickActions[0]) {
      selected = active.filter(event => eventDay(event, demo.meta.timezone) === today)
      answer = `演示日期 ${today} 的安排：\n${selected.map(event => `• ${eventTime(event, demo.meta.timezone)} ${event.title}`).join('\n') || '没有安排。'}`
    } else if (text === quickActions[1]) {
      const start = new Date(`${today}T12:00:00Z`)
      const weekday = (start.getUTCDay() + 6) % 7
      start.setUTCDate(start.getUTCDate() - weekday)
      const end = new Date(start)
      end.setUTCDate(end.getUTCDate() + 7)
      const from = start.toISOString().slice(0, 10), to = end.toISOString().slice(0, 10)
      selected = active.filter(event => event.type === 'deadline' && from <= eventDay(event, demo.meta.timezone) && eventDay(event, demo.meta.timezone) < to)
      answer = `本周（${from} 起）的虚构 DDL：\n${selected.map(event => `• ${eventDay(event, demo.meta.timezone)} ${event.title} · ${eventTime(event, demo.meta.timezone)}`).join('\n') || '没有 DDL。'}`
    } else if (text === quickActions[2]) {
      const starred = demo.emails.filter(mail => mail.local_star).slice(0, 5)
      answer = `预置星标邮件示例：\n${starred.map(mail => `• ${mail.subject}`).join('\n')}`
      emailIds = starred.map(mail => mail.id)
    } else if (text === quickActions[3]) {
      selected = demo.recommendations
      answer = `预置活动列表（尚未执行个性化排序）：\n${selected.map(event => `• ${eventDay(event, demo.meta.timezone)} ${event.title}`).join('\n')}`
    } else {
      answer = '目前是虚构演示，我还不能理解任意问题。可以点击下面四个快捷操作查看预置数据。真实模型、SMOA 和邮箱连接将在后续阶段接入。'
    }
    if (selected.length) emailIds = [...new Set(selected.map(event => event.source_email_id))]
    setMessages(previous => [...previous, { role: 'user', text }, { role: 'assistant', text: answer, emailIds }])
    setInput('')
  }

  return <section className="panel assistant" id="assistant" aria-labelledby="assistant-title">
    <div className="panel-heading"><h2 id="assistant-title"><Icon kind="chat" />私人秘书</h2><span className="subtle">预置回答</span></div>
    <div className="chat-thread" ref={thread} aria-live="polite">
      {!messages.length && <div className="assistant-empty"><div className="assistant-orb"><Icon kind="chat" /></div><h3>让校园生活，井然有序。</h3><p>从今天的安排开始，<br />体验你的私人校园助理。</p><span className="tiny-label">FICTIONAL DATA · NO CLOUD</span></div>}
      {messages.map((message, index) => <div key={index} className={`bubble ${message.role}`}><p>{message.text}</p>{!!message.emailIds?.length && <div className="citations">{message.emailIds.map(id => <button key={id} onClick={() => openEmail(id)}>来源 {id}</button>)}</div>}</div>)}
    </div>
    <div className="quick-actions">{quickActions.map((action, index) => <button key={action} onClick={() => send(action)}><span aria-hidden="true">{['◷', '▤', '✉', '✧'][index]}</span>{action}</button>)}</div>
    <form className="chat-form" onSubmit={event => { event.preventDefault(); send(input) }}><input aria-label="向演示助手提问" placeholder="试试上面的快捷操作…" maxLength={500} value={input} onChange={event => setInput(event.target.value)} /><button aria-label="发送" disabled={!input.trim()}><Icon kind="arrow" /></button></form>
    <p className="panel-footnote">预置回答，无模型调用；不会保存对话。</p>
  </section>
}

export default function App() {
  const [demo, setDemo] = useState<Demo | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [eventFilter, setEventFilter] = useState<'all' | EventType>('all')
  const [mailFilter, setMailFilter] = useState<'all' | Category>('all')
  const [stars, setStars] = useState<Set<string>>(new Set())
  const [selectedMail, setSelectedMail] = useState<Email | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [foundationStatus, setFoundationStatus] = useState('正在准备本机会话')
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    let active = true
    establishSession().then(() => { if (active) setFoundationStatus('启动检查通过：本机会话与防跨站保护') })
      .catch(() => { if (active) setFoundationStatus('本机会话暂不可用；虚构预览仍可查看') })
    return () => { active = false }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setError('')
    getDemo(controller.signal).then(data => {
      setDemo(data)
      setStars(new Set(data.emails.filter(mail => mail.local_star).map(mail => mail.id)))
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '加载失败') })
    return () => controller.abort()
  }, [retry])

  useEffect(() => {
    if (selectedMail || showSettings) dialog.current?.showModal()
    else dialog.current?.close()
  }, [selectedMail, showSettings])

  function openEmail(id: string) { setSelectedMail(demo?.emails.find(mail => mail.id === id) ?? null) }
  function closeDialog() { setSelectedMail(null); setShowSettings(false) }
  function toggleStar(id: string) { setStars(previous => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next }) }
  const events = demo?.events.filter(event => event.status === 'confirmed' && (eventFilter === 'all' || event.type === eventFilter)).sort((a, b) => (a.start_at ?? a.date ?? '').localeCompare(b.start_at ?? b.date ?? '')) ?? []
  const days = [...new Set(events.map(event => eventDay(event, demo?.meta.timezone ?? 'Asia/Shanghai')))]
  const emails = demo?.emails.filter(mail => mailFilter === 'all' || mail.category === mailFilter) ?? []

  return <>
    <header className="app-header"><div className="header-inner">
      <a className="brand" href="#home"><span className="brand-mark"><Icon kind="book" /></span>Campus<span>Flow</span></a>
      <nav aria-label="主导航"><a href="#home" className="nav-active">主页</a><a href="#assistant">对话</a></nav>
      <div className="header-actions"><span className="source-pill">虚构校园邮箱</span><span className="model-pill"><i />离线演示</span><button aria-label="设置" onClick={() => setShowSettings(true)} className="settings-button"><Icon kind="settings" /><span>设置</span></button></div>
    </div></header>
    <main id="home">
      <section className="welcome"><div><p className="eyebrow">YOUR CAMPUS, IN ONE PLACE</p><h1>欢迎回来<span className="wave" aria-hidden="true">✦</span></h1><p className="welcome-subtitle">把重要的事，留在眼前。</p></div><div className="date-display"><span>{demo?.meta.demo_date ?? '正在准备演示'}</span><small>{demo?.meta.timezone ?? 'Asia/Shanghai'}</small></div></section>
      <div className="demo-banner"><span className="banner-tag">M2 · DEMO</span><p>全量虚构数据 · 未连接邮箱 · 无需 API Key · 不发送到云端</p><button onClick={() => setShowSettings(true)}>了解演示范围 <span aria-hidden="true">↗</span></button></div>
      {error ? <div role="alert" className="load-state"><h2>暂时无法加载演示</h2><p>{error}。请检查本地服务是否启动。</p><button onClick={() => setRetry(value => value + 1)}>重新加载</button></div> : !demo ? <div role="status" className="load-state">正在加载虚构校园数据…</div> : <>
        <div className="overview-strip"><span><b>{demo.stats.today_events}</b> 今日安排</span><span><b>{demo.stats.upcoming_deadlines}</b> 未来 7 天 DDL</span><span><b>{demo.emails.length}</b> 虚构邮件</span><span><b>{demo.stats.needs_confirmation}</b> 待确认时间</span></div>
        <div className="dashboard-grid">
          <section className="panel calendar" aria-labelledby="calendar-title"><div className="panel-heading"><h2 id="calendar-title"><Icon kind="calendar" />日程 <span className="badge">{demo.stats.upcoming_deadlines} DDL</span></h2><span className="subtle">按天查看</span></div>
            <div className="tabs" aria-label="日程分类">{(['all', 'deadline', 'course', 'activity', 'personal'] as const).map(type => <button key={type} aria-pressed={eventFilter === type} className={eventFilter === type ? 'selected' : ''} onClick={() => setEventFilter(type)}>{type === 'all' ? '全部' : labels[type]}</button>)}</div>
            <div className="panel-scroll">{days.map(day => <div className="day-group" key={day}><h3>{new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short', timeZone: 'UTC' }).format(new Date(`${day}T12:00:00Z`))}{day === demo.meta.demo_date && <span>今天</span>}</h3>{events.filter(event => eventDay(event, demo.meta.timezone) === day).map(event => <button className={`event-card ${event.type}`} key={event.id} onClick={() => openEmail(event.source_email_id)}><div className="event-top"><strong>{event.title}</strong><span className="type-label">{labels[event.type]}</span></div><p>{eventTime(event, demo.meta.timezone)}{event.location && ` · ${event.location}`}</p><small>查看来源通知 <span aria-hidden="true">↗</span></small></button>)}</div>)}{!events.length && <p className="empty-list">这个分类暂无演示日程。</p>}</div>
            <p className="panel-footnote">日期不明的通知保留为待确认，不编造时间。</p>
          </section>
          <section className="panel email" aria-labelledby="email-title"><div className="panel-heading"><h2 id="email-title"><Icon kind="mail" />邮件 <span className="count">{emails.length}</span></h2><span className="subtle">示例来源</span></div>
            <div className="tabs" aria-label="邮件分类">{(['all', 'academic', 'admin', 'activity'] as const).map(type => <button key={type} aria-pressed={mailFilter === type} className={mailFilter === type ? 'selected' : ''} onClick={() => setMailFilter(type)}>{type === 'all' ? '全部' : labels[type]}</button>)}</div>
            <div className="panel-scroll mail-list">{emails.map(mail => <article className="mail-card" key={mail.id}><div className="mail-meta"><span className={`read-dot ${mail.local_read ? 'read' : ''}`} aria-label={mail.local_read ? '已读样例' : '未读样例'} /><button className={`star ${stars.has(mail.id) ? 'starred' : ''}`} aria-label={`${stars.has(mail.id) ? '取消' : '添加'}星标：${mail.subject}`} aria-pressed={stars.has(mail.id)} onClick={() => toggleStar(mail.id)}>{stars.has(mail.id) ? '★' : '☆'}</button><strong>{mail.sender_name}</strong><span className={`category-dot ${mail.category}`} /></div><button className="mail-content" onClick={() => openEmail(mail.id)}><h3>{mail.subject}</h3><p>{mail.summary}</p></button></article>)}</div>
            <p className="panel-footnote">星标只在本次页面中变化，不写入邮箱。</p>
          </section>
          <Assistant demo={demo} openEmail={openEmail} />
        </div>
        <section className="recommendations" aria-labelledby="recommendation-title"><div className="recommendation-heading"><div><p className="eyebrow">EXPLORE SOMETHING NEW</p><h2 id="recommendation-title">推荐活动 <span className="subtle">虚构活动预览</span></h2></div><span className="recommendation-note">预置列表，个性化推荐将在 M7 接入</span></div><div className="recommendation-list">{demo.recommendations.map((event, index) => <article key={event.id} className="rec-card"><span className="rec-number">{String(index + 1).padStart(2, '0')}</span><div className="rec-body"><h3>{event.title}</h3><p>{eventDay(event, demo.meta.timezone)} · {eventTime(event, demo.meta.timezone)} · {event.location}</p>{event.capacity_remaining !== null && <small>通知发布时剩余 {event.capacity_remaining} 个名额 · 非实时信息</small>}</div><button className="rec-link" onClick={() => openEmail(event.source_email_id)}>查看通知 <Icon kind="arrow" /></button></article>)}</div></section>
      </>}
      <footer><span>CampusFlow <span className="subtle">/ 开源重建</span></span><span>M2 · FixtureProvider · 所有内容均为虚构</span></footer>
    </main>
    <dialog ref={dialog} onCancel={closeDialog} onClose={closeDialog} aria-labelledby="dialog-title"><div className="dialog-header"><h2 id="dialog-title">{selectedMail ? '虚构邮件详情' : '演示与隐私'}</h2><button autoFocus onClick={closeDialog} aria-label="关闭">×</button></div>{selectedMail ? <div className="dialog-content"><span className="tiny-label">FICTIONAL · {selectedMail.id}</span><h3>{selectedMail.subject}</h3><p className="subtle">{selectedMail.sender_name} &lt;{selectedMail.sender}&gt;</p><p className="mail-body">{selectedMail.body_text}</p><p className="dialog-note">这是一封人工构造的虚构邮件，不来自真实邮箱。</p></div> : <div className="dialog-content"><p className="settings-lead">先体验，再连接。</p><p>当前为 M2 的虚构演示。本机会话、来源隔离和处理权限已建立，预览仍只读取公开样例，不访问真实邮箱或外部模型。</p><dl><dt>本机保护</dt><dd>{foundationStatus}</dd><dt>本地存储</dt><dd>数据库已初始化；演示数据仍独立读取公开样例，未导入真实邮件。</dd><dt>数据来源</dt><dd>30 封虚构邮件，彼此引用的标注日程</dd><dt>模型与检索</dt><dd>预置回答；没有模型调用或向量检索</dd><dt>保存方式</dt><dd>页面内存，刷新后星标和对话重置</dd><dt>后续连接</dt><dd>本地 EML/MBOX → 只读 IMAP / MCP</dd></dl><p className="dialog-note">邮箱选择、授权及数据清理会在后续阶段提供，此处尚未实现真实连接。</p></div>}</dialog>
  </>
}
