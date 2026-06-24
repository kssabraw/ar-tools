import { supabase } from './supabase'

const BASE_URL = import.meta.env.VITE_PLATFORM_API_URL as string

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers = await authHeaders()
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? res.statusText)
  }
  // 204 No Content (and any empty body, e.g. DELETE endpoints) has nothing to
  // parse — calling res.json() on it throws, which would reject the mutation
  // even though the request succeeded (leaving the UI stale until a refresh).
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

// POST to a heartbeat-SSE endpoint and resolve with the final `done` result.
// Used for long-running Local SEO operations that stream keepalives so a
// multi-minute request isn't killed by a load-balancer idle timeout.
async function streamJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const headers = await authHeaders()
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  })
  // Auth / validation failures happen before the stream starts → normal JSON.
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? res.statusText)
  }
  if (!res.body) throw new Error('no_response_body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: T | undefined
  let failure: string | undefined

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let nl: number
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trimEnd()
      buffer = buffer.slice(nl + 1)
      if (!line.startsWith('data:')) continue // skip heartbeats / comments
      const payload = line.slice(5).trim()
      if (!payload) continue
      let evt: { step?: string; result?: unknown; detail?: string }
      try {
        evt = JSON.parse(payload)
      } catch {
        continue
      }
      if (evt.step === 'error') failure = evt.detail ?? 'local_seo_error'
      else if (evt.step === 'done') result = evt.result as T
    }
  }

  if (failure !== undefined) throw new Error(failure)
  if (result === undefined) throw new Error('local_seo_no_result')
  return result
}

async function upload<T>(path: string, form: FormData): Promise<T> {
  // Multipart upload — let the browser set Content-Type (with boundary),
  // so we send only the auth header here.
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? res.statusText)
  }
  return res.json()
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, form: FormData) => upload<T>(path, form),
  stream: <T>(path: string, body: unknown, signal?: AbortSignal) => streamJson<T>(path, body, signal),
}
