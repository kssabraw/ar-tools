import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, TrendingUp } from 'lucide-react'
import { api } from '../lib/api'
import type { Client, GscProperty, RankOverview as RankOverviewData } from '../lib/types'
import { backLink } from '../components/localseo/shared'
import { RankSettings } from '../components/rankings/RankSettings'
import { RankOverview } from '../components/rankings/RankOverview'
import { RankKeywords } from '../components/rankings/RankKeywords'
import { RankPages } from '../components/rankings/RankPages'
import { RankReports } from '../components/rankings/RankReports'
import { RankAlerts } from '../components/rankings/RankAlerts'
import { SerpTrends } from '../components/rankings/SerpTrends'
import { Rankability } from '../components/rankings/Rankability'
import { BrandSearch } from '../components/rankings/BrandSearch'

type Tab = 'overview' | 'keywords' | 'pages' | 'rankability' | 'trends' | 'brand' | 'alerts' | 'reports' | 'settings'

// Per-client Organic Rank Tracker (Module #4). Tabbed shell over the connected
// GSC property: Overview (triage), Keywords (wide table), Settings (connection).
export function Rankings() {
  const { id } = useParams<{ id: string }>()
  const clientId = id as string
  const navigate = useNavigate()

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

  // Overview drives the gsc/df mode copy and the Alerts-tab unread badge.
  const { data: overview } = useQuery<RankOverviewData>({
    queryKey: ['rank-overview', clientId],
    queryFn: () => api.get<RankOverviewData>(`/clients/${clientId}/rank/overview`),
    enabled: Boolean(clientId),
  })

  const gscConnected = (properties ?? []).some(p => p.access_status === 'ok')
  const unreadAlerts = overview?.unread_alert_count ?? 0
  const [tab, setTab] = useState<Tab>('overview')

  // The Overview tab is a GSC dashboard (avg-position/clicks/impressions charts,
  // striking distance). Without GSC it collapses into a weaker copy of Keywords,
  // so we hide it and land on Keywords once we know the client has no property.
  const propsLoaded = properties !== undefined
  const showOverview = !propsLoaded || gscConnected
  const effectiveTab: Tab = tab === 'overview' && !showOverview ? 'keywords' : tab

  return (
    <div style={{ padding: 32, maxWidth: 1400 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <TrendingUp size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Organic Rank Tracker</h1>
        <span style={gscConnected ? modeGsc : modeDf}>
          {gscConnected ? 'Search Console' : 'DataForSEO'}
        </span>
      </div>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 20px' }}>
        {client?.name ?? 'This client'} · {gscConnected
          ? 'organic positions, clicks & impressions from Search Console.'
          : 'organic positions from DataForSEO live SERP checks.'}
      </p>

      {/* Tabs */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, borderBottom: '1px solid #e2e8f0', marginBottom: 24 }}>
        {showOverview && <TabButton active={effectiveTab === 'overview'} onClick={() => setTab('overview')} label="Overview" />}
        <TabButton active={effectiveTab === 'keywords'} onClick={() => setTab('keywords')} label="Keywords" />
        {gscConnected && <TabButton active={effectiveTab === 'pages'} onClick={() => setTab('pages')} label="Pages" />}
        <TabButton active={effectiveTab === 'rankability'} onClick={() => setTab('rankability')} label="Rankability" />
        <TabButton active={effectiveTab === 'trends'} onClick={() => setTab('trends')} label="SERP Trends" />
        {gscConnected && <TabButton active={effectiveTab === 'brand'} onClick={() => setTab('brand')} label="Brand search" />}
        <TabButton active={effectiveTab === 'alerts'} onClick={() => setTab('alerts')} label="Alerts" badge={unreadAlerts} />
        <TabButton active={effectiveTab === 'reports'} onClick={() => setTab('reports')} label="Reports" />
        <TabButton active={effectiveTab === 'settings'} onClick={() => setTab('settings')} label="Settings" />
      </div>

      {/* Body */}
      {effectiveTab === 'settings' ? (
        <RankSettings clientId={clientId} />
      ) : effectiveTab === 'overview' ? (
        <RankOverview clientId={clientId} />
      ) : effectiveTab === 'pages' ? (
        <RankPages clientId={clientId} />
      ) : effectiveTab === 'rankability' ? (
        <Rankability clientId={clientId} />
      ) : effectiveTab === 'trends' ? (
        <SerpTrends clientId={clientId} />
      ) : effectiveTab === 'brand' ? (
        <BrandSearch clientId={clientId} />
      ) : effectiveTab === 'alerts' ? (
        <RankAlerts clientId={clientId} />
      ) : effectiveTab === 'reports' ? (
        <RankReports clientId={clientId} />
      ) : (
        <RankKeywords clientId={clientId} gscConnected={gscConnected} onViewRankability={() => setTab('rankability')} />
      )}
    </div>
  )
}

const modeGsc: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#166534', background: '#dcfce7', borderRadius: 999, padding: '3px 10px' }
const modeDf: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#0369a1', background: '#e0f2fe', borderRadius: 999, padding: '3px 10px' }

function TabButton({ active, onClick, label, badge }: { active: boolean; onClick: () => void; label: string; badge?: number }) {
  return (
    <button onClick={onClick} style={{
      background: 'none', border: 'none', cursor: 'pointer',
      padding: '10px 14px', fontSize: 14, fontWeight: 600,
      color: active ? '#6366f1' : '#64748b',
      borderBottom: active ? '2px solid #6366f1' : '2px solid transparent',
      marginBottom: -1, display: 'inline-flex', alignItems: 'center', gap: 6,
    }}>
      {label}
      {badge ? (
        <span style={{
          fontSize: 11, fontWeight: 700, color: '#fff', background: '#dc2626',
          borderRadius: 999, padding: '1px 6px', minWidth: 16, textAlign: 'center',
        }}>{badge}</span>
      ) : null}
    </button>
  )
}
