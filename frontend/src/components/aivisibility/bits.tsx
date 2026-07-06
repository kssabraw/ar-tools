import { TrendingUp, TrendingDown, Minus, CheckCircle2, XCircle } from 'lucide-react'
import './animations.css'

// Small shared pieces for the AI Visibility result cards + detail sheet.

export function Chip({ children, tone = 'slate' }: { children: React.ReactNode; tone?: 'slate' | 'violet' | 'amber' | 'green' | 'red' }) {
  const tones = {
    slate: { bg: '#f1f5f9', fg: '#475569' }, violet: { bg: '#f5f3ff', fg: '#6d28d9' },
    amber: { bg: '#fffbeb', fg: '#b45309' }, green: { bg: '#f0fdf4', fg: '#15803d' },
    red: { bg: '#fef2f2', fg: '#b91c1c' },
  }[tone]
  return <span style={{ display: 'inline-block', fontSize: 11, padding: '2px 8px', borderRadius: 10, background: tones.bg, color: tones.fg, marginRight: 6, marginBottom: 4 }}>{children}</span>
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>{title}</div>
      {children}
    </div>
  )
}

// LABS segmented confidence bar: track with tick marks at 25/50/75%, fill
// colored by level, percentage readout on the right.
export function ConfidenceBar({ value }: { value: number | null }) {
  const pct = value == null ? null : Math.round(Math.max(0, Math.min(1, value)) * 100)
  const fill = pct == null ? '#cbd5e1'
    : pct >= 75 ? '#15803d'
    : pct >= 50 ? '#b45309'
    : pct >= 25 ? '#6366f1'
    : '#b91c1c'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, position: 'relative', height: 10, background: '#f1f5f9', borderRadius: 999, overflow: 'hidden' }}>
        {pct != null && (
          <div className="aiv-confidence-seg" style={{ width: `${pct}%`, height: '100%', background: fill, borderRadius: 999 }} />
        )}
        {/* tick marks at 25/50/75% */}
        <div style={{ position: 'absolute', inset: 0, display: 'flex', pointerEvents: 'none' }}>
          <span style={{ width: '25%', borderRight: '1px solid rgba(255,255,255,0.55)' }} />
          <span style={{ width: '25%', borderRight: '1px solid rgba(255,255,255,0.55)' }} />
          <span style={{ width: '25%', borderRight: '1px solid rgba(255,255,255,0.55)' }} />
        </div>
      </div>
      <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b', width: 34, textAlign: 'right' }}>
        {pct == null ? '—' : `${pct}%`}
      </span>
    </div>
  )
}

export function SentimentIndicator({ value }: { value: number | null }) {
  if (value == null) return <span style={{ fontSize: 13, color: '#94a3b8' }}>—</span>
  const icon = value > 0.3 ? <TrendingUp size={14} color="#15803d" />
    : value < -0.3 ? <TrendingDown size={14} color="#b91c1c" />
    : <Minus size={14} color="#94a3b8" />
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 13, color: '#334155', fontWeight: 600 }}>
      {icon} {value.toFixed(2)}
    </span>
  )
}

// FOUND / NOT FOUND pill (LABS card + sheet header).
export function FoundPill({ found, size = 'sm' }: { found: boolean; size?: 'sm' | 'md' }) {
  const pad = size === 'md' ? '4px 12px' : '2px 9px'
  const fs = size === 'md' ? 12 : 11
  return found ? (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: pad, borderRadius: 999, background: '#f0fdf4', color: '#15803d', fontSize: fs, fontWeight: 700 }}>
      <CheckCircle2 size={fs + 1} /> {size === 'md' ? 'FOUND' : 'YES'}
    </span>
  ) : (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: pad, borderRadius: 999, background: '#fef2f2', color: '#b91c1c', fontSize: fs, fontWeight: 700 }}>
      <XCircle size={fs + 1} /> {size === 'md' ? 'NOT FOUND' : 'NO'}
    </span>
  )
}

// Compact relative time ("3h ago") — avoids a date-fns dependency.
export function relativeTime(iso: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  if (d < 30) return `${d}d ago`
  const mo = Math.floor(d / 30)
  return mo < 12 ? `${mo}mo ago` : `${Math.floor(mo / 12)}y ago`
}

export function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url }
}
