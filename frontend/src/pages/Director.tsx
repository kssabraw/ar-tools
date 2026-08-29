import { DirectorChat } from '../components/DirectorChat'

// Dedicated DORA page — the Director of Operations chat, sibling of the SerMaStr
// /assistant and PACE /pace pages. Gets the full content area so the message
// field can be large.
export function Director() {
  return (
    <div style={{ padding: 32, height: '100%', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', maxWidth: 1000, margin: '0 auto' }}>
      <DirectorChat fullPage />
    </div>
  )
}
