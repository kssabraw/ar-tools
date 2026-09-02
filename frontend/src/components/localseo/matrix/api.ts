import { api } from '../../../lib/api'
import type {
  MatrixCreateBody,
  MatrixDetail,
  MatrixEstimate,
  MatrixReleaseBody,
  MatrixReleaseState,
  MatrixSuggestResult,
  MatrixSummary,
  MatrixUpdateBody,
} from './types'

const base = (clientId: string) => `/clients/${clientId}/local-seo/matrices`

// All matrix calls go through platform-api (routers/local_seo_matrix.py).
// Generation itself rides the same background local_seo_generate jobs as
// bulk-create; the matrix reconciles its cells from those jobs on every read,
// so the grid is safe to poll and safe to leave.
export const matrixApi = {
  list: (clientId: string) => api.get<MatrixSummary[]>(base(clientId)),

  create: (clientId: string, body: MatrixCreateBody) => api.post<MatrixDetail>(base(clientId), body),

  get: (clientId: string, matrixId: string) => api.get<MatrixDetail>(`${base(clientId)}/${matrixId}`),

  update: (clientId: string, matrixId: string, body: MatrixUpdateBody) =>
    api.put<MatrixDetail>(`${base(clientId)}/${matrixId}`, body),

  remove: (clientId: string, matrixId: string) => api.delete<{ deleted: boolean }>(`${base(clientId)}/${matrixId}`),

  recheck: (clientId: string, matrixId: string) =>
    api.post<{ changed: number; coverage: Record<string, number>; degraded_notes: string[] }>(
      `${base(clientId)}/${matrixId}/recheck`, {},
    ),

  estimate: (
    clientId: string,
    matrixId: string,
    opts: { cell_ids?: string[]; include_covered?: boolean; signoff_acknowledged?: boolean } = {},
  ) => {
    const q = new URLSearchParams()
    for (const id of opts.cell_ids ?? []) q.append('cell_ids', id)
    if (opts.include_covered) q.set('include_covered', 'true')
    if (opts.signoff_acknowledged) q.set('signoff_acknowledged', 'true')
    const qs = q.toString()
    return api.get<MatrixEstimate>(`${base(clientId)}/${matrixId}/estimate${qs ? `?${qs}` : ''}`)
  },

  generate: (
    clientId: string,
    matrixId: string,
    body: { cell_ids?: string[] | null; include_covered?: boolean; signoff_acknowledged?: boolean; force_refresh?: boolean },
  ) => api.post<{ job_ids: string[]; cell_ids: string[]; estimate: MatrixEstimate }>(
    `${base(clientId)}/${matrixId}/generate`, body,
  ),

  // Drip release: immediate batch now, then N per day / week / month — each
  // cell generated THEN published to the matrix's destination.
  getRelease: (clientId: string, matrixId: string) =>
    api.get<MatrixReleaseState>(`${base(clientId)}/${matrixId}/release`),
  setRelease: (clientId: string, matrixId: string, body: MatrixReleaseBody) =>
    api.put<MatrixReleaseState>(`${base(clientId)}/${matrixId}/release`, body),
  clearRelease: (clientId: string, matrixId: string) =>
    api.delete<{ deleted: boolean }>(`${base(clientId)}/${matrixId}/release`),
  runRelease: (clientId: string, matrixId: string, count: number) =>
    api.post<MatrixReleaseState>(`${base(clientId)}/${matrixId}/release/run?count=${count}`, {}),

  suggest: (clientId: string, matrixId: string, body: { axis: 'services' | 'locations'; seed_service?: string | null }) =>
    api.post<{ job_id: string; status: string }>(`${base(clientId)}/${matrixId}/suggest`, body),

  getSuggest: (clientId: string, matrixId: string, jobId: string) =>
    api.get<MatrixSuggestResult>(`${base(clientId)}/${matrixId}/suggest/${jobId}`),
}
