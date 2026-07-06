import { useState } from 'react'
import { ChevronLeft, ChevronRight, ExternalLink, FileText, Stethoscope, CheckCircle2, XCircle } from 'lucide-react'
import { engineMeta } from './engines'
import { EngineIcon } from './engines'
import { AIO_ENGINES, AIO_KIND_LABELS, type CompResult, type Mention } from './types'
import { ConfidenceBar, SentimentIndicator, FoundPill, relativeTime, hostOf } from './bits'
import './animations.css'

// LABS-style scan-result cards for the latest batch: left-border accent by
// outcome, engine-accented snippet quote box, sentiment + segmented confidence
// bar, citations, competitor hits, and a details/diagnosis CTA. AR grafts: the
// position/prominence line and the AIO inline-link marker. Credit-free.

const PAGE_SIZE = 6

export function ScanResultCards({ mentions, keywordById, onOpen }: {
  mentions: Mention[]
  keywordById: Map<string, string>
  onOpen: (m: Mention, keyword: string) => void
}) {
  const [page, setPage] = useState(0)
  const pages = Math.max(1, Math.ceil(mentions.length / PAGE_SIZE))
  const current = Math.min(page, pages - 1)
  const visible = mentions.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE)

  if (mentions.length === 0) return null

  return (
    <div>
      <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))' }}>
        {visible.map((m, i) => (
          <ResultCard key={m.id} m={m} index={i} keyword={keywordById.get(m.keyword_id ?? '') ?? ''} onOpen={onOpen} />
        ))}
      </div>
      {pages > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 14 }}>
          <button style={pageBtn} disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Previous page">
            <ChevronLeft size={14} />
          </button>
          {Array.from({ length: pages }, (_, p) => (
            <button
              key={p}
              style={{ ...pageBtn, ...(p === current ? { background: '#6366f1', color: '#fff', borderColor: '#6366f1' } : {}) }}
              onClick={() => setPage(p)}
            >
              {p + 1}
            </button>
          ))}
          <button style={pageBtn} disabled={current === pages - 1} onClick={() => setPage(current + 1)} aria-label="Next page">
            <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  )
}

function ResultCard({ m, index, keyword, onOpen }: {
  m: Mention; index: number; keyword: string; onOpen: (m: Mention, keyword: string) => void
}) {
  const meta = engineMeta(m.engine)
  const found = m.mention_found === true
  const failed = m.status === 'failed'
  const accent = failed ? '#cbd5e1' : found ? '#15803d' : '#b91c1c'
  const ra = m.response_analysis ?? undefined
  const rank = ra?.position?.rank
  const total = ra?.position?.total_businesses
  const aioKind = AIO_ENGINES.has(m.engine) ? ra?.aio?.mention_kind : undefined
  const comps = Array.isArray(m.competitor_results) ? (m.competitor_results as CompResult[]) : []
  const citations = (m.citations ?? []).slice(0, 3)
  const extraCitations = Math.max(0, (m.citations ?? []).length - 3)
  const hasDiagnosis = Boolean(m.invisibility_diagnosis)

  return (
    <div
      className={`aiv-card-enter aiv-stagger-${Math.min(index + 1, 6)}`}
      style={{
        background: '#fff', border: '1px solid #e2e8f0', borderLeft: `3px solid ${accent}`,
        borderRadius: 12, padding: 14, display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0,
      }}
    >
      {/* header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: '#0f172a', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={keyword}>
            {keyword}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 3 }}>
            <EngineIcon engine={m.engine} size={13} />
            <span style={{ fontSize: 11.5, color: '#64748b' }}>{meta.label}</span>
            {aioKind && aioKind !== 'none' && (
              <span title={AIO_KIND_LABELS[aioKind]} style={{ fontSize: 10, color: aioKind === 'citation_only' ? '#94a3b8' : '#7c3aed' }}>
                {aioKind === 'citation_only' ? '◦ sources strip' : '🔗 linked inline'}
              </span>
            )}
          </div>
        </div>
        {!failed && <FoundPill found={found} />}
      </div>

      {/* AR graft: position / prominence */}
      {found && (rank != null || (ra?.prominence && ra.prominence !== 'none')) && (
        <div style={{ fontSize: 11.5, color: '#15803d' }}>
          {rank != null && <>Position {rank}{total ? ` of ${total}` : ''}</>}
          {rank != null && ra?.prominence && ra.prominence !== 'none' && ' · '}
          {ra?.prominence && ra.prominence !== 'none' && <>{ra.prominence} mention</>}
        </div>
      )}

      {/* snippet quote box */}
      {m.snippet && (
        <div style={{ background: '#f8fafc', borderRadius: 8, padding: '8px 10px', borderLeft: `2px solid ${meta.color}` }}>
          <span style={{
            fontSize: 12.5, color: '#475569', fontStyle: 'italic', lineHeight: 1.5,
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }}>
            “{m.snippet}”
          </span>
        </div>
      )}

      {/* failed */}
      {failed && (
        <div style={{ fontSize: 12, color: '#b91c1c' }}>Scan failed: {m.failure_reason ?? 'unknown error'}</div>
      )}

      {/* metrics */}
      {!failed && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 12 }}>
          <div>
            <div style={metricLabel}>Sentiment</div>
            <SentimentIndicator value={m.sentiment} />
          </div>
          <div>
            <div style={metricLabel}>Confidence</div>
            <ConfidenceBar value={m.confidence_score} />
          </div>
        </div>
      )}

      {/* citations */}
      {citations.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          {citations.map((u, i) => (
            <a key={i} href={u} target="_blank" rel="noreferrer"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, color: '#6366f1', textDecoration: 'none' }}>
              <ExternalLink size={10} /> {hostOf(u)}
            </a>
          ))}
          {extraCitations > 0 && <span style={{ fontSize: 11, color: '#94a3b8' }}>+{extraCitations} more</span>}
        </div>
      )}

      {/* competitor hits */}
      {comps.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {comps.slice(0, 3).map((c, i) => (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, color: c.found ? '#334155' : '#94a3b8' }}>
              {c.found ? <CheckCircle2 size={11} color="#15803d" /> : <XCircle size={11} color="#cbd5e1" />} {c.name}
            </span>
          ))}
          {comps.length > 3 && <span style={{ fontSize: 11, color: '#94a3b8' }}>+{comps.length - 3}</span>}
        </div>
      )}

      {/* footer */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid #f1f5f9', paddingTop: 8, marginTop: 'auto' }}>
        <span style={{ fontSize: 11, color: '#94a3b8' }}>{relativeTime(m.created_at)}</span>
        {m.status === 'completed' && (
          !found ? (
            <button style={hasDiagnosis ? outlineBtn : diagnoseBtn} onClick={() => onOpen(m, keyword)}>
              <Stethoscope size={12} /> {hasDiagnosis ? 'View diagnosis' : 'Diagnose'}
            </button>
          ) : (
            <button style={outlineBtn} onClick={() => onOpen(m, keyword)}>
              <FileText size={12} /> View details
            </button>
          )
        )}
      </div>
    </div>
  )
}

const metricLabel: React.CSSProperties = { fontSize: 10.5, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }
const outlineBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, background: '#fff', color: '#475569',
  border: '1px solid #e2e8f0', borderRadius: 7, padding: '5px 10px', fontSize: 11.5, fontWeight: 600, cursor: 'pointer',
}
const diagnoseBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, background: '#6366f1', color: '#fff',
  border: 'none', borderRadius: 7, padding: '5px 10px', fontSize: 11.5, fontWeight: 600, cursor: 'pointer',
}
const pageBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', minWidth: 28, height: 28,
  background: '#fff', color: '#475569', border: '1px solid #e2e8f0', borderRadius: 7,
  fontSize: 12, fontWeight: 600, cursor: 'pointer', padding: '0 8px',
}
