import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { ClientAsset, ClientAssetKind, TrustBadge, TrustSignals } from '../lib/types'

/**
 * Trust & Proof editor (docs/modules/local-landing-page-structure.md).
 *
 * Edits the scalar/list `trust_signals` (certifications / affiliations /
 * financing partners / license number / founding year) that the Local SEO
 * writer renders in the deterministic Trust & Proof block, plus the media
 * gallery (client_assets — team/owner photo, branded vehicle, before/after,
 * video embed). Badge + asset images are uploaded through the generic
 * /files/logo public-image uploader; a video embed carries an external URL.
 *
 * The scalar/list half is controlled (value + onChange, saved with the client
 * form). The gallery is server-side per-asset and only available for an
 * existing client (needs a client id), so it saves immediately via its own API.
 */

export const EMPTY_TRUST_SIGNALS: TrustSignals = {
  certifications: [],
  affiliations: [],
  financing_partners: [],
  license_number: null,
  years_founded: null,
  founding_date: null,
}

const ASSET_KINDS: { value: ClientAssetKind; label: string }[] = [
  { value: 'team_photo', label: 'Team photo' },
  { value: 'owner_photo', label: 'Owner photo' },
  { value: 'vehicle', label: 'Branded vehicle' },
  { value: 'before_after', label: 'Before / after' },
  { value: 'video_embed', label: 'Video (embed URL)' },
  { value: 'other', label: 'Other' },
]

async function uploadImage(file: File): Promise<string> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await api.upload<{ logo_url: string }>('/files/logo', fd)
  return res.logo_url
}

function BadgeListEditor({
  label, hint, value, onChange,
}: {
  label: string
  hint: string
  value: TrustBadge[]
  onChange: (v: TrustBadge[]) => void
}) {
  const [uploadingIdx, setUploadingIdx] = useState<number | null>(null)
  const rows = value ?? []

  const update = (i: number, patch: Partial<TrustBadge>) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))

  return (
    <div style={{ marginBottom: 16 }}>
      <label style={labelStyle}>{label}</label>
      <p style={hintStyle}>{hint}</p>
      {rows.map((badge, i) => (
        <div key={i} style={rowStyle}>
          <input
            style={{ ...inputStyle, flex: 1 }}
            placeholder="Name (e.g. BBB Accredited)"
            value={badge.name}
            onChange={e => update(i, { name: e.target.value })}
          />
          {badge.logo_url ? (
            <img src={badge.logo_url} alt="" style={thumbStyle} />
          ) : null}
          <label style={{ ...smallBtnStyle, ...(uploadingIdx === i ? disabledBtn : {}) }}>
            {uploadingIdx === i ? '…' : badge.logo_url ? 'Replace logo' : 'Logo'}
            <input
              type="file"
              accept="image/png,image/jpeg,image/svg+xml,image/webp"
              style={{ display: 'none' }}
              disabled={uploadingIdx === i}
              onChange={async e => {
                const file = e.target.files?.[0]
                if (!file) return
                setUploadingIdx(i)
                try {
                  update(i, { logo_url: await uploadImage(file) })
                } catch { /* surfaced by the disabled state resetting */ }
                setUploadingIdx(null)
                e.target.value = ''
              }}
            />
          </label>
          <button type="button" style={removeBtnStyle} onClick={() => onChange(rows.filter((_, idx) => idx !== i))}>
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        style={addBtnStyle}
        onClick={() => onChange([...rows, { name: '', logo_url: '' }])}
      >
        + Add
      </button>
    </div>
  )
}

function MediaGallery({ clientId }: { clientId: string }) {
  const [assets, setAssets] = useState<ClientAsset[]>([])
  const [loading, setLoading] = useState(true)
  const [kind, setKind] = useState<ClientAssetKind>('team_photo')
  const [videoUrl, setVideoUrl] = useState('')
  const [caption, setCaption] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    try {
      setAssets(await api.get<ClientAsset[]>(`/clients/${clientId}/assets`))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [clientId])

  const addAsset = async (url: string) => {
    setBusy(true)
    setError(null)
    try {
      const created = await api.post<ClientAsset>(`/clients/${clientId}/assets`, {
        kind, url, caption: caption.trim() || null, sort_order: assets.length,
      })
      setAssets(a => [...a, created])
      setCaption('')
      setVideoUrl('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: string) => {
    try {
      await api.delete(`/clients/${clientId}/assets/${id}`)
      setAssets(a => a.filter(x => x.id !== id))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div style={{ marginTop: 8 }}>
      <label style={labelStyle}>Photo &amp; video gallery</label>
      <p style={hintStyle}>
        Team/owner photos, a branded vehicle, before/after shots, or a video embed URL.
        Rendered in the page's Trust &amp; Proof block. Never invented — only what you add here.
      </p>
      {loading ? (
        <p style={hintStyle}>Loading…</p>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 10 }}>
          {assets.map(a => (
            <div key={a.id} style={assetCardStyle}>
              {a.kind === 'video_embed'
                ? <div style={videoBadgeStyle}>▶ video</div>
                : <img src={a.url} alt={a.caption ?? ''} style={assetThumbStyle} />}
              <div style={{ fontSize: 11, color: '#64748b' }}>
                {ASSET_KINDS.find(k => k.value === a.kind)?.label ?? a.kind}
              </div>
              {a.caption ? <div style={{ fontSize: 11 }}>{a.caption}</div> : null}
              <button type="button" style={removeBtnStyle} onClick={() => remove(a.id)}>Remove</button>
            </div>
          ))}
          {assets.length === 0 && <p style={hintStyle}>No media added yet.</p>}
        </div>
      )}
      <div style={{ ...rowStyle, alignItems: 'flex-start' }}>
        <select style={{ ...inputStyle, width: 160 }} value={kind} onChange={e => setKind(e.target.value as ClientAssetKind)}>
          {ASSET_KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
        <input
          style={{ ...inputStyle, flex: 1 }}
          placeholder="Caption (optional)"
          value={caption}
          onChange={e => setCaption(e.target.value)}
        />
      </div>
      {kind === 'video_embed' ? (
        <div style={rowStyle}>
          <input
            style={{ ...inputStyle, flex: 1 }}
            placeholder="Embed URL (e.g. https://www.youtube.com/embed/…)"
            value={videoUrl}
            onChange={e => setVideoUrl(e.target.value)}
          />
          <button
            type="button"
            style={{ ...addBtnStyle, ...(busy || !videoUrl.trim() ? disabledBtn : {}) }}
            disabled={busy || !videoUrl.trim()}
            onClick={() => addAsset(videoUrl.trim())}
          >
            Add video
          </button>
        </div>
      ) : (
        <label style={{ ...smallBtnStyle, ...(busy ? disabledBtn : {}) }}>
          {busy ? 'Uploading…' : 'Upload image'}
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/svg+xml,image/webp"
            style={{ display: 'none' }}
            disabled={busy}
            onChange={async e => {
              const file = e.target.files?.[0]
              if (!file) return
              setBusy(true)
              setError(null)
              try {
                await addAsset(await uploadImage(file))
              } catch (err) {
                setError((err as Error).message)
              } finally {
                setBusy(false)
                if (fileRef.current) fileRef.current.value = ''
              }
            }}
          />
        </label>
      )}
      {error && <p style={{ ...hintStyle, color: '#dc2626' }}>{error}</p>}
    </div>
  )
}

export function TrustAndProofSection({
  value, onChange, clientId,
}: {
  value: TrustSignals
  onChange: (v: TrustSignals) => void
  clientId?: string
}) {
  const set = <K extends keyof TrustSignals>(key: K, v: TrustSignals[K]) => onChange({ ...value, [key]: v })

  return (
    <div>
      <BadgeListEditor
        label="Certifications & accreditations"
        hint="BBB, Google Guaranteed, licensing bodies, trade certifications — a name and (optionally) a logo image."
        value={value.certifications}
        onChange={v => set('certifications', v)}
      />
      <BadgeListEditor
        label="Trade associations & affiliations"
        hint="Industry/association memberships shown as trust badges."
        value={value.affiliations}
        onChange={v => set('affiliations', v)}
      />
      <BadgeListEditor
        label="Financing partners"
        hint="Financing providers (e.g. Wisetack, Synchrony) shown as partner logos."
        value={value.financing_partners}
        onChange={v => set('financing_partners', v)}
      />

      <div style={rowStyle}>
        <div style={{ flex: 1 }}>
          <label style={labelStyle}>License number</label>
          <input
            style={inputStyle}
            placeholder="e.g. CCC1234567"
            value={value.license_number ?? ''}
            onChange={e => set('license_number', e.target.value.trim() || null)}
          />
        </div>
        <div style={{ width: 140 }}>
          <label style={labelStyle}>Founded (year)</label>
          <input
            style={inputStyle}
            type="number"
            placeholder="1998"
            value={value.years_founded ?? ''}
            onChange={e => set('years_founded', e.target.value ? Number(e.target.value) : null)}
          />
        </div>
        <div style={{ width: 180 }}>
          <label style={labelStyle}>Founding date (label)</label>
          <input
            style={inputStyle}
            placeholder='e.g. "since 1998"'
            value={value.founding_date ?? ''}
            onChange={e => set('founding_date', e.target.value.trim() || null)}
          />
        </div>
      </div>

      {clientId
        ? <MediaGallery clientId={clientId} />
        : <p style={hintStyle}>Save the client first to add a photo/video gallery.</p>}
    </div>
  )
}

const labelStyle: React.CSSProperties = { display: 'block', fontSize: 13, fontWeight: 600, color: '#334155', marginBottom: 4 }
const hintStyle: React.CSSProperties = { fontSize: 12, color: '#64748b', margin: '2px 0 8px' }
const inputStyle: React.CSSProperties = { width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 14, boxSizing: 'border-box' }
const rowStyle: React.CSSProperties = { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }
const smallBtnStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', padding: '7px 12px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#f8fafc', fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap' }
const addBtnStyle: React.CSSProperties = { ...smallBtnStyle, borderColor: '#3b82f6', color: '#2563eb', background: '#eff6ff' }
const removeBtnStyle: React.CSSProperties = { ...smallBtnStyle, borderColor: '#fca5a5', color: '#dc2626', background: '#fef2f2' }
const disabledBtn: React.CSSProperties = { opacity: 0.6, cursor: 'default', pointerEvents: 'none' }
const thumbStyle: React.CSSProperties = { width: 32, height: 32, objectFit: 'contain', borderRadius: 6, border: '1px solid #e2e8f0' }
const assetCardStyle: React.CSSProperties = { width: 130, padding: 8, borderRadius: 10, border: '1px solid #e2e8f0', background: '#fff', display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }
const assetThumbStyle: React.CSSProperties = { width: '100%', height: 72, objectFit: 'cover', borderRadius: 6, border: '1px solid #e2e8f0' }
const videoBadgeStyle: React.CSSProperties = { width: '100%', height: 72, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 6, background: '#0f172a', color: '#fff', fontSize: 13 }
