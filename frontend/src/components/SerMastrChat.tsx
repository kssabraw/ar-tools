import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Markdown } from './Markdown'
import { Send, Sparkles, X } from 'lucide-react'

// SerMaStr chatbox on the Home dashboard — same brain as the Slack assistant,
// spoken over POST /assistant/chat. The conversation (and its sticky client +
// any staged confirm token) lives in sessionStorage so navigating around the
// suite doesn't lose the thread; a new browser session starts fresh.
//
// The thread is scoped to the signed-in user (storage key carries their id), so
// on a shared browser one user never sees another's chat: switching accounts
// loads that account's own (empty) thread, and logout clears it. History is not
// persisted server-side — it stays local to this browser session.

type ChatMsg = { role: 'user' | 'assistant'; content: string }

type ChatResponse = {
  reply: string
  client_id?: string | null
  client_name?: string | null
  pending_token?: string | null
}

type ChatState = {
  messages: ChatMsg[]
  clientId: string | null
  clientName: string | null
  pendingToken: string | null
}

type BriefItem = {
  client_name?: string | null
  kind?: string
  severity?: string
  title: string
  created_at?: string
}
type BriefResponse = { window_hours: number; items: BriefItem[] }

const STORAGE_PREFIX = 'sermastr-chat-v1'
// Pre-isolation key: a single shared bucket not tied to any user. Purged on
// mount so a previous user's chat can't linger on a shared browser.
const LEGACY_STORAGE_KEY = 'sermastr-chat-v1'
const EMPTY: ChatState = { messages: [], clientId: null, clientName: null, pendingToken: null }

function storageKey(userId: string | null): string | null {
  return userId ? `${STORAGE_PREFIX}:${userId}` : null
}

function loadState(userId: string | null): ChatState {
  const key = storageKey(userId)
  if (!key) return EMPTY
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return EMPTY
    const parsed = JSON.parse(raw) as Partial<ChatState>
    return { ...EMPTY, ...parsed, messages: Array.isArray(parsed.messages) ? parsed.messages : [] }
  } catch {
    return EMPTY
  }
}

// The assistant's action confirmations use Slack-style *bold* — lift single
// asterisks to Markdown ** so they render bold instead of literally.
function slackToMd(text: string): string {
  return text.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1**$2**')
}

export function SerMastrChat({ exampleClient, fullPage = false }: { exampleClient?: string; fullPage?: boolean }) {
  const { user } = useAuth()
  const userId = user?.id ?? null
  const [state, setState] = useState<ChatState>(() => loadState(userId))
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  // Live streaming turn: the partial reply as tokens arrive + the current
  // tool-activity label ("Reading SOP…"). Cleared when the turn lands.
  const [streaming, setStreaming] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const prevUserId = useRef(userId)

  // Opening brief — "since you were last here" across all clients, shown in
  // the dedicated page's empty state so the chat opens with awareness.
  const { data: brief } = useQuery<BriefResponse>({
    queryKey: ['assistant-brief'],
    queryFn: () => api.get<BriefResponse>('/assistant/brief'),
    enabled: fullPage,
    staleTime: 60_000,
  })

  // Purge the pre-isolation shared bucket once, so an older suite version's
  // chat can't be read on a shared browser.
  useEffect(() => {
    try { sessionStorage.removeItem(LEGACY_STORAGE_KEY) } catch { /* ignore */ }
  }, [])

  // When the signed-in user changes (switch accounts / login / logout), load
  // that user's own thread — never carry one user's chat into another's view.
  useEffect(() => {
    if (prevUserId.current !== userId) {
      prevUserId.current = userId
      setState(loadState(userId))
    }
  }, [userId])

  useEffect(() => {
    const key = storageKey(userId)
    if (!key) return // logged out — nothing to persist to
    try {
      sessionStorage.setItem(key, JSON.stringify(state))
    } catch { /* storage full/blocked — chat still works, just not persisted */ }
  }, [state, userId])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [state.messages.length, sending, streaming, status])

  // The reply streams over SSE (tokens render as they generate). Falls back to
  // the original blocking endpoint when the stream endpoint isn't deployed yet
  // (the frontend can ship ahead of the backend).
  async function requestReply(payload: unknown): Promise<ChatResponse> {
    try {
      let final: ChatResponse | null = null
      let failure: string | null = null
      await api.streamEvents('/assistant/chat/stream', payload, evt => {
        if (evt.type === 'text') {
          setStatus(null)
          setStreaming(s => s + String(evt.text ?? ''))
        } else if (evt.type === 'status') {
          setStatus(String(evt.label ?? ''))
        } else if (evt.type === 'done') {
          final = evt as unknown as ChatResponse
        } else if (evt.type === 'error') {
          failure = String(evt.detail ?? 'assistant_error')
        }
      })
      if (failure) throw new Error(failure)
      if (!final) throw new Error('stream_ended_early')
      return final
    } catch (err) {
      const detail = err instanceof Error ? err.message : ''
      if (detail === 'Not Found' || detail === 'stream_ended_early') {
        return api.post<ChatResponse>('/assistant/chat', payload)
      }
      throw err
    }
  }

  async function send(text: string) {
    const message = text.trim()
    if (!message || sending) return
    const history = state.messages.slice(-12)
    setState(s => ({ ...s, messages: [...s.messages, { role: 'user', content: message }] }))
    setInput('')
    setSending(true)
    setStreaming('')
    setStatus(null)
    try {
      const res = await requestReply({
        message,
        history,
        client_id: state.clientId,
        pending_token: state.pendingToken,
      })
      setState(s => ({
        messages: [...s.messages, { role: 'assistant', content: res.reply }],
        clientId: res.client_id ?? s.clientId,
        clientName: res.client_name ?? s.clientName,
        // The server consumes a sent token either way, so only a fresh one survives.
        pendingToken: res.pending_token ?? null,
      }))
    } catch (e) {
      const detail = e instanceof Error ? e.message : 'unknown_error'
      const friendly = detail === 'assistant_not_configured'
        ? 'The assistant isn’t configured on the server yet (missing Anthropic key).'
        : detail === 'Not Found'
          // The frontend shipped ahead of the backend (e.g. a deploy preview
          // pointed at the production API before the endpoint was deployed).
          ? 'The assistant backend isn’t live yet — the platform API this app points at doesn’t have /assistant/chat deployed.'
          : `Sorry — I hit an error answering that (${detail}). Try again in a moment.`
      setState(s => ({ ...s, messages: [...s.messages, { role: 'assistant', content: friendly }], pendingToken: null }))
    } finally {
      setSending(false)
      setStreaming('')
      setStatus(null)
    }
  }

  function cancelPending() {
    setState(s => ({
      ...s,
      pendingToken: null,
      messages: [...s.messages, { role: 'assistant', content: 'Okay — cancelled, nothing was run.' }],
    }))
  }

  const placeholder = exampleClient
    ? `Ask about a client — e.g. “How is ${exampleClient}’s campaign going?”`
    : 'Ask about a client’s SEO, or tell me to run something…'

  return (
    <div style={fullPage ? cardFull : card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: state.messages.length > 0 || fullPage ? 12 : 10 }}>
        <span style={logo}><Sparkles size={15} /></span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>SerMaStr</div>
          <div style={{ fontSize: 12, color: '#64748b' }}>
            Your SEO strategist — ask about any client, or tell me to run something.
          </div>
        </div>
        {state.clientName && (
          <span style={clientChip} title="The client this conversation is about — name another client to switch.">
            {state.clientName}
            <button
              onClick={() => setState(s => ({ ...s, clientId: null, clientName: null }))}
              style={chipX}
              title="Forget this client"
            >
              <X size={11} />
            </button>
          </span>
        )}
        {state.messages.length > 0 && (
          <button onClick={() => setState(EMPTY)} style={clearBtn}>Clear chat</button>
        )}
      </div>

      {(state.messages.length > 0 || fullPage) && (
        <div ref={scrollRef} style={fullPage ? threadFull : thread}>
          {state.messages.length === 0 && fullPage ? (
            <div style={{ margin: 'auto', width: '100%', maxWidth: 520 }}>
              {brief?.items?.length ? (
                <div style={briefCard}>
                  <div style={briefTitle}>While you were away</div>
                  {brief.items.map((it, i) => (
                    <div key={i} style={briefRow}>
                      <span style={sevDot(it.severity)} />
                      <span style={briefClient}>{it.client_name ?? 'Agency'}</span>
                      <span style={briefText}>{it.title}</span>
                    </div>
                  ))}
                  <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 12 }}>
                    Ask me about any of these — or anything else.
                  </div>
                </div>
              ) : (
                <div style={emptyHint}>
                  Ask about a client’s SEO performance, the whole portfolio, or tell me to run something — the conversation stays here.
                </div>
              )}
            </div>
          ) : (
            <>
              {state.messages.map((m, i) => (
                m.role === 'user' ? (
                  <div key={i} style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <div style={userBubble}>{m.content}</div>
                  </div>
                ) : (
                  <div key={i} style={{ display: 'flex' }}>
                    <div style={botBubble}><Markdown>{slackToMd(m.content)}</Markdown></div>
                  </div>
                )
              ))}
              {sending && (
                <div style={{ display: 'flex' }}>
                  {streaming ? (
                    <div style={botBubble}><Markdown>{slackToMd(streaming)}</Markdown></div>
                  ) : (
                    <div style={{ ...botBubble, color: '#94a3b8', fontSize: 13 }}>
                      {status ? `${status}…` : 'SerMaStr is thinking…'}
                    </div>
                  )}
                </div>
              )}
              {!sending && state.pendingToken && (
                <div style={{ display: 'flex', gap: 8, paddingLeft: 2 }}>
                  <button onClick={() => send('yes')} style={confirmBtn}>Confirm</button>
                  <button onClick={cancelPending} style={cancelBtn}>Cancel</button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      <form
        onSubmit={e => { e.preventDefault(); void send(input) }}
        style={{ display: 'flex', gap: 8 }}
      >
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder={placeholder}
          style={inputStyle}
          maxLength={4000}
        />
        <button type="submit" disabled={sending || !input.trim()} style={sendBtn(sending || !input.trim())}>
          <Send size={14} /> Send
        </button>
      </form>
    </div>
  )
}

const card: React.CSSProperties = {
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12,
  padding: 16, marginBottom: 24,
}
// Dedicated-page variant: fill the available height so the message field is as
// large as the viewport allows, with the input pinned to the bottom.
const cardFull: React.CSSProperties = {
  ...card, marginBottom: 0, height: '100%', minHeight: 0,
  display: 'flex', flexDirection: 'column',
}
const logo: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  width: 30, height: 30, borderRadius: 8, flexShrink: 0,
  background: '#eef2ff', color: '#6366f1',
}
const clientChip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0,
  fontSize: 12, fontWeight: 600, color: '#4338ca', background: '#eef2ff',
  borderRadius: 999, padding: '3px 6px 3px 10px',
}
const chipX: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  border: 'none', background: 'transparent', color: '#6366f1',
  cursor: 'pointer', padding: 2, borderRadius: 999,
}
const clearBtn: React.CSSProperties = {
  border: '1px solid #e2e8f0', background: '#fff', color: '#64748b',
  fontSize: 12, borderRadius: 8, padding: '4px 10px', cursor: 'pointer', flexShrink: 0,
}
const thread: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 10,
  maxHeight: 360, overflowY: 'auto', marginBottom: 12,
  paddingRight: 4,
}
// On the dedicated page the thread grows to fill the card instead of capping.
const threadFull: React.CSSProperties = {
  ...thread, maxHeight: 'none', flex: 1, minHeight: 0,
}
const emptyHint: React.CSSProperties = {
  margin: '0 auto', maxWidth: 380, textAlign: 'center',
  color: '#94a3b8', fontSize: 13, lineHeight: 1.6,
}
const briefCard: React.CSSProperties = {
  background: '#f8fafc', border: '1px solid #eef2f7', borderRadius: 12,
  padding: '16px 18px',
}
const briefTitle: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: '#94a3b8', letterSpacing: '0.04em',
  textTransform: 'uppercase', marginBottom: 10,
}
const briefRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0',
  fontSize: 13, minWidth: 0,
}
const briefClient: React.CSSProperties = {
  color: '#334155', fontWeight: 600, flexShrink: 0,
}
const briefText: React.CSSProperties = {
  color: '#64748b', minWidth: 0, overflow: 'hidden',
  textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}
const sevDot = (severity?: string): React.CSSProperties => ({
  width: 7, height: 7, borderRadius: 999, flexShrink: 0,
  background: severity === 'critical' ? '#dc2626' : severity === 'warning' ? '#f59e0b' : '#6366f1',
})
const userBubble: React.CSSProperties = {
  background: '#6366f1', color: '#fff', fontSize: 13, lineHeight: 1.5,
  borderRadius: '12px 12px 2px 12px', padding: '8px 12px', maxWidth: '78%',
  whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
}
const botBubble: React.CSSProperties = {
  background: '#f8fafc', border: '1px solid #eef2f7', color: '#334155',
  borderRadius: '12px 12px 12px 2px', padding: '8px 12px', maxWidth: '86%',
  overflowWrap: 'anywhere',
}
const inputStyle: React.CSSProperties = {
  flex: 1, fontSize: 13, color: '#0f172a', background: '#fff',
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '9px 12px', outline: 'none',
}
const sendBtn = (disabled: boolean): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0,
  background: disabled ? '#c7d2fe' : '#6366f1', color: '#fff',
  border: 'none', borderRadius: 8, padding: '8px 14px',
  fontSize: 13, fontWeight: 600, cursor: disabled ? 'default' : 'pointer',
})
const confirmBtn: React.CSSProperties = {
  background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8,
  padding: '6px 14px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
}
const cancelBtn: React.CSSProperties = {
  background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: 8,
  padding: '6px 14px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
}
