import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Markdown } from './Markdown'
import { ConversationHistory, type ConversationDetail } from './ConversationHistory'
import { Send, Compass, X } from 'lucide-react'

// DORA chatbox — the Director of Operations persona (Director of Operations,
// Reconciliation & Awareness), spoken over POST /director/chat (same brain as
// the #dora Slack channel). The cross-agent lens: it watches how work flows
// across SerMaStr (strategy), PACE (delivery), QA (quality) and the autonomy
// executor, and reports where work snags between them. READ-ONLY — it never
// changes anything, so (unlike PaceChat) there is no confirm/cancel machinery.
//
// The conversation (sticky client) lives in sessionStorage so navigating the
// suite doesn't lose the thread; a new browser session starts fresh. The thread
// is scoped to the signed-in user (storage key carries their id).

type ChatMsg = { role: 'user' | 'assistant'; content: string }

type ChatResponse = {
  reply: string
  client_id?: string | null
  client_name?: string | null
  conversation_id?: string | null
}

type ChatState = {
  messages: ChatMsg[]
  clientId: string | null
  clientName: string | null
  // The durable thread these messages belong to (assistant_conversations,
  // surface 'director'); null until the first reply opens one server-side.
  conversationId: string | null
}

type BriefResponse = { text: string }

const STORAGE_PREFIX = 'director-chat-v1'
const EMPTY: ChatState = { messages: [], clientId: null, clientName: null, conversationId: null }

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

// DORA replies use Slack-style *bold* on the Slack surface; on web it answers in
// Markdown already, but lift any single asterisks defensively (harmless).
function slackToMd(text: string): string {
  return text.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1**$2**')
}

export function DirectorChat({ fullPage = false }: { fullPage?: boolean }) {
  const { user } = useAuth()
  const userId = user?.id ?? null
  const [state, setState] = useState<ChatState>(() => loadState(userId))
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [streaming, setStreaming] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const prevUserId = useRef(userId)

  // Opening brief — the open cross-agent seam flags right now, shown in the
  // dedicated page's empty state so DORA opens with the current state of play.
  const { data: brief } = useQuery<BriefResponse>({
    queryKey: ['director-brief'],
    queryFn: () => api.get<BriefResponse>('/director/brief'),
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

  async function recoverReply(conversationId: string, sentMessage: string): Promise<ChatResponse | null> {
    try {
      const convo = await api.get<{ client_id?: string | null; messages: ChatMsg[] }>(
        `/director/conversations/${conversationId}`,
      )
      const msgs = convo.messages ?? []
      const lastUser = [...msgs].reverse().find(m => m.role === 'user')
      if (!lastUser || lastUser.content !== sentMessage) return null
      const last = msgs[msgs.length - 1]
      if (!last || last.role !== 'assistant' || !last.content.trim()) return null
      return {
        reply: last.content,
        client_id: convo.client_id ?? undefined,
        conversation_id: conversationId,
      } as ChatResponse
    } catch {
      return null
    }
  }

  async function requestReply(payload: unknown): Promise<ChatResponse> {
    let streamed = ''
    let streamOpened = false
    const sentMessage = String((payload as { message?: string })?.message ?? '')
    let convoId: string | null =
      (payload as { conversation_id?: string | null })?.conversation_id ?? null
    try {
      let final: ChatResponse | null = null
      let failure: string | null = null
      await api.streamEvents('/director/chat/stream', payload, evt => {
        streamOpened = true
        if (evt.type === 'text') {
          setStatus(null)
          const chunk = String(evt.text ?? '')
          streamed += chunk
          setStreaming(s => s + chunk)
        } else if (evt.type === 'status') {
          setStatus(String(evt.label ?? ''))
        } else if (evt.type === 'meta') {
          convoId = String(evt.conversation_id ?? '') || convoId
        } else if (evt.type === 'done') {
          final = evt as unknown as ChatResponse
        } else if (evt.type === 'error') {
          failure = String(evt.detail ?? 'director_error')
        }
      })
      if (failure) throw new Error(failure)
      if (!final) throw new Error('stream_ended_early')
      return final
    } catch (err) {
      const detail = err instanceof Error ? err.message : ''
      if (detail === 'Not Found' || detail === 'stream_ended_early') {
        return api.post<ChatResponse>('/director/chat', payload)
      }
      if (streamOpened && convoId) {
        const recovered = await recoverReply(convoId, sentMessage)
        if (recovered) return recovered
      }
      if (streamed.trim()) {
        return {
          reply: `${streamed}\n\n---\n\n_The connection dropped before this finished. The text above is what arrived — ask me to continue if it's cut short._`,
          conversation_id: convoId ?? undefined,
        } as ChatResponse
      }
      throw err
    }
  }

  async function send(text: string) {
    const message = text.trim()
    if (!message || sending) return
    const history = state.conversationId ? [] : state.messages.slice(-12)
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
        conversation_id: state.conversationId,
      })
      setState(s => ({
        messages: [...s.messages, { role: 'assistant', content: res.reply }],
        clientId: res.client_id ?? s.clientId,
        clientName: res.client_name ?? s.clientName,
        conversationId: res.conversation_id ?? s.conversationId,
      }))
    } catch (e) {
      const detail = e instanceof Error ? e.message : 'unknown_error'
      const friendly = detail === 'director_not_enabled'
        ? 'DORA isn’t enabled on the server yet — an admin can turn it on (DIRECTOR_ENABLED).'
        : detail === 'assistant_not_configured'
          ? 'DORA isn’t configured on the server yet (missing Anthropic key).'
          : detail === 'Not Found'
            ? 'The DORA backend isn’t live yet — the platform API this app points at doesn’t have /director/chat deployed.'
            : `Sorry — I hit an error with that (${detail}). Try again in a moment.`
      setState(s => ({ ...s, messages: [...s.messages, { role: 'assistant', content: friendly }] }))
    } finally {
      setSending(false)
      setStreaming('')
      setStatus(null)
    }
  }

  const placeholder = 'Ask how work is flowing across the agents — e.g. “where are we bottlenecked?”'

  return (
    <div style={fullPage ? cardFull : card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: state.messages.length > 0 || fullPage ? 12 : 10 }}>
        <span style={logo}><Compass size={15} /></span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>DORA</div>
          <div style={{ fontSize: 12, color: '#64748b' }}>
            Director of Operations — how work flows across SerMaStr, PACE, QA &amp; autonomy.
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
        <ConversationHistory
          basePath="/director"
          accent="#6366f1"
          activeId={state.conversationId}
          onOpen={(d: ConversationDetail) => setState({
            messages: d.messages,
            clientId: d.client_id ?? null,
            clientName: null,     // re-resolved by the next turn
            conversationId: d.id,
          })}
          onArchiveActive={() => setState(EMPTY)}
        />
        {state.messages.length > 0 && (
          <button onClick={() => setState(EMPTY)} style={clearBtn} title="Start a new conversation — this one stays in History">New chat</button>
        )}
      </div>

      {(state.messages.length > 0 || fullPage) && (
        <div ref={scrollRef} style={fullPage ? threadFull : thread}>
          {state.messages.length === 0 && fullPage ? (
            <div style={{ margin: 'auto', width: '100%', maxWidth: 520 }}>
              {brief?.text ? (
                <div style={briefCard}>
                  <div style={briefTitle}>Cross-agent flow right now</div>
                  <div style={{ fontSize: 13, color: '#334155' }}>
                    <Markdown>{slackToMd(brief.text)}</Markdown>
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 12 }}>
                    Ask where we’re bottlenecked, where two agents overlap on a target, or how a client is flowing.
                  </div>
                </div>
              ) : (
                <div style={emptyHint}>
                  Ask how work is flowing across the agents — where it’s snagging between SerMaStr, PACE,
                  QA and autonomy. I observe and flag; I don’t change anything.
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
                      {status ? `${status}…` : 'DORA is reading the board…'}
                    </div>
                  )}
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
  background: '#e0e7ff', color: '#6366f1',
}
const clientChip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0,
  fontSize: 12, fontWeight: 600, color: '#4f46e5', background: '#e0e7ff',
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
const threadFull: React.CSSProperties = {
  ...thread, maxHeight: 'none', flex: 1, minHeight: 0,
}
const emptyHint: React.CSSProperties = {
  margin: '0 auto', maxWidth: 400, textAlign: 'center',
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
