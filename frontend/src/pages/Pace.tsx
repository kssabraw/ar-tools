import { PaceChat } from '../components/PaceChat'

// Dedicated PACE page — the delivery-PM chat, sibling of the SerMaStr /assistant
// page. Gets the full content area so the message field can be large.
export function Pace() {
  return (
    <div style={{ padding: 32, height: '100%', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', maxWidth: 1000, margin: '0 auto' }}>
      <PaceChat fullPage />
    </div>
  )
}
