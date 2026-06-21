import { api } from '../../lib/api'
import type { Differentiator, IcpResponse, IcpSegment } from '../../lib/types'

// ICP is a client-level asset served by platform-api. The scan is a heartbeat-SSE
// stream (page discovery + title/H1 enrichment + 1 LLM call); get/update are JSON.
export const icpApi = {
  get: (clientId: string) =>
    api.get<IcpResponse>(`/clients/${clientId}/icp`),

  // force=true re-analyzes even over a user-edited structured ICP.
  scan: (clientId: string, force = false) =>
    api.stream<IcpResponse>(`/clients/${clientId}/icp/scan`, { force }),

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
