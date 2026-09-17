import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ClipboardList, ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '../../lib/api'

// Mirrors services/outreach_script.build_script's response shape. Deterministic + read-only: the
// caller's talk track past the opener (open → discovery → evidence → value → close) plus rebuttals
// keyed to what the prospect says back, each fed by that prospect's own measured facts. Nothing here
// spends; it renders scan data already assembled (Tier 3 / T3.2).
interface ScriptSection {
  key: string
  title: string
  lines: string[]
  note: string | null
  facts: Record<string, unknown>
}
interface Rebuttal {
  key: string
  objection: string
  response: string
  grounded: boolean
  facts: Record<string, unknown>
}
export interface ScriptData {
  measured: boolean
  grounded: boolean
  prospect_id: string
  prospect_name: string
  opening_line: string | null
  sections: ScriptSection[]
  rebuttals: Rebuttal[]
  caveats?: string[]
  provenance?: Record<string, unknown>
}

export function Script({ prospectId }: { prospectId: string }) {
  const { data, isLoading, error } = useQuery<ScriptData>({
    queryKey: ['outreach-script', prospectId],
    queryFn: () => api.get(`/outreach/prospects/${prospectId}/script`),
  })

  if (isLoading) {
    return (
      <div style={{ fontSize: 12, color: '#64748b', display: 'flex', gap: 6, alignItems: 'center', padding: '6px 0' }}>
        <Loader2 size={13} className="animate-spin" /> Building the script…
      </div>
    )
  }
  if (error instanceof Error) {
    return <div style={{ fontSize: 12, color: '#b91c1c', padding: '6px 0' }}>Couldn’t build the script: {error.message}</div>
  }
  if (!data) return null

  return (
    <div style={{ padding: '10px 12px', background: '#f8fafc', borderRadius: 10, border: '1px solid #eef2f7' }}>
      {!data.grounded && (
        <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 8 }}>
          {data.measured
            ? 'Generic fallback — the scan produced no strong signal to ground rebuttals in.'
            : 'Generic fallback — no rolled-up scan for this area yet. Run or await a scan for fact-grounded lines.'}
        </div>
      )}

      {/* The talk track. */}
      {data.sections.map((s) => (
        <div key={s.key} style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#0369a1', textTransform: 'uppercase',
            letterSpacing: 0.4, marginBottom: 4 }}>
            {s.title}
          </div>
          <div style={{ display: 'grid', gap: 4 }}>
            {s.lines.map((line, i) => (
              <div key={i} style={{ fontSize: 13, color: '#0f172a', lineHeight: 1.45 }}>{line}</div>
            ))}
          </div>
          {s.note && (
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4, fontStyle: 'italic' }}>{s.note}</div>
          )}
        </div>
      ))}

      {/* The objection/rebuttal library. */}
      {data.rebuttals.length > 0 && (
        <>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase',
            letterSpacing: 0.4, margin: '4px 0 6px', display: 'flex', gap: 6, alignItems: 'center' }}>
            <ClipboardList size={12} /> If they push back
          </div>
          <div style={{ display: 'grid', gap: 6 }}>
            {data.rebuttals.map((r) => <RebuttalRow key={r.key} rebuttal={r} />)}
          </div>
        </>
      )}

      {data.caveats && data.caveats.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 11, color: '#94a3b8' }}>
          {data.caveats.map((c, i) => <div key={i}>· {c}</div>)}
        </div>
      )}
    </div>
  )
}

function RebuttalRow({ rebuttal }: { rebuttal: Rebuttal }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ border: '1px solid #eef2f7', borderRadius: 8, background: '#fff' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{ width: '100%', display: 'flex', gap: 8, alignItems: 'center', textAlign: 'left',
          border: 'none', background: 'none', cursor: 'pointer', padding: '7px 10px' }}>
        {open ? <ChevronDown size={13} style={{ flexShrink: 0, color: '#94a3b8' }} />
          : <ChevronRight size={13} style={{ flexShrink: 0, color: '#94a3b8' }} />}
        <span style={{ fontSize: 12.5, fontWeight: 600, color: '#334155', flex: 1 }}>“{rebuttal.objection}”</span>
        {rebuttal.grounded && (
          <span title="Grounded in this prospect's scan data"
            style={{ fontSize: 9.5, fontWeight: 700, color: '#166534', background: '#dcfce7',
              borderRadius: 999, padding: '1px 7px', textTransform: 'uppercase', letterSpacing: 0.3 }}>
            grounded
          </span>
        )}
      </button>
      {open && (
        <div style={{ padding: '0 10px 9px 31px', fontSize: 12.5, color: '#0f172a', lineHeight: 1.45 }}>
          {rebuttal.response}
        </div>
      )}
    </div>
  )
}
