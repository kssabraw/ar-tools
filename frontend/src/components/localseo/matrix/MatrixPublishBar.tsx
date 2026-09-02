import { useState } from 'react'
import { Send } from 'lucide-react'
import { ErrorDetails } from '../../ErrorDetails'
import { Spinner } from '../Spinner'
import { card, input, label, primaryBtn } from '../shared'
import { matrixApi } from './api'
import type { MatrixDetail } from './types'

interface Props {
  clientId: string
  matrix: MatrixDetail
  onStarted: () => void
}

const select: React.CSSProperties = { ...input, appearance: 'auto' as React.CSSProperties['appearance'] }

// "Publish all done cells" (plan §5.3): every generated-but-unpublished cell
// goes to one destination as one background job per cell. A blocked cell
// (brand-guide violation) is never swept up here — it gets its own "Publish
// anyway" in the grid, which is the same deliberate override the per-page
// Publish button offers.
export function MatrixPublishBar({ clientId, matrix, onStarted }: Props) {
  const [destination, setDestination] = useState<'google_docs' | 'wordpress' | 'github'>(matrix.publish_destination)
  const [status, setStatus] = useState<'draft' | 'publish'>(matrix.publish_status)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')

  const publishable = matrix.cells.filter(c => c.page_id && (c.status === 'done' || c.status === 'publish_failed'))
  const blocked = matrix.cells.filter(c => c.status === 'publish_blocked').length
  const publishing = matrix.cells.filter(c => c.status === 'publishing').length
  const published = matrix.cells.filter(c => c.status === 'published').length

  const start = async () => {
    if (!publishable.length || starting) return
    setStarting(true)
    setError('')
    try {
      await matrixApi.publish(clientId, matrix.id, { destination, status })
      onStarted()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start publishing')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}><Send size={15} /> Publish done cells</h3>
          <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 0' }}>
            {publishable.length} ready to publish · {published} published{publishing ? ` · ${publishing} publishing` : ''}{blocked ? ` · ${blocked} blocked by the brand guide (use “Publish anyway” on the cell)` : ''}
          </p>
        </div>
        <div style={{ width: 150 }}>
          <label style={label}>Destination</label>
          <select style={select} value={destination} onChange={e => setDestination(e.target.value as typeof destination)} disabled={starting}>
            <option value="google_docs">Google Docs</option>
            <option value="wordpress">WordPress</option>
            <option value="github">GitHub</option>
          </select>
        </div>
        <div style={{ width: 120 }}>
          <label style={label}>As</label>
          <select style={select} value={status} onChange={e => setStatus(e.target.value as typeof status)} disabled={starting}>
            <option value="draft">Draft</option>
            <option value="publish">Published</option>
          </select>
        </div>
        <button
          style={{ ...primaryBtn, opacity: publishable.length && !starting ? 1 : 0.5, cursor: publishable.length && !starting ? 'pointer' : 'not-allowed' }}
          disabled={!publishable.length || starting}
          onClick={start}
        >
          {starting ? <Spinner size={16} color="#fff" /> : <Send size={16} />} Publish {publishable.length || ''} now
        </button>
      </div>
      {error && <ErrorDetails message={error} />}
    </div>
  )
}
