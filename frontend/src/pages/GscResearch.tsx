import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FileSearch, Download, RefreshCw, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import { toCsv, downloadCsv } from '../lib/csv'
import type { Client } from '../lib/types'

// ── Types (mirror models/gsc_research.py) ───────────────────────────────────
interface CannibalizationPage {
  page: string
  clicks: number
  impressions: number
  position: number | null
}
interface CannibalizationRow {
  query: string
  page_count: number
  total_clicks: number
  total_impressions: number
  pages: CannibalizationPage[]
}
interface OpportunityRow {
  keyword: string
  page: string
  position: number
  impressions: number
  clicks: number
  search_volume: number | null
  cpc: number | null
  competition: string | null
}
interface ResearchRun {
  id: string
  status: 'pending' | 'running' | 'complete' | 'failed'
  trigger: string
  gsc_connected: boolean
  cannibalization_count: number
  quick_wins_count: number
  hidden_wins_count: number
  error: string | null
  requested_at: string | null
  completed_at: string | null
  date_from?: string | null
  date_to?: string | null
  cannibalization?: CannibalizationRow[]
  quick_wins?: OpportunityRow[]
  hidden_wins?: OpportunityRow[]
}

type Tab = 'cannibalization' | 'quick_wins' | 'hidden_wins'

export function GscResearch() {
  const { id: clientId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('quick_wins')

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data: run, isLoading } = useQuery<ResearchRun>({
    queryKey: ['gsc-research-latest', clientId],
    queryFn: () => api.get<ResearchRun>(`/clients/${clientId}/gsc-research/latest`),
    enabled: Boolean(clientId),
    retry: false,
    // Poll while a run is in flight so results land as soon as the job finishes.
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'pending' || s === 'running' ? 4000 : false
    },
  })

  const running = run?.status === 'pending' || run?.status === 'running'

  const runMut = useMutation({
    mutationFn: () => api.post<{ run_id: string; status: string }>(`/clients/${clientId}/gsc-research/run`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gsc-research-latest', clientId] }),
  })

  const hasRun = Boolean(run) && !(isLoading && !run)

  return (
    <div style={{ padding: 32, maxWidth: 1040 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <FileSearch size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>GSC Research</h1>
        {running && <span style={pill}>Analyzing…</span>}
      </div>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 20px' }}>
        {client?.name ?? 'This client'} · opportunity analysis from Search Console — cannibalization, quick wins &amp; hidden wins.
      </p>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <button
          style={{ ...runBtn, opacity: running || runMut.isPending ? 0.6 : 1 }}
          disabled={running || runMut.isPending}
          onClick={() => runMut.mutate()}
        >
          <RefreshCw size={15} /> {running ? 'Analyzing…' : hasRun ? 'Re-run analysis' : 'Run analysis'}
        </button>
        {run?.completed_at && !running && (
          <span style={{ fontSize: 12, color: '#94a3b8' }}>
            Last run {new Date(run.completed_at).toLocaleString()}
            {run.date_from && run.date_to ? ` · ${run.date_from} → ${run.date_to}` : ''}
          </span>
        )}
      </div>

      {runMut.isError && <Banner kind="error">{(runMut.error as Error).message}</Banner>}

      {!hasRun ? (
        <EmptyState
          title="No analysis yet"
          body="Run an analysis to surface keyword cannibalization, quick wins, and hidden wins from this client's Search Console data."
        />
      ) : run?.status === 'failed' ? (
        <Banner kind="error">Analysis failed: {run.error ?? 'unknown_error'}</Banner>
      ) : running && !run?.completed_at ? (
        <EmptyState title="Analyzing…" body="Crunching Search Console data and enriching keywords with market data. This usually takes under a minute." />
      ) : run && !run.gsc_connected ? (
        <Banner kind="warn">
          Search Console isn’t connected for this client yet. Connect a verified property in the Organic Rank Tracker, let it ingest data, then run this analysis.
        </Banner>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid #e2e8f0', marginBottom: 20 }}>
            <TabButton active={tab === 'quick_wins'} onClick={() => setTab('quick_wins')} label={`Quick Wins (${run?.quick_wins_count ?? 0})`} />
            <TabButton active={tab === 'hidden_wins'} onClick={() => setTab('hidden_wins')} label={`Hidden Wins (${run?.hidden_wins_count ?? 0})`} />
            <TabButton active={tab === 'cannibalization'} onClick={() => setTab('cannibalization')} label={`Cannibalization (${run?.cannibalization_count ?? 0})`} />
          </div>

          {tab === 'quick_wins' && (
            <OpportunityTable
              rows={run?.quick_wins ?? []}
              caption="Queries ranking positions 6–10 — a small push lands them on page 1."
              csvName="gsc-quick-wins"
            />
          )}
          {tab === 'hidden_wins' && (
            <OpportunityTable
              rows={run?.hidden_wins ?? []}
              caption="Queries at positions 11–30 with real impressions — demand stuck on page 2–3."
              csvName="gsc-hidden-wins"
            />
          )}
          {tab === 'cannibalization' && (
            <CannibalizationTable rows={run?.cannibalization ?? []} />
          )}
        </>
      )}
    </div>
  )
}

// ── Quick / Hidden wins table ───────────────────────────────────────────────
function OpportunityTable({ rows, caption, csvName }: { rows: OpportunityRow[]; caption: string; csvName: string }) {
  const exportCsv = () => {
    const headers = ['Keyword', 'Page', 'Position', 'Impressions', 'Clicks', 'Search Volume', 'CPC', 'Competition']
    const data = rows.map(r => [r.keyword, r.page, r.position, r.impressions, r.clicks, r.search_volume, r.cpc, r.competition])
    downloadCsv(`${csvName}-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(headers, data))
  }
  return (
    <div>
      <TableToolbar caption={caption} count={rows.length} onExport={exportCsv} />
      {rows.length === 0 ? (
        <EmptyState title="Nothing here" body="No opportunities matched this band in the latest analysis." />
      ) : (
        <div style={tableWrap}>
          <table style={table}>
            <thead>
              <tr>
                <Th>Keyword</Th><Th>Page</Th><Th right>Position</Th><Th right>Impr.</Th>
                <Th right>Clicks</Th><Th right>Volume</Th><Th right>CPC</Th><Th>Competition</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.keyword}-${r.page}-${i}`} style={i % 2 ? rowAlt : undefined}>
                  <Td><strong>{r.keyword}</strong></Td>
                  <Td><PageLink url={r.page} /></Td>
                  <Td right>{r.position.toFixed(1)}</Td>
                  <Td right>{r.impressions.toLocaleString()}</Td>
                  <Td right>{r.clicks.toLocaleString()}</Td>
                  <Td right>{r.search_volume?.toLocaleString() ?? '—'}</Td>
                  <Td right>{r.cpc != null ? `$${r.cpc.toFixed(2)}` : '—'}</Td>
                  <Td>{r.competition ? <CompChip value={r.competition} /> : '—'}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Cannibalization table ───────────────────────────────────────────────────
function CannibalizationTable({ rows }: { rows: CannibalizationRow[] }) {
  const exportCsv = () => {
    const headers = ['Query', 'Page', 'Position', 'Impressions', 'Clicks', 'Page Count', 'Total Impressions']
    const data: (string | number | null)[][] = []
    rows.forEach(r => {
      r.pages.forEach(p => {
        data.push([r.query, p.page, p.position, p.impressions, p.clicks, r.page_count, r.total_impressions])
      })
    })
    downloadCsv(`gsc-cannibalization-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(headers, data))
  }
  return (
    <div>
      <TableToolbar
        caption="Queries where Google splits ranking across multiple URLs that all rank well — consolidate or differentiate these pages."
        count={rows.length}
        onExport={exportCsv}
      />
      {rows.length === 0 ? (
        <EmptyState title="No cannibalization found" body="No queries showed multiple well-ranking URLs with clustered impressions." />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {rows.map((r, i) => (
            <div key={`${r.query}-${i}`} style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
                <strong style={{ fontSize: 15, color: '#0f172a' }}>{r.query}</strong>
                <span style={{ fontSize: 12, color: '#94a3b8' }}>
                  {r.page_count} pages · {r.total_impressions.toLocaleString()} impr · {r.total_clicks.toLocaleString()} clicks
                </span>
              </div>
              <table style={table}>
                <thead>
                  <tr><Th>Competing URL</Th><Th right>Position</Th><Th right>Impr.</Th><Th right>Clicks</Th></tr>
                </thead>
                <tbody>
                  {r.pages.map((p, j) => (
                    <tr key={`${p.page}-${j}`} style={j % 2 ? rowAlt : undefined}>
                      <Td><PageLink url={p.page} /></Td>
                      <Td right>{p.position != null ? p.position.toFixed(1) : '—'}</Td>
                      <Td right>{p.impressions.toLocaleString()}</Td>
                      <Td right>{p.clicks.toLocaleString()}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Small UI bits ───────────────────────────────────────────────────────────
function TableToolbar({ caption, count, onExport }: { caption: string; count: number; onExport: () => void }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 12 }}>
      <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>{caption}</p>
      {count > 0 && (
        <button style={exportBtn} onClick={onExport}>
          <Download size={14} /> CSV
        </button>
      )}
    </div>
  )
}

function PageLink({ url }: { url: string }) {
  let label = url
  try { const u = new URL(url); label = u.pathname + u.search } catch { /* keep raw */ }
  return (
    <a href={url} target="_blank" rel="noreferrer" style={{ color: '#6366f1', textDecoration: 'none', fontSize: 13 }} title={url}>
      {label || url}
    </a>
  )
}

function CompChip({ value }: { value: string }) {
  const v = value.toUpperCase()
  const color = v === 'HIGH' ? '#b91c1c' : v === 'MEDIUM' ? '#b45309' : '#15803d'
  const bg = v === 'HIGH' ? '#fee2e2' : v === 'MEDIUM' ? '#fef3c7' : '#dcfce7'
  return <span style={{ fontSize: 11, fontWeight: 600, color, background: bg, borderRadius: 999, padding: '2px 8px' }}>{v}</span>
}

function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: 'none', border: 'none', cursor: 'pointer', padding: '8px 14px',
        fontSize: 13, fontWeight: 600,
        color: active ? '#6366f1' : '#64748b',
        borderBottom: active ? '2px solid #6366f1' : '2px solid transparent',
      }}
    >
      {label}
    </button>
  )
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div style={{ textAlign: 'center', padding: '48px 24px', background: '#f8fafc', border: '1px dashed #e2e8f0', borderRadius: 12 }}>
      <div style={{ fontSize: 15, fontWeight: 600, color: '#475569', marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 13, color: '#94a3b8', maxWidth: 460, margin: '0 auto' }}>{body}</div>
    </div>
  )
}

function Banner({ kind, children }: { kind: 'error' | 'warn'; children: React.ReactNode }) {
  const color = kind === 'error' ? '#b91c1c' : '#b45309'
  const bg = kind === 'error' ? '#fef2f2' : '#fffbeb'
  const border = kind === 'error' ? '#fecaca' : '#fde68a'
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', background: bg, border: `1px solid ${border}`, color, borderRadius: 10, padding: '12px 14px', fontSize: 13, marginBottom: 16 }}>
      <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span>{children}</span>
    </div>
  )
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th style={{ textAlign: right ? 'right' : 'left', padding: '8px 12px', fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', borderBottom: '1px solid #e2e8f0' }}>{children}</th>
}
function Td({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <td style={{ textAlign: right ? 'right' : 'left', padding: '8px 12px', fontSize: 13, color: '#334155', borderBottom: '1px solid #f1f5f9' }}>{children}</td>
}

// ── Styles ──────────────────────────────────────────────────────────────────
const backLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', color: '#6366f1', cursor: 'pointer', fontSize: 13, marginBottom: 20, padding: 0 }
const pill: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#6366f1', background: '#eef2ff', borderRadius: 999, padding: '3px 10px' }
const runBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, padding: '9px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }
const exportBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 5, background: '#fff', color: '#475569', border: '1px solid #e2e8f0', borderRadius: 8, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }
const tableWrap: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }
const table: React.CSSProperties = { width: '100%', borderCollapse: 'collapse' }
const rowAlt: React.CSSProperties = { background: '#fafbfc' }
const card: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16 }
