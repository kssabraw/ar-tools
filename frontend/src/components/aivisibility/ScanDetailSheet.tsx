import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, Lightbulb, Quote, Brain, Link2 } from 'lucide-react'
import { api } from '../../lib/api'
import { Markdown } from '../Markdown'
import { engineMeta, EngineIcon } from './engines'
import { AIO_ENGINES, AIO_KIND_LABELS, type Mention } from './types'
import { Chip, Section, ConfidenceBar, SentimentIndicator, FoundPill, relativeTime, hostOf } from './bits'
import './animations.css'

// LABS-style right-side detail sheet for one keyword×engine scan result — the
// union of LABS' sections (summary, diagnosis, evidence, reasoning, citations,
// raw response) and the AR Tools-only analysis LABS lacks (position/prominence
// chips, misinformation flags, who-appeared-&-why, source classification,
// query intent, the AIO inline-link distinction). No credit affordances.

interface MentionDetail extends Mention {
  raw_response: string | null
  retry_count: number | null
}

export function ScanDetailSheet({ clientId, mention, keyword, onClose }: {
  clientId: string; mention: Mention; keyword: string; onClose: () => void
}) {
  const found = mention.mention_found === true
  const meta = engineMeta(mention.engine)
  const ra = mention.response_analysis ?? undefined
  const isAio = AIO_ENGINES.has(mention.engine)
  const rank = ra?.position?.rank
  const total = ra?.position?.total_businesses

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Heavy fields (raw answer, retry count) fetched lazily — the history list
  // omits them for payload size.
  const { data: detail } = useQuery<MentionDetail>({
    queryKey: ['brand-mention-detail', clientId, mention.id],
    queryFn: () => api.get<MentionDetail>(`/clients/${clientId}/brand/mentions/${mention.id}`),
    staleTime: 60_000,
  })

  // New scans auto-diagnose during the scan, so the explanation is already on
  // the row — show it instantly. Only fall back to the on-demand endpoint for
  // older rows scanned before auto-diagnosis (or when it was disabled/failed).
  const precomputed = mention.invisibility_diagnosis ?? detail?.invisibility_diagnosis ?? null
  const { data: diagnosed, isLoading: diagnosing, isError: diagnoseFailed, error: diagnoseError } = useQuery<{ diagnosis: string }>({
    queryKey: ['brand-diagnose', clientId, mention.id],
    queryFn: () => api.post<{ diagnosis: string }>(`/clients/${clientId}/brand/mentions/${mention.id}/diagnose`, {}),
    retry: false,
    // Never refire on window refocus: a failed diagnosis isn't cached server-side,
    // so each refetch would re-run the paid signals lookup + LLM attempt.
    refetchOnWindowFocus: false,
    staleTime: Infinity,
    enabled: !found && !precomputed && mention.status === 'completed',
  })
  const diagnosis = precomputed ?? diagnosed?.diagnosis ?? null

  const citations = mention.citations ?? []
  const byDomain = new Map<string, string[]>()
  for (const url of citations) {
    const host = hostOf(url)
    byDomain.set(host, [...(byDomain.get(host) ?? []), url])
  }

  return (
    <div style={overlay} onClick={onClose}>
      <div className="aiv-sheet-enter" style={sheet} onClick={e => e.stopPropagation()}>
        {/* 1 — header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 2 }}>
          <EngineIcon engine={mention.engine} size={24} />
          <strong style={{ fontSize: 16, color: '#0f172a', flex: 1 }}>{meta.fullLabel} analysis</strong>
          {mention.status === 'completed' && <FoundPill found={found} size="md" />}
          <button style={closeBtn} onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div style={{ fontSize: 12.5, color: '#94a3b8', marginBottom: 6 }}>“{keyword}”</div>

        {/* 2 — at-a-glance chips (AR analysis) */}
        <div>
          {found && rank != null && <Chip tone="green">Position {rank}{total ? ` of ${total}` : ''}</Chip>}
          {found && ra?.prominence && ra.prominence !== 'none' && (
            <Chip tone={ra.prominence === 'leading' ? 'green' : ra.prominence === 'caveated' ? 'amber' : 'slate'}>{ra.prominence} mention</Chip>
          )}
          {!found && total != null && <Chip tone="slate">{total} businesses listed, none of them this brand</Chip>}
          {isAio && ra?.aio && (
            <Chip tone={ra.aio.mention_kind === 'in_content_link' || ra.aio.mention_kind === 'both' ? 'violet' : 'slate'}>
              {AIO_KIND_LABELS[ra.aio.mention_kind]}
            </Chip>
          )}
          {ra?.sources?.client_cited && <Chip tone="green">Your site was cited as a source</Chip>}
        </div>

        {/* 3 — analysis summary (LABS) */}
        {mention.status === 'completed' && (
          <div style={summaryCard}>
            <div>
              <div style={summaryLabel}>Mention type</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#334155', textTransform: 'capitalize' }}>{mention.mention_type ?? '—'}</div>
            </div>
            <div>
              <div style={summaryLabel}>Sentiment</div>
              <SentimentIndicator value={mention.sentiment} />
            </div>
            <div>
              <div style={summaryLabel}>Confidence</div>
              <ConfidenceBar value={mention.confidence_score} />
            </div>
          </div>
        )}

        {/* failure */}
        {mention.status === 'failed' && (
          <Section title="Scan failed">
            <div style={{ fontSize: 13, color: '#b91c1c' }}>{mention.failure_reason ?? 'unknown error'}</div>
          </Section>
        )}

        {/* 4 — misinformation (AR) */}
        {ra?.accuracy_flags && ra.accuracy_flags.length > 0 && (
          <Section title="⚠ Possible misinformation">
            {ra.accuracy_flags.map((f, i) => (
              <div key={i} style={{ fontSize: 12.5, color: '#b91c1c', marginBottom: 3 }}>
                <strong>{f.field}:</strong> AI said “{f.stated}” — on file: “{f.actual}”
              </div>
            ))}
          </Section>
        )}

        {/* 5 — invisibility diagnosis (LABS shell, AR grounded/cached data) */}
        {!found && mention.status === 'completed' && (
          <Section title="Why invisible">
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <Lightbulb size={14} color="#b45309" />
              <span style={{ fontSize: 12.5, fontWeight: 600, color: '#b45309' }}>Invisibility diagnosis</span>
            </div>
            <div style={diagnosisBox}>
              {diagnosing && <div style={{ fontSize: 13, color: '#64748b' }}>Analyzing the competitors that did appear…</div>}
              {diagnoseFailed && <div style={{ fontSize: 13, color: '#b91c1c' }}>{(diagnoseError as Error).message}</div>}
              {diagnosis && <Markdown>{diagnosis}</Markdown>}
            </div>
          </Section>
        )}

        {/* 6 — who appeared & why (AR) */}
        {ra?.competitor_attributes && ra.competitor_attributes.length > 0 && (
          <Section title="Who appeared & why">
            {ra.competitor_attributes.slice(0, 8).map((b, i) => (
              <div key={i} style={{ fontSize: 12.5, color: '#334155', marginBottom: 5 }}>
                <strong>{b.name}</strong>{b.attributes.length > 0 && <> — {b.attributes.join(', ')}</>}
              </div>
            ))}
          </Section>
        )}

        {/* 7 — sources the AI cited (AR classification) */}
        {ra?.sources && ra.sources.domains.length > 0 && (
          <Section title="Sources the AI cited">
            <div>
              {ra.sources.domains.slice(0, 12).map((d, i) => (
                <Chip key={i} tone={d.is_client ? 'green' : d.is_competitor ? 'amber' : 'slate'}>
                  {d.domain}{d.is_client ? ' (you)' : d.is_competitor ? ' (competitor)' : ''}
                </Chip>
              ))}
            </div>
            {ra.sources.competitor_only_sources.length > 0 && (
              <div style={{ fontSize: 12.5, color: '#b45309', marginTop: 6 }}>
                Cites a competitor but not you: {ra.sources.competitor_only_sources.join(', ')} — get listed/mentioned here.
              </div>
            )}
          </Section>
        )}

        {/* 8 — how the AI read the query (AR) */}
        {ra?.intent && (ra.intent.inferred || ra.intent.locations.length > 0) && (
          <Section title="How the AI read the query">
            {ra.intent.inferred && <div style={{ fontSize: 12.5, color: '#334155' }}>{ra.intent.inferred}</div>}
            {ra.intent.locations.length > 0 && <div style={{ fontSize: 12.5, color: '#64748b', marginTop: 3 }}>Places named: {ra.intent.locations.join(', ')}</div>}
          </Section>
        )}

        {/* 9 — evidence snippet (LABS) */}
        {mention.snippet && (
          <Section title="Evidence snippet">
            <div style={{ display: 'flex', gap: 8, background: '#f8fafc', borderRadius: 10, padding: '10px 12px', borderLeft: `3px solid ${meta.color}` }}>
              <Quote size={13} color="#94a3b8" style={{ flexShrink: 0, marginTop: 2 }} />
              <span style={{ fontSize: 13, color: '#334155', fontStyle: 'italic', lineHeight: 1.55 }}>“{mention.snippet}”</span>
            </div>
          </Section>
        )}

        {/* 10 — AI reasoning (LABS) */}
        {mention.reasoning && (
          <Section title="AI reasoning">
            <div style={{ display: 'flex', gap: 8, background: '#f1f5f9', borderRadius: 10, padding: '10px 12px' }}>
              <Brain size={13} color="#94a3b8" style={{ flexShrink: 0, marginTop: 2 }} />
              <span style={{ fontSize: 13, color: '#475569', lineHeight: 1.55 }}>{mention.reasoning}</span>
            </div>
          </Section>
        )}

        {/* 11 — citations grouped by domain (LABS) */}
        {citations.length > 0 && (
          <Section title={`All citations (${citations.length})`}>
            <div style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 10, padding: '8px 12px' }}>
              {[...byDomain.entries()].map(([host, urls]) => (
                <details key={host} style={{ marginBottom: 6 }}>
                  <summary style={{ fontSize: 12.5, fontWeight: 600, color: '#334155', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Link2 size={12} color="#94a3b8" /> {host} <span style={{ color: '#94a3b8', fontWeight: 400 }}>({urls.length})</span>
                  </summary>
                  {urls.map((u, i) => (
                    <div key={i} style={{ marginLeft: 18, marginTop: 3 }}>
                      <a href={u} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: '#6366f1', wordBreak: 'break-all' }}>{u}</a>
                    </div>
                  ))}
                </details>
              ))}
            </div>
          </Section>
        )}

        {/* 12 — raw AI response (LABS; lazily fetched) */}
        {detail?.raw_response && (
          <Section title="Raw AI response">
            <details>
              <summary style={{ fontSize: 12.5, fontWeight: 600, color: '#64748b', cursor: 'pointer' }}>Show the full answer</summary>
              <pre style={{ maxHeight: 260, overflowY: 'auto', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: 12, fontSize: 11.5, color: '#475569', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: 8 }}>
                {detail.raw_response}
              </pre>
            </details>
          </Section>
        )}

        {/* 13 — footer */}
        <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid #f1f5f9', marginTop: 18, paddingTop: 10, fontSize: 11.5, color: '#94a3b8' }}>
          <span>Scanned {mention.created_at ? `${relativeTime(mention.created_at)} · ${new Date(mention.created_at).toLocaleString()}` : '—'}</span>
          {detail?.retry_count != null && detail.retry_count > 0 && <span>{detail.retry_count} retr{detail.retry_count === 1 ? 'y' : 'ies'}</span>}
        </div>
      </div>
    </div>
  )
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', zIndex: 50,
}
const sheet: React.CSSProperties = {
  position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(560px, 100vw)',
  background: '#fff', boxShadow: '-12px 0 40px rgba(15,23,42,0.18)',
  padding: 22, overflowY: 'auto',
}
const closeBtn: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 2 }
const summaryCard: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 12,
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 14, marginTop: 12,
}
const summaryLabel: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 5 }
const diagnosisBox: React.CSSProperties = {
  background: '#fffbeb', border: '1px solid #fde68a', borderLeft: '4px solid #f59e0b',
  borderRadius: 10, padding: '12px 14px',
}
