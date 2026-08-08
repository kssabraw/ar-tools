import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, X, FileText, Users, Phone, Printer, AlertTriangle, CheckCircle2, Download } from 'lucide-react'
import { api } from '../../lib/api'
import { useAuth } from '../../context/AuthContext'

// Mirrors services/outreach_report.build_report. Deterministic, read-only — assembled from scan
// data already captured (outreach report-assembly module). Two faces over ONE document: an internal
// competitive brief and a client-facing DRAFT (approval-gated before it's ever a real asset).
interface MapsCompetitor {
  place_id: string
  name: string | null
  pack_points: number
  pack_share_pct: number | null
  best_rank: number | null
}
interface Section {
  status: 'measured' | 'not_scanned' | 'not_measured'
  signal: string
  reason?: string
  prospect?: {
    coverage_pct: number; points_present: number; live_points: number | null
    best_rank: number | null; avg_rank: number | null
    pack_points: number; pack_best_rank: number | null
  }
  competitors?: MapsCompetitor[]
  total_competitors?: number
}
interface OrganicCompetitor { domain: string; rank: number | null; title: string | null }
interface OrganicSection {
  status: 'measured' | 'not_scanned'
  signal: string
  reason?: string
  prospect_domain?: string | null
  prospect_rank?: number | null
  ai_overview_present?: boolean
  captured_depth?: number | null
  competitors?: OrganicCompetitor[]
}
interface LlmEngine {
  engine: string
  present: boolean
  visible: boolean
  named_count: number
  sample_businesses: string[]
}
interface LlmSection {
  status: 'measured' | 'not_scanned'
  signal: string
  reason?: string
  region?: string | null
  name_level?: string | null
  caveat?: string
  engines?: LlmEngine[]
}
interface TalkingPoint { element: string; text: string }
interface ReportData {
  prospect_id: string
  measured: boolean
  identity: {
    name: string | null; category: string | null; phone: string | null; website: string | null
    address: string | null; rating: number | null; review_count: number | null
  }
  keyword: string
  submarket: string
  signals: { maps: Section; organic: OrganicSection; llm: LlmSection }
  heatmap_available: boolean
  justification: {
    measured: boolean; headline?: string; hook?: string; talking_points: TalkingPoint[]
    caveats?: string[]; message?: string
  }
  client_facing: {
    status: string; approved: boolean; note: string
    approved_by?: string | null; approved_at?: string | null
  }
}

type Face = 'internal' | 'client'

// ── Entry: two buttons, one per report face ──────────────────────────────────
export function ProspectReportButtons({ prospectId, compact }: { prospectId: string; compact?: boolean }) {
  const [face, setFace] = useState<Face | null>(null)
  const btn = (f: Face, label: string, Icon: typeof FileText) => (
    <button
      onClick={() => setFace(f)}
      style={{ fontSize: 12, border: '1px solid #e2e8f0', background: '#fff', borderRadius: 6,
        padding: compact ? '2px 8px' : '4px 10px', cursor: 'pointer', display: 'inline-flex',
        gap: 4, alignItems: 'center', color: '#334155' }}>
      <Icon size={12} /> {label}
    </button>
  )
  return (
    <>
      {btn('internal', 'Internal report', FileText)}
      {btn('client', 'Client report', Users)}
      {face && <ReportModal prospectId={prospectId} face={face} onClose={() => setFace(null)} />}
    </>
  )
}

// ── The modal ────────────────────────────────────────────────────────────────
function ReportModal({ prospectId, face: initialFace, onClose }: {
  prospectId: string; face: Face; onClose: () => void
}) {
  const [face, setFace] = useState<Face>(initialFace)
  const { data, isLoading, error } = useQuery<ReportData>({
    queryKey: ['outreach-report', prospectId],
    queryFn: () => api.get(`/outreach/prospects/${prospectId}/report`),
  })

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)',
      zIndex: 50, display: 'flex', justifyContent: 'center', alignItems: 'flex-start', padding: 24, overflowY: 'auto' }}>
      <div onClick={e => e.stopPropagation()} style={{ background: '#fff', borderRadius: 14, width: 760,
        maxWidth: '96vw', boxShadow: '0 20px 60px rgba(15,23,42,0.25)', padding: 22 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'inline-flex', background: '#f1f5f9', borderRadius: 999, padding: 3 }}>
            {(['internal', 'client'] as Face[]).map(f => (
              <button key={f} onClick={() => setFace(f)}
                style={{ border: 'none', borderRadius: 999, padding: '5px 14px', fontSize: 12.5,
                  fontWeight: 600, cursor: 'pointer',
                  background: face === f ? '#fff' : 'transparent',
                  color: face === f ? '#0f172a' : '#64748b',
                  boxShadow: face === f ? '0 1px 3px rgba(15,23,42,0.12)' : 'none' }}>
                {f === 'internal' ? 'Internal brief' : 'Client-facing draft'}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => window.print()} title="Print / save as PDF"
              style={{ border: '1px solid #e2e8f0', background: '#fff', borderRadius: 8, padding: '5px 10px',
                cursor: 'pointer', display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: 12 }}>
              <Printer size={13} /> Print
            </button>
            <button onClick={onClose} style={{ border: 'none', background: 'none', cursor: 'pointer' }}><X size={18} /></button>
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          {isLoading ? (
            <div style={{ fontSize: 13, color: '#64748b', display: 'flex', gap: 6, alignItems: 'center', padding: 20 }}>
              <Loader2 size={14} className="animate-spin" /> Assembling the report…
            </div>
          ) : error instanceof Error ? (
            <div style={{ fontSize: 13, color: '#b91c1c', padding: 12 }}>Couldn’t build the report: {error.message}</div>
          ) : !data ? null : !data.measured ? (
            <div style={{ fontSize: 13, color: '#64748b', padding: '12px 14px', background: '#f8fafc', borderRadius: 10 }}>
              {data.justification.message ?? 'Not measured yet — no rolled-up scan for this business’s area.'}
            </div>
          ) : face === 'internal' ? (
            <InternalBrief data={data} />
          ) : (
            <ClientDraft data={data} />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Shared section pieces ────────────────────────────────────────────────────
function NotScanned({ label, reason }: { label: string; reason?: string }) {
  return (
    <div style={{ padding: '10px 12px', background: '#f8fafc', borderRadius: 10, border: '1px dashed #e2e8f0',
      fontSize: 12.5, color: '#64748b' }}>
      <strong style={{ color: '#475569' }}>{label}:</strong> not scanned yet. {reason}
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase',
    letterSpacing: 0.4, margin: '18px 0 6px' }}>{children}</div>
}

function MapsTable({ s, name, keyword, submarket, clientTone }: {
  s: Section; name: string; keyword: string; submarket: string; clientTone?: boolean
}) {
  if (s.status !== 'measured' || !s.prospect) {
    return <NotScanned label="Google Maps" reason={s.reason ?? 'the raw ranking data has aged out.'} />
  }
  const p = s.prospect
  return (
    <>
      <div style={{ fontSize: 12.5, color: '#334155', marginBottom: 6 }}>
        {clientTone
          ? `For “${keyword}” across ${submarket}, you appear in the Google map results at ${p.points_present} of ${p.live_points ?? '—'} points (${p.coverage_pct}%). Here’s how the businesses winning that search compare:`
          : `“${keyword}” · ${submarket} — coverage ${p.coverage_pct}% (${p.points_present}/${p.live_points ?? '—'} points), best rank ${p.best_rank ?? '—'}, avg ${p.avg_rank ?? '—'}.`}
      </div>
      <table style={{ width: '100%', fontSize: 12.5, borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ textAlign: 'left', color: '#64748b', fontSize: 11 }}>
            <th style={{ padding: '4px 8px' }}>Business</th>
            <th style={{ padding: '4px 8px', textAlign: 'right' }}>Map-pack points</th>
            <th style={{ padding: '4px 8px', textAlign: 'right' }}>Share</th>
            <th style={{ padding: '4px 8px', textAlign: 'right' }}>Best rank</th>
          </tr>
        </thead>
        <tbody>
          <tr style={{ borderTop: '1px solid #f1f5f9', background: '#eff6ff', fontWeight: 600 }}>
            <td style={{ padding: '6px 8px' }}>{name} {clientTone ? '(you)' : '(prospect)'}</td>
            <td style={{ padding: '6px 8px', textAlign: 'right' }}>{p.pack_points}</td>
            <td style={{ padding: '6px 8px', textAlign: 'right' }}>
              {p.live_points ? `${Math.round((p.pack_points / p.live_points) * 100)}%` : '—'}
            </td>
            <td style={{ padding: '6px 8px', textAlign: 'right' }}>{p.pack_best_rank ?? '—'}</td>
          </tr>
          {(s.competitors ?? []).map(c => (
            <tr key={c.place_id} style={{ borderTop: '1px solid #f1f5f9' }}>
              <td style={{ padding: '6px 8px' }}>{c.name}</td>
              <td style={{ padding: '6px 8px', textAlign: 'right' }}>{c.pack_points}</td>
              <td style={{ padding: '6px 8px', textAlign: 'right' }}>{c.pack_share_pct != null ? `${c.pack_share_pct}%` : '—'}</td>
              <td style={{ padding: '6px 8px', textAlign: 'right' }}>{c.best_rank ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {(s.total_competitors ?? 0) > (s.competitors?.length ?? 0) && (
        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
          {s.total_competitors} competitors hold the map pack in all; showing the top {s.competitors?.length}.
        </div>
      )}
    </>
  )
}

function OrganicTable({ s, keyword, submarket, clientTone }: {
  s: OrganicSection; keyword: string; submarket: string; clientTone?: boolean
}) {
  if (s.status !== 'measured') {
    return <NotScanned label={clientTone ? 'Google search results' : 'Organic search'}
      reason={s.reason ?? 'the search scan hasn’t run for this prospect yet.'} />
  }
  const rankLine = s.prospect_rank != null
    ? (clientTone
      ? `You rank #${s.prospect_rank} in Google’s standard search results for “${keyword}”.`
      : `Prospect ranks #${s.prospect_rank} for “${keyword}” (organic).`)
    : (clientTone
      ? `You don’t appear in the top ${s.captured_depth ?? '—'} Google search results for “${keyword}” in ${submarket}.`
      : `Prospect not in the top ${s.captured_depth ?? '—'} organic results for “${keyword}”.`)
  return (
    <>
      <div style={{ fontSize: 12.5, color: '#334155', marginBottom: 6 }}>
        {rankLine}
        {s.ai_overview_present && ' Google is also showing an AI overview for this search.'}
      </div>
      <table style={{ width: '100%', fontSize: 12.5, borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ textAlign: 'left', color: '#64748b', fontSize: 11 }}>
            <th style={{ padding: '4px 8px' }}>{clientTone ? 'Ranking ahead of you' : 'Top domains'}</th>
            <th style={{ padding: '4px 8px', textAlign: 'right' }}>Rank</th>
          </tr>
        </thead>
        <tbody>
          {(s.competitors ?? []).map(c => (
            <tr key={`${c.domain}-${c.rank}`} style={{ borderTop: '1px solid #f1f5f9' }}>
              <td style={{ padding: '6px 8px' }}>{c.domain}</td>
              <td style={{ padding: '6px 8px', textAlign: 'right' }}>{c.rank ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

const LLM_ENGINE_LABEL: Record<string, string> = {
  chatgpt: 'ChatGPT',
  google_aio: 'Google AI Overview',
}

function LlmTable({ s, name, clientTone }: { s: LlmSection; name: string; clientTone?: boolean }) {
  if (s.status !== 'measured' || !s.engines || s.engines.length === 0) {
    return <NotScanned label={clientTone ? 'AI assistants' : 'AI answers'}
      reason={s.reason ?? 'the AI-visibility scan hasn’t run for this region yet.'} />
  }
  return (
    <>
      <div style={{ display: 'grid', gap: 8 }}>
        {s.engines.map(e => (
          <div key={e.engine} style={{ display: 'flex', gap: 10, alignItems: 'flex-start',
            padding: '8px 10px', background: '#f8fafc', borderRadius: 8 }}>
            <span style={{ minWidth: 140, fontWeight: 600, fontSize: 12.5, color: '#334155' }}>
              {LLM_ENGINE_LABEL[e.engine] ?? e.engine}
            </span>
            <div style={{ fontSize: 12.5 }}>
              {!e.present ? (
                <span style={{ color: '#94a3b8' }}>No AI answer returned for this search.</span>
              ) : e.visible ? (
                <span style={{ color: '#166534', fontWeight: 600 }}>
                  ✓ {clientTone ? `You’re named` : `${name} is named`} in the AI answer.
                </span>
              ) : (
                <div>
                  <span style={{ color: '#b91c1c', fontWeight: 600 }}>
                    ✗ {clientTone ? 'You’re not named' : `${name} is not named`}.
                  </span>
                  {e.sample_businesses.length > 0 && (
                    <div style={{ color: '#64748b', marginTop: 2 }}>
                      It names: {e.sample_businesses.slice(0, 4).join(', ')}
                      {e.named_count > 4 ? ` (+${e.named_count - 4} more)` : ''}.
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      {s.caveat && <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>{s.caveat}</div>}
    </>
  )
}

// ── Internal brief ───────────────────────────────────────────────────────────
function InternalBrief({ data }: { data: ReportData }) {
  const j = data.justification
  return (
    <div>
      <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>{data.identity.name}</div>
      <div style={{ fontSize: 12, color: '#64748b' }}>
        {[data.identity.category, data.identity.address, data.identity.phone].filter(Boolean).join(' · ')}
        {data.identity.rating != null && ` · ${data.identity.rating}★`}
        {data.identity.review_count != null && ` · ${data.identity.review_count} reviews`}
      </div>
      {j.headline && <div style={{ fontSize: 13.5, fontWeight: 600, color: '#0f172a', marginTop: 10 }}>{j.headline}</div>}

      <SectionTitle>Maps rankings vs competitors</SectionTitle>
      <MapsTable s={data.signals.maps} name={data.identity.name ?? 'This business'} keyword={data.keyword} submarket={data.submarket} />

      <SectionTitle>Organic rankings vs competitors</SectionTitle>
      <OrganicTable s={data.signals.organic} keyword={data.keyword} submarket={data.submarket} />

      <SectionTitle>AI / LLM visibility</SectionTitle>
      <LlmTable s={data.signals.llm} name={data.identity.name ?? 'This business'} />

      {j.hook && (
        <>
          <SectionTitle>Call hook</SectionTitle>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <Phone size={14} style={{ color: '#0369a1', flexShrink: 0, marginTop: 2 }} />
            <div style={{ fontSize: 13, color: '#0c4a6e', fontStyle: 'italic' }}>“{j.hook}”</div>
          </div>
          {j.talking_points.length > 0 && (
            <ul style={{ margin: '8px 0 0', paddingLeft: 18, display: 'grid', gap: 4, fontSize: 12.5, color: '#334155' }}>
              {j.talking_points.map((p, i) => <li key={i}>{p.text}</li>)}
            </ul>
          )}
        </>
      )}
      {j.caveats && j.caveats.length > 0 && (
        <div style={{ marginTop: 12, fontSize: 11, color: '#94a3b8' }}>
          {j.caveats.map((c, i) => <div key={i}>· {c}</div>)}
        </div>
      )}
    </div>
  )
}

// ── Client-facing draft ──────────────────────────────────────────────────────
function ClientDraft({ data }: { data: ReportData }) {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const approved = data.client_facing.approved

  const generate = useMutation({
    mutationFn: async () => {
      const blob = await api.postBlob(`/outreach/prospects/${data.prospect_id}/report/pdf`)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report-${data.identity.name ?? data.prospect_id}.pdf`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['outreach-report', data.prospect_id] }),
  })

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        gap: 10, marginBottom: 14 }}>
        <div style={{ flex: 1, padding: '8px 12px', borderRadius: 10, fontSize: 12,
          display: 'flex', gap: 6, alignItems: 'center',
          background: approved ? '#f0fdf4' : '#fffbeb',
          border: `1px solid ${approved ? '#bbf7d0' : '#fde68a'}`,
          color: approved ? '#166534' : '#92400e' }}>
          {approved
            ? <><CheckCircle2 size={14} /> <strong>Approved.</strong> This report may be shared with the prospect.</>
            : <><AlertTriangle size={14} /> <strong>Draft.</strong> {data.client_facing.note}</>}
        </div>
        {isAdmin && (
          <button
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
            title="Approve this report and download it as a PDF to send"
            style={{ flexShrink: 0, display: 'inline-flex', gap: 6, alignItems: 'center',
              padding: '8px 12px', borderRadius: 8, border: 'none', fontWeight: 600, fontSize: 12.5,
              background: '#0f172a', color: '#fff', cursor: 'pointer' }}>
            {generate.isPending
              ? <Loader2 size={13} className="animate-spin" />
              : <Download size={13} />}
            {approved ? 'Download PDF' : 'Approve & download PDF'}
          </button>
        )}
      </div>
      {generate.error instanceof Error && (
        <div style={{ fontSize: 12, color: '#b91c1c', marginBottom: 10 }}>
          {generate.error.message === 'report_not_measured'
            ? 'Can’t generate a report yet — this area hasn’t been scanned.'
            : generate.error.message}
        </div>
      )}

      <div style={{ fontSize: 18, fontWeight: 700, color: '#0f172a' }}>
        Your Google visibility for “{data.keyword}” in {data.submarket}
      </div>
      <div style={{ fontSize: 12.5, color: '#64748b', marginTop: 2 }}>Prepared for {data.identity.name}</div>

      <SectionTitle>Google Maps — where customers do (and don’t) find you</SectionTitle>
      <MapsTable s={data.signals.maps} name={data.identity.name ?? 'You'} keyword={data.keyword} submarket={data.submarket} clientTone />

      <SectionTitle>Google search results</SectionTitle>
      <OrganicTable s={data.signals.organic} keyword={data.keyword} submarket={data.submarket} clientTone />

      <SectionTitle>AI assistants (ChatGPT, Google AI Overview)</SectionTitle>
      <LlmTable s={data.signals.llm} name={data.identity.name ?? 'You'} clientTone />

      <div style={{ marginTop: 16, fontSize: 11, color: '#94a3b8' }}>
        Based on a live scan of the Google map results across {data.submarket}. Figures are a point-in-time snapshot.
      </div>
    </div>
  )
}
