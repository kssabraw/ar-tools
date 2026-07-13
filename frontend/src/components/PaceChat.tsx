import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Markdown } from './Markdown'
import { Send, ListChecks, X } from 'lucide-react'

// PACE chatbox — the delivery project-manager persona, spoken over
// POST /pace/chat (same brain as the PACE Slack channel). Sibling of
// SerMastrChat: SerMaStr decides what should be done (strategy); PACE keeps the
// task board moving (delivery). The conversation (sticky client + any staged,
// actor-bound confirm token) lives in sessionStorage so navigating the suite
// doesn't lose the thread; a new browser session starts fresh.
//
// The thread is scoped to the signed-in user (storage key carries their id), so
// on a shared browser one user never sees another's chat.

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

type BriefResponse = { text: string }

const STORAGE_PREFIX = 'pace-chat-v1'
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

// PACE replies use Slack-style *bold* — lift single asterisks to Markdown **.
function slackToMd(text: string): string {
  return text.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1**$2**')
}

export function PaceChat({ fullPage = false }: { fullPage?: boolean }) {
  const { user } = useAuth()
  const userId = user?.id ?? null
  const [state, setState] = useState<ChatState>(() => loadState(userId))
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [streaming, setStreaming] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const prevUserId = useRef(userId)

  // Opening brief — the signed-in user's own tasks (overdue → today → this
  // week), shown in the dedicated page's empty state so PACE opens with a plan.
  const { data: brief } = useQuery<BriefResponse>({
    queryKey: ['pace-brief'],
    queryFn: () => api.get<BriefResponse>('/pace/brief'),
    enabled: fullPage,
    staleTime: 60_000,
  })

  useEffect(() => {
    if (prevUserId.current !== userId) {
      prevUserId.current = userId
      setState(loadState(userId))
    }
  }, [userId])

  useEffect(() => {
    const key = storageKey(userId)
    if (!key) return
    try {
      sessionStorage.setItem(key, JSON.stringify(state))
    } catch { /* storage full/blocked — chat still works, just not persisted */ }
  }, [state, userId])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [state.messages.length, sending, streaming, status])

  // The reply streams over SSE; falls back to the blocking endpoint when the
  // stream endpoint isn't deployed yet (the frontend can ship ahead).
  async function requestReply(payload: unknown): Promise<ChatResponse> {
    try {
      let final: ChatResponse | null = null
      let failure: string | null = null
      await api.streamEvents('/pace/chat/stream', payload, evt => {
        if (evt.type === 'text') {
          setStatus(null)
          setStreaming(s => s + String(evt.text ?? ''))
        } else if (evt.type === 'status') {
          setStatus(String(evt.label ?? ''))
        } else if (evt.type === 'done') {
          final = evt as unknown as ChatResponse
        } else if (evt.type === 'error') {
          failure = String(evt.detail ?? 'pace_error')
        }
      })
      if (failure) throw new Error(failure)
      if (!final) throw new Error('stream_ended_early')
      return final
    } catch (err) {
      const detail = err instanceof Error ? err.message : ''
      if (detail === 'Not Found' || detail === 'stream_ended_early') {
        return api.post<ChatResponse>('/pace/chat', payload)
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
        pendingToken: res.pending_token ?? null,
      }))
    } catch (e) {
      const detail = e instanceof Error ? e.message : 'unknown_error'
      const friendly = detail === 'pace_not_enabled'
        ? 'PACE isn’t enabled on the server yet — an admin can turn it on (PACE_ENABLED).'
        : detail === 'assistant_not_configured'
          ? 'PACE isn’t configured on the server yet (missing Anthropic key).'
          : detail === 'Not Found'
            ? 'The PACE backend isn’t live yet — the platform API this app points at doesn’t have /pace/chat deployed.'
            : `Sorry — I hit an error with that (${detail}). Try again in a moment.`
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

  const placeholder = 'Ask about the task board, or tell me to move something — e.g. “what’s overdue?”'

  return (
    <div style={fullPage ? cardFull : card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: state.messages.length > 0 || fullPage ? 12 : 10 }}>
        <span style={logo}><ListChecks size={15} /></span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>PACE</div>
          <div style={{ fontSize: 12, color: '#64748b' }}>
            Your delivery PM — ask about the task board, or tell me to move something.
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
              {brief?.text ? (
                <div style={briefCard}>
                  <div style={briefTitle}>Your plan today</div>
                  <div style={{ fontSize: 13, color: '#334155' }}>
                    <Markdown>{slackToMd(brief.text)}</Markdown>
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 12 }}>
                    Ask me to reassign, set a due date, unblock, nudge, or generate this month’s tasks.
                  </div>
                </div>
              ) : (
                <div style={emptyHint}>
                  Ask about the task board for a client, what’s overdue or stuck, or tell me to move
                  something — the conversation stays here.
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
                      {status ? `${status}…` : 'PACE is thinking…'}
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
const cardFull: React.CSSProperties = {
  ...card, marginBottom: 0, height: '100%', minHeight: 0,
  display: 'flex', flexDirection: 'column',
}
const logo: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  width: 30, height: 30, borderRadius: 8, flexShrink: 0,
  background: '#ccfbf1', color: '#0d9488',
}
const clientChip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0,
  fontSize: 12, fontWeight: 600, color: '#0f766e', background: '#ccfbf1',
  borderRadius: 999, padding: '3px 6px 3px 10px',
}
const chipX: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  border: 'none', background: 'transparent', color: '#0d9488',
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
const userBubble: React.CSSProperties = {
  background: '#0d9488', color: '#fff', fontSize: 13, lineHeight: 1.5,
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
  background: disabled ? '#99f6e4' : '#0d9488', color: '#fff',
  border: 'none', borderRadius: 8, padding: '8px 14px',
  fontSize: 13, fontWeight: 600, cursor: disabled ? 'default' : 'pointer',
})
const confirmBtn: React.CSSProperties = {
  background: '#0d9488', color: '#fff', border: 'none', borderRadius: 8,
  padding: '6px 14px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
}
const cancelBtn: React.CSSProperties = {
  background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: 8,
  padding: '6px 14px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
}
