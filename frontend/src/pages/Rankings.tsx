import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, TrendingUp } from 'lucide-react'
import { api } from '../lib/api'
import type { Client, GscProperty } from '../lib/types'
import { useAuth } from '../context/AuthContext'
import { backLink } from '../components/localseo/shared'
import { RankSettings } from '../components/rankings/RankSettings'
import { RankOverview } from '../components/rankings/RankOverview'
import { RankKeywords } from '../components/rankings/RankKeywords'

type Tab = 'overview' | 'keywords' | 'settings'

// Per-client Organic Rank Tracker (Module #4). Tabbed shell over the connected
// GSC property: Overview (triage), Keywords (wide table), Settings (connection).
export function Rankings() {
  const { id } = useParams<{ id: string }>()
  const clientId = id as string
  const navigate = useNavigate()
  const { isAdmin } = useAuth()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data: properties } = useQuery<GscProperty[]>({
    queryKey: ['gsc-properties', clientId],
    queryFn: () => api.get<GscProperty[]>(`/clients/${clientId}/gsc-properties`),
    enabled: Boolean(clientId),
  })

  const connected = (properties ?? []).filter(p => p.access_status === 'ok')
  const [tab, setTab] = useState<Tab>('overview')
  const [activeProp, setActiveProp] = useState<string | null>(null)

  // Default the active property to the first connected one; fall back to
  // Settings when nothing is connected yet.
  useEffect(() => {
    if (connected.length && !connected.some(p => p.id === activeProp)) {
      setActiveProp(connected[0].id)
    }
    if (properties && connected.length === 0) setTab('settings')
  }, [properties]) // eslint-disable-line react-hooks/exhaustive-deps

  const hasConnection = connected.length > 0
  const propId = activeProp ?? connected[0]?.id ?? null

  return (
    <div style={{ padding: 32, maxWidth: 980 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <TrendingUp size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Organic Rank Tracker</h1>
      </div>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 20px' }}>
        {client?.name ?? 'This client'} · organic positions, clicks &amp; impressions from Search Console.
      </p>

      {/* Tabs */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, borderBottom: '1px solid #e2e8f0', marginBottom: 24 }}>
        <TabButton active={tab === 'overview'} onClick={() => setTab('overview')} label="Overview" />
        <TabButton active={tab === 'keywords'} onClick={() => setTab('keywords')} label="Keywords" />
        <TabButton active={tab === 'settings'} onClick={() => setTab('settings')} label="Settings" />

        {hasConnection && connected.length > 1 && tab !== 'settings' && (
          <select
            value={propId ?? ''} onChange={(e) => setActiveProp(e.target.value)}
            style={{ marginLeft: 'auto', fontSize: 12, padding: '4px 8px', borderRadius: 6, border: '1px solid #e2e8f0' }}
          >
            {connected.map(p => <option key={p.id} value={p.id}>{p.site_url}</option>)}
          </select>
        )}
      </div>

      {/* Body */}
      {tab === 'settings' ? (
        <RankSettings clientId={clientId} isAdmin={isAdmin} />
      ) : !hasConnection || !propId ? (
        <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 12, padding: 28, textAlign: 'center', color: '#64748b' }}>
          <p style={{ margin: '0 0 12px', fontSize: 14 }}>
            Connect a Search Console property to start tracking rankings.
          </p>
          <button
            style={{ background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, padding: '9px 16px', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}
            onClick={() => setTab('settings')}
          >
            Go to Settings
          </button>
        </div>
      ) : tab === 'overview' ? (
        <RankOverview propertyId={propId} />
      ) : (
        <RankKeywords propertyId={propId} isAdmin={isAdmin} />
      )}
    </div>
  )
}

function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button onClick={onClick} style={{
      background: 'none', border: 'none', cursor: 'pointer',
      padding: '10px 14px', fontSize: 14, fontWeight: 600,
      color: active ? '#6366f1' : '#64748b',
      borderBottom: active ? '2px solid #6366f1' : '2px solid transparent',
      marginBottom: -1,
    }}>{label}</button>
  )
}
