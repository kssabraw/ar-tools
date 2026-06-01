import type { CSSProperties } from 'react'
import { Loader2 } from 'lucide-react'

// Spinner uses the global `spin` keyframe defined in index.css.
export function Spinner({ size = 16, color = '#6366f1', style }: { size?: number; color?: string; style?: CSSProperties }) {
  return <Loader2 size={size} color={color} style={{ animation: 'spin 1s linear infinite', flexShrink: 0, ...style }} />
}
