import { useState } from 'react'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import type { AnalysisResult } from './types'
import { backLink, card } from './shared'

interface Props {
  result: AnalysisResult
  onBack: () => void
}

type Tab = 'keywords' | 'phrases' | 'entities' | 'serp'

function str(v: unknown): string {
  return v == null ? '' : String(v)
}

export function AnalysisResultsView({ result, onBack }: Props) {
  const [tab, setTab] = useState<Tab>('keywords')

  const zones: Array<{ key: keyof AnalysisResult['related_keywords']; label: string }> = [
    { key: 'title', label: 'Title' },
    { key: 'h1', label: 'H1' },
    { key: 'h2_h3', label: 'H2 / H3' },
    { key: 'paragraphs', label: 'Body' },
  ]

  const TABS: Array<{ key: Tab; label: string }> = [
    { key: 'keywords', label: 'Related Keywords' },
    { key: 'phrases', label: 'Key Phrases' },
    { key: 'entities', label: 'Entities' },
    { key: 'serp', label: `Competitors (${result.serp_urls.length})` },
  ]

  return (
    <div style={{ maxWidth: 820, margin: '0 auto' }}>
      <button onClick={onBack} style={backLink}><ArrowLeft size={14} /> Back</button>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Competitor Analysis</h1>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 20px' }}>
        <span style={{ fontWeight: 600 }}>{result.keyword}</span> · {result.location}
      </p>

      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid #e2e8f0', marginBottom: 16, flexWrap: 'wrap' }}>
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              padding: '9px 14px', fontSize: 14, fontWeight: 600, cursor: 'pointer', background: 'none',
              border: 'none', borderBottom: '2px solid', borderBottomColor: tab === t.key ? '#6366f1' : 'transparent',
              color: tab === t.key ? '#0f172a' : '#94a3b8', marginBottom: -1,
            }}
          >{t.label}</button>
        ))}
      </div>

      {tab === 'keywords' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 16 }}>
          {zones.map(zone => {
            const terms = result.related_keywords[zone.key] ?? []
            return (
              <div key={zone.key} style={card}>
                <p style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#94a3b8', margin: '0 0 10px' }}>{zone.label}</p>
                {terms.length === 0 ? (
                  <p style={{ fontSize: 13, color: '#cbd5e1', margin: 0 }}>None</p>
                ) : (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {terms.slice(0, 20).map((t, i) => (
                      <span key={i} style={{ fontSize: 12, background: '#eef2ff', color: '#4338ca', borderRadius: 999, padding: '3px 9px' }}>
                        {str(t.term ?? t.phrase ?? t.name)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {tab === 'phrases' && (
        <div style={card}>
          {result.top_quadgrams.length === 0 ? (
            <p style={{ fontSize: 13, color: '#94a3b8', margin: 0 }}>No common phrases found.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {result.top_quadgrams.slice(0, 30).map((q, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13, color: '#0f172a' }}>
                  <span>{str(q.phrase)}</span>
                  {q.page_spread_pct != null && (
                    <span style={{ color: '#94a3b8', flexShrink: 0 }}>{Math.round(Number(q.page_spread_pct) * 100)}% of pages</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'entities' && (
        <div style={card}>
          {result.google_entities.length === 0 ? (
            <p style={{ fontSize: 13, color: '#94a3b8', margin: 0 }}>No entities found.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {result.google_entities.slice(0, 40).map((e, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13 }}>
                  <span style={{ color: '#0f172a' }}>
                    {str(e.name)}
                    {e.entity_type ? <span style={{ color: '#94a3b8', marginLeft: 8, fontSize: 11 }}>{str(e.entity_type)}</span> : null}
                  </span>
                  {e.recommended_mentions != null && (
                    <span style={{ color: '#94a3b8', flexShrink: 0 }}>{str(e.recommended_mentions)} mentions</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'serp' && (
        <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
          {result.serp_urls.map((url, i) => (
            <a
              key={i}
              href={url}
              target="_blank"
              rel="noreferrer"
              style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', fontSize: 13,
                color: '#0f172a', textDecoration: 'none', borderTop: i ? '1px solid #f1f5f9' : 'none',
              }}
            >
              <span style={{ color: '#94a3b8', width: 20, flexShrink: 0 }}>{i + 1}</span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{url}</span>
              <ExternalLink size={13} color="#94a3b8" style={{ flexShrink: 0 }} />
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
