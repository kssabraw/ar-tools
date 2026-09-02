import { useState } from 'react'
import { Grid3x3 } from 'lucide-react'
import { EntityProviderSelect, type EntityProvider } from '../../EntityProviderSelect'
import { ErrorDetails } from '../../ErrorDetails'
import { LocationAutocomplete } from '../LocationAutocomplete'
import { Spinner } from '../Spinner'
import { card, input, label, primaryBtn } from '../shared'
import { matrixApi } from './api'
import { MatrixAxesEditor } from './MatrixAxesEditor'
import { splitLines, URL_PATTERN_PRESETS } from './types'
import type { MatrixDetail } from './types'

interface Props {
  clientId: string
  onCreated: (matrix: MatrixDetail) => void
  onCancel: () => void
  // Pre-fill from the one-shot "Upload your own" panel ("Save as matrix").
  initialServices?: string
  initialLocations?: string
  initialLocation?: { location: string; locationCode: number | null }
}

const select: React.CSSProperties = { ...input, appearance: 'auto' as React.CSSProperties['appearance'] }

// Create a saved matrix: name, metro anchor, the two axes, URL pattern and the
// generation / publish defaults. Suggest buttons live on the saved matrix (they
// need a matrix id) — see MatrixDetail's axes panel.
export function MatrixBuilder({ clientId, onCreated, onCancel, initialServices, initialLocations, initialLocation }: Props) {
  const [name, setName] = useState('')
  const [location, setLocation] = useState(initialLocation?.location ?? '')
  const [locationCode, setLocationCode] = useState<number | null>(initialLocation?.locationCode ?? null)
  const [services, setServices] = useState(initialServices ?? '')
  const [locations, setLocations] = useState(initialLocations ?? '')
  const [pattern, setPattern] = useState<string>(URL_PATTERN_PRESETS[0].value)
  const [customPattern, setCustomPattern] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [templateUrl, setTemplateUrl] = useState('')
  const [entityProvider, setEntityProvider] = useState<EntityProvider>('textrazor')
  const [destination, setDestination] = useState<'google_docs' | 'wordpress' | 'github'>('google_docs')
  const [publishStatus, setPublishStatus] = useState<'draft' | 'publish'>('draft')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const serviceCount = splitLines(services).length
  const locationCount = splitLines(locations).length
  const cells = serviceCount * locationCount
  const urlPattern = pattern === 'custom' ? customPattern.trim() : pattern
  const canSave = !saving && !!location.trim() && serviceCount > 0 && locationCount > 0 && !!urlPattern

  const save = async () => {
    if (!canSave) return
    setSaving(true)
    setError('')
    try {
      const matrix = await matrixApi.create(clientId, {
        name: name.trim() || `${splitLines(services)[0]} × ${locationCount} location${locationCount === 1 ? '' : 's'}`,
        location: location.trim(),
        location_code: locationCode,
        services: splitLines(services),
        locations: splitLines(locations),
        url_pattern: urlPattern,
        base_url: baseUrl.trim() || null,
        page_template_url: templateUrl.trim() || null,
        entity_provider: entityProvider,
        publish_destination: destination,
        publish_status: publishStatus,
      })
      onCreated(matrix)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the matrix')
      setSaving(false)
    }
  }

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Grid3x3 size={16} /> New service × location matrix
        </h2>
        <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
          One page per service in each location. The matrix is saved: every cell keeps its coverage status, you can add a
          service or suburb later and fill only the new cells, and the pages link to each other as a silo.
        </p>
      </div>

      <div>
        <label style={label}>Name</label>
        <input style={input} value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Roof restoration × Melbourne suburbs" disabled={saving} />
      </div>

      <div>
        <label style={label}>Metro area (SERP anchor)</label>
        <LocationAutocomplete
          clientId={clientId}
          value={location}
          onChange={(loc, code) => { setLocation(loc); setLocationCode(code) }}
          placeholder="Start typing a city, e.g. Melbourne…"
          disabled={saving}
        />
        <p style={{ fontSize: 12, color: '#94a3b8', margin: '4px 0 0' }}>
          Every cell is generated against this area with its own location in the keyword (the live-verified path). A
          location that is a different metro can be pinned to its own code later.
        </p>
      </div>

      <MatrixAxesEditor services={services} locations={locations} onChange={(s, l) => { setServices(s); setLocations(l) }} disabled={saving} />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div>
          <label style={label}>URL pattern</label>
          <select style={select} value={pattern} onChange={e => setPattern(e.target.value)} disabled={saving}>
            {URL_PATTERN_PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
            <option value="custom">Custom…</option>
          </select>
          {pattern === 'custom' && (
            <input style={{ ...input, marginTop: 6 }} value={customPattern} onChange={e => setCustomPattern(e.target.value)} placeholder="/{location}-{service}/" disabled={saving} />
          )}
          <p style={{ fontSize: 12, color: '#94a3b8', margin: '4px 0 0' }}>Where each page will live — sibling links point here.</p>
        </div>
        <div>
          <label style={label}>Site base URL <span style={{ fontWeight: 400, color: '#94a3b8' }}>(optional — defaults to the client’s website)</span></label>
          <input style={input} value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://www.example.com.au" disabled={saving} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div>
          <label style={label}>Page template URL <span style={{ fontWeight: 400, color: '#94a3b8' }}>(optional)</span></label>
          <input style={input} value={templateUrl} onChange={e => setTemplateUrl(e.target.value)} placeholder="https://… (mirror this page’s structure)" disabled={saving} />
        </div>
        <EntityProviderSelect value={entityProvider} onChange={setEntityProvider} disabled={saving} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div>
          <label style={label}>Publish destination (default)</label>
          <select style={select} value={destination} onChange={e => setDestination(e.target.value as typeof destination)} disabled={saving}>
            <option value="google_docs">Google Docs</option>
            <option value="wordpress">WordPress</option>
            <option value="github">GitHub</option>
          </select>
        </div>
        <div>
          <label style={label}>Publish as</label>
          <select style={select} value={publishStatus} onChange={e => setPublishStatus(e.target.value as typeof publishStatus)} disabled={saving}>
            <option value="draft">Draft</option>
            <option value="publish">Published</option>
          </select>
        </div>
      </div>

      {error && <ErrorDetails message={error} />}

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button style={{ ...primaryBtn, opacity: canSave ? 1 : 0.5, cursor: canSave ? 'pointer' : 'not-allowed' }} disabled={!canSave} onClick={save}>
          {saving ? <Spinner size={16} color="#fff" /> : <Grid3x3 size={16} />} {saving ? 'Creating…' : `Create matrix${cells ? ` (${cells} cells)` : ''}`}
        </button>
        <button type="button" onClick={onCancel} disabled={saving} style={{ background: 'none', border: 'none', color: '#64748b', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
      </div>
    </div>
  )
}
