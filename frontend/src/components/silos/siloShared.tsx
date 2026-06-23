/**
 * Non-component shared bits for the silo UI: status labels, formatters, the
 * mutations hook, and styles. Kept separate from `SiloTable.tsx` (which only
 * exports components) so React Fast Refresh works for both.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type {
  SiloBulkResponse,
  SiloListItem,
  SiloPromoteResponse,
  SiloStatus,
} from '../../lib/types'

export const SILO_STATUS_LABEL: Record<SiloStatus, string> = {
  proposed: 'Proposed',
  approved: 'Approved',
  rejected: 'Rejected',
  in_progress: 'In Progress',
  published: 'Published',
  superseded: 'Superseded',
}

export function siloStatusBadge(status: SiloStatus) {
  const map: Record<SiloStatus, { bg: string; color: string }> = {
    proposed:    { bg: '#fef3c7', color: '#92400e' },
    approved:    { bg: '#dbeafe', color: '#1e40af' },
    rejected:    { bg: '#fee2e2', color: '#991b1b' },
    in_progress: { bg: '#e0e7ff', color: '#3730a3' },
    published:   { bg: '#dcfce7', color: '#166534' },
    superseded:  { bg: '#f1f5f9', color: '#64748b' },
  }
  const s = map[status]
  return (
    <span style={{ background: s.bg, color: s.color, borderRadius: 999, padding: '2px 10px', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' }}>
      {SILO_STATUS_LABEL[status]}
    </span>
  )
}

export function formatSiloScore(n: number | null | undefined) {
  if (n === null || n === undefined) return '—'
  return n.toFixed(2)
}

export function formatSiloDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

// Number of columns the silo table spans (used by the detail drawer's colSpan).
export const SILO_COLSPAN = 13

// ----------------------------------------------------------------------
// Mutations
// ----------------------------------------------------------------------

export interface SiloMutations {
  updateStatus: ReturnType<typeof useMutation<SiloListItem, Error, { id: string; status: 'approved' | 'rejected' }>>
  promote: ReturnType<typeof useMutation<SiloPromoteResponse, Error, string>>
  bulkApproveAndGenerate: ReturnType<typeof useMutation<SiloBulkResponse, Error, string[]>>
  bulkApprove: ReturnType<typeof useMutation<SiloBulkResponse, Error, string[]>>
  bulkReject: ReturnType<typeof useMutation<SiloBulkResponse, Error, string[]>>
}

// Shared silo mutations. Invalidates all silo/run queries broadly so both the
// dashboard (`['silos', clientId, …]`) and the content-runs view
// (`['silos', 'runs-scoped', …]`) refresh after any change.
export function useSiloMutations(): SiloMutations {
  const qc = useQueryClient()

  function invalidate() {
    qc.invalidateQueries({ queryKey: ['silos'] })
    qc.invalidateQueries({ queryKey: ['silo-metrics'] })
    qc.invalidateQueries({ queryKey: ['runs'] })
  }

  const updateStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'approved' | 'rejected' }) =>
      api.patch<SiloListItem>(`/silos/${id}`, { status }),
    onSuccess: invalidate,
  })

  const promote = useMutation<SiloPromoteResponse, Error, string>({
    mutationFn: (id) => api.post<SiloPromoteResponse>(`/silos/${id}/promote`, {}),
    onSuccess: invalidate,
  })

  const bulkApproveAndGenerate = useMutation<SiloBulkResponse, Error, string[]>({
    mutationFn: (ids) => api.post<SiloBulkResponse>('/silos/bulk-approve-and-generate', { ids }),
    onSuccess: (res) => {
      invalidate()
      if (res.failed.length > 0) {
        alert(
          `Dispatched ${res.runs_dispatched.length} runs. ${res.failed.length} failed: ` +
            res.failed.map(f => `${f.id.slice(0, 8)}: ${f.reason}`).join('; ')
        )
      }
    },
  })

  const bulkApprove = useMutation<SiloBulkResponse, Error, string[]>({
    mutationFn: (ids) => api.post<SiloBulkResponse>('/silos/bulk-approve', { ids }),
    onSuccess: invalidate,
  })

  const bulkReject = useMutation<SiloBulkResponse, Error, string[]>({
    mutationFn: (ids) => api.post<SiloBulkResponse>('/silos/bulk-reject', { ids }),
    onSuccess: invalidate,
  })

  return { updateStatus, promote, bulkApproveAndGenerate, bulkApprove, bulkReject }
}

// ----------------------------------------------------------------------
// Styles (shared by the silo components)
// ----------------------------------------------------------------------

export const siloCardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
export const siloThStyle: React.CSSProperties = { textAlign: 'left', padding: '10px 12px', fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }
export const siloTdStyle: React.CSSProperties = { padding: '12px 12px', fontSize: 14, color: '#374151', verticalAlign: 'top' }
export const siloPrimaryBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer' }
export const siloGhostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
export const siloDangerBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#fff', color: '#991b1b', border: '1px solid #fecaca', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
export const siloRowAction: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', padding: '4px 6px', marginLeft: 4 }
export const siloDrawerH4: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 8px' }
export const siloDrawerBody: React.CSSProperties = { fontSize: 14, color: '#374151', margin: '0 0 16px', lineHeight: 1.5 }
export const siloBreakdownPill: React.CSSProperties = { background: '#f1f5f9', color: '#475569', padding: '3px 10px', borderRadius: 999, fontSize: 12 }
