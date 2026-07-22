import { QaChat } from '../components/QaChat'

// Dedicated QA page — the quality-reviewer chat, sibling of the SerMaStr
// /assistant and PACE /pace pages. Gets the full content area so the message
// field and streamed verdicts have room.
export function Qa() {
  return (
    <div style={{ padding: 32, height: '100%', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', maxWidth: 1000, margin: '0 auto' }}>
      <QaChat fullPage />
    </div>
  )
}
