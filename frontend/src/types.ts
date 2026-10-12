export type Category = 'academic' | 'admin' | 'activity'
export type EventType = 'course' | 'deadline' | 'activity' | 'personal'
export interface Email {
  id: string; source_id: 'demo'; subject: string; sender_name: string; sender: string
  body_text: string; received_at: string; category: Category; summary: string
  local_star: boolean; local_read: boolean; tags: string[]
}
export interface Event {
  id: string; source_id: 'demo'; source_email_id: string; title: string; type: EventType
  start_at: string | null; end_at: string | null; date: string | null; all_day: boolean
  location: string | null; status: 'confirmed' | 'needs_confirmation' | 'superseded'
  evidence: string; capacity_remaining: number | null; supersedes_event_id: string | null
}
export interface Demo {
  meta: { milestone: string; source_name: string; provider: string; retrieval: string; timezone: string; demo_date: string }
  stats: { today_events: number; upcoming_deadlines: number; unread_emails: number; needs_confirmation: number }
  emails: Email[]; events: Event[]; recommendations: Event[]
  profile: { display_name: string; preferences: string[] }
}
