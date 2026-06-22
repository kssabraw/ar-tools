import type { CSSProperties } from 'react'
import { Loader2 } from 'lucide-react'

// The app doesn't import index.css, so the global `spin` keyframe it declares
// isn't present at runtime. Inject a self-contained keyframe once so the spinner
// actually animates regardless of global stylesheet state.
const KEYFRAME_ID = 'ls-spin-keyframes'
if (typeof document !== 'undefined' && !document.getElementById(KEYFRAME_ID)) {
  const el = document.createElement('style')
  el.id = KEYFRAME_ID
  el.textContent = '@keyframes ls-spin { to { transform: rotate(360deg); } }'
  document.head.appendChild(el)
}

export function Spinner({ size = 16, color = '#6366f1', style }: { size?: number; color?: string; style?: CSSProperties }) {
  return <Loader2 size={size} color={color} style={{ animation: 'ls-spin 1s linear infinite', flexShrink: 0, ...style }} />
}
