import { useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Download, ExternalLink, Gauge, X, Zap } from 'lucide-react'
import { api } from '../lib/api'
import { downloadCsv, toCsv } from '../lib/csv'

// Authority report (RD / DR / UR) — an on-demand comparison of link authority
// between the client and the competitors a rank tracker already knows about.
// Organic: everyone in the keyword's latest SERP snapshot. Maps: the latest
// geo-grid scan's local-pack leaderboard. Runs on open (the button click is the
// explicit action); the paid call is labeled loudly while in flight.

interface AuthorityRow {
  position?: number | null
  url?: string | null
  domain: string | null
  name?: string | null
  top3_pins?: number | null
  found_pins?: number | null
  is_client: boolean
  dr: number | null
  ur: number | null
  rd: number | null
}
interface AuthorityResponse {
  kind?: 'organic' | 'maps'
  keyword?: string
  snapshot_captured_at?: string | null
  needs_snapshot?: boolean
  needs_scan?: boolean
  rows: AuthorityRow[]
}

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString()
}
function rating(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : n.toFixed(1)
}
function pathOf(url: string | null | undefined): string {
  if (!url) return '—'
  try {
    const u = new URL(url.includes('//') ? url : `https://${url}`)
    return u.hostname.replace(/^www\./, '') + (u.pathname === '/' ? '' : u.pathname)
  } catch {
    return url
  }
}

export function AuthorityReport({ kind, endpoint, body, title, onClose }: {
  kind: 'organic' | 'maps'
  endpoint: string
  body?: unknown
  title: string
  onClose: () => void
}) {
  const run = useMutation({
    mutationFn: () => api.post<AuthorityResponse>(endpoint, body ?? {}),
  })
  useEffect(() => { run.mutate() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const data = run.data
  const rows = data?.rows ?? []

  function exportCsv() {
    if (kind === 'organic') {
      downloadCsv(`authority-${title}.csv`, toCsv(
        ['Position', 'URL', 'Domain', 'DR', 'UR', 'RD', 'Client'],
        rows.map((r) => [r.position ?? '', r.url ?? '', r.domain ?? '', r.dr ?? '', r.ur ?? '', r.rd ?? '', r.is_client ? 'yes' : '']),
      ))
    } else {
      downloadCsv(`authority-${title}.csv`, toCsv(
        ['Business', 'Domain', 'Top-3 pins', 'Found pins', 'DR', 'UR (home)', 'RD', 'Client'],
        rows.map((r) => [r.name ?? '', r.domain ?? '', r.top3_pins ?? '', r.found_pins ?? '', r.dr ?? '', r.ur ?? '', r.rd ?? '', r.is_client ? 'yes' : '']),
      ))
    }
  }

  return (
    <div style={panel}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Gauge size={15} color="#4f46e5" />
        <span style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>Authority report — {title}</span>
        {data?.snapshot_captured_at && (
          <span style={{ fontSize: 12, color: '#94a3b8' }}>
            SERP from snapshot {String(data.snapshot_captured_at).slice(0, 10)} · metrics fetched live
          </span>
        )}
        <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6 }}>
          {rows.length > 0 && (
            <button style={ghostBtn} onClick={exportCsv}><Download size={13} /> CSV</button>
          )}
          <button style={ghostBtn} onClick={onClose}><X size={13} /> Close</button>
        </span>
      </div>

      {run.isPending && (
        <div style={{ ...notice, borderColor: '#fcd34d', background: '#fffbeb', color: '#92400e' }}>
          <Zap size={13} /> Fetching live DR / UR / referring-domain metrics from DataForSEO — 2 paid API calls…
        </div>
      )}
      {run.isError && (
        <div style={{ ...notice, borderColor: '#fecaca', background: '#fef2f2', color: '#b91c1c' }}>
          {(run.error as Error).message === 'backlink_budget_exceeded'
            ? 'The daily backlink API budget is used up — try again tomorrow.'
            : 'Could not fetch authority metrics.'}
        </div>
      )}
      {data?.needs_snapshot && (
        <div style={notice}>No SERP snapshot exists for this keyword yet — capture one (camera button) first, then run the report.</div>
      )}
      {data?.needs_scan && (
        <div style={notice}>No completed geo-grid scan yet — run a scan first, then run the report.</div>
      )}

      {rows.length > 0 && (
        <table style={table}>
          <thead>
            <tr>
              {kind === 'organic'
                ? <><Th>#</Th><Th>Page</Th><Th right>DR</Th><Th right>UR</Th><Th right>Ref. domains</Th></>
                : <><Th>Business</Th><Th>Domain</Th><Th right>Top-3 pins</Th><Th right>DR</Th><Th right>UR (home)</Th><Th right>Ref. domains</Th></>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ borderTop: '1px solid #f1f5f9', background: r.is_client ? '#eef2ff' : undefined }}>
                {kind === 'organic' ? (
                  <>
                    <td style={td}>{r.position ?? <span style={{ color: '#94a3b8' }}>n/r</span>}</td>
                    <td style={{ ...td, maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.url ? (
                        <a href={r.url} target="_blank" rel="noreferrer" style={linkCell} title={r.url}>
                          {pathOf(r.url)} <ExternalLink size={11} />
                        </a>
                      ) : (r.domain ?? '—')}
                      {r.is_client && <span style={clientChip}>you</span>}
                    </td>
                  </>
                ) : (
                  <>
                    <td style={td}>{r.name ?? '—'}{r.is_client && <span style={clientChip}>you</span>}</td>
                    <td style={td}>{r.domain ?? <span style={{ color: '#94a3b8' }}>no website</span>}</td>
                    <td style={tdRight}>{fmt(r.top3_pins)}</td>
                  </>
                )}
                <td style={tdRight}>{rating(r.dr)}</td>
                <td style={tdRight}>{rating(r.ur)}</td>
                <td style={tdRight}>{fmt(r.rd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th style={{ textAlign: right ? 'right' : 'left', fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.3, padding: '6px 10px' }}>{children}</th>
}

const panel: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, background: '#fff', margin: '8px 0',
}
const notice: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, border: '1px solid #e2e8f0', borderRadius: 10,
  padding: '10px 14px', fontSize: 13, color: '#64748b', marginBottom: 4,
}
const table: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 13, background: '#fff' }
const td: React.CSSProperties = { padding: '8px 10px', color: '#334155' }
const tdRight: React.CSSProperties = { ...td, textAlign: 'right', color: '#475569' }
const linkCell: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, color: '#4f46e5', textDecoration: 'none' }
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 10px', fontSize: 12,
  fontWeight: 600, color: '#475569', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, cursor: 'pointer',
}
const clientChip: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: '#4f46e5', background: '#e0e7ff',
  padding: '1px 6px', borderRadius: 999, marginLeft: 6, textTransform: 'uppercase',
}
