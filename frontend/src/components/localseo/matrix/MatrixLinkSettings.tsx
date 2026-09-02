import { useState } from 'react'
import { Link2 } from 'lucide-react'
import { ErrorDetails } from '../../ErrorDetails'
import { Spinner } from '../Spinner'
import { card, input, primaryBtn } from '../shared'
import { matrixApi } from './api'
import type { MatrixDetail } from './types'

interface Props {
  clientId: string
  matrix: MatrixDetail
  onChanged: () => void
}

// Internal-linking settings for an existing matrix: besides sibling interlinks,
// each page can link UP to its top-level service page and the home page. Editing
// only changes what NEW / regenerated pages carry — already-generated pages keep
// the links they were built with until re-run.
export function MatrixLinkSettings({ clientId, matrix, onChanged }: Props) {
  const [hub, setHub] = useState(matrix.link_to_service_hub)
  const [pattern, setPattern] = useState(matrix.service_hub_pattern || '/{service}/')
  const [home, setHome] = useState(matrix.link_to_home)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const dirty =
    hub !== matrix.link_to_service_hub ||
    home !== matrix.link_to_home ||
    (hub && (pattern.trim() || '/{service}/') !== (matrix.service_hub_pattern || '/{service}/'))

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      await matrixApi.update(clientId, matrix.id, {
        link_to_service_hub: hub,
        service_hub_pattern: hub ? (pattern.trim() || '/{service}/') : null,
        link_to_home: home,
      })
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save link settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div>
        <h3 style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Link2 size={15} /> Internal linking
        </h3>
        <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 0' }}>
          Pages always interlink with their siblings. They can also link <strong>up</strong> to the top-level service page and the home page.
          Changes apply to pages generated from now on.
        </p>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#334155' }}>
        <input type="checkbox" checked={hub} onChange={e => setHub(e.target.checked)} disabled={saving} />
        Link up to the top-level service page
      </label>
      {hub && (
        <div style={{ paddingLeft: 24 }}>
          <input style={{ ...input, maxWidth: 320 }} value={pattern} onChange={e => setPattern(e.target.value)} placeholder="/{service}/" disabled={saving} />
          <p style={{ fontSize: 12, color: '#94a3b8', margin: '4px 0 0' }}>
            Must contain <code>{'{service}'}</code>, no <code>{'{location}'}</code>. e.g. <code>/{'{service}'}/</code> → <code>/roof-restoration/</code>.
          </p>
        </div>
      )}
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#334155' }}>
        <input type="checkbox" checked={home} onChange={e => setHome(e.target.checked)} disabled={saving} />
        Link up to the home page (site root)
      </label>
      {error && <ErrorDetails message={error} />}
      <div>
        <button style={{ ...primaryBtn, opacity: dirty && !saving ? 1 : 0.5, cursor: dirty && !saving ? 'pointer' : 'not-allowed' }} disabled={!dirty || saving} onClick={save}>
          {saving ? <Spinner size={16} color="#fff" /> : <Link2 size={16} />} Save link settings
        </button>
      </div>
    </div>
  )
}
