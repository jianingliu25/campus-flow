export type Category = 'academic' | 'admin' | 'activity'
export type EventType = 'course' | 'deadline' | 'activity' | 'personal'
export interface Email {
  id: string; source_id: string; subject: string; sender_name: string; sender: string
  body_text: string | null; received_at: string | null; category: Category | null; summary: string
  local_star: boolean; local_read: boolean; tags: string[]
  date_status?: string; extraction_status?: string; extraction_method?: string | null
  source_locator?: string | null; import_warnings?: string[]; extraction_warnings?: string[]
}
export interface Event {
  id: string; source_id: string; source_email_id: string | null; title: string; type: EventType
  start_at: string | null; end_at: string | null; date: string | null; all_day: boolean
  location: string | null; status: 'confirmed' | 'needs_confirmation' | 'superseded'
  evidence: string; capacity_remaining: number | null; supersedes_event_id: string | null
  source_changed?: boolean; user_modified?: boolean
}

export interface Source { id: string; kind: string; display_name: string; timezone: string | null; status: string }
export interface Policy { version: number; scope: {recent_days: number; max_messages: number; folders: string[]}; retain_body: boolean; allow_remote_processing: boolean; consent_fingerprint: string | null; enable_qa_memory: boolean; enable_implicit_profile: boolean }
export interface Provider { mode: string; model: string | null; host: string | null; configured: boolean; remote_globally_enabled: boolean; fingerprint: string; connection_tested: boolean }
export interface Snapshot {
  source_id: string; timezone: string; today: string; page_size: number; mail_total: number; event_total: number
  mail_offset: number; event_offset: number; stats: {today_events: number; upcoming_deadlines: number; needs_confirmation: number}
  processing: {last_import_at: string | null; index_jobs: Record<string,number>; vector_search_enabled: boolean; account_connected: boolean}
  emails: Omit<Email, 'sender_name' | 'body_text' | 'tags'>[]; events: Omit<Event, 'capacity_remaining' | 'supersedes_event_id'>[]
}
export interface Demo {
  meta: { milestone: string; source_name: string; provider: string; retrieval: string; timezone: string; demo_date: string }
  stats: { today_events: number; upcoming_deadlines: number; unread_emails: number; needs_confirmation: number }
  emails: Email[]; events: Event[]; recommendations: Event[]
  profile: { display_name: string; preferences: string[] }
}
