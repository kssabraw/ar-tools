import { useQuery } from '@tanstack/react-query'
import { Loader2, Phone } from 'lucide-react'
import { api } from '../../lib/api'

// Mirrors services/outreach_justification.build_justification's response shape. The whole thing is
// deterministic and read-only — the caller's "why this is a lead" talking points (outreach PRD
// §716, HANDOFF §12 item 1). Nothing here spends; it renders scan data already captured.
interface TalkingPoint {
  element: string
  text: string
  facts: Record<string, unknown>
}
export interface JustificationData {
  measured: boolean
  prospect_id: string
  prospect_name: string
  message?: string
  headline?: string
  hook?: string
  hook_element?: string | null
  available_elements?: string[]
  talking_points: TalkingPoint[]
  caveats?: string[]
  provenance?: Record<string, unknown>
}

// A short human label per evidence element, so the talking-point list reads as a checklist a
// caller can scan. Unknown elements fall back to the raw key rather than being hidden.
const ELEMENT_LABEL: Record<string, string> = {
  coverage: 'Invisibility',
  paying: 'Paying & losing',
  competitor: 'Who’s winning',
  paid: 'Paying to win',
  geography: 'Where they drop off',
  reviews: 'Reviews',
  no_website: 'No website',
  no_phone: 'No phone',
  listing_status: 'Listing status',
}

export function Justification({ prospectId }: { prospectId: string }) {
  const { data, isLoading, error } = useQuery<JustificationData>({
    queryKey: ['outreach-justification', prospectId],
    queryFn: () => api.get(`/outreach/prospects/${prospectId}/justification`),
  })

  if (isLoading) {
    return (
      <div style={{ fontSize: 12, color: '#64748b', display: 'flex', gap: 6, alignItems: 'center', padding: '6px 0' }}>
        <Loader2 size={13} className="animate-spin" /> Building the call hook…
      </div>
    )
  }
  if (error instanceof Error) {
    return <div style={{ fontSize: 12, color: '#b91c1c', padding: '6px 0' }}>Couldn’t build the hook: {error.message}</div>
  }
  if (!data) return null

  if (!data.measured) {
    return (
      <div style={{ fontSize: 12, color: '#64748b', padding: '8px 10px', background: '#f8fafc', borderRadius: 8 }}>
        {data.message ?? 'Not measured yet — no rolled-up scan for this business’s area.'}
      </div>
    )
  }

  return (
    <div style={{ padding: '10px 12px', background: '#f8fafc', borderRadius: 10, border: '1px solid #eef2f7' }}>
      {data.headline && (
        <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>{data.headline}</div>
      )}

      {data.hook && (
        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <Phone size={14} style={{ color: '#0369a1', flexShrink: 0, marginTop: 2 }} />
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#0369a1', textTransform: 'uppercase', letterSpacing: 0.4 }}>
              Opening line
            </div>
            <div style={{ fontSize: 13, color: '#0c4a6e', fontStyle: 'italic' }}>“{data.hook}”</div>
          </div>
        </div>
      )}

      {data.talking_points.length > 0 && (
        <>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase',
            letterSpacing: 0.4, margin: '12px 0 4px' }}>
            Points to make
          </div>
          <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none', display: 'grid', gap: 6 }}>
            {data.talking_points.map((p, i) => (
              <li key={`${p.element}-${i}`} style={{ display: 'flex', gap: 8, fontSize: 12.5, color: '#334155' }}>
                <span style={{ flexShrink: 0, minWidth: 108, fontWeight: 600, color: '#475569' }}>
                  {ELEMENT_LABEL[p.element] ?? p.element}
                </span>
                <span>{p.text}</span>
              </li>
            ))}
          </ul>
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
