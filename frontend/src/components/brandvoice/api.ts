import { api } from '../../lib/api'
import type { BrandVoiceResponse, VoiceProfile } from '../../lib/types'

// Brand voice is a client-level asset served by platform-api. The scan is a
// heartbeat-SSE stream (probe + up to ~25 scrapes + 3 LLM calls) so it can't be
// dropped by a proxy idle timeout; get/update are plain JSON.
export const brandVoiceApi = {
  get: (clientId: string) =>
    api.get<BrandVoiceResponse>(`/clients/${clientId}/brand-voice`),

  // force=true regenerates even over a user-edited voice (explicit re-scan).
  scan: (clientId: string, force = false) =>
    api.stream<BrandVoiceResponse>(`/clients/${clientId}/brand-voice/scan`, { force }),

  update: (
    clientId: string,
    body: {
      raw_text?: string | null
      current_voice?: VoiceProfile | null
      recommended_accepted?: boolean | null
    },
  ) => api.put<BrandVoiceResponse>(`/clients/${clientId}/brand-voice`, body),
}
