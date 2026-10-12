import type { Event } from './types'

export function Icon({ kind }: { kind: 'calendar' | 'mail' | 'chat' | 'book' | 'settings' | 'arrow' }) {
  const paths = {
    calendar: 'M7 3v4m10-4v4M4 10h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Z',
    mail: 'M3 5h18v14H3V5Zm0 1 9 7 9-7', chat: 'M4 4h16v12H9l-5 4V4Zm4 5h8m-8 3h5',
    book: 'M12 5v16M3 4h5l4 2 4-2h5v15h-5l-4 2-4-2H3V4Z',
    settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-5v2m0 14v2M3 12h2m14 0h2M6 6l1 1m10 10 1 1M6 18l1-1M17 7l1-1',
    arrow: 'M4 12h16m-6-6 6 6-6 6',
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true" className="icon"><path d={paths[kind]} /></svg>
}

export function eventDay(event: Event, timezone: string) {
  if (!event.start_at) return event.date ?? ''
  const parts = new Intl.DateTimeFormat('en', {timeZone: timezone, year:'numeric', month:'2-digit', day:'2-digit'}).formatToParts(new Date(event.start_at))
  const value = (name:string) => parts.find(part=>part.type===name)?.value
  return `${value('year')}-${value('month')}-${value('day')}`
}

export function eventTime(event: Event, timezone: string) {
  if (!event.start_at) return event.all_day ? '全天' : '具体时刻未知'
  const format = new Intl.DateTimeFormat('zh-CN', {timeZone:timezone, hour:'2-digit', minute:'2-digit', hourCycle:'h23'})
  const end = event.end_at ? `–${eventDay(event, timezone) !== eventDay({...event, start_at:event.end_at}, timezone) ? eventDay({...event, start_at:event.end_at}, timezone)+' ' : ''}${format.format(new Date(event.end_at))}` : ''
  return format.format(new Date(event.start_at)) + end
}

export function nextDay(day: string, offset=1) {
  const date = new Date(`${day}T12:00:00Z`)
  date.setUTCDate(date.getUTCDate()+offset)
  return date.toISOString().slice(0,10)
}
