// Shared engine taxonomy for the AI Visibility module: keys, display labels,
// brand colors (used for chart lines / accents), and inline SVG logo marks.
// Mirrors services/brand_scan.ENGINE_ORDER. Logos are lightweight, hand-drawn
// approximations of each provider's mark — recognizable via shape + brand color,
// no external image assets (matches the suite's dependency-free convention).

export type EngineKey =
  | 'chatgpt' | 'claude' | 'gemini' | 'perplexity' | 'google_ai_overview' | 'google_ai_mode'

export const ENGINE_ORDER: EngineKey[] = [
  'chatgpt', 'claude', 'gemini', 'perplexity', 'google_ai_overview', 'google_ai_mode',
]

export interface EngineMeta {
  key: EngineKey
  label: string       // short label for cards / matrix / legend
  fullLabel: string   // full label for the detail sheet header
  color: string       // brand color for chart lines / accents
}

export const ENGINES: Record<EngineKey, EngineMeta> = {
  chatgpt:            { key: 'chatgpt',            label: 'ChatGPT',     fullLabel: 'ChatGPT',            color: '#10a37f' },
  claude:             { key: 'claude',             label: 'Claude',      fullLabel: 'Claude',             color: '#d97706' },
  gemini:             { key: 'gemini',             label: 'Gemini',      fullLabel: 'Gemini',             color: '#4285f4' },
  perplexity:         { key: 'perplexity',         label: 'Perplexity',  fullLabel: 'Perplexity',         color: '#20808d' },
  google_ai_overview: { key: 'google_ai_overview', label: 'AI Overview', fullLabel: 'Google AI Overview', color: '#ea4335' },
  google_ai_mode:     { key: 'google_ai_mode',     label: 'AI Mode',     fullLabel: 'Google AI Mode',     color: '#fbbc05' },
}

export function engineMeta(key: string): EngineMeta {
  return (ENGINES as Record<string, EngineMeta>)[key]
    ?? { key: key as EngineKey, label: key, fullLabel: key, color: '#64748b' }
}

// ── Logo marks ───────────────────────────────────────────────────────────────
// Single-color marks use `currentColor`; multicolor ones (Gemini/Google) carry
// their own fills. Each accepts a pixel size.

function ChatGptMark({ size }: { size: number }) {
  // Simplified OpenAI hex-knot silhouette.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2.4 4.9 6.6v8.8L12 19.6l7.1-4.2V6.6L12 2.4Zm0 2.3 5.1 3v6l-5.1 3-5.1-3v-6l5.1-3Z"
        fill="currentColor"
      />
      <path d="M12 7.6 8.2 9.8v4.4L12 16.4l3.8-2.2V9.8L12 7.6Z" fill="currentColor" opacity="0.55" />
    </svg>
  )
}

function ClaudeMark({ size }: { size: number }) {
  // Anthropic-style radial burst.
  const spokes = Array.from({ length: 12 }, (_, i) => i * 30)
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      {spokes.map(a => (
        <rect
          key={a} x="11.2" y="3" width="1.6" height="6.4" rx="0.8"
          fill="currentColor"
          transform={`rotate(${a} 12 12)`}
        />
      ))}
    </svg>
  )
}

function GeminiMark({ size }: { size: number }) {
  // Four-point spark with Gemini's blue→purple→pink gradient.
  const id = 'aiv-gemini-grad'
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
          <stop stopColor="#4285f4" />
          <stop offset="0.5" stopColor="#9b72cb" />
          <stop offset="1" stopColor="#d96570" />
        </linearGradient>
      </defs>
      <path
        d="M12 2c.4 5 4.9 9.6 10 10-5.1.4-9.6 5-10 10-.4-5-4.9-9.6-10-10C7.1 11.6 11.6 7 12 2Z"
        fill={`url(#${id})`}
      />
    </svg>
  )
}

function PerplexityMark({ size }: { size: number }) {
  // Stylized Perplexity glyph: framed with a central seat.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v18" />
      <path d="M12 7 5 4v7l7 4 7-4V4l-7 3Z" />
      <path d="M5 13v4l7 4 7-4v-4" />
    </svg>
  )
}

function GoogleMark({ size }: { size: number }) {
  // Multicolor Google "G" approximation: four colored arcs + blue crossbar.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true"
      strokeWidth="3.4" strokeLinecap="butt">
      <path d="M6.34 6.34A8 8 0 0 1 17.66 6.34" stroke="#ea4335" />
      <path d="M17.66 6.34A8 8 0 0 1 17.66 17.66" stroke="#4285f4" />
      <path d="M17.66 17.66A8 8 0 0 1 6.34 17.66" stroke="#34a853" />
      <path d="M6.34 17.66A8 8 0 0 1 6.34 6.34" stroke="#fbbc05" />
      <path d="M12.5 12H20" stroke="#4285f4" />
    </svg>
  )
}

const MARKS: Record<EngineKey, (p: { size: number }) => React.ReactElement> = {
  chatgpt: ChatGptMark,
  claude: ClaudeMark,
  gemini: GeminiMark,
  perplexity: PerplexityMark,
  google_ai_overview: GoogleMark,
  google_ai_mode: GoogleMark,
}

// EngineIcon — renders an engine's logo mark. Single-color marks inherit
// `color` (defaults to the engine's brand color); multicolor marks ignore it.
export function EngineIcon({ engine, size = 20, color }: { engine: string; size?: number; color?: string }) {
  const meta = engineMeta(engine)
  const Mark = MARKS[meta.key] ?? MARKS.chatgpt
  return (
    <span style={{ display: 'inline-flex', color: color ?? meta.color, lineHeight: 0 }}>
      <Mark size={size} />
    </span>
  )
}
