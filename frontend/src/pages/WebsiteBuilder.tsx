import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Globe, Loader2, Plus } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import { useAuth } from '../context/AuthContext'
import { FreezeBanner } from '../components/FreezeBanner'
import { ACCENT, btn, card, denyReason, input, label } from '../components/website/shared'
import type { Deploy, PlanResponse, SiteType, Website, WebsitePage } from '../components/website/shared'
import { OverviewTab } from '../components/website/OverviewTab'
import { PlanTab } from '../components/website/PlanTab'
import { PagesTab } from '../components/website/PagesTab'
import { DeploysTab } from '../components/website/DeploysTab'

// Website Builder — the per-client work surface (PRD §6.1).
//
// "Publish" in this module means committing a generated page into the site's
// private GitHub repo; the repo builds and deploys itself. The copy throughout
// says so, because the word means something else everywhere else in the suite.
//
// The whole module is gated on website_builder_enabled: while it is off, every
// backend route 503s, so this page renders a plain notice rather than a screen
// of dead buttons.

type Tab = 'overview' | 'plan' | 'pages' | 'deploys'
const TABS: Tab[] = ['overview', 'plan', 'pages', 'deploys']

const SITE_TYPES: { value: SiteType; label: string; hint: string }[] = [
  { value: 'local_business', label: 'Local business', hint: 'Service pages, city pages and the service × city matrix.' },
  { value: 'informational', label: 'Informational', hint: 'A content property — posts, categories, archive.' },
  { value: 'lead_gen', label: 'Lead generation', hint: 'Agency-owned. No business schema, no NAP, no trust badges.' },
]

export function WebsiteBuilder() {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()
  const { isAdmin, isStaff } = useAuth()
  const [tab, setTab] = useState<Tab>('overview')

  const { data: status, isLoading: statusLoading } = useQuery<{ enabled: boolean }>({
    queryKey: ['website-status'],
    queryFn: () => api.get<{ enabled: boolean }>('/websites/status'),
    staleTime: 5 * 60_000,
  })
  const enabled = status?.enabled ?? false

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  const { data: list, isLoading: listLoading } = useQuery<{ websites: Website[] }>({
    queryKey: ['websites', id],
    queryFn: () => api.get<{ websites: Website[] }>(`/clients/${id}/websites`),
    enabled: Boolean(id) && enabled,
  })
  const site = list?.websites?.[0]

  const { data: detail } = useQuery<{ website: Website; pages: WebsitePage[]; deploys: Deploy[] }>({
    queryKey: ['website', site?.id],
    queryFn: () => api.get(`/websites/${site!.id}`),
    enabled: Boolean(site?.id),
    // Provisioning and deploys resolve server-side; refresh while either is in
    // flight so the step machine and the deploy chips move without a reload.
    refetchInterval: (q) => {
      const d = q.state.data as { website?: Website; deploys?: Deploy[] } | undefined
      const busy = d?.website?.status === 'provisioning'
        || (d?.deploys ?? []).some((x) => ['queued', 'building'].includes(x.status))
      return busy ? 5000 : false
    },
  })

  const { data: plan } = useQuery<PlanResponse>({
    queryKey: ['website-plan', site?.id],
    queryFn: () => api.get<PlanResponse>(`/websites/${site!.id}/plan`),
    enabled: Boolean(site?.id),
  })

  // A frozen client's content output is paused everywhere (Freeze Protocol), so
  // every write action here disables with that reason rather than failing at the
  // router with a 409 the user has to decode.
  const { data: freeze } = useQuery<{ active: unknown | null }>({
    queryKey: ['freeze', id],
    queryFn: () => api.get<{ active: unknown | null }>(`/clients/${id}/freeze`),
    enabled: Boolean(id),
  })
  const perms = { isStaff, isAdmin, frozen: Boolean(freeze?.active) }

  // A client with a site opens on Overview; one without gets the empty state.
  useEffect(() => { if (!site) setTab('overview') }, [site])

  if (statusLoading) return <Shell clientId={id}><Loading /></Shell>
  if (!enabled) {
    return (
      <Shell clientId={id} clientName={client?.name}>
        <div style={{ ...card, fontSize: 13, color: '#64748b' }}>
          <strong style={{ color: '#0f172a' }}>The Website Builder is switched off.</strong>
          <p style={{ margin: '6px 0 0' }}>
            It ships dark behind <code>website_builder_enabled</code>. While that is unset the
            backend refuses every call, so nothing here can create a repository by accident.
            An admin turns it on from the platform's environment settings.
          </p>
        </div>
      </Shell>
    )
  }

  return (
    <Shell clientId={id} clientName={client?.name}>
      {id && <FreezeBanner clientId={id} />}

      {listLoading ? (
        <Loading />
      ) : !site ? (
        <CreateSite clientId={id!} perms={perms} onCreated={() => qc.invalidateQueries({ queryKey: ['websites', id] })} />
      ) : (
        <>
          <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid #e2e8f0' }}>
            {TABS.map((t) => (
              <button key={t} onClick={() => setTab(t)}
                style={{
                  padding: '9px 16px', border: 'none', background: 'none', cursor: 'pointer',
                  borderBottom: tab === t ? `2px solid ${ACCENT}` : '2px solid transparent',
                  color: tab === t ? ACCENT : '#64748b', fontSize: 13, fontWeight: 600,
                  textTransform: 'capitalize',
                }}>
                {t}
              </button>
            ))}
          </div>

          {tab === 'overview' && (
            <OverviewTab
              website={detail?.website ?? site}
              deploys={detail?.deploys ?? []}
              pageCount={detail?.pages.length ?? 0}
              publishedCount={(detail?.pages ?? []).filter((p) => p.status === 'published').length}
              perms={perms}
            />
          )}
          {tab === 'plan' && <PlanTab website={detail?.website ?? site} plan={plan} perms={perms} />}
          {tab === 'pages' && (
            <PagesTab
              website={detail?.website ?? site}
              pages={plan?.pages ?? detail?.pages ?? []}
              approved={plan?.approved ?? false}
              perms={perms}
            />
          )}
          {tab === 'deploys' && <DeploysTab website={detail?.website ?? site} deploys={detail?.deploys ?? []} />}
        </>
      )}
    </Shell>
  )
}

function Shell({ clientId, clientName, children }: { clientId?: string; clientName?: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: 32, maxWidth: 1080 }}>
      <Link to={`/clients/${clientId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: ACCENT, textDecoration: 'none', marginBottom: 16 }}>
        <ArrowLeft size={14} /> Back to {clientName ?? 'client'}
      </Link>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <Globe size={22} color={ACCENT} />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Website Builder</h1>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', marginTop: 0, marginBottom: 20 }}>
        Plan, generate and publish a site. Publishing commits a page into the site's own
        GitHub repo, which builds and deploys itself — the repo <em>is</em> the site.
      </p>
      {children}
    </div>
  )
}

function Loading() {
  return <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
}

function CreateSite({ clientId, perms, onCreated }: {
  clientId: string
  perms: { isStaff: boolean; isAdmin: boolean; frozen: boolean }
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [siteType, setSiteType] = useState<SiteType>('local_business')
  const deny = denyReason('staff', perms)

  const create = useMutation({
    mutationFn: () => api.post(`/clients/${clientId}/websites`, { name, site_type: siteType }),
    onSuccess: onCreated,
  })

  return (
    <div style={{ ...card, maxWidth: 560 }}>
      <strong style={{ fontSize: 15, color: '#0f172a' }}>No site for this client yet</strong>
      <p style={{ fontSize: 13, color: '#64748b', margin: '6px 0 16px' }}>
        Creating one records the intent and nothing else. Provisioning — which mints a real
        GitHub repository and a Cloudflare project — is a separate, deliberate second step.
      </p>

      <div style={{ marginBottom: 12 }}>
        <label style={label}>Site name</label>
        <input style={input} value={name} onChange={(e) => setName(e.target.value)}
               placeholder="Acme Roofing" disabled={Boolean(deny)} />
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={label}>Site type</label>
        <div style={{ display: 'grid', gap: 6 }}>
          {SITE_TYPES.map((t) => (
            <label key={t.value} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, cursor: deny ? 'not-allowed' : 'pointer' }}>
              <input type="radio" name="site_type" checked={siteType === t.value} disabled={Boolean(deny)}
                     onChange={() => setSiteType(t.value)} style={{ marginTop: 3 }} />
              <span>
                <span style={{ fontWeight: 600, color: '#0f172a' }}>{t.label}</span>
                <span style={{ display: 'block', color: '#64748b', fontSize: 12 }}>{t.hint}</span>
              </span>
            </label>
          ))}
        </div>
      </div>

      <button
        onClick={() => create.mutate()}
        disabled={Boolean(deny) || !name.trim() || create.isPending}
        title={deny ?? undefined}
        style={{ ...btn(deny || !name.trim() ? '#e2e8f0' : ACCENT, deny || !name.trim() ? '#94a3b8' : '#fff') }}
      >
        {create.isPending ? <Loader2 size={14} className="spin" /> : <Plus size={14} />}
        Create site
      </button>
      {deny && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 8 }}>{deny}</div>}
      {create.error && (
        <div style={{ marginTop: 10, padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
          {(create.error as Error).message}
        </div>
      )}
    </div>
  )
}
