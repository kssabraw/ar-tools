import { PaceChat } from '../components/PaceChat'
import { InterventionsPanel } from '../components/pace/InterventionsPanel'

// Dedicated PACE page — the delivery-PM chat, sibling of the SerMaStr /assistant
// page. The Proactive Interventions approvals panel sits above the chat (it
// renders nothing when there's nothing to decide), then the chat fills the rest.
export function Pace() {
  return (
    <div style={{ padding: 32, height: '100%', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', maxWidth: 1000, margin: '0 auto' }}>
      <div style={{ flexShrink: 0 }}>
        <InterventionsPanel />
      </div>
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        <PaceChat fullPage />
      </div>
    </div>
  )
}
