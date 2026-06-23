/**
 * Shared silo-management components.
 *
 * The standalone Silos dashboard (`pages/Silos.tsx`) and the per-client
 * Content Runs page (`pages/Runs.tsx`) render the same silo rows — rich
 * columns, an expandable detail drawer, per-row promote/approve/reject
 * actions, and a bulk-action toolbar. Those pieces live here so both pages
 * stay in sync. Non-component helpers live in `siloShared.tsx`.
 */

import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle, Check, ChevronDown, ChevronRight, ExternalLink, Play, X,
} from 'lucide-react'
import { api } from '../../lib/api'
import type { SiloDetail, SiloListItem } from '../../lib/types'
import {
  formatSiloDate,
  formatSiloScore,
  siloStatusBadge,
  SILO_COLSPAN,
  type SiloMutations,
  siloBreakdownPill,
  siloCardStyle,
  siloDangerBtn,
  siloDrawerBody,
  siloDrawerH4,
  siloGhostBtn,
  siloPrimaryBtn,
  siloRowAction,
  siloTdStyle,
  siloThStyle,
} from './siloShared'

// ----------------------------------------------------------------------
// Bulk-action toolbar
// ----------------------------------------------------------------------

export function SiloBulkToolbar({
  selectedIds,
  mutations,
  onClear,
}: {
  selectedIds: Set<string>
  mutations: SiloMutations
  onClear: () => void
}) {
  if (selectedIds.size === 0) return null
  const ids = Array.from(selectedIds)
  return (
    <div style={{
      ...siloCardStyle,
      padding: 12,
      display: 'flex',
      gap: 10,
      alignItems: 'center',
      background: '#eef2ff',
      borderColor: '#c7d2fe',
    }}>
      <span style={{ color: '#3730a3', fontWeight: 600, fontSize: 13 }}>
        {selectedIds.size} selected
      </span>
      <button
        onClick={() => {
          if (confirm(`Approve ${ids.length} candidate(s) and dispatch runs?`)) {
            mutations.bulkApproveAndGenerate.mutate(ids, { onSuccess: onClear })
          }
        }}
        disabled={mutations.bulkApproveAndGenerate.isPending}
        style={siloPrimaryBtn}
      >
        <Play size={14} /> Approve &amp; generate
      </button>
      <button
        onClick={() => mutations.bulkApprove.mutate(ids, { onSuccess: onClear })}
        disabled={mutations.bulkApprove.isPending}
        style={siloGhostBtn}
      >
        <Check size={14} /> Approve only
      </button>
      <button
        onClick={() => {
          if (ids.length > 10) {
            const typed = prompt(`You're rejecting ${ids.length} candidates. Type "reject" to confirm:`)
            if (typed !== 'reject') return
          } else if (!confirm(`Reject ${ids.length} candidate(s)?`)) {
            return
          }
          mutations.bulkReject.mutate(ids, { onSuccess: onClear })
        }}
        disabled={mutations.bulkReject.isPending}
        style={siloDangerBtn}
      >
        <X size={14} /> Reject
      </button>
      <button onClick={onClear} style={{ ...siloGhostBtn, marginLeft: 'auto' }}>
        Clear
      </button>
    </div>
  )
}

// ----------------------------------------------------------------------
// Table head
// ----------------------------------------------------------------------

export function SiloTableHead({
  allChecked,
  onToggleAll,
}: {
  allChecked: boolean
  onToggleAll: () => void
}) {
  return (
    <thead>
      <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
        <th style={{ ...siloThStyle, width: 32 }}>
          <input type="checkbox" checked={allChecked} onChange={onToggleAll} />
        </th>
        <th style={{ ...siloThStyle, width: 28 }}></th>
        <th style={siloThStyle}>Keyword</th>
        <th style={siloThStyle}>Status</th>
        <th style={siloThStyle}>Occurrences</th>
        <th style={siloThStyle}>Demand</th>
        <th style={siloThStyle}>Coherence</th>
        <th style={siloThStyle}>Viable</th>
        <th style={siloThStyle}>Intent</th>
        <th style={siloThStyle}>Routed from</th>
        <th style={siloThStyle}>First seen</th>
        <th style={siloThStyle}>Last seen</th>
        <th style={siloThStyle}></th>
      </tr>
    </thead>
  )
}

// ----------------------------------------------------------------------
// Row + drawer
// ----------------------------------------------------------------------

export function SiloRow(props: {
  silo: SiloListItem
  selected: boolean
  expanded: boolean
  onToggleSelect: () => void
  onToggleExpand: () => void
  onApprove: () => void
  onReject: () => void
  onPromote: () => void
  promoting: boolean
}) {
  const { silo, selected, expanded, promoting } = props
  const canApprove = silo.status === 'proposed' || silo.status === 'published'
  const canReject = silo.status !== 'in_progress' && silo.status !== 'rejected'
  const canPromote =
    silo.status === 'proposed' || silo.status === 'approved' || silo.status === 'published'

  const failed = !!silo.last_promotion_failed_at

  return (
    <>
      <tr style={{ borderBottom: '1px solid #f8fafc', background: selected ? '#fafbff' : undefined }}>
        <td style={siloTdStyle}>
          <input type="checkbox" checked={selected} onChange={props.onToggleSelect} />
        </td>
        <td style={siloTdStyle}>
          <button
            onClick={props.onToggleExpand}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', display: 'flex', alignItems: 'center' }}
            aria-label={expanded ? 'Collapse' : 'Expand'}
          >
            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
        </td>
        <td style={{ ...siloTdStyle, fontWeight: 500, color: '#0f172a', maxWidth: 360 }}>
          <div>{silo.suggested_keyword}</div>
          {failed && (
            <div style={{ marginTop: 4, fontSize: 12, color: '#b91c1c', display: 'flex', alignItems: 'center', gap: 4 }}>
              <AlertCircle size={12} /> last promotion failed
            </div>
          )}
        </td>
        <td style={siloTdStyle}>{siloStatusBadge(silo.status)}</td>
        <td style={siloTdStyle}>{silo.occurrence_count}</td>
        <td style={siloTdStyle}>{formatSiloScore(silo.search_demand_score)}</td>
        <td style={siloTdStyle}>{formatSiloScore(silo.cluster_coherence_score)}</td>
        <td style={siloTdStyle}>{silo.viable_as_standalone_article ? '✓' : '✗'}</td>
        <td style={siloTdStyle}>{silo.estimated_intent ?? '—'}</td>
        <td style={{ ...siloTdStyle, fontSize: 12, color: '#64748b' }}>
          {silo.routed_from?.replace('_', ' ') ?? '—'}
        </td>
        <td style={{ ...siloTdStyle, color: '#64748b', fontSize: 13 }}>{formatSiloDate(silo.created_at)}</td>
        <td style={{ ...siloTdStyle, color: '#64748b', fontSize: 13 }}>{formatSiloDate(silo.updated_at)}</td>
        <td style={{ ...siloTdStyle, textAlign: 'right', whiteSpace: 'nowrap' }}>
          {canPromote && (
            <button onClick={props.onPromote} disabled={promoting} style={{ ...siloRowAction, color: '#3730a3' }} title="Approve and generate run">
              {promoting ? '…' : <Play size={14} />}
            </button>
          )}
          {canApprove && (
            <button onClick={props.onApprove} style={{ ...siloRowAction, color: '#166534' }} title="Approve">
              <Check size={14} />
            </button>
          )}
          {canReject && (
            <button onClick={props.onReject} style={{ ...siloRowAction, color: '#991b1b' }} title="Reject">
              <X size={14} />
            </button>
          )}
        </td>
      </tr>
      {expanded && <SiloDrawer siloId={silo.id} />}
    </>
  )
}

function SiloDrawer({ siloId }: { siloId: string }) {
  const { data: detail, isLoading } = useQuery<SiloDetail>({
    queryKey: ['silo-detail', siloId],
    queryFn: () => api.get<SiloDetail>(`/silos/${siloId}`),
  })

  return (
    <tr>
      <td colSpan={SILO_COLSPAN} style={{ padding: 0, background: '#f8fafc' }}>
        <div style={{ padding: '16px 24px', borderBottom: '1px solid #f1f5f9' }}>
          {isLoading || !detail ? (
            <div style={{ color: '#64748b', fontSize: 13 }}>Loading detail…</div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
              <div>
                <h4 style={siloDrawerH4}>Viability reasoning</h4>
                <p style={siloDrawerBody}>
                  {detail.viability_reasoning || <span style={{ color: '#94a3b8' }}>—</span>}
                </p>

                <h4 style={siloDrawerH4}>Discard reason breakdown</h4>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {Object.entries(detail.discard_reason_breakdown ?? {}).length === 0 ? (
                    <span style={{ color: '#94a3b8', fontSize: 13 }}>none</span>
                  ) : (
                    Object.entries(detail.discard_reason_breakdown).map(([reason, count]) => (
                      <span key={reason} style={siloBreakdownPill}>
                        {reason}: <strong>{count}</strong>
                      </span>
                    ))
                  )}
                </div>

                <h4 style={siloDrawerH4}>Source briefs ({detail.source_run_ids.length})</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {detail.source_run_ids.map(runId => (
                    <Link
                      key={runId}
                      to={`/runs/${runId}`}
                      style={{ color: '#6366f1', fontSize: 13, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}
                    >
                      <ExternalLink size={12} /> {runId.slice(0, 8)}…
                    </Link>
                  ))}
                </div>
              </div>
              <div>
                <h4 style={siloDrawerH4}>Source headings ({detail.source_headings.length})</h4>
                <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                  <table style={{ width: '100%', fontSize: 13 }}>
                    <thead>
                      <tr style={{ color: '#64748b', textAlign: 'left' }}>
                        <th style={{ padding: '4px 0', fontWeight: 600 }}>Heading</th>
                        <th style={{ padding: '4px 0', fontWeight: 600, width: 80 }}>Source</th>
                        <th style={{ padding: '4px 0', fontWeight: 600, width: 60 }}>Rel.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.source_headings.map((h, i) => (
                        <tr key={i} style={{ borderTop: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '6px 0', color: '#0f172a' }}>{h.text}</td>
                          <td style={{ padding: '6px 0', color: '#64748b', fontSize: 12 }}>{h.source}</td>
                          <td style={{ padding: '6px 0', color: '#64748b', fontSize: 12 }}>
                            {h.title_relevance !== undefined ? h.title_relevance.toFixed(2) : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      </td>
    </tr>
  )
}
