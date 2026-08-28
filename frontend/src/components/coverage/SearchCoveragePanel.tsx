import { type CSSProperties } from 'react'
import type { EntityCoverage, CoverageZone } from '../localseo/types'

// The subset of a serp_signal_coverage engine score this panel reads. All fields
// optional so any engine-score object (Local SEO or Ecommerce — both come from
// the same nlp `_compute_serp_signal_coverage` engine) is assignable. Older saved
// pages carry only the percentages; a page scored without a SERP analysis carries
// none of it and the panel hides.
export interface CoverageScore {
  score?: number
  recommendations?: string[]
  keyword_coverage?: number
  entity_coverage?: number
  quadgram_coverage?: number
  frequency_coverage?: number | null
  entities_used?: string[]
  entities_missing?: string[]
  entity_detail?: EntityCoverage[]
  total_entity_shortfall?: number
  keyword_detail?: EntityCoverage[]
  total_keyword_shortfall?: number
  bold_detail?: EntityCoverage[]
  total_bold_shortfall?: number
  zones?: CoverageZone[]
}

// SERP-signal coverage: how well the page covers the entities, keywords, bolded
// terms and competitor phrases mined from the SERP — presence AND per-term
// mention frequency vs the (capped/raw) competitor benchmark, with a per-zone
// breakdown. Shared across the Local SEO + Ecommerce generated/score views.
export function SearchCoveragePanel({ coverage }: { coverage?: CoverageScore }) {
  if (!coverage || coverage.entity_coverage == null) return null
  const pct = (n?: number | null) => (n == null ? '—' : `${Math.round(n)}%`)
  const used = coverage.entities_used ?? []
  const missing = coverage.entities_missing ?? []
  const zones = coverage.zones ?? []
  const recs = coverage.recommendations ?? []
  const entityDetail = coverage.entity_detail ?? []
  const keywordDetail = coverage.keyword_detail ?? []
  const boldDetail = coverage.bold_detail ?? []
  const chip = (text: string, bg: string, color: string) => (
    <span key={text} style={{ fontSize: 12, fontWeight: 600, padding: '3px 9px', borderRadius: 999, background: bg, color }}>{text}</span>
  )
  const th: CSSProperties = { textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#64748b', padding: '6px 12px', textTransform: 'uppercase', letterSpacing: 0.3 }
  const td: CSSProperties = { fontSize: 13, color: '#0f172a', padding: '6px 12px', borderTop: '1px solid #f1f5f9' }
  const cell = (found?: number, target?: number) =>
    found == null || target == null ? '—' : `${found}/${target}${found >= target ? ' ✓' : ''}`
  // Cora-style term-target table (shared by entities / related keywords / bolded
  // terms): On page / Target (capped-max competitor) / Top competitor / Needed,
  // with a per-term per-zone breakdown line.
  const renderTermTable = (label: string, rows: EntityCoverage[], total: number) => {
    if (rows.length === 0) return null
    const hasCompetitor = rows.some((r) => r.max_competitor != null)
    return (
      <div style={{ overflowX: 'auto' }}>
        <p style={{ fontSize: 12, fontWeight: 600, color: '#475569', margin: '0 0 6px' }}>
          {label}{total > 0 && ` — ${total} mention${total > 1 ? 's' : ''} to add`}
        </p>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 380 }}>
          <thead>
            <tr>
              <th style={th}>Term</th>
              <th style={{ ...th, textAlign: 'right' }}>On page</th>
              <th style={{ ...th, textAlign: 'right' }}>Target</th>
              {hasCompetitor && <th style={{ ...th, textAlign: 'right' }}>Top comp.</th>}
              <th style={{ ...th, textAlign: 'right' }}>Needed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => {
              const short = e.shortfall > 0
              return (
                <tr key={e.name} style={short ? { background: '#fef2f2' } : undefined}>
                  <td style={{ ...td, fontWeight: short ? 600 : 400 }}>
                    {e.name}
                    {e.zones && e.zones.length > 0 && (
                      <div style={{ fontSize: 11, fontWeight: 400, color: '#94a3b8', marginTop: 2 }}>
                        {e.zones.map((z) => `${z.zone} ${z.current}/${z.recommended}`).join(' · ')}
                      </div>
                    )}
                  </td>
                  <td style={{ ...td, textAlign: 'right' }}>{e.current}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{e.recommended}</td>
                  {hasCompetitor && (
                    <td style={{ ...td, textAlign: 'right', color: '#94a3b8' }}>{e.max_competitor ?? '—'}</td>
                  )}
                  <td style={{ ...td, textAlign: 'right', color: short ? '#b91c1c' : '#94a3b8', fontWeight: short ? 700 : 400 }}>
                    {short ? `+${e.shortfall}` : '✓'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <p style={{ fontSize: 11, color: '#94a3b8', margin: '6px 0 0' }}>
          Target = the top competitor's usage, capped so one outlier can't inflate it. "Needed" is how many more mentions to add on this page.
        </p>
      </div>
    )
  }
  const stats: Array<[string, number | null | undefined]> = [
    ['Entities', coverage.entity_coverage],
    ['Keywords', coverage.keyword_coverage],
    ['Frequency', coverage.frequency_coverage],
    ['Competitor phrases', coverage.quadgram_coverage],
  ]
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
      <div style={{ background: '#f8fafc', padding: '16px 20px', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <p style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>Search coverage</p>
          <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 0' }}>How well this page covers the entities, keywords and competitor phrases from the SERP — presence and mention frequency.</p>
        </div>
        <span style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', whiteSpace: 'nowrap' }}>{pct(coverage.score)}</span>
      </div>
      <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Total coverage */}
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          {stats.filter(([, v]) => v != null).map(([label, val]) => (
            <div key={label}>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', lineHeight: 1.1 }}>{pct(val)}</div>
              <div style={{ fontSize: 12, color: '#64748b' }}>{label}</div>
            </div>
          ))}
        </div>

        {/* Entities used / missing */}
        {(used.length > 0 || missing.length > 0) && (
          <div>
            <p style={{ fontSize: 12, fontWeight: 600, color: '#475569', margin: '0 0 6px' }}>
              Entities used {used.length > 0 && `(${used.length})`}
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {used.map((e) => chip(e, '#ecfdf5', '#047857'))}
              {missing.map((e) => chip(e, '#fef2f2', '#b91c1c'))}
            </div>
            {missing.length > 0 && (
              <p style={{ fontSize: 11, color: '#94a3b8', margin: '6px 0 0' }}>Red = target entities not yet on the page.</p>
            )}
          </div>
        )}

        {/* Entity + keyword + bolded-term targets — current vs competitor usage.
            Each row's zone breakdown (e.g. "body 2/4 · H2/H3 0/1") shows per-zone counts. */}
        {renderTermTable('Entity targets', entityDetail, coverage.total_entity_shortfall ?? 0)}
        {renderTermTable('Keyword targets', keywordDetail, coverage.total_keyword_shortfall ?? 0)}
        {renderTermTable('Google-bolded term targets', boldDetail, coverage.total_bold_shortfall ?? 0)}

        {/* Coverage by zone */}
        {zones.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <p style={{ fontSize: 12, fontWeight: 600, color: '#475569', margin: '0 0 6px' }}>Coverage by zone</p>
            <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 360 }}>
              <thead>
                <tr>
                  <th style={th}>Zone</th>
                  <th style={th}>Keywords</th>
                  <th style={th}>Entities</th>
                </tr>
              </thead>
              <tbody>
                {zones.map((z) => (
                  <tr key={z.zone}>
                    <td style={td}>{z.zone}</td>
                    <td style={td}>{cell(z.keyword_found, z.keyword_target)}</td>
                    <td style={td}>{cell(z.entity_found, z.entity_target)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Recommendations */}
        {recs.length > 0 && (
          <div>
            <p style={{ fontSize: 12, fontWeight: 600, color: '#475569', margin: '0 0 6px' }}>Recommendations</p>
            <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {recs.map((r, i) => (
                <li key={i} style={{ fontSize: 12, color: '#475569' }}>{r}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
