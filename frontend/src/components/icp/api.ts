import { api } from '../../lib/api'
import type { Differentiator, IcpResponse, IcpSegment } from '../../lib/types'

// ICP is a client-level asset served by platform-api. The scan (page discovery +
// title/H1 enrichment + 1 LLM call) runs as a background async job, so it survives
// the UI navigating away; get/update are plain JSON.
export const icpApi = {
  get: (clientId: string) =>
    api.get<IcpResponse>(`/clients/${clientId}/icp`),

  // Enqueue a scan (background job). force=true re-analyzes even over a
  // user-edited structured ICP. Poll scanStatus, then refetch get().
  scan: (clientId: string, force = false) =>
    api.post<{ job_id: string; status: string }>(`/clients/${clientId}/icp/scan`, { force }),

  scanStatus: (clientId: string, jobId: string) =>
    api.get<{ status: string; error?: string | null }>(
      `/clients/${clientId}/icp/scan/${jobId}`,
    ),

  update: (
    clientId: string,
    body: {
      raw_text?: string | null
      segments?: IcpSegment[] | null
      reasoning?: string | null
      differentiators?: Differentiator[] | null
    },
  ) => api.put<IcpResponse>(`/clients/${clientId}/icp`, body),
}
