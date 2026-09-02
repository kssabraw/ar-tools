import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Building2, Pencil, RefreshCw, Trash2 } from 'lucide-react'
import { ErrorDetails } from '../../ErrorDetails'
import { Spinner } from '../Spinner'
import { card, label, primaryBtn } from '../shared'
import { matrixApi } from './api'
import { MatrixAxesEditor } from './MatrixAxesEditor'
import { MatrixGrid } from './MatrixGrid'
import { composeLocations, pinsFromRows, type LocationPins } from './locationPins'
import { MatrixLocationPins } from './MatrixLocationPins'
import { MatrixPublishBar } from './MatrixPublishBar'
import { MatrixReleaseCard } from './MatrixReleaseCard'
import { MatrixRunBar } from './MatrixRunBar'
import { IN_FLIGHT, splitLines } from './types'
import type { MatrixDetail as MatrixDetailT } from './types'
import { useSuggest } from './useSuggest'

interface Props {
  clientId: string
  matrixId: string
  onBack: () => void
  onDeleted: () => void
  onOpenPage: (pageId: string) => void
}

const smallBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 600, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 7, padding: '5px 10px', cursor: 'pointer', color: '#334155' }

// A saved matrix: header + coverage rollup, the axes editor (with Suggest),
// the grid, and the run bar. Polls while any cell is in flight — the backend
// reconciles cells from their jobs on every read, so this is the only client
// state and it survives navigation for free.
export function MatrixDetail({ clientId, matrixId, onBack, onDeleted, onOpenPage }: Props) {
  const queryClient = useQueryClient()
  const key = ['local-seo-matrix', clientId, matrixId]
  const { data: matrix, isLoading, error: loadError } = useQuery<MatrixDetailT>({
    queryKey: key,
    queryFn: () => matrixApi.get(clientId, matrixId),
    refetchInterval: q => {
      const m = q.state.data as MatrixDetailT | undefined
      return m && m.cells.some(c => IN_FLIGHT.has(c.status)) ? 15000 : false
    },
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })

  const [selected, setSelectedSet] = useState<Set<string>>(new Set())
  const onToggle = (id: string, checked: boolean) => setSelectedSet(prev => { const n = new Set(prev); if (checked) n.add(id); else n.delete(id); return n })
  const setSelected = (ids: string[]) => setSelectedSet(new Set(ids))

  // Axes editing (gap-fill on save).
  const [editing, setEditing] = useState(false)
  const [services, setServices] = useState('')
  const [locations, setLocations] = useState('')
  const [pins, setPins] = useState<LocationPins>({})
  const [saving, setSaving] = useState(false)
  const [rechecking, setRechecking] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')
  const suggest = useSuggest(clientId, matrixId)

  // The editor's text is seeded from the matrix when the editor opens (not
  // synced by an effect), so typing never fights a background refetch.
  const openEditor = () => {
    if (!matrix) return
    setServices(matrix.services.map(s => s.label).join('\n'))
    setLocations(matrix.locations.map(l => l.name).join('\n'))
    setPins(pinsFromRows(matrix.locations))
    setEditing(true)
  }

  const coverage = useMemo(() => matrix?.coverage ?? {}, [matrix])

  const saveAxes = async () => {
    if (!matrix) return
    setSaving(true)
    setError('')
    try {
      // Pins (seeded from the saved rows, edited in the pins list) ride on the
      // rows by name, so a pin survives re-ordering and is dropped with its line.
      await matrixApi.update(clientId, matrixId, { services: splitLines(services), locations: composeLocations(locations, pins) })
      setEditing(false)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the axes')
    } finally {
      setSaving(false)
    }
  }

  const recheck = async () => {
    setRechecking(true)
    setError('')
    try {
      await matrixApi.recheck(clientId, matrixId)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not re-check coverage')
    } finally {
      setRechecking(false)
    }
  }

  // "Publish anyway" for one blocked cell: the same explicit override the
  // per-page Publish button offers, scoped to that cell (force_voice needs ids).
  const forcePublish = async (cellId: string) => {
    setError('')
    try {
      await matrixApi.publish(clientId, matrixId, { cell_ids: [cellId], force_voice: true })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not publish')
    }
  }

  const remove = async () => {
    if (!window.confirm('Delete this matrix? Generated pages are kept in Saved Pages.')) return
    setDeleting(true)
    try {
      await matrixApi.remove(clientId, matrixId)
      onDeleted()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete the matrix')
      setDeleting(false)
    }
  }

  if (isLoading || !matrix) {
    return (
      <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', fontSize: 13 }}>
        {loadError ? <ErrorDetails message={loadError instanceof Error ? loadError.message : 'Could not load the matrix'} /> : <><Spinner size={16} /> Loading matrix…</>}
      </div>
    )
  }

  const total = coverage.total ?? matrix.cells.length
  const built = (coverage.done ?? 0) + (coverage.published ?? 0)
  const covered = (coverage.found ?? 0) + (coverage.on_site ?? 0)
  const inFlight = (coverage.queued ?? 0) + (coverage.generating ?? 0)
  const pct = total ? Math.round(((built + covered) / total) * 100) : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <button type="button" onClick={onBack} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', padding: 0, color: '#64748b', fontSize: 13, cursor: 'pointer', alignSelf: 'flex-start' }}>
        <ArrowLeft size={14} /> All matrices
      </button>

      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>{matrix.name}</h2>
            <p style={{ fontSize: 12, color: '#94a3b8', margin: '4px 0 0' }}>
              {matrix.services.length} service{matrix.services.length === 1 ? '' : 's'} × {matrix.locations.length} location{matrix.locations.length === 1 ? '' : 's'} · {matrix.location} · <code style={{ fontSize: 11 }}>{matrix.url_pattern}</code>
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" style={smallBtn} onClick={recheck} disabled={rechecking}>{rechecking ? <Spinner size={12} /> : <RefreshCw size={13} />} Re-check coverage</button>
            <button type="button" style={smallBtn} onClick={() => (editing ? setEditing(false) : openEditor())}><Pencil size={13} /> {editing ? 'Close editor' : 'Edit axes'}</button>
            <button type="button" style={{ ...smallBtn, color: '#b91c1c' }} onClick={remove} disabled={deleting}><Trash2 size={13} /> Delete</button>
          </div>
        </div>

        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#64748b', flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, color: '#0f172a' }}>{pct}% covered</span>
            <span style={{ background: '#dcfce7', color: '#166534', padding: '1px 8px', borderRadius: 5, fontWeight: 600 }}>{built} built</span>
            <span style={{ background: '#dbeafe', color: '#1e40af', padding: '1px 8px', borderRadius: 5, fontWeight: 600 }}>{covered} already on site</span>
            {inFlight > 0 && <span style={{ background: '#fef3c7', color: '#92400e', padding: '1px 8px', borderRadius: 5, fontWeight: 600 }}>{inFlight} in progress</span>}
            {(coverage.failed ?? 0) > 0 && <span style={{ background: '#fee2e2', color: '#991b1b', padding: '1px 8px', borderRadius: 5, fontWeight: 600 }}>{coverage.failed} failed</span>}
            <span style={{ background: '#f1f5f9', color: '#64748b', padding: '1px 8px', borderRadius: 5, fontWeight: 600 }}>{coverage.missing ?? 0} missing</span>
          </div>
          <div style={{ height: 6, background: '#f1f5f9', borderRadius: 999, marginTop: 8, overflow: 'hidden' }}>
            <div style={{ width: `${pct}%`, height: '100%', background: '#6366f1' }} />
          </div>
        </div>

        {matrix.degraded_notes.length > 0 && (
          <div style={{ display: 'flex', gap: 10, padding: '8px 12px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e' }}>
            <Building2 size={14} style={{ flexShrink: 0, marginTop: 1 }} /><span>{matrix.degraded_notes.join(' · ')}</span>
          </div>
        )}
        {error && <ErrorDetails message={error} />}
      </div>

      {editing && (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={label}>Edit the axes</label>
            <p style={{ fontSize: 12, color: '#94a3b8', margin: '2px 0 0' }}>
              Saving gap-fills: new combinations are added as missing; a removed combination is deleted only if it has no page (otherwise it’s parked, never lost).
            </p>
          </div>
          <MatrixAxesEditor
            services={services}
            locations={locations}
            onChange={(s, l) => { setServices(s); setLocations(l) }}
            disabled={saving}
            suggest={{
              onSuggest: axis => suggest.run(axis, axis === 'services' ? splitLines(services)[0] ?? null : null),
              suggesting: suggest.suggesting,
              services: suggest.services,
              locations: suggest.locations,
              notes: suggest.notes,
            }}
          />
          {suggest.error && <ErrorDetails message={suggest.error} />}
          <MatrixLocationPins clientId={clientId} locationsText={locations} pins={pins} onChange={setPins} disabled={saving} />
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button style={{ ...primaryBtn, opacity: saving ? 0.6 : 1 }} disabled={saving} onClick={saveAxes}>
              {saving ? <Spinner size={16} color="#fff" /> : null} Save axes
            </button>
            <button type="button" onClick={() => setEditing(false)} disabled={saving} style={{ background: 'none', border: 'none', color: '#64748b', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          </div>
        </div>
      )}

      <MatrixGrid matrix={matrix} selected={selected} onToggle={onToggle} onOpenPage={onOpenPage} onForcePublish={forcePublish} />

      <MatrixRunBar clientId={clientId} matrix={matrix} selected={selected} setSelected={setSelected} onStarted={refresh} />

      <MatrixPublishBar clientId={clientId} matrix={matrix} onStarted={refresh} />

      <MatrixReleaseCard clientId={clientId} matrix={matrix} onChanged={refresh} />
    </div>
  )
}
