import type { ActionRequest, InteractionRequest, Result, State } from './types'

export interface Health {
  status: string
  model_configured: boolean
  model: string
  debug_enabled: boolean
}
export interface ApiClient {
  health(): Promise<Health>
  createSession(): Promise<State>
  getState(id: string): Promise<State>
  reset(id: string): Promise<State>
  interact(id: string, body: InteractionRequest): Promise<Result>
  action(id: string, body: ActionRequest): Promise<Result>
  debug(id: string, token: string): Promise<unknown>
  exportSave(id: string, token: string): Promise<unknown>
}
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly result?: Result) {
    super(message)
  }
}

export function createApiClient(fetcher: typeof fetch = fetch): ApiClient {
  async function request<T>(url: string, init?: RequestInit, retryable = false): Promise<T> {
    let response: Response | undefined
    for (let attempt = 0; attempt < (retryable ? 2 : 1); attempt += 1) {
      try {
        response = await fetcher(`/api${url}`, {
          ...init,
          headers: { 'Content-Type': 'application/json', ...init?.headers },
          signal: AbortSignal.timeout(70000),
        })
        break
      } catch (cause) {
        if (!retryable || attempt === 1) throw cause
      }
    }
    if (!response) throw new Error('网络连接失败，请重试上一请求')
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as {
        detail?: unknown; error?: { message?: string }; state?: State; status?: string
      }
      const detail = body.detail
      const text = body.error?.message ?? (typeof detail === 'string' ? detail :
        Array.isArray(detail) ? detail.map(item =>
          typeof item === 'object' && item !== null && 'msg' in item ? String(item.msg) : String(item)
        ).join('；') : `请求失败（${response.status}）`)
      throw new ApiError(text, response.status, body.state && body.status ? body as Result : undefined)
    }
    return response.json() as Promise<T>
  }
  const sessionUrl = (id: string) => `/sessions/${encodeURIComponent(id)}`
  return {
    health: () => request('/health'),
    createSession: () => request('/sessions', { method: 'POST' }),
    getState: id => request(sessionUrl(id)),
    reset: id => request(`${sessionUrl(id)}/reset`, { method: 'POST' }),
    interact: (id, body) => request(`${sessionUrl(id)}/interactions`, {
      method: 'POST', body: JSON.stringify(body),
    }, true),
    action: (id, body) => request(`${sessionUrl(id)}/actions`, {
      method: 'POST', body: JSON.stringify(body),
    }, true),
    debug: (id, token) => request(`${sessionUrl(id)}/debug`, { headers: { 'X-Debug-Token': token } }),
    exportSave: (id, token) => request(`${sessionUrl(id)}/export`, { headers: { 'X-Debug-Token': token } }),
  }
}
