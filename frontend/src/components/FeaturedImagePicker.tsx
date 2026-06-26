import { useRef, useState } from 'react'
import { ImagePlus, X, Loader2 } from 'lucide-react'
import { api } from '../lib/api'

/**
 * Featured/hero image picker for published content. Uploads the selected image
 * to the public wordpress_images bucket (POST /files/image) and hands the public
 * URL to `onChange`, which persists it on the run/page. On WordPress publish the
 * image becomes the post's featured image; on Google Docs it renders as a hero.
 */
export function FeaturedImagePicker({
  value,
  onChange,
  disabled,
}: {
  value: string | null
  onChange: (url: string | null) => Promise<void> | void
  disabled?: boolean
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handleSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await api.upload<{ url: string }>('/files/image', form)
      await onChange(res.url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'upload_failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemove() {
    setBusy(true)
    setError('')
    try {
      await onChange(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'remove_failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {value ? (
          <div style={{ position: 'relative' }}>
            <img
              src={value}
              alt="Featured"
              style={{ width: 96, height: 64, objectFit: 'cover', borderRadius: 6, border: '1px solid #e2e8f0', display: 'block' }}
            />
            {!disabled && (
              <button
                onClick={handleRemove}
                disabled={busy}
                title="Remove featured image"
                style={{
                  position: 'absolute', top: -7, right: -7, width: 18, height: 18, borderRadius: 9,
                  border: '1px solid #e2e8f0', background: '#fff', color: '#64748b', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0,
                }}
              >
                <X size={11} />
              </button>
            )}
          </div>
        ) : (
          <div
            style={{
              width: 96, height: 64, borderRadius: 6, border: '1px dashed #cbd5e1', background: '#f8fafc',
              display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8',
            }}
          >
            <ImagePlus size={18} />
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={disabled || busy}
            style={{
              display: 'flex', alignItems: 'center', gap: 5, padding: '6px 12px', background: '#fff',
              color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13,
              cursor: disabled || busy ? 'default' : 'pointer', opacity: disabled || busy ? 0.6 : 1,
            }}
          >
            {busy ? <Loader2 size={13} className="spin" /> : <ImagePlus size={13} />}
            {busy ? 'Uploading…' : value ? 'Replace featured image' : 'Add featured image'}
          </button>
          <span style={{ fontSize: 11, color: '#94a3b8' }}>JPG/PNG/WebP · WordPress featured image</span>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          onChange={handleSelect}
          style={{ display: 'none' }}
        />
      </div>
      {error && <span style={{ fontSize: 12, color: '#dc2626' }}>{error}</span>}
    </div>
  )
}
