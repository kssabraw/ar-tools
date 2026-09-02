import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Grid3x3, Plus } from 'lucide-react'
import { ErrorDetails } from '../../ErrorDetails'
import { Spinner } from '../Spinner'
import { card, primaryBtn } from '../shared'
import { matrixApi } from './api'
import { MatrixBuilder } from './MatrixBuilder'
import { MatrixDetail } from './MatrixDetail'
import type { MatrixSummary } from './types'

interface Props {
  clientId: string
  // Open straight onto a matrix (deep link ?matrix=<id>, or "Save as matrix").
  // The parent keys this component on it, so a new focus remounts onto the
  // matrix instead of syncing state in an effect.
  focusMatrixId?: string | null
  onOpenPage: (pageId: string) => void
}

type View = { kind: 'list' } | { kind: 'new' } | { kind: 'detail'; id: string }

// The Matrix tab: the client's saved matrices → a builder → a matrix's grid.
export function MatrixTab({ clientId, focusMatrixId, onOpenPage }: Props) {
  const [view, setView] = useState<View>(focusMatrixId ? { kind: 'detail', id: focusMatrixId } : { kind: 'list' })

  const { data: matrices, isLoading, error, refetch } = useQuery<MatrixSummary[]>({
    queryKey: ['local-seo-matrices', clientId],
    queryFn: () => matrixApi.list(clientId),
    enabled: view.kind === 'list',
  })

  if (view.kind === 'new') {
    return <MatrixBuilder clientId={clientId} onCreated={m => { void refetch(); setView({ kind: 'detail', id: m.id }) }} onCancel={() => setView({ kind: 'list' })} />
  }
  if (view.kind === 'detail') {
    return (
      <MatrixDetail
        clientId={clientId}
        matrixId={view.id}
        onBack={() => { void refetch(); setView({ kind: 'list' }) }}
        onDeleted={() => { void refetch(); setView({ kind: 'list' }) }}
        onOpenPage={onOpenPage}
      />
    )
  }

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}><Grid3x3 size={16} /> Service × location matrices</h2>
          <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
            A saved grid of services × locations: every cell is a page with its own coverage status, the pages link to each
            other as a silo, and you can add a service or suburb later and fill only the new cells.
          </p>
        </div>
        <button style={primaryBtn} onClick={() => setView({ kind: 'new' })}><Plus size={16} /> New matrix</button>
      </div>

      {error && <ErrorDetails message={error instanceof Error ? error.message : 'Could not load matrices'} />}
      {isLoading && <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#64748b', fontSize: 13 }}><Spinner size={14} /> Loading…</div>}

      {matrices && matrices.length === 0 && (
        <p style={{ fontSize: 13, color: '#94a3b8', margin: 0 }}>No matrices yet. Create one here, or build the axes in Plan Silo → Upload your own → Matrix and “Save as matrix”.</p>
      )}

      {matrices && matrices.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {matrices.map(m => {
            const total = m.coverage.total ?? 0
            const built = (m.coverage.done ?? 0) + (m.coverage.published ?? 0)
            const covered = (m.coverage.found ?? 0) + (m.coverage.on_site ?? 0)
            const inFlight = (m.coverage.queued ?? 0) + (m.coverage.generating ?? 0)
            const pct = total ? Math.round(((built + covered) / total) * 100) : 0
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => setView({ kind: 'detail', id: m.id })}
                style={{ textAlign: 'left', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: '12px 14px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 8 }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{m.name}</span>
                  <span style={{ fontSize: 12, color: '#94a3b8' }}>{m.services.length} × {m.locations.length} · {m.location}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 600, color: '#0f172a' }}>{pct}%</span>
                  {inFlight > 0 && <span style={{ fontSize: 11, fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: '#fef3c7', color: '#92400e' }}>{inFlight} in progress</span>}
                  {m.release_enabled && <span style={{ fontSize: 11, fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: '#eef2ff', color: '#4338ca' }}>drip {m.release_status}</span>}
                </div>
                <div style={{ height: 5, background: '#f1f5f9', borderRadius: 999, overflow: 'hidden' }}>
                  <div style={{ width: `${pct}%`, height: '100%', background: '#6366f1' }} />
                </div>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
