import { api } from '../../lib/api'
import type { BrandVoiceResponse, VoiceProfile } from '../../lib/types'

// Brand voice is a client-level asset served by platform-api. The scan (probe +
// up to ~25 scrapes + 3 LLM calls) runs as a background async job, so it can't be
// dropped by a proxy idle timeout AND survives the UI navigating away; get/update
// are plain JSON.
export const brandVoiceApi = {
  get: (clientId: string) =>
    api.get<BrandVoiceResponse>(`/clients/${clientId}/brand-voice`),

  // Enqueue a scan (background job). force=true regenerates even over a
  // user-edited voice (explicit re-scan). Poll scanStatus, then refetch get().
  scan: (clientId: string, force = false) =>
    api.post<{ job_id: string; status: string }>(`/clients/${clientId}/brand-voice/scan`, { force }),

  scanStatus: (clientId: string, jobId: string) =>
    api.get<{ status: string; error?: string | null }>(
      `/clients/${clientId}/brand-voice/scan/${jobId}`,
    ),

  update: (
    clientId: string,
    body: {
      raw_text?: string | null
      current_voice?: VoiceProfile | null
      recommended_accepted?: boolean | null
    },
  ) => api.put<BrandVoiceResponse>(`/clients/${clientId}/brand-voice`, body),
}
