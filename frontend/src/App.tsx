import { useEffect, useRef, useState } from 'react'
import { activateSource, deactivateSource, establishSession, getDemo, privateRequest } from './api/client'
import { labels } from './i18n'
import type { Category, Demo, Email, Event, EventType, Policy, Provider, Snapshot, Source } from './types'
import { eventDay, eventTime, Icon, nextDay } from './view'
import Assistant from './Assistant'
import LocalImport from './LocalImport'
import Settings from './Settings'

const json = (body:unknown,method='POST'):RequestInit => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})

export default function App() {
  const [choice,setChoice]=useState('welcome'), [sources,setSources]=useState<Source[]>([])
  const [demo,setDemo]=useState<Demo|null>(null), [snapshot,setSnapshot]=useState<Snapshot|null>(null)
  const [policy,setPolicy]=useState<Policy|null>(null), [provider,setProvider]=useState<Provider|null>(null)
  const [workspaceZone,setWorkspaceZone]=useState('Asia/Shanghai')
  const [busy,setBusy]=useState(false), [loading,setLoading]=useState(false), [error,setError]=useState(''), [notice,setNotice]=useState('')
  const [page,setPage]=useState('home'), [mobile,setMobile]=useState('calendar'), [importOpen,setImportOpen]=useState(false)
  const [eventFilter,setEventFilter]=useState<'all'|EventType>('all'), [mailFilter,setMailFilter]=useState<'all'|Category|'unprocessed'>('all')
  const [starOnly,setStarOnly]=useState(false), [stars,setStars]=useState<Set<string>>(new Set())
  const [detail,setDetail]=useState<Email|null>(null), [selectedEvent,setSelectedEvent]=useState<Event|null>(null), [showSettings,setShowSettings]=useState(false)
  const dialog=useRef<HTMLDialogElement>(null), epoch=useRef(0), locked=useRef(false)
  const source=sources.find(item=>item.id===choice) ?? null
  const fictional=choice==='demo'
  const timezone=fictional ? demo?.meta.timezone ?? workspaceZone : snapshot?.timezone ?? source?.timezone ?? workspaceZone
  const today=fictional ? demo?.meta.demo_date ?? '' : snapshot?.today ?? ''
  const allEmails:Email[]=fictional ? (demo?.emails ?? []).map(mail=>({...mail,local_star:stars.has(mail.id)})) : (snapshot?.emails ?? []).map(mail=>({...mail,sender_name:mail.sender,body_text:null,tags:[],summary:mail.summary ?? ''}))
  const allEvents:Event[]=fictional ? demo?.events ?? [] : (snapshot?.events ?? []).map(event=>({...event,evidence:event.evidence ?? '',capacity_remaining:null,supersedes_event_id:null}))
  const stats=fictional ? demo?.stats : snapshot?.stats
  const emails=allEmails.filter(mail=>(mailFilter==='all' || (mailFilter==='unprocessed' ? !mail.category : mail.category===mailFilter)) && (!starOnly || mail.local_star))
  const active=allEvents.filter(event=>event.status==='confirmed' && (eventFilter==='all'||event.type===eventFilter)).sort((a,b)=>eventDay(a,timezone).localeCompare(eventDay(b,timezone)) || (a.start_at??'').localeCompare(b.start_at??''))
  const pending=allEvents.filter(event=>event.status==='needs_confirmation' && (eventFilter==='all'||event.type===eventFilter))
  const days=[...new Set(active.map(event=>eventDay(event,timezone)).filter(Boolean))]
  const activities=allEvents.filter(event=>event.status==='confirmed' && event.type==='activity' && eventDay(event,timezone)>=today).sort((a,b)=>eventDay(a,timezone).localeCompare(eventDay(b,timezone)))
  const ready=fictional ? !!demo : !!snapshot

  useEffect(()=>{
    let alive=true
    Promise.all([establishSession(),privateRequest<Source[]>('/api/sources'),privateRequest<Provider>('/api/provider-status')])
      .then(([session,items,config])=>{if(alive){setSources(items.filter(item=>item.kind==='local_files'));setProvider(config);setWorkspaceZone(session.workspace_timezone)}})
      .catch(()=>{if(alive)setNotice('本地服务暂不可用；请确认服务启动后重新加载。')})
    return ()=>{alive=false}
  },[])
  useEffect(()=>{
    if(detail || selectedEvent || showSettings) {if(!dialog.current?.open)dialog.current?.showModal()}
    else dialog.current?.close()
  },[detail,selectedEvent,showSettings])
  function closeDialog(){setDetail(null);setSelectedEvent(null);setShowSettings(false)}
  function markBusy(value:boolean){locked.current=value;setBusy(value)}
  async function task(action:()=>Promise<void>) {
    if(locked.current)return
    markBusy(true);setNotice('')
    try{await action()}catch(reason){setNotice(reason instanceof Error?reason.message:'操作未完成')}
    finally{markBusy(false)}
  }
  async function loadPrivate(id:string,mailOffset=0,eventOffset=0) {
    const mark=epoch.current
    setLoading(true);setError('')
    try {
      const [data,permissions,config]=await Promise.all([
        privateRequest<Snapshot>(`/api/dashboard?mail_offset=${mailOffset}&event_offset=${eventOffset}`,{},id),
        privateRequest<Policy>(`/api/sources/${id}/policy`,{},id),privateRequest<Provider>('/api/provider-status')])
      if(mark===epoch.current && data.source_id===id){setSnapshot(data);setPolicy(permissions);setProvider(config)}
    }catch(reason){if(mark===epoch.current){setSnapshot(null);setError(reason instanceof Error?reason.message:'读取未完成')}throw reason}
    finally{if(mark===epoch.current)setLoading(false)}
  }
  async function select(id:string) {
    epoch.current+=1;setChoice(id);setSnapshot(null);setDemo(null);setPolicy(null);setError('');setNotice('')
    setDetail(null);setSelectedEvent(null);setPage('home');setMobile('calendar');setImportOpen(false);setShowSettings(false)
    setEventFilter('all');setMailFilter('all');setStarOnly(false);setStars(new Set())
    setLoading(true)
    try {
      if(id==='demo') {await deactivateSource();const data=await getDemo();setDemo(data);setStars(new Set(data.emails.filter(mail=>mail.local_star).map(mail=>mail.id)))}
      else {await activateSource(id);await loadPrivate(id)}
    }catch(reason){setError(reason instanceof Error?reason.message:'加载未完成')}
    finally{setLoading(false)}
  }
  async function create(label:string,zone:string) {
    if(locked.current)return
    markBusy(true)
    try{const item=await privateRequest<Source>('/api/sources',json({kind:'local_files',display_name:label,timezone:zone}));setSources(previous=>[...previous,item]);await select(item.id);setImportOpen(true)}finally{markBusy(false)}
  }
  async function savePolicy(body:Record<string,unknown>) {
    if(!source || locked.current)return
    markBusy(true)
    try{await privateRequest(`/api/sources/${source.id}/policy`,json(body,'PATCH'),source.id);await loadPrivate(source.id,snapshot?.mail_offset,snapshot?.event_offset)}finally{markBusy(false)}
  }
  async function openEmail(id:string) {
    setSelectedEvent(null)
    if(fictional){setDetail(allEmails.find(mail=>mail.id===id)??null);return}
    if(!source)return
    await task(async()=>{
      const mail=await privateRequest<Email>(`/api/emails/${id}`,{},source.id)
      setDetail({...mail,sender_name:mail.sender,tags:[],summary:mail.summary??''})
      if(!mail.local_read){await privateRequest(`/api/emails/${id}/flags`,json({local_read:true},'PATCH'),source.id);setSnapshot(previous=>previous?{...previous,emails:previous.emails.map(item=>item.id===id?{...item,local_read:true}:item)}:previous);setDetail(previous=>previous?{...previous,local_read:true}:previous)}
    })
  }
  async function toggleStar(mail:Email) {
    if(fictional){setStars(previous=>{const next=new Set(previous);if(next.has(mail.id))next.delete(mail.id);else next.add(mail.id);return next});return}
    if(!source)return
    await task(async()=>{await privateRequest(`/api/emails/${mail.id}/flags`,json({local_star:!mail.local_star},'PATCH'),source.id);setSnapshot(previous=>previous?{...previous,emails:previous.emails.map(item=>item.id===mail.id?{...item,local_star:!mail.local_star}:item)}:previous);setDetail(previous=>previous?.id===mail.id?{...previous,local_star:!mail.local_star}:previous)})
  }
  async function reprocess(mode:'rules'|'model') {
    if(!source || !detail)return
    const id=detail.id
    await task(async()=>{await privateRequest(`/api/emails/${id}/reprocess`,json({mode}),source.id);await loadPrivate(source.id,snapshot?.mail_offset,snapshot?.event_offset);const mail=await privateRequest<Email>(`/api/emails/${id}`,{},source.id);setDetail({...mail,sender_name:mail.sender,tags:[],summary:mail.summary??''});setNotice(mode==='rules'?'本地规则已重新处理。':'模型候选已生成，请核对证据。')})
  }
  function paging(kind:'mail'|'event',offset:number) {if(source)void task(()=>loadPrivate(source.id,kind==='mail'?offset:snapshot?.mail_offset,kind==='event'?offset:snapshot?.event_offset))}
  function eventCard(event:Event) {return <button className={`event-card ${event.type}`} key={event.id} disabled={busy} onClick={()=>setSelectedEvent(event)}><div className="event-top"><strong>{event.title}</strong><span className="type-label">{labels[event.type]}</span></div><p>{eventDay(event,timezone)||'日期未知'} · {eventTime(event,timezone)}{event.location && ` · ${event.location}`}</p><small>{event.status==='needs_confirmation'?'待核对日期与时间':'查看详情与来源'}{event.source_changed?' · 原通知已更新':''} ↗</small></button>}

  return <><header className="app-header"><div className="header-inner"><a className="brand" href="#home" onClick={()=>setPage('home')}><span className="brand-mark"><Icon kind="book"/></span>Campus<span>Flow</span></a><nav aria-label="主导航"><button aria-current={page==='home'?'page':undefined} className={page==='home'?'nav-active':''} onClick={()=>setPage('home')}>主页</button><button aria-current={page==='conversation'?'page':undefined} className={page==='conversation'?'nav-active':''} disabled={!ready} onClick={()=>setPage('conversation')}>对话</button></nav><div className="header-actions"><label className="source-selector"><span className="sr-only">当前来源</span><select aria-label="当前来源" value={choice} disabled={busy || loading} onChange={event=>void task(()=>select(event.target.value))}><option value="welcome" disabled>选择数据来源</option><option value="demo">虚构演示</option>{sources.map(item=><option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label><span className="model-pill"><i/>{fictional?'虚构演示':'本地浏览'}</span><button aria-label="设置" disabled={busy} className="settings-button" onClick={()=>{setDetail(null);setSelectedEvent(null);setShowSettings(true)}}><Icon kind="settings"/><span>设置</span></button></div></div></header>
    <main id="home"><section className="welcome"><div><p className="eyebrow">YOUR CAMPUS, IN ONE PLACE</p><h1>{page==='conversation'?'你的私人秘书':'欢迎回来'}<span className="wave" aria-hidden="true">✦</span></h1><p className="welcome-subtitle">{source?`${source.display_name} · 只查看当前来源`:'把重要的事，留在眼前。'}</p></div><div className="date-display"><span>{today}</span><small>{timezone}</small></div></section>
    {choice==='welcome'?<section className="onboarding"><h2>从哪里开始？</h2><p>先体验虚构校园数据，或选择你自己的本地邮件。数据来源之间独立显示。</p><div className="onboarding-actions"><button className="primary-button" disabled={busy} onClick={()=>void task(()=>select('demo'))}>体验虚构演示</button><button disabled={busy} onClick={()=>setShowSettings(true)}>导入我的本地邮件</button></div><p className="subtle">无需邮箱密码或 API Key；不会自动扫描文件或连接账号。</p></section>:<>
    <div className="demo-banner"><span className="banner-tag">M4 · {fictional?'DEMO':'LOCAL'}</span><p>{fictional?'全量虚构样例 · 快捷查询无模型调用':`本机数据 · ${provider?.configured ? '模型需主动调用' : '规则处理可用，尚未配置模型'} · ${provider?.remote_globally_enabled && policy?.allow_remote_processing && policy.consent_fingerprint===provider?.fingerprint?'此来源已授权指定云端服务':'云端未授权'}`}</p><button disabled={busy} onClick={()=>setShowSettings(true)}>来源与隐私 ↗</button></div>
    {source && page==='home' && <LocalImport key={source.id} source={source} policy={policy} busy={busy} onBusy={markBusy} onSaved={()=>loadPrivate(source.id)} open={importOpen} onOpen={setImportOpen}/>}
    {source && <div className="source-status"><span>最近导入：{snapshot?.processing.last_import_at?new Date(snapshot.processing.last_import_at).toLocaleString('zh-CN',{timeZone:timezone}):'尚未导入'} · 邮箱同步未连接</span><button disabled={busy || loading} onClick={()=>{setPage("home");setImportOpen(true)}}>导入邮件</button><button disabled={busy || loading} onClick={()=>void task(async()=>{await activateSource(source.id);await loadPrivate(source.id,snapshot?.mail_offset,snapshot?.event_offset)})}>刷新此来源</button><details><summary>查看处理状态</summary><p>解析与提取在导入或重处理时完成。待索引任务 {Object.entries(snapshot?.processing.index_jobs ?? {}).filter(([key])=>key!=='done').reduce((total,[,count])=>total+count,0)} 项；本地语义索引尚未接入，不代表同步完成。</p></details></div>}
    {error?<div role="alert" className="load-state"><h2>暂时无法加载当前来源</h2><p>{error}</p><button disabled={busy} onClick={()=>void task(()=>select(choice))}>重新选择并加载</button></div>:!ready?<div role="status" className="load-state">正在加载当前来源…</div>:<>
    <div className="overview-strip"><span><b>{stats?.today_events??0}</b> 今日安排</span><span><b>{stats?.upcoming_deadlines??0}</b> 未来 7 天 DDL</span><span><b>{fictional?allEmails.length:snapshot?.mail_total}</b> {fictional?'虚构邮件':'本地邮件'}</span><span><b>{stats?.needs_confirmation??0}</b> 待确认时间</span></div>
    {page==='home' && <div className="mobile-tabs" aria-label="手机面板">{[['calendar','日程'],['email','邮件'],['assistant','助手']].map(([key,name])=><button key={key} aria-pressed={mobile===key} className={mobile===key?'selected':''} onClick={()=>setMobile(key)}>{name}</button>)}</div>}
    <div className={`dashboard-grid ${page==='conversation'?'conversation-view':''} mobile-${mobile}`}>
    <section className="panel calendar" aria-labelledby="calendar-title"><div className="panel-heading"><h2 id="calendar-title"><Icon kind="calendar"/>日程 <span className="badge">{stats?.upcoming_deadlines??0} DDL</span></h2><span className="subtle">按天查看</span></div><div className="tabs" aria-label="日程分类">{(['all','deadline','course','activity','personal'] as const).map(type=><button key={type} aria-pressed={eventFilter===type} className={eventFilter===type?'selected':''} onClick={()=>setEventFilter(type)}>{type==='all'?'全部':labels[type]}</button>)}</div><div className="panel-scroll">{days.map(day=><div className="day-group" key={day}><h3>{new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'short',timeZone:'UTC'}).format(new Date(`${day}T12:00:00Z`))}{(day===today||day===nextDay(today))&&<span>{day===today?'今天':'明天'}</span>}</h3>{active.filter(event=>eventDay(event,timezone)===day).map(eventCard)}</div>)}{!!pending.length&&<div className="day-group pending-group"><h3>待确认 · {pending.length}</h3>{pending.map(eventCard)}</div>}{!active.length&&!pending.length&&<div className="empty-list"><p>此分类暂无日程。</p><p>导入后选择规则提取，或在邮件详情中重处理。</p></div>}</div>{snapshot&&<div className="pagination"><button disabled={busy||snapshot.event_offset===0} onClick={()=>paging('event',Math.max(0,snapshot.event_offset-50))}>上一页日程</button><span>{snapshot.event_total?`${snapshot.event_offset+1}–${Math.min(snapshot.event_offset+50,snapshot.event_total)}`:'0'} / {snapshot.event_total}</span><button disabled={busy||snapshot.event_offset+50>=snapshot.event_total} onClick={()=>paging('event',snapshot.event_offset+50)}>下一页日程</button></div>}<p className="panel-footnote">日期不明保留为待确认，不编造时间。当前显示一页日程。</p></section>
    <section className="panel email" aria-labelledby="email-title"><div className="panel-heading"><h2 id="email-title"><Icon kind="mail"/>邮件 <span className="count">{emails.length}</span></h2><button className="text-button" aria-pressed={starOnly} onClick={()=>setStarOnly(!starOnly)}>{starOnly?'显示全部':'只看星标'}</button></div><div className="tabs mail-tabs" aria-label="邮件分类">{(['all','academic','admin','activity','unprocessed'] as const).map(type=><button key={type} aria-pressed={mailFilter===type} className={mailFilter===type?'selected':''} onClick={()=>setMailFilter(type)}>{type==='all'?'全部':type==='unprocessed'?'未分类':labels[type]}</button>)}</div><div className="panel-scroll mail-list">{emails.map(mail=><article className="mail-card" key={mail.id}><div className="mail-meta"><span className={`read-dot ${mail.local_read?'read':''}`} aria-label={mail.local_read?'本地已读':'本地未读'}/><button className={`star ${mail.local_star?'starred':''}`} aria-label={`${mail.local_star?'取消':'添加'}星标：${mail.subject}`} aria-pressed={mail.local_star} disabled={busy} onClick={()=>void toggleStar(mail)}>{mail.local_star?'★':'☆'}</button><strong>{mail.sender_name}</strong><span className={`category-dot ${mail.category??''}`} title={mail.category?labels[mail.category]:'未分类'}/></div><button className="mail-content" disabled={busy} onClick={()=>void openEmail(mail.id)}><h3>{mail.subject}</h3><p>{mail.summary||'暂无摘要'}</p><small>{mail.received_at?new Date(mail.received_at).toLocaleDateString('zh-CN',{timeZone:timezone}):'接收日期未知'} · {fictional?'虚构样例':mail.extraction_method==='rules'?'规则候选':mail.extraction_method==='model'?'模型候选':'尚未提取'}</small></button></article>)}{!emails.length&&<div className="empty-list"><p>{allEmails.length?'此筛选暂无邮件。':'此来源还没有邮件。'}</p>{!fictional&&<button onClick={()=>setImportOpen(true)}>选择文件开始导入</button>}</div>}</div>{snapshot&&<div className="pagination"><button disabled={busy||snapshot.mail_offset===0} onClick={()=>paging('mail',Math.max(0,snapshot.mail_offset-50))}>上一页邮件</button><span>{snapshot.mail_total?`${snapshot.mail_offset+1}–${Math.min(snapshot.mail_offset+50,snapshot.mail_total)}`:'0'} / {snapshot.mail_total}</span><button disabled={busy||snapshot.mail_offset+50>=snapshot.mail_total} onClick={()=>paging('mail',snapshot.mail_offset+50)}>下一页邮件</button></div>}<p className="panel-footnote">{fictional?'演示星标刷新后重置。':'星标与已读保存在本机，不修改远端邮箱。'}筛选作用于当前页。</p></section>
    <Assistant key={choice} emails={allEmails} events={allEvents} today={today} timezone={timezone} fictional={fictional} openEmail={id=>void openEmail(id)} expanded={page==='conversation'} onExpand={()=>setPage(page==='home'?'conversation':'home')}/>
    </div>
    {page==='home'&&<section className="recommendations" aria-labelledby="recommendation-title"><div className="recommendation-heading"><div><p className="eyebrow">EXPLORE SOMETHING NEW</p><h2 id="recommendation-title">推荐活动 <span className="subtle">当前页活动</span></h2></div><span className="recommendation-note">按日期列出，个性化推荐将在 M7 接入</span></div><div className="recommendation-list">{activities.map((event,index)=><article className="rec-card" key={event.id}><span className="rec-number">{String(index+1).padStart(2,'0')}</span><div className="rec-body"><h3>{event.title}</h3><p>{eventDay(event,timezone)} · {eventTime(event,timezone)}{event.location&&` · ${event.location}`}</p>{event.capacity_remaining!==null&&<small>通知发布时剩余 {event.capacity_remaining} 个名额 · 非实时信息</small>}</div><button className="rec-link" disabled={busy} onClick={()=>setSelectedEvent(event)}>查看通知 <Icon kind="arrow"/></button></article>)}{!activities.length&&<p className="empty-list">当前页暂无有明确日期的后续活动。</p>}</div></section>}
    </>}
    </>}{notice&&<p role="status" className="app-notice">{notice}</p>}{(busy||loading)&&<p role="status" className="work-status">正在处理，请稍候…</p>}<footer><span>CampusFlow / 开源重建</span><span>M4 · {fictional?'虚构演示':source?'本地来源':'选择来源'} · 邮箱账号连接待 M5</span></footer></main>
    <dialog ref={dialog} onCancel={event=>{if(busy)event.preventDefault();else closeDialog()}} onClose={closeDialog} aria-labelledby="dialog-title"><div className="dialog-header"><h2 id="dialog-title">{showSettings?'设置':detail?'邮件详情':'日程详情'}</h2><button aria-label="关闭" disabled={busy} onClick={closeDialog}>×</button></div>
    {showSettings?<Settings key={`${choice}:${policy?.version??0}`} source={source} policy={policy} provider={provider} busy={busy} onCreate={create} onSave={savePolicy}/>:detail?<div className="dialog-content"><span className="tiny-label">{fictional?'FICTIONAL':'LOCAL'} · {source?.display_name??'虚构演示'}</span><h3>{detail.subject}</h3><p className="subtle">{detail.sender} · {detail.received_at?new Date(detail.received_at).toLocaleString('zh-CN',{timeZone:timezone}):'接收日期未知'}</p><p className="mail-body">{detail.body_text??'此邮件未保留正文，无法离线查看或重处理。'}</p><div className="detail-actions"><button disabled={busy} onClick={()=>void toggleStar(detail)}>{detail.local_star?'取消星标':'添加星标'}</button>{!fictional&&<><button disabled={busy||detail.body_text===null} onClick={()=>void reprocess('rules')}>规则重处理</button><button disabled={busy||detail.body_text===null||!provider?.configured|| (provider.mode==='cloud'&& (!provider.remote_globally_enabled||!policy?.allow_remote_processing||policy.consent_fingerprint!==provider.fingerprint))} onClick={()=>void reprocess('model')}>{provider?.mode==='cloud'?'发送到已授权模型':'使用已配置模型'}</button><button disabled={busy} onClick={()=>void task(async()=>{if(!source)return;await privateRequest(`/api/emails/${detail.id}/flags`,json({local_read:!detail.local_read},'PATCH'),source.id);setDetail(previous=>previous?{...previous,local_read:!previous.local_read}:previous);await loadPrivate(source.id,snapshot?.mail_offset,snapshot?.event_offset)})}>{detail.local_read?'标记本地未读':'标记本地已读'}</button></>}</div><details><summary>来源与处理记录</summary><p>{detail.source_locator??'内置虚构数据'}</p><p>{[...detail.import_warnings??[],...detail.extraction_warnings??[]].join(' · ')||'无额外检查提示'}</p><p>提取方式：{detail.extraction_method??'未提取'}</p></details><h4>关联日程 · 当前页</h4>{allEvents.filter(event=>event.source_email_id===detail.id&&event.status!=='superseded').map(event=><button className="detail-event" key={event.id} onClick={()=>{setDetail(null);setSelectedEvent(event)}}>{event.title} · {eventDay(event,timezone)||'日期未知'}</button>)}{notice&&<p role="status">{notice}</p>}</div>:selectedEvent?<div className="dialog-content"><span className="tiny-label">{labels[selectedEvent.type]} · {selectedEvent.status==='confirmed'?'有明确日期或时间':'待确认'}</span><h3>{selectedEvent.title}</h3><p>{eventDay(selectedEvent,timezone)||'日期未知'} · {eventTime(selectedEvent,timezone)}</p><p>{selectedEvent.location??'地点未指定'}</p>{selectedEvent.source_changed&&<p className="dialog-note">原通知已变化，已保留你修改过的日程，请核对来源。</p>}<h4>邮件证据</h4><p className="mail-body">{selectedEvent.evidence||'未保存证据'}</p><button className="primary-button" disabled={busy||!selectedEvent.source_email_id} onClick={()=>{if(selectedEvent.source_email_id)void openEmail(selectedEvent.source_email_id)}}>查看来源邮件</button><p className="dialog-note">候选日期不代表已加入外部日历。未知时间保持待确认。</p></div>:null}
    </dialog></>
}
