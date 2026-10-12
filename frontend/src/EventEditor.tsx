import {useState} from 'react'
import type {Event} from './types'
import {privateRequest} from './api/client'

export default function EventEditor({event,sourceId,onSaved,onBusy}:{event:Event;sourceId:string;onSaved:()=>Promise<void>;onBusy:(busy:boolean)=>void}) {
  const [editing,setEditing]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const [title,setTitle]=useState(event.title),[location,setLocation]=useState(event.location??'')
  const [start,setStart]=useState(event.start_at??''),[end,setEnd]=useState(event.end_at??''),[day,setDay]=useState(event.date??'')
  const [allDay,setAllDay]=useState(event.all_day)
  async function submit(path:string,body:unknown,method:string) {
    setBusy(true);onBusy(true);setError('')
    try {await privateRequest(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},sourceId);await onSaved()}
    catch(e){setError(e instanceof Error?e.message:'操作未完成')}
    finally{setBusy(false);onBusy(false)}
  }
  return <div className="event-editor">
    <p>{event.in_calendar===false?'候选活动尚未计入私人日程':'已计入私人日程'}{event.user_modified?' · 你已手工修改':''}</p>
    <button disabled={busy} onClick={()=>void submit(`/api/events/${event.id}/selection`,{selected:event.in_calendar===false},'PUT')}>{event.in_calendar===false?'加入私人日程':'移出私人日程'}</button>
    <button disabled={busy} onClick={()=>setEditing(!editing)}>修改并核对</button>
    {editing&&<form onSubmit={e=>{e.preventDefault();void submit(`/api/events/${event.id}`,{expected_revision:event.revision??1,title,type:event.type,location:location||null,start_at:allDay?null:start||null,end_at:allDay?null:end||null,date:day||null,all_day:allDay,status:'confirmed'},'PATCH')}}>
      <label>标题<input value={title} maxLength={300} required onChange={e=>setTitle(e.target.value)}/></label>
      <label>地点<input value={location} maxLength={300} onChange={e=>setLocation(e.target.value)}/></label>
      <label>日期<input type="date" value={day} onChange={e=>setDay(e.target.value)}/></label>
      <label><input type="checkbox" checked={allDay} onChange={e=>setAllDay(e.target.checked)}/>全天事件</label>
      {!allDay&&<><label>开始时间<input value={start} placeholder="2026-10-15T09:00:00+08:00" onChange={e=>setStart(e.target.value)}/></label><label>结束时间<input value={end} placeholder="可留空，表示结束时间未知" onChange={e=>setEnd(e.target.value)}/></label></>}
      <p className="subtle">未填写偏移的时间使用此来源时区。只知道截止日期时保留日期即可。</p>
      <button className="primary-button" disabled={busy}>保存已核对的日程</button>
    </form>}
    {error&&<p role="alert">{error}</p>}
    <p className="subtle">加入只影响本机日历，不会替你报名或写入邮箱。</p>
  </div>
}
