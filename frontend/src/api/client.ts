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
  if (!response.ok) {
    const data = await response.json().catch(() => ({})) as {code?: string}
    const messages: Record<string, string> = {
      FIXTURE_PROVIDER_FOR_REAL_SOURCE: '尚未配置实际模型；可先使用规则提取或仅浏览。',
      REMOTE_PROCESSING_DISABLED: '此来源未允许云端处理，请使用本地模式。',
      INVALID_PROVIDER_ENDPOINT: '请先配置本地模型地址，再尝试模型提取。',
      BODY_NOT_RETAINED: '此邮件没有保留正文，不能重新提取。',
      PREVIEW_NOT_FOUND: '预览已过期或来源已改变，请重新选择文件。',
      POLICY_VERSION_CHANGED: '读取策略已变更，请重新预览文件。',
      SOURCE_SELECTION_CHANGED: '来源或会话已变化，请重新选择来源。',
      UNSUPPORTED_MAIL_FORMAT: '仅支持 EML 和 MBOX 邮件文件。',
      INVALID_MBOX: '这个文件不符合支持的 MBOX 格式。',
    }
    throw new Error(messages[data.code || ''] || `本机请求未完成（${data.code || response.status}）`)
  }
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
