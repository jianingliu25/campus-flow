import type { Demo } from '../types'

interface LocalSession {
  csrf_token: string
  active_source_id: string | null
  ttl_seconds: number
  milestone: string
}
let sessionRequest: Promise<LocalSession> | undefined

export function establishSession(): Promise<LocalSession> {
  if (!sessionRequest) {
    sessionRequest = fetch('/api/session', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: '{}',
    }).then(async response => {
      if (!response.ok) throw new Error('本机会话暂不可用')
      return response.json() as Promise<LocalSession>
    }).catch(error => { sessionRequest = undefined; throw error })
  }
  return sessionRequest
}

export async function privateRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (!path.startsWith('/api/') || path.startsWith('/api//')) throw new Error('仅允许本机 API')
  const session = await establishSession()
  const headers = new Headers(options.headers)
  if (session.active_source_id) headers.set('X-CampusFlow-Source', session.active_source_id)
  if (options.method && !['GET', 'HEAD', 'OPTIONS'].includes(options.method.toUpperCase())) headers.set('X-CSRF-Token', session.csrf_token)
  const response = await fetch(path, { ...options, credentials: 'same-origin', redirect: 'error', headers })
  if (response.status === 401) sessionRequest = undefined
  if (!response.ok) throw new Error(`本机请求未完成（${response.status}）`)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function activateSource(id: string): Promise<void> {
  const result = await privateRequest<{active_source_id: string}>(`/api/sources/${encodeURIComponent(id)}/activate`, { method: 'POST' })
  const session = await establishSession()
  session.active_source_id = result.active_source_id
}

export async function getDemo(signal?: AbortSignal): Promise<Demo> {
  const response = await fetch('/api/demo', { signal })
  if (!response.ok) throw new Error(`演示数据加载失败（${response.status}）`)
  return response.json() as Promise<Demo>
}
