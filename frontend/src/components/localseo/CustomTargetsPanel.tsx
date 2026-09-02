import { useRef, useState } from 'react'
import { Building2, Grid3x3, List, Save, Search, Upload } from 'lucide-react'
import { localSeoApi } from './api'
import { LocationAutocomplete } from './LocationAutocomplete'
import { RelatedPagesList } from './RelatedPagesList'
import { BulkCreateBar } from './BulkCreateBar'
import { useBulkCreate } from './useBulkCreate'
import { Spinner } from './Spinner'
import { ErrorDetails } from '../ErrorDetails'
import { card, input, label, primaryBtn } from './shared'
import type { RelatedPageItem } from './types'
import { matrixApi } from './matrix/api'
import { MatrixAxesEditor } from './matrix/MatrixAxesEditor'
import { splitLines } from './matrix/types'

type Mode = 'matrix' | 'list'

const textarea: React.CSSProperties = { ...input, minHeight: 120, resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5 }

// "Upload your own" Plan Silo entry point: the team supplies its own page targets
// — a matrix (services × locations → every combination) or an explicit list/CSV —
// and we mark each found/on_site/missing against the client's site + in-tool pages
// (the same check the AI plan uses), then hand the missing ones to the same
// bulk-create flow. Self-contained: own inputs, own area, own bulk-create instance.
export function CustomTargetsPanel({
  clientId,
  clientName,
  hasWebsite,
  onCreated,
  onFoundAction,
  onSaveMatrix,
}: {
  clientId: string
  clientName?: string
  hasWebsite: boolean
  onCreated: () => void
  onFoundAction: (item: RelatedPageItem) => void
  // Matrix mode → persist the axes as a saved matrix (opens the Matrix tab).
  onSaveMatrix?: (matrixId: string) => void
}) {
  const [mode, setMode] = useState<Mode>('matrix')
  const [services, setServices] = useState('')
  const [locations, setLocations] = useState('')
  const [targets, setTargets] = useState('')
  const [location, setLocation] = useState('')
  const [locationCode, setLocationCode] = useState<number | null>(null)
  const [items, setItems] = useState<RelatedPageItem[] | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState('')
  const [savingMatrix, setSavingMatrix] = useState(false)
  const [matrixName, setMatrixName] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const checkRef = useRef(0) // invalidates a superseded check (input edited mid-request)

  const bulk = useBulkCreate(clientId, onCreated)

  const reset = () => { checkRef.current++; setItems(null); setNotes([]); setError(''); bulk.reset() }

  const matrixCount = (() => {
    const s = services.split('\n').map(x => x.trim()).filter(Boolean).length
    const l = locations.split('\n').map(x => x.trim()).filter(Boolean).length
    return s * l
  })()
  const listCount = targets.split('\n').map(x => x.trim()).filter(Boolean).length

  const canCheck = !!location.trim() && !checking && !bulk.creating &&
    (mode === 'matrix' ? matrixCount > 0 : listCount > 0)
  const canSaveMatrix = Boolean(onSaveMatrix) && mode === 'matrix' && matrixCount > 0 && !!location.trim() && !savingMatrix && !bulk.creating

  const saveMatrix = async () => {
    if (!canSaveMatrix || !onSaveMatrix) return
    setSavingMatrix(true)
    setError('')
    try {
      const svc = splitLines(services)
      const locs = splitLines(locations)
      const m = await matrixApi.create(clientId, {
        name: matrixName.trim() || `${svc[0]} × ${locs.length} location${locs.length === 1 ? '' : 's'}`,
        location: location.trim(),
        location_code: locationCode,
        services: svc,
        locations: locs,
      })
      onSaveMatrix(m.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the matrix')
    } finally {
      setSavingMatrix(false)
    }
  }

  const onPickFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const text = await file.text()
    setTargets(prev => (prev.trim() ? `${prev.trim()}\n${text}` : text))
    reset()
    if (fileRef.current) fileRef.current.value = '' // allow re-picking the same file
  }

  const check = async () => {
    if (!canCheck) return
    const myCheck = ++checkRef.current // any input edit (via reset) or re-check invalidates this
    setChecking(true)
    setError('')
    setItems(null)
    setNotes([])
    bulk.reset()
    try {
      const res = await localSeoApi.customTargets(clientId, {
        input_mode: mode,
        services: mode === 'matrix' ? services : '',
        locations: mode === 'matrix' ? locations : '',
        targets: mode === 'list' ? targets : '',
        location: location.trim(),
        location_code: locationCode,
      })
      if (checkRef.current !== myCheck) return // superseded (input edited) — discard stale result
      setItems(res.items ?? [])
      setNotes(res.degraded_notes ?? [])
    } catch (e) {
      if (checkRef.current === myCheck) setError(e instanceof Error ? e.message : 'Could not check targets')
    } finally {
      // Unconditional: no second check can run concurrently (the button is disabled
      // while checking and reset() never starts one), so the spinner is always ours.
      setChecking(false)
    }
  }

  const modeBtn = (m: Mode, icon: React.ReactNode, text: string) => (
    <button
      type="button"
      onClick={() => { setMode(m); reset() }}
      disabled={bulk.creating}
      style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
        padding: '8px 12px', fontSize: 13, fontWeight: 600, cursor: bulk.creating ? 'not-allowed' : 'pointer',
        border: '1px solid', borderColor: mode === m ? '#6366f1' : '#e2e8f0',
        background: mode === m ? '#eef2ff' : '#fff', color: mode === m ? '#4338ca' : '#64748b',
        borderRadius: 8,
      }}
    >{icon}{text}</button>
  )

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>Upload your own targets</h2>
        <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
          Supply your own pages instead of the AI plan — a matrix (services × locations) or an explicit list.
          Each is checked against {clientName ?? 'this client'}'s existing pages, so you can create the missing ones in one batch.
        </p>
      </div>

      {!hasWebsite && (
        <div style={{ display: 'flex', gap: 10, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 13, color: '#92400e' }}>
          <Building2 size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>No website is on file for this client, so every page will show as “missing”. Add one to detect existing pages.</span>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        {modeBtn('matrix', <Grid3x3 size={15} />, 'Matrix (services × locations)')}
        {modeBtn('list', <List size={15} />, 'List / CSV')}
      </div>

      {mode === 'matrix' ? (
        <MatrixAxesEditor
          services={services}
          locations={locations}
          onChange={(s, l) => { setServices(s); setLocations(l); reset() }}
          disabled={bulk.creating || savingMatrix}
        />
      ) : (
        <div>
          <label style={label}>Page targets</label>
          <textarea style={textarea} value={targets} disabled={bulk.creating}
            onChange={e => { setTargets(e.target.value); reset() }}
            placeholder={'roof restoration melbourne\ngutter cleaning geelong\n\n— or CSV —\nkeyword,group,location\nroof restoration melbourne,Roofing,Melbourne'} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
            <button type="button" onClick={() => fileRef.current?.click()} disabled={bulk.creating}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#6366f1' }}>
              <Upload size={14} /> Upload a CSV
            </button>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>
              One target per line, or a CSV with a header row (<code>keyword</code>, optional <code>group</code>, <code>location</code>, <code>supporting</code>).
            </span>
            <input ref={fileRef} type="file" accept=".csv,text/csv,text/plain" onChange={onPickFile} style={{ display: 'none' }} />
          </div>
        </div>
      )}

      <div>
        <label style={label}>Area / Location (for the site check + generation)</label>
        <LocationAutocomplete
          clientId={clientId}
          value={location}
          onChange={(loc, code) => { setLocation(loc); setLocationCode(code); reset() }}
          placeholder="Start typing a city, e.g. Melbourne…"
          disabled={bulk.creating}
        />
      </div>

      {error && <ErrorDetails message={error} />}

      <button
        style={{ ...primaryBtn, width: '100%', opacity: canCheck ? 1 : 0.5, cursor: canCheck ? 'pointer' : 'not-allowed' }}
        disabled={!canCheck}
        onClick={check}
      >
        {checking ? <Spinner size={16} /> : <Search size={16} />}
        {(() => {
          if (checking) return 'Checking targets…'
          const n = mode === 'matrix' ? matrixCount : listCount
          return n > 0 ? `Check ${n} target${n === 1 ? '' : 's'}` : 'Check targets'
        })()}
      </button>

      {onSaveMatrix && mode === 'matrix' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: '#eef2ff', border: '1px solid #c7d2fe', borderRadius: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: '#4338ca', flex: 1, minWidth: 220 }}>
            Keep this grid: a saved matrix tracks every cell’s coverage, gap-fills when you add a suburb later, and links the pages as a silo.
          </span>
          <input style={{ ...input, width: 220 }} value={matrixName} onChange={e => setMatrixName(e.target.value)} placeholder="Matrix name (optional)" disabled={savingMatrix} />
          <button
            type="button"
            onClick={saveMatrix}
            disabled={!canSaveMatrix}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600, background: '#fff', border: '1px solid #c7d2fe', borderRadius: 8, padding: '7px 12px', cursor: canSaveMatrix ? 'pointer' : 'not-allowed', color: '#4338ca', opacity: canSaveMatrix ? 1 : 0.5 }}
          >
            {savingMatrix ? <Spinner size={14} /> : <Save size={14} />} Save as matrix
          </button>
        </div>
      )}

      {notes.length > 0 && (
        <div style={{ display: 'flex', gap: 10, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e' }}>
          <Building2 size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{notes.join(' · ')}</span>
        </div>
      )}

      {items && items.length === 0 && !checking && (
        <p style={{ fontSize: 14, color: '#64748b', textAlign: 'center', padding: 24 }}>No targets parsed — check your input.</p>
      )}

      {items && items.length > 0 && (() => {
        const found = items.filter(r => r.status === 'found').length
        const onSite = items.filter(r => r.status === 'on_site').length
        const missingCount = items.filter(r => r.status === 'missing').length
        const siloCount = new Set(items.map(r => r.group)).size
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#64748b', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, color: '#0f172a' }}>{items.length} target{items.length === 1 ? '' : 's'} across {siloCount} group{siloCount === 1 ? '' : 's'}</span>
              <span style={{ fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: '#dcfce7', color: '#166534' }}>{found} exist</span>
              {onSite > 0 && (
                <span style={{ fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: '#dbeafe', color: '#1e40af' }} title="Already on the client's live site">{onSite} on site</span>
              )}
              <span style={{ fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: '#fef3c7', color: '#92400e' }}>{missingCount} missing</span>
            </div>

            <RelatedPagesList
              items={items}
              onAction={onFoundAction}
              selection={{ selected: bulk.selected, onToggle: bulk.toggle, disabled: bulk.creating }}
            />

            <BulkCreateBar
              items={items}
              bulk={bulk}
              location={location}
              locationCode={locationCode}
              onViewSaved={onCreated}
            />
          </div>
        )
      })()}
    </div>
  )
}
