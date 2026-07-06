import { ENGINE_ORDER, ENGINES, EngineIcon } from './engines'
import {
  AIO_ENGINES, AIO_KIND_LABELS, compResultFor,
  type AioKind, type Keyword, type Mention,
} from './types'
import './animations.css'

// LABS-style "Recent Scans" matrix: one row per keyword, each engine rendered
// as its logo with a found/not-found corner badge. Keeps the AR Tools signals
// LABS lacks: clickable cells open the full detail view, and the Google AI
// columns carry the inline-link (🔗) vs citation-only (◦) marker.
// `viewing` switches the badges to a tracked competitor's re-classification
// (read off the same rows' competitor_results — those cells aren't clickable,
// the drill-down analysis is brand-specific).

type CellState = 'none' | 'pending' | 'failed' | 'found' | 'notfound' | 'nocomp'

function cellState(m: Mention | undefined, competitor: string | undefined): { state: CellState; title: string } {
  if (!m) return { state: 'none', title: 'Not scanned' }
  if (competitor) {
    if (m.status !== 'completed') return { state: m.status === 'failed' ? 'failed' : 'pending', title: m.status }
    const cr = compResultFor(m, competitor)
    if (!cr) return { state: 'nocomp', title: 'Competitor not included in this scan' }
    return cr.found
      ? { state: 'found', title: `Found (${cr.mention_type ?? 'direct'})` }
      : { state: 'notfound', title: 'Not found' }
  }
  if (m.status === 'failed') return { state: 'failed', title: m.failure_reason ?? 'Scan failed' }
  if (m.status === 'queued' || m.status === 'processing') return { state: 'pending', title: m.status }
  if (m.mention_found) return { state: 'found', title: 'Mentioned — click for details' }
  return { state: 'notfound', title: 'Not found — click for why + details' }
}

function Badge({ state }: { state: CellState }) {
  if (state === 'none' || state === 'nocomp') return null
  const style: React.CSSProperties = {
    position: 'absolute', top: -4, right: -5, width: 13, height: 13, borderRadius: 999,
    background: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
    boxShadow: '0 0 0 1px #e2e8f0',
  }
  if (state === 'found') {
    return (
      <span style={style}>
        <svg width="9" height="9" viewBox="0 0 24 24" fill="#15803d" aria-hidden="true">
          <path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z" />
        </svg>
      </span>
    )
  }
  if (state === 'notfound') {
    return (
      <span style={style}>
        <svg width="8" height="8" viewBox="0 0 24 24" fill="#b91c1c" aria-hidden="true">
          <path d="M18.3 5.7 12 12l-6.3-6.3-1.4 1.4L10.6 13.4 4.3 19.7l1.4 1.4L12 14.8l6.3 6.3 1.4-1.4L13.4 13.4l6.3-6.3z" />
        </svg>
      </span>
    )
  }
  if (state === 'failed') {
    return <span style={{ ...style, color: '#94a3b8', fontSize: 9, fontWeight: 700 }}>!</span>
  }
  // pending — pulsing dot
  return (
    <span style={style}>
      <span className="aiv-scan-pulse" style={{ width: 6, height: 6, borderRadius: 999, background: '#6366f1' }} />
    </span>
  )
}

// Small corner marker on the Google AI columns: linked inline in the answer
// (🔗, the strong signal) vs listed in the sources strip only (◦).
function AioBadge({ kind }: { kind: AioKind }) {
  if (kind === 'none') return null
  const inline = kind === 'in_content_link' || kind === 'both'
  return (
    <span
      title={AIO_KIND_LABELS[kind]}
      style={{
        position: 'absolute', bottom: -6, right: -7, fontSize: 9,
        color: inline ? '#7c3aed' : '#94a3b8',
      }}
    >
      {inline ? '🔗' : '◦'}
    </span>
  )
}

export function RecentScansMatrix(props: {
  keywords: Keyword[]                        // active keywords, in display order
  latestByCell: Map<string, Mention>         // `${keyword_id}::${engine}` → latest mention
  viewing?: string                           // undefined/'brand' = the client; else a competitor name
  onOpenCell: (m: Mention, keyword: string) => void
}) {
  const { keywords, latestByCell, viewing, onOpenCell } = props
  const competitor = viewing && viewing !== 'brand' ? viewing : undefined

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {/* Engine column headers */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '0 14px' }}>
        <span style={{ flex: 1 }} />
        {ENGINE_ORDER.map(e => (
          <span
            key={e}
            style={{ width: 64, textAlign: 'center', fontSize: 10, fontWeight: 600, color: '#94a3b8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
            title={ENGINES[e].fullLabel}
          >
            {ENGINES[e].label}
          </span>
        ))}
      </div>

      {keywords.map((k, i) => (
        <div
          key={k.id}
          className={`aiv-card-enter aiv-stagger-${Math.min(i + 1, 6)}`}
          style={{
            display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
            background: '#f8fafc', border: '1px solid #f1f5f9', borderRadius: 10,
          }}
        >
          <span
            style={{
              flex: 1, fontSize: 13, fontWeight: 600, color: '#0f172a',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0,
            }}
            title={k.keyword}
          >
            {k.keyword}
          </span>

          {ENGINE_ORDER.map(e => {
            const m = latestByCell.get(`${k.id}::${e}`)
            const { state, title } = cellState(m, competitor)
            const clickable = !competitor && m?.status === 'completed'
            const aioKind =
              !competitor && m?.status === 'completed' && AIO_ENGINES.has(e)
                ? m.response_analysis?.aio?.mention_kind
                : undefined
            return (
              <span
                key={e}
                title={title}
                onClick={clickable ? () => onOpenCell(m!, k.keyword) : undefined}
                style={{
                  width: 64, display: 'flex', justifyContent: 'center',
                  cursor: clickable ? 'pointer' : 'default',
                }}
              >
                <span style={{ position: 'relative', display: 'inline-flex', opacity: state === 'none' || state === 'nocomp' ? 0.22 : 1 }}>
                  <EngineIcon engine={e} size={22} />
                  <Badge state={state} />
                  {aioKind && <AioBadge kind={aioKind} />}
                </span>
              </span>
            )
          })}
        </div>
      ))}
    </div>
  )
}
