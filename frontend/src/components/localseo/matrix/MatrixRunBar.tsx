import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { ErrorDetails } from '../../ErrorDetails'
import { Spinner } from '../Spinner'
import { card, primaryBtn } from '../shared'
import { matrixApi } from './api'
import { COVERED, RUNNABLE } from './types'
import type { MatrixDetail, MatrixEstimate } from './types'

interface Props {
  clientId: string
  matrix: MatrixDetail
  selected: Set<string>
  setSelected: (ids: string[]) => void
  onStarted: () => void
}

// Selection → estimate (count / cost / time + gates) → Generate now. The
// generation is background jobs (the same staggered path as bulk-create), so
// the user can leave; the grid reconciles from the jobs on every read.
export function MatrixRunBar({ clientId, matrix, selected, setSelected, onStarted }: Props) {
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const [signoff, setSignoff] = useState(false)

  const runnableIds = matrix.cells.filter(c => RUNNABLE.has(c.status)).map(c => c.id)
  const allRunnableSelected = runnableIds.length > 0 && runnableIds.every(id => selected.has(id))
  const cellIds = [...selected].sort()
  const includesCovered = matrix.cells.some(c => selected.has(c.id) && COVERED.has(c.status))

  // The estimate is a derived read keyed on the selection — no effect/state sync.
  const { data: estimate, isFetching: estimating, error: estimateError } = useQuery<MatrixEstimate>({
    queryKey: ['local-seo-matrix-estimate', clientId, matrix.id, cellIds.join(','), includesCovered, signoff],
    queryFn: () => matrixApi.estimate(clientId, matrix.id, { cell_ids: cellIds, include_covered: includesCovered, signoff_acknowledged: signoff }),
    enabled: cellIds.length > 0,
    staleTime: 10_000,
  })

  const blocking = (estimate?.gates ?? []).filter(g => g.blocking)
  const needsSignoff = blocking.some(g => g.kind === 'matrix_signoff_required')
  const canStart = cellIds.length > 0 && !starting && !estimating && blocking.length === 0

  const start = async () => {
    if (!canStart) return
    setStarting(true)
    setError('')
    try {
      await matrixApi.generate(clientId, matrix.id, {
        cell_ids: cellIds, include_covered: includesCovered, signoff_acknowledged: signoff,
      })
      setSelected([])
      onStarted()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start generation')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10, background: '#f8fafc' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#94a3b8', flexWrap: 'wrap' }}>
        <span>Tick the cells to generate (missing / failed by default; a covered cell can be ticked to generate anyway), then run them in one batch.</span>
        <button
          type="button"
          onClick={() => setSelected(allRunnableSelected ? [] : runnableIds)}
          style={{ marginLeft: 'auto', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1' }}
        >{allRunnableSelected ? 'Deselect all' : `Select all missing (${runnableIds.length})`}</button>
      </div>

      {error && <ErrorDetails message={error} />}
      {estimateError && <ErrorDetails message={estimateError instanceof Error ? estimateError.message : 'Could not estimate'} />}

      {cellIds.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, fontSize: 13, color: '#0f172a', flexWrap: 'wrap' }}>
          {estimating || !estimate ? <Spinner size={14} /> : (
            <>
              <span><strong>{estimate.count}</strong> page{estimate.count === 1 ? '' : 's'}</span>
              <span>≈ <strong>${estimate.est_cost_usd.toFixed(2)}</strong></span>
              <span>≈ <strong>{estimate.est_minutes >= 90 ? `${(estimate.est_minutes / 60).toFixed(1)} h` : `${estimate.est_minutes} min`}</strong> of background generation</span>
            </>
          )}
        </div>
      )}

      {blocking.map(g => (
        <div key={g.kind} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e' }}>
          <span style={{ flex: 1 }}>{g.message}</span>
          {g.kind === 'matrix_signoff_required' && (
            <button type="button" onClick={() => setSignoff(true)} style={{ fontSize: 12, fontWeight: 600, background: '#fff', border: '1px solid #fde68a', borderRadius: 6, padding: '4px 10px', cursor: 'pointer', color: '#92400e' }}>
              I’ve reviewed the link-equity impact — proceed
            </button>
          )}
        </div>
      ))}
      {needsSignoff && signoff && <p style={{ fontSize: 12, color: '#166534', margin: 0 }}>Sign-off acknowledged.</p>}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button style={{ ...primaryBtn, opacity: canStart ? 1 : 0.5, cursor: canStart ? 'pointer' : 'not-allowed' }} disabled={!canStart} onClick={start}>
          {starting ? <Spinner size={16} color="#fff" /> : <Play size={16} />} {starting ? 'Starting…' : `Generate ${cellIds.length || ''} now`}
        </button>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>Runs in the background — you can leave this page; cells update as pages finish.</span>
      </div>
    </div>
  )
}
