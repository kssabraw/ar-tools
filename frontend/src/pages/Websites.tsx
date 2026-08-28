import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Globe, Loader2, Plus, RotateCcw, Trash2, X } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { ACCENT, Chip, btn, card, input, label } from '../components/website/shared'
import type { DeployStatus, SiteType, Website } from '../components/website/shared'

// The fleet view (PRD §6.1). Every other module in the suite is purely
// client-scoped, and that is right for them — you pick a client, then work.
// This module is the exception because its unit of management is the *fleet*:
// "what's live", "what failed to deploy last night", "how many shipped this
// month" are none of them answerable from inside one client's workspace, and
// §7's throughput metrics are read straight off this screen.
//
// Deliberately read-only. Rows link into the client's workspace card, which is
// where work happens; the only actions here are on the Trash.

interface FleetSite extends Website {
  client_name: string
  client_kind: string
  last_deploy: { status: DeployStatus; created_at: string; url: string | null } | null
}

export function Websites() {
  const qc = useQueryClient()
  const { isStaff } = useAuth()
  const [view, setView] = useState<'active' | 'trash'>('active')
  const [filter, setFilter] = useState('')
  const [creating, setCreating] = useState(false)

  const { data: status } = useQuery<{ enabled: boolean }>({
    queryKey: ['website-status'],
    queryFn: () => api.get<{ enabled: boolean }>('/websites/status'),
    staleTime: 5 * 60_000,
  })

  const { data, isLoading } = useQuery<{ websites: FleetSite[] }>({
    queryKey: ['websites-fleet', view],
    queryFn: () => api.get<{ websites: FleetSite[] }>(
      `/websites${view === 'trash' ? '?include_deleted=true' : ''}`,
    ),
    enabled: status?.enabled === true,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['websites-fleet'] })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/websites/${id}`),
    onSuccess: invalidate,
  })
  const restore = useMutation({
    mutationFn: (id: string) => api.post(`/websites/${id}/restore`, {}),
    onSuccess: invalidate,
  })

  const sites = useMemo(() => {
    const rows = data?.websites ?? []
    const q = filter.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((s) =>
      [s.name, s.client_name, s.custom_domain, s.status].some((v) => (v ?? '').toLowerCase().includes(q)),
    )
  }, [data, filter])

  // §7 metrics 1-4 are read off this screen; these are the two it can compute
  // from the list alone without another round trip.
  const liveCount = (data?.websites ?? []).filter((s) => s.status === 'live').length
  const withDomain = (data?.websites ?? []).filter((s) => s.domain_status === 'active').length
  const failedDeploys = (data?.websites ?? []).filter((s) => s.last_deploy?.status === 'failed').length

  if (status && !status.enabled) {
    return (
      <Shell>
        <div style={{ ...card, fontSize: 13, color: '#64748b' }}>
          <strong style={{ color: '#0f172a' }}>The Website Builder is switched off.</strong>
          <p style={{ margin: '6px 0 0' }}>
            It ships dark behind <code>website_builder_enabled</code>. While that is unset the
            backend refuses every call, so no site can be created by accident. An admin turns
            it on from the platform's environment settings.
          </p>
        </div>
      </Shell>
    )
  }

  return (
    <Shell>
      {view === 'active' && (data?.websites ?? []).length > 0 && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
          <Stat label="Live" value={liveCount} />
          <Stat label="On a custom domain" value={withDomain} />
          <Stat label="Last deploy failed" value={failedDeploys} tone={failedDeploys > 0 ? 'bad' : undefined} />
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14, flexWrap: 'wrap' }}>
        {(['active', 'trash'] as const).map((v) => (
          <button key={v} onClick={() => setView(v)}
            style={{
              ...btn(view === v ? ACCENT : '#fff', view === v ? '#fff' : '#64748b'),
              textTransform: 'capitalize',
            }}>
            {v}
          </button>
        ))}
        {isStaff && view === 'active' && (
          <button onClick={() => setCreating(true)}
                  title="Create a site with no client — an agency-owned property (rank-and-rent, PBN, or a niche site)."
                  style={btn(ACCENT, '#fff')}>
            <Plus size={14} /> New site
          </button>
        )}
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by site, client, domain or status"
          style={{ flex: 1, minWidth: 220, padding: 9, borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}
        />
      </div>

      {creating && <NewSiteModal onClose={() => setCreating(false)} />}

      {view === 'trash' && (
        <p style={{ fontSize: 12, color: '#64748b', marginTop: 0 }}>
          Deleting a site removes it from these lists and nothing else — the repository, the
          Worker, the domain and the live site are all untouched. Restoring is a flag clear;
          nothing is re-provisioned.
        </p>
      )}

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      ) : sites.length === 0 ? (
        <div style={{ ...card, color: '#64748b', fontSize: 13 }}>
          {view === 'trash'
            ? 'Nothing in the trash.'
            : 'No sites yet. Use “New site” for a standalone property (rank-and-rent, PBN, niche), or open a client and use the Website Builder card for a client site.'}
        </div>
      ) : (
        <div style={card}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: '#64748b' }}>
                <th style={th}>Site</th><th style={th}>Client</th><th style={th}>Status</th>
                <th style={th}>Domain</th><th style={th}>Last deploy</th><th style={th} />
              </tr>
            </thead>
            <tbody>
              {sites.map((s) => (
                <tr key={s.id} style={{ borderTop: '1px solid #f1f5f9' }}>
                  <td style={td}>
                    <strong style={{ color: '#0f172a' }}>{s.name}</strong>
                    <div style={{ color: '#94a3b8' }}>{s.site_type.replace(/_/g, ' ')}</div>
                  </td>
                  <td style={td}>
                    {s.client_name}
                    {s.client_kind === 'owned_property' && (
                      <div style={{ color: '#7c3aed', fontSize: 11 }}>owned property</div>
                    )}
                  </td>
                  <td style={td}><Chip status={s.status} /></td>
                  <td style={td}>
                    {s.custom_domain
                      ? <>{s.custom_domain}<div style={{ color: '#94a3b8' }}>{s.domain_status.replace(/_/g, ' ')}</div></>
                      : <span style={{ color: '#94a3b8' }}>staging only</span>}
                  </td>
                  <td style={td}>
                    {s.last_deploy
                      ? <><Chip status={s.last_deploy.status} />
                          <div style={{ color: '#94a3b8' }}>{new Date(s.last_deploy.created_at).toLocaleDateString()}</div></>
                      : <span style={{ color: '#94a3b8' }}>none</span>}
                  </td>
                  <td style={{ ...td, textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {view === 'active' ? (
                      <>
                        <Link to={`/clients/${s.client_id}/website`}
                              style={{ color: ACCENT, display: 'inline-flex', alignItems: 'center', gap: 4, marginRight: 10 }}>
                          Open <ArrowRight size={12} />
                        </Link>
                        {isStaff && (
                          <button onClick={() => remove.mutate(s.id)}
                                  title="Removes it from these lists only — the repo and the live site are untouched."
                                  style={{ ...btn('#fff', '#b91c1c'), padding: '5px 8px' }}>
                            <Trash2 size={12} />
                          </button>
                        )}
                      </>
                    ) : (
                      isStaff && (
                        <button onClick={() => restore.mutate(s.id)} style={{ ...btn('#fff', ACCENT), padding: '5px 8px' }}>
                          <RotateCcw size={12} /> Restore
                        </button>
                      )
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Shell>
  )
}

const SITE_TYPES: { value: SiteType; label: string; hint: string }[] = [
  { value: 'local_business', label: 'Local business', hint: 'Services × cities — a rank-and-rent local site.' },
  { value: 'informational', label: 'Informational / niche', hint: 'A content site — e.g. a PBN or niche property.' },
  { value: 'lead_gen', label: 'Lead-gen', hint: 'An owned lead-gen property.' },
]

// Create a standalone site — one with no external client. It still has a business
// identity (name, city, brand voice), which is captured here and stored on a
// hidden owned-property record so every generator works unchanged. On success we
// drop into the normal builder workspace for the new site.
function NewSiteModal({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [siteType, setSiteType] = useState<SiteType>('local_business')
  const [businessName, setBusinessName] = useState('')
  const [businessCity, setBusinessCity] = useState('')
  const [websiteUrl, setWebsiteUrl] = useState('')
  const [brandVoice, setBrandVoice] = useState('')
  const [showMore, setShowMore] = useState(false)

  const create = useMutation({
    mutationFn: () => api.post<{ client_id: string }>('/websites', {
      name: name.trim(),
      site_type: siteType,
      business_name: businessName.trim() || undefined,
      business_city: businessCity.trim() || undefined,
      website_url: websiteUrl.trim() || undefined,
      brand_voice: brandVoice.trim() || undefined,
    }),
    onSuccess: (res) => { onClose(); navigate(`/clients/${res.client_id}/website`) },
  })

  const typeDef = SITE_TYPES.find((t) => t.value === siteType) as (typeof SITE_TYPES)[number]

  return (
    <div onClick={onClose} style={overlay}>
      <div onClick={(e) => e.stopPropagation()} style={{ ...card, width: 480, maxWidth: '92vw', maxHeight: '86vh', overflowY: 'auto', display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <strong style={{ fontSize: 15 }}>New standalone site</strong>
          <button onClick={onClose} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={15} /></button>
        </div>
        <p style={{ margin: 0, fontSize: 12, color: '#64748b' }}>
          A site with no client — an agency-owned property. It gets its own business identity
          (kept out of your client lists). You can refine the brand voice later on the site’s
          Settings tab.
        </p>

        <div>
          <label style={label}>Site name</label>
          <input style={input} value={name} onChange={(e) => setName(e.target.value)}
                 placeholder="Seattle Tree Pros (internal label)" />
        </div>

        <div>
          <label style={label}>Site type</label>
          <select value={siteType} onChange={(e) => setSiteType(e.target.value as SiteType)} style={{ ...input, cursor: 'pointer' }}>
            {SITE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>{typeDef.hint}</div>
        </div>

        <div>
          <label style={label}>Business name <span style={{ color: '#94a3b8', fontWeight: 400 }}>(public)</span></label>
          <input style={input} value={businessName} onChange={(e) => setBusinessName(e.target.value)}
                 placeholder="Defaults to the site name" />
        </div>

        <div>
          <label style={label}>Brand voice / guide</label>
          <textarea value={brandVoice} onChange={(e) => setBrandVoice(e.target.value)} rows={3}
                    placeholder="How the business should sound (needed to generate content — can be added later)."
                    style={{ ...input, resize: 'vertical' }} />
        </div>

        <button onClick={() => setShowMore((s) => !s)} style={{ ...btn('#fff', '#64748b'), justifySelf: 'start', padding: '4px 8px', fontSize: 12 }}>
          {showMore ? 'Hide' : 'Show'} optional
        </button>
        {showMore && (
          <div style={{ display: 'grid', gap: 10, padding: 12, background: '#f8fafc', borderRadius: 8 }}>
            <div>
              <label style={label}>City</label>
              <input style={input} value={businessCity} onChange={(e) => setBusinessCity(e.target.value)}
                     placeholder="Seattle" />
            </div>
            <div>
              <label style={label}>Website URL</label>
              <input style={input} value={websiteUrl} onChange={(e) => setWebsiteUrl(e.target.value)}
                     placeholder="https://… — if the site is live, we’ll scan its voice" />
            </div>
          </div>
        )}

        {create.error && (
          <div style={{ padding: 9, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
            {(create.error as Error).message}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onClose} style={btn('#fff', '#64748b')}>Cancel</button>
          <button onClick={() => create.mutate()} disabled={!name.trim() || create.isPending}
                  style={btn(!name.trim() ? '#e2e8f0' : ACCENT, !name.trim() ? '#94a3b8' : '#fff')}>
            {create.isPending ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Create site
          </button>
        </div>
      </div>
    </div>
  )
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 50, padding: 16,
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <Globe size={22} color={ACCENT} />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Websites</h1>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', marginTop: 0, marginBottom: 20 }}>
        Every site across every client. Open one to plan, generate and publish — the work
        happens in that client's workspace.
      </p>
      {children}
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'bad' }) {
  return (
    <div style={{ ...card, padding: '10px 14px', minWidth: 130 }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: tone === 'bad' && value > 0 ? '#b91c1c' : '#0f172a' }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: '#64748b' }}>{label}</div>
    </div>
  )
}

const th: React.CSSProperties = { padding: '6px 8px', fontWeight: 600 }
const td: React.CSSProperties = { padding: '8px', verticalAlign: 'top' }
