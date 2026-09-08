import React, { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Share2, Image as ImageIcon, Video, X, Loader2, Send,
  Clock, ExternalLink, RefreshCw, ChevronDown, ChevronRight, Sparkles,
} from 'lucide-react'
import { api } from '../lib/api'
import { ErrorDetails } from '../components/ErrorDetails'

// ── types ────────────────────────────────────────────────────────────────────
interface Client { id: string; name: string }
interface SocialAccount {
  account_id: string
  platform: string
  handle: string | null
  reconnect_required: boolean
}
type PostStatus =
  | 'scheduled' | 'publishing' | 'published' | 'rejected' | 'failed' | 'blocked_account'
interface SocialPost {
  id: string
  platform: string
  account_id: string | null
  status: PostStatus
  status_detail: string | null
  post_url: string | null
  scheduled_at: string | null
  published_at: string | null
  created_at: string | null
}
interface UploadResult { url: string; type: string }

const TERMINAL: PostStatus[] = ['published', 'rejected', 'failed', 'blocked_account']

// Client-side hints only — the backend Platform Spec is the source of truth and
// returns a 422 on any real violation. Mirrors the seeded social_platform_specs
// for the platforms the backend enforces; the rest are advisory.
interface Spec {
  label: string; charLimit: number; maxImages: number; maxVideos: number
  requiresImage: boolean; note?: string; enforced: boolean
}
const SPECS: Record<string, Spec> = {
  twitter: { label: 'X (Twitter)', charLimit: 280, maxImages: 4, maxVideos: 1, requiresImage: false, note: 'A link in the post costs 50 credits vs 5.', enforced: true },
  facebook: { label: 'Facebook', charLimit: 63206, maxImages: 10, maxVideos: 1, requiresImage: false, enforced: true },
  instagram: { label: 'Instagram', charLimit: 2200, maxImages: 10, maxVideos: 1, requiresImage: true, note: 'Instagram requires at least one image or video.', enforced: true },
  pinterest: { label: 'Pinterest', charLimit: 500, maxImages: 1, maxVideos: 0, requiresImage: true, note: 'A pin requires exactly one image.', enforced: true },
  youtube: { label: 'YouTube', charLimit: 5000, maxImages: 0, maxVideos: 1, requiresImage: true, enforced: true },
  linkedin: { label: 'LinkedIn', charLimit: 3000, maxImages: 9, maxVideos: 1, requiresImage: false, enforced: false },
  tiktok: { label: 'TikTok', charLimit: 2200, maxImages: 0, maxVideos: 1, requiresImage: true, enforced: false },
  threads: { label: 'Threads', charLimit: 500, maxImages: 10, maxVideos: 1, requiresImage: false, enforced: false },
}
const specFor = (platform: string): Spec =>
  SPECS[(platform || '').toLowerCase()] ?? {
    label: platform || 'Platform', charLimit: 5000, maxImages: 10, maxVideos: 1,
    requiresImage: false, enforced: false,
  }

const MAX_UPLOAD_MB = 200 // mirrors settings.social_max_upload_mb
const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const VIDEO_TYPES = ['video/mp4', 'video/quicktime']

// ── styles ───────────────────────────────────────────────────────────────────
const btn = (bg: string, fg = '#fff'): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8,
  border: bg === '#fff' ? '1px solid #e2e8f0' : 'none', background: bg, color: fg,
  fontSize: 13, fontWeight: 600, cursor: 'pointer',
})
const card: React.CSSProperties = {
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, marginBottom: 20,
}
const input: React.CSSProperties = {
  width: '100%', padding: 9, borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13,
  fontFamily: 'inherit', boxSizing: 'border-box',
}
const label: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4, display: 'block' }

const STATUS_STYLE: Record<PostStatus, { bg: string; fg: string; label: string }> = {
  scheduled: { bg: '#eff6ff', fg: '#1d4ed8', label: 'Scheduled' },
  publishing: { bg: '#fffbeb', fg: '#b45309', label: 'Publishing…' },
  published: { bg: '#ecfdf5', fg: '#047857', label: 'Published' },
  rejected: { bg: '#fef2f2', fg: '#b91c1c', label: 'Rejected' },
  failed: { bg: '#fef2f2', fg: '#b91c1c', label: 'Failed' },
  blocked_account: { bg: '#fff7ed', fg: '#c2410c', label: 'Account needs reconnect' },
}

function StatusBadge({ status }: { status: PostStatus }) {
  const s = STATUS_STYLE[status] ?? { bg: '#f1f5f9', fg: '#475569', label: status }
  return (
    <span style={{ background: s.bg, color: s.fg, fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 999 }}>
      {s.label}
    </span>
  )
}

// ── media upload helper ──────────────────────────────────────────────────────
function validateFile(file: File, expect: 'image' | 'video'): string | null {
  const types = expect === 'image' ? IMAGE_TYPES : VIDEO_TYPES
  if (!types.includes(file.type)) {
    return `Unsupported ${expect} type (${file.type || 'unknown'}). Allowed: ${types.join(', ')}.`
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return `File is ${(file.size / 1024 / 1024).toFixed(0)} MB — over the ${MAX_UPLOAD_MB} MB limit.`
  }
  return null
}

// ── AI copy drafting panel ────────────────────────────────────────────────────
type SourceType = 'topic' | 'url' | 'blog_run' | 'local_seo_page'
interface RunListItem { id: string; keyword: string; title?: string | null }
interface PageListItem { id: string; keyword: string; location: string; page_title?: string | null }
interface DraftResult {
  copy: string
  voice_warnings: string[]
  spec_warnings: string[]
  notes: string[]
  source_title?: string | null
  over_limit: boolean
  char_count: number
  char_limit?: number | null
}

const SOURCE_LABELS: Record<SourceType, string> = {
  topic: 'Topic / notes', url: 'A web page (URL)', blog_run: 'A blog post', local_seo_page: 'A saved page',
}
const NOTE_TEXT: Record<string, string> = {
  no_source_content: 'The source had no readable content — the draft is based on the topic and brand voice only.',
  voice_uncorrected: 'A word from the client’s “never use” list is still present — review before publishing.',
}

function AiDraftPanel({
  clientId, platform, disabled, format, onDraft,
}: {
  clientId: string; platform: string; disabled: boolean; format: string
  onDraft: (copy: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [sourceType, setSourceType] = useState<SourceType>('topic')
  const [topic, setTopic] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [angle, setAngle] = useState('')
  const [tone, setTone] = useState('')
  const [result, setResult] = useState<DraftResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const runsQ = useQuery<{ data: RunListItem[] }>({
    queryKey: ['social-source-runs', clientId],
    queryFn: () => api.get<{ data: RunListItem[] }>(`/runs?client_id=${clientId}&content_type=blog_post&status=complete&page_size=50`),
    enabled: open && sourceType === 'blog_run',
  })
  const pagesQ = useQuery<PageListItem[]>({
    queryKey: ['social-source-pages', clientId],
    queryFn: () => api.get<PageListItem[]>(`/clients/${clientId}/local-seo/pages`),
    enabled: open && sourceType === 'local_seo_page',
  })

  const sourceReady =
    (sourceType === 'topic' && topic.trim().length > 0) ||
    (sourceType === 'url' && /^https?:\/\/\S+/.test(sourceUrl.trim())) ||
    ((sourceType === 'blog_run' || sourceType === 'local_seo_page') && Boolean(sourceId))

  const draftMut = useMutation({
    mutationFn: async () => {
      setError(null)
      return api.post<DraftResult>(`/clients/${clientId}/social/draft-copy`, {
        platform,
        source_type: sourceType,
        source_id: sourceType === 'blog_run' || sourceType === 'local_seo_page' ? sourceId : undefined,
        url: sourceType === 'url' ? sourceUrl.trim() : undefined,
        text: sourceType === 'topic' ? topic.trim() : undefined,
        angle: angle.trim() || undefined,
        tone: tone.trim() || undefined,
        format,
        include_hashtags: true,
      })
    },
    onSuccess: (r) => { setResult(r); onDraft(r.copy) },
    onError: (e) => setError(e instanceof Error ? e.message : 'social_copy_generation_failed'),
  })

  const canDraft = !disabled && sourceReady && !draftMut.isPending

  return (
    <div style={{ marginBottom: 14, border: '1px solid #e9d5ff', background: '#faf5ff', borderRadius: 10 }}>
      <button onClick={() => setOpen((o) => !o)}
        style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', background: 'none', border: 'none', cursor: 'pointer', color: '#7c3aed', fontSize: 13, fontWeight: 700 }}>
        <Sparkles size={15} /> Draft with AI
        <span style={{ marginLeft: 'auto' }}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
      </button>
      {open && (
        <div style={{ padding: '0 12px 12px' }}>
          {disabled && (
            <p style={{ margin: '0 0 10px', fontSize: 12, color: '#a16207' }}>
              Select a connected account first — the draft is written for that platform.
            </p>
          )}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
            <div style={{ flex: '1 1 200px' }}>
              <label style={label}>Draft from</label>
              <select style={input} value={sourceType}
                onChange={(e) => { setSourceType(e.target.value as SourceType); setSourceId(''); setResult(null) }}>
                {(Object.keys(SOURCE_LABELS) as SourceType[]).map((k) => (
                  <option key={k} value={k}>{SOURCE_LABELS[k]}</option>
                ))}
              </select>
            </div>
          </div>

          {sourceType === 'topic' && (
            <textarea style={{ ...input, minHeight: 60, resize: 'vertical', marginBottom: 10 }}
              value={topic} onChange={(e) => setTopic(e.target.value)}
              placeholder="What's the post about? A few notes, an announcement, a promotion angle…" />
          )}
          {sourceType === 'url' && (
            <input style={{ ...input, marginBottom: 10 }} value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="https://example.com/blog/post-to-repurpose" />
          )}
          {sourceType === 'blog_run' && (
            <select style={{ ...input, marginBottom: 10 }} value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
              <option value="">{runsQ.isLoading ? 'Loading blog posts…' : 'Choose a completed blog post…'}</option>
              {(runsQ.data?.data ?? []).map((r) => (
                <option key={r.id} value={r.id}>{r.title || r.keyword}</option>
              ))}
            </select>
          )}
          {sourceType === 'local_seo_page' && (
            <select style={{ ...input, marginBottom: 10 }} value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
              <option value="">{pagesQ.isLoading ? 'Loading pages…' : 'Choose a saved page…'}</option>
              {(pagesQ.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.page_title || `${p.keyword} — ${p.location}`}</option>
              ))}
            </select>
          )}
          {((sourceType === 'blog_run' && !runsQ.isLoading && (runsQ.data?.data ?? []).length === 0) ||
            (sourceType === 'local_seo_page' && !pagesQ.isLoading && (pagesQ.data ?? []).length === 0)) && (
            <p style={{ margin: '-4px 0 10px', fontSize: 12, color: '#94a3b8' }}>
              No {sourceType === 'blog_run' ? 'completed blog posts' : 'saved pages'} for this client yet.
            </p>
          )}

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
            <div style={{ flex: '1 1 180px' }}>
              <label style={label}>Angle / hook <span style={{ color: '#94a3b8', fontWeight: 400 }}>(optional)</span></label>
              <input style={input} value={angle} onChange={(e) => setAngle(e.target.value)}
                placeholder="e.g. lead with the biggest benefit" />
            </div>
            <div style={{ flex: '1 1 140px' }}>
              <label style={label}>Tone <span style={{ color: '#94a3b8', fontWeight: 400 }}>(optional)</span></label>
              <input style={input} value={tone} onChange={(e) => setTone(e.target.value)}
                placeholder="e.g. upbeat, expert" />
            </div>
          </div>

          <button disabled={!canDraft} onClick={() => draftMut.mutate()}
            style={{ ...btn(canDraft ? '#7c3aed' : '#ddd6fe'), cursor: canDraft ? 'pointer' : 'not-allowed' }}>
            {draftMut.isPending ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
            {draftMut.isPending ? 'Drafting…' : result ? 'Redraft' : 'Draft with AI'}
          </button>
          {result && !draftMut.isPending && (
            <span style={{ marginLeft: 10, fontSize: 12, color: '#059669', fontWeight: 600 }}>
              Draft added to the copy box below — edit it before publishing.
            </span>
          )}

          {(result?.notes?.length || result?.voice_warnings?.length) ? (
            <ul style={{ margin: '10px 0 0', padding: '8px 10px 8px 26px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, color: '#92400e', fontSize: 12 }}>
              {(result?.notes ?? []).map((n) => <li key={n}>{NOTE_TEXT[n] ?? n}</li>)}
              {(result?.voice_warnings ?? []).map((w) => (
                <li key={w}>Still contains a discouraged term ({w.replace('forbidden_term:', '')}).</li>
              ))}
            </ul>
          ) : null}
          {error && <div style={{ marginTop: 10 }}><ErrorDetails message={error} /></div>}
        </div>
      )}
    </div>
  )
}

// ── page ─────────────────────────────────────────────────────────────────────
export function SocialCompose() {
  const { id } = useParams<{ id: string }>()
  const clientId = id as string
  const qc = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const accountsQ = useQuery<SocialAccount[]>({
    queryKey: ['social-accounts', clientId],
    queryFn: () => api.get<SocialAccount[]>(`/clients/${clientId}/social/accounts`),
    enabled: Boolean(clientId),
  })

  const postsQ = useQuery<SocialPost[]>({
    queryKey: ['social-posts', clientId],
    queryFn: () => api.get<SocialPost[]>(`/clients/${clientId}/social/posts`),
    enabled: Boolean(clientId),
    // Poll while anything is still in flight (scheduled/publishing).
    refetchInterval: (q) => {
      const rows = (q.state.data as SocialPost[] | undefined) ?? []
      return rows.some((p) => !TERMINAL.includes(p.status)) ? 5000 : false
    },
  })

  const accounts = accountsQ.data ?? []
  const [accountId, setAccountId] = useState<string>('')
  const selected = accounts.find((a) => a.account_id === accountId) ?? accounts[0]
  const platform = selected?.platform ?? ''
  const spec = specFor(platform)

  const [copy, setCopy] = useState('')
  const [images, setImages] = useState<string[]>([])
  const [video, setVideo] = useState<string | null>(null)
  const [format, setFormat] = useState('feed')
  const [scheduleMode, setScheduleMode] = useState<'now' | 'later'>('now')
  const [scheduledLocal, setScheduledLocal] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [platformSpecificText, setPlatformSpecificText] = useState('')

  const [uploadingImage, setUploadingImage] = useState(false)
  const [uploadingVideo, setUploadingVideo] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [publishError, setPublishError] = useState<string | null>(null)

  // Default the account selection once accounts load.
  React.useEffect(() => {
    if (!accountId && accounts.length) setAccountId(accounts[0].account_id)
  }, [accounts, accountId])

  async function uploadFiles(files: FileList, expect: 'image' | 'video') {
    setUploadError(null)
    const list = Array.from(files)
    const setBusy = expect === 'image' ? setUploadingImage : setUploadingVideo
    setBusy(true)
    try {
      for (const file of list) {
        const bad = validateFile(file, expect)
        if (bad) { setUploadError(bad); continue }
        const form = new FormData()
        form.append('file', file)
        const res = await api.upload<UploadResult>(`/clients/${clientId}/social/media`, form)
        if (res.type === 'video') setVideo(res.url)
        else setImages((prev) => [...prev, res.url])
      }
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'upload_failed')
    } finally {
      setBusy(false)
    }
  }

  // Client-side advisory hints (backend still enforces).
  const hints = useMemo(() => {
    const out: string[] = []
    const hasMedia = images.length > 0 || Boolean(video)
    if (!copy.trim() && !hasMedia) out.push('Add some copy or media — an empty post can’t publish.')
    if (spec.charLimit && copy.length > spec.charLimit)
      out.push(`Copy is ${copy.length} / ${spec.charLimit} characters — over the ${spec.label} limit.`)
    if (spec.requiresImage && !hasMedia) out.push(spec.note ?? `${spec.label} requires at least one image or video.`)
    if (spec.maxImages != null && images.length > spec.maxImages)
      out.push(`${images.length} images — ${spec.label} allows at most ${spec.maxImages}.`)
    if (video && spec.maxVideos === 0) out.push(`${spec.label} doesn’t support video.`)
    return out
  }, [copy, images, video, spec])

  const warnings = useMemo(() => {
    const out: string[] = []
    if ((platform === 'twitter' || platform === 'x') && /https?:\/\//.test(copy))
      out.push('This X post contains a link — it will cost 50 credits instead of 5.')
    return out
  }, [platform, copy])

  const canPublish =
    Boolean(selected) &&
    !uploadingImage && !uploadingVideo &&
    (copy.trim().length > 0 || images.length > 0 || Boolean(video)) &&
    hints.length === 0 &&
    (scheduleMode === 'now' || Boolean(scheduledLocal))

  const publishMut = useMutation({
    mutationFn: async () => {
      setPublishError(null)
      let platform_specific: Record<string, unknown> | undefined
      if (platformSpecificText.trim()) {
        try { platform_specific = JSON.parse(platformSpecificText) } catch { throw new Error('platform_specific_invalid_json') }
      }
      let scheduled_at: string | undefined
      if (scheduleMode === 'later' && scheduledLocal) {
        const dt = new Date(scheduledLocal)
        if (isNaN(dt.getTime())) throw new Error('scheduled_invalid')
        if (dt.getTime() <= Date.now()) throw new Error('scheduled_in_past')
        scheduled_at = dt.toISOString()
      }
      return api.post<SocialPost>(`/clients/${clientId}/social/posts`, {
        platform,
        account_id: selected!.account_id,
        copy,
        image_urls: images,
        video_urls: video ? [video] : [],
        platform_specific,
        format,
        scheduled_at,
      })
    },
    onSuccess: () => {
      setCopy(''); setImages([]); setVideo(null); setPlatformSpecificText('')
      setScheduleMode('now'); setScheduledLocal(''); setFormat('feed')
      void qc.invalidateQueries({ queryKey: ['social-posts', clientId] })
    },
    onError: (e) => setPublishError(e instanceof Error ? e.message : 'publish_failed'),
  })

  return (
    <div style={{ maxWidth: 780, margin: '0 auto', padding: '24px 16px' }}>
      <Link to={`/clients/${clientId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 13, textDecoration: 'none', marginBottom: 16 }}>
        <ArrowLeft size={15} /> {client?.name ?? 'Client'} workspace
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
        <div style={{ background: '#eef2ff', color: '#4f46e5', width: 40, height: 40, borderRadius: 10, display: 'grid', placeItems: 'center' }}>
          <Share2 size={20} />
        </div>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: '#0f172a' }}>Social Media</h1>
          <p style={{ margin: 0, fontSize: 13, color: '#64748b' }}>Compose and publish a post for {client?.name ?? 'this client'}.</p>
        </div>
      </div>

      {/* Accounts state */}
      {accountsQ.isLoading && (
        <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 8, color: '#64748b' }}>
          <Loader2 size={16} className="spin" /> Loading connected accounts…
        </div>
      )}
      {accountsQ.isError && (
        <ErrorDetails message={accountsQ.error instanceof Error ? accountsQ.error.message : 'accounts_load_failed'} />
      )}
      {!accountsQ.isLoading && !accountsQ.isError && accounts.length === 0 && (
        <div style={card}>
          <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>No connected accounts</h3>
          <p style={{ margin: 0, fontSize: 13, color: '#64748b' }}>
            This client has no social accounts connected yet. Accounts are connected manually in
            PostPeer (added to the client’s Social group), then they appear here automatically.
          </p>
        </div>
      )}

      {/* Compose */}
      {accounts.length > 0 && (
        <div style={card}>
          {/* account */}
          <div style={{ marginBottom: 14 }}>
            <label style={label}>Account</label>
            <select style={input} value={selected?.account_id ?? ''} onChange={(e) => setAccountId(e.target.value)}>
              {accounts.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {specFor(a.platform).label}{a.handle ? ` — ${a.handle}` : ''}{a.reconnect_required ? ' (reconnect needed)' : ''}
                </option>
              ))}
            </select>
            {selected?.reconnect_required && (
              <p style={{ margin: '6px 0 0', fontSize: 12, color: '#c2410c' }}>
                This account needs reconnecting in PostPeer before it can publish.
              </p>
            )}
          </div>

          {/* AI copy drafting */}
          <AiDraftPanel
            clientId={clientId}
            platform={platform}
            disabled={!selected}
            format={format}
            onDraft={(text) => setCopy(text)}
          />

          {/* copy */}
          <div style={{ marginBottom: 14 }}>
            <label style={label}>Post copy</label>
            <textarea
              style={{ ...input, minHeight: 120, resize: 'vertical' }}
              value={copy}
              onChange={(e) => setCopy(e.target.value)}
              placeholder={`Write your ${spec.label} post…`}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
              <span style={{ fontSize: 11, color: '#94a3b8' }}>{spec.note ?? ''}</span>
              <span style={{ fontSize: 11, fontWeight: 600, color: copy.length > spec.charLimit ? '#b91c1c' : '#94a3b8' }}>
                {copy.length.toLocaleString()} / {spec.charLimit.toLocaleString()}
              </span>
            </div>
          </div>

          {/* media */}
          <div style={{ marginBottom: 14 }}>
            <label style={label}>Media</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 10 }}>
              {images.map((url) => (
                <div key={url} style={{ position: 'relative', width: 84, height: 84 }}>
                  <img src={url} alt="" style={{ width: 84, height: 84, objectFit: 'cover', borderRadius: 8, border: '1px solid #e2e8f0' }} />
                  <button onClick={() => setImages((p) => p.filter((u) => u !== url))} title="Remove"
                    style={{ position: 'absolute', top: -8, right: -8, background: '#0f172a', color: '#fff', border: 'none', borderRadius: 999, width: 22, height: 22, cursor: 'pointer', display: 'grid', placeItems: 'center' }}>
                    <X size={13} />
                  </button>
                </div>
              ))}
              {video && (
                <div style={{ position: 'relative', width: 84, height: 84 }}>
                  <video src={video} style={{ width: 84, height: 84, objectFit: 'cover', borderRadius: 8, border: '1px solid #e2e8f0', background: '#000' }} muted />
                  <button onClick={() => setVideo(null)} title="Remove video"
                    style={{ position: 'absolute', top: -8, right: -8, background: '#0f172a', color: '#fff', border: 'none', borderRadius: 999, width: 22, height: 22, cursor: 'pointer', display: 'grid', placeItems: 'center' }}>
                    <X size={13} />
                  </button>
                </div>
              )}
            </div>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <label style={{ ...btn('#fff', '#334155'), cursor: uploadingImage ? 'wait' : 'pointer' }}>
                {uploadingImage ? <Loader2 size={14} className="spin" /> : <ImageIcon size={14} />}
                {uploadingImage ? 'Uploading…' : 'Add image(s)'}
                <input type="file" accept={IMAGE_TYPES.join(',')} multiple hidden disabled={uploadingImage}
                  onChange={(e) => { if (e.target.files?.length) void uploadFiles(e.target.files, 'image'); e.target.value = '' }} />
              </label>
              <label style={{ ...btn('#fff', '#334155'), cursor: uploadingVideo ? 'wait' : (spec.maxVideos === 0 ? 'not-allowed' : 'pointer'), opacity: spec.maxVideos === 0 ? 0.5 : 1 }}>
                {uploadingVideo ? <Loader2 size={14} className="spin" /> : <Video size={14} />}
                {uploadingVideo ? 'Uploading…' : 'Add video'}
                <input type="file" accept={VIDEO_TYPES.join(',')} hidden disabled={uploadingVideo || spec.maxVideos === 0}
                  onChange={(e) => { if (e.target.files?.length) void uploadFiles(e.target.files, 'video'); e.target.value = '' }} />
              </label>
            </div>
            <p style={{ margin: '6px 0 0', fontSize: 11, color: '#94a3b8' }}>
              Up to {MAX_UPLOAD_MB} MB per file. Images: JPG/PNG/WebP/GIF. Video: MP4/MOV (one per post).
            </p>
            {uploadError && <div style={{ marginTop: 8 }}><ErrorDetails message={uploadError} /></div>}
          </div>

          {/* format */}
          <div style={{ marginBottom: 14, maxWidth: 220 }}>
            <label style={label}>Format</label>
            <select style={input} value={format} onChange={(e) => setFormat(e.target.value)}>
              <option value="feed">Feed post</option>
              <option value="reel">Reel</option>
              <option value="story">Story</option>
            </select>
          </div>

          {/* schedule */}
          <div style={{ marginBottom: 14 }}>
            <label style={label}>When to publish</label>
            <div style={{ display: 'flex', gap: 16, marginBottom: scheduleMode === 'later' ? 8 : 0 }}>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                <input type="radio" checked={scheduleMode === 'now'} onChange={() => setScheduleMode('now')} /> Publish now
              </label>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                <input type="radio" checked={scheduleMode === 'later'} onChange={() => setScheduleMode('later')} /> Schedule for later
              </label>
            </div>
            {scheduleMode === 'later' && (
              <input type="datetime-local" style={{ ...input, maxWidth: 260 }} value={scheduledLocal}
                min={new Date(Date.now() + 60000).toISOString().slice(0, 16)}
                onChange={(e) => setScheduledLocal(e.target.value)} />
            )}
          </div>

          {/* advanced */}
          <div style={{ marginBottom: 14 }}>
            <button onClick={() => setAdvancedOpen((o) => !o)}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', color: '#64748b', fontSize: 12, fontWeight: 600, cursor: 'pointer', padding: 0 }}>
              {advancedOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Advanced — platform-specific options
            </button>
            {advancedOpen && (
              <div style={{ marginTop: 8 }}>
                <textarea style={{ ...input, minHeight: 80, fontFamily: 'monospace', fontSize: 12 }}
                  value={platformSpecificText}
                  onChange={(e) => setPlatformSpecificText(e.target.value)}
                  placeholder={'Optional JSON passed to the provider, e.g.\n{ "boardId": "123", "firstComment": "…" }'} />
                <p style={{ margin: '4px 0 0', fontSize: 11, color: '#94a3b8' }}>
                  Passed through verbatim as the provider’s platformSpecificData. Leave blank for none.
                </p>
              </div>
            )}
          </div>

          {/* hints / warnings */}
          {hints.length > 0 && (
            <ul style={{ margin: '0 0 12px', padding: '10px 12px 10px 28px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, color: '#991b1b', fontSize: 12 }}>
              {hints.map((h) => <li key={h}>{h}</li>)}
            </ul>
          )}
          {warnings.map((w) => (
            <div key={w} style={{ margin: '0 0 12px', padding: '10px 12px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, color: '#92400e', fontSize: 12 }}>{w}</div>
          ))}

          {/* publish */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button
              disabled={!canPublish || publishMut.isPending}
              onClick={() => publishMut.mutate()}
              style={{ ...btn(canPublish && !publishMut.isPending ? '#4f46e5' : '#c7d2fe'), cursor: canPublish && !publishMut.isPending ? 'pointer' : 'not-allowed' }}>
              {publishMut.isPending ? <Loader2 size={15} className="spin" /> : scheduleMode === 'later' ? <Clock size={15} /> : <Send size={15} />}
              {publishMut.isPending ? 'Submitting…' : scheduleMode === 'later' ? 'Schedule post' : 'Publish now'}
            </button>
            {publishMut.isSuccess && !publishMut.isPending && (
              <span style={{ fontSize: 13, color: '#047857', fontWeight: 600 }}>
                {scheduleMode === 'later' ? 'Scheduled.' : 'Submitted — publishing…'}
              </span>
            )}
          </div>
          {publishError && <div style={{ marginTop: 12 }}><ErrorDetails message={publishError} /></div>}
        </div>
      )}

      {/* Recent posts */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Recent posts</h3>
          <button onClick={() => void postsQ.refetch()} style={{ ...btn('#fff', '#334155'), padding: '6px 10px' }}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
        {postsQ.isLoading ? (
          <div style={{ color: '#64748b', fontSize: 13, display: 'flex', gap: 8, alignItems: 'center' }}>
            <Loader2 size={15} className="spin" /> Loading…
          </div>
        ) : (postsQ.data ?? []).length === 0 ? (
          <p style={{ margin: 0, fontSize: 13, color: '#94a3b8' }}>No posts yet.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(postsQ.data ?? []).map((p) => (
              <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px', border: '1px solid #f1f5f9', borderRadius: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{specFor(p.platform).label}</span>
                    <StatusBadge status={p.status} />
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8' }}>
                    {p.status === 'scheduled' && p.scheduled_at
                      ? `Scheduled for ${new Date(p.scheduled_at).toLocaleString()}`
                      : p.published_at
                        ? `Published ${new Date(p.published_at).toLocaleString()}`
                        : p.created_at
                          ? new Date(p.created_at).toLocaleString()
                          : ''}
                    {p.status_detail && (p.status === 'rejected' || p.status === 'failed') ? ` — ${p.status_detail}` : ''}
                  </div>
                </div>
                {p.post_url && (
                  <a href={p.post_url} target="_blank" rel="noreferrer" style={{ ...btn('#fff', '#334155'), padding: '6px 10px', textDecoration: 'none' }}>
                    <ExternalLink size={13} /> View
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
