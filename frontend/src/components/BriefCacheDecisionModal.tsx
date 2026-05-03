/**
 * BriefCacheDecisionModal
 *
 * Shown before a run is launched (or re-launched) when a cached brief
 * already exists for the chosen keyword. Lets the user decide whether
 * to reuse the cached brief or force a regeneration. The choice flows
 * into `brief_force_refresh` on the run-create / rerun request.
 *
 * Pattern: modal opens after a pre-flight `GET /briefs/cache-status`
 * call returns `exists=true`. When `exists=false`, the caller skips
 * the modal and submits straight through.
 */

import type React from 'react'

export type BriefCacheStatus = {
  exists: boolean
  cached_at?: string | null
  age_days?: number | null
  schema_version?: string | null
}

type Props = {
  open: boolean
  cacheStatus: BriefCacheStatus | null
  onReuse: () => void
  onRegenerate: () => void
  onCancel: () => void
  busy?: boolean
}

export function BriefCacheDecisionModal({
  open,
  cacheStatus,
  onReuse,
  onRegenerate,
  onCancel,
  busy = false,
}: Props) {
  if (!open || !cacheStatus || !cacheStatus.exists) return null

  const ageDays = cacheStatus.age_days
  const ageLabel =
    ageDays == null
      ? 'recent'
      : ageDays < 1
        ? 'less than a day ago'
        : ageDays < 2
          ? '1 day ago'
          : `${Math.round(ageDays)} days ago`

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="brief-cache-modal-title"
      style={overlayStyle}
      onClick={(e) => {
        // Click on the backdrop (not the panel) cancels.
        if (e.target === e.currentTarget && !busy) onCancel()
      }}
    >
      <div style={panelStyle} onClick={(e) => e.stopPropagation()}>
        <h2 id="brief-cache-modal-title" style={titleStyle}>
          Cached brief found
        </h2>
        <p style={bodyStyle}>
          A brief for this keyword was generated <strong>{ageLabel}</strong>.
          You can reuse it (faster, cheaper) or regenerate from scratch (latest
          SERP and signals; takes ~60–120 seconds).
        </p>
        {cacheStatus.schema_version ? (
          <p style={metaStyle}>
            Cached schema: <code>{cacheStatus.schema_version}</code>
          </p>
        ) : null}
        <div style={actionsStyle}>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            style={ghostBtnStyle}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onRegenerate}
            disabled={busy}
            style={secondaryBtnStyle}
          >
            {busy ? 'Working…' : 'Regenerate'}
          </button>
          <button
            type="button"
            onClick={onReuse}
            disabled={busy}
            style={primaryBtnStyle}
          >
            {busy ? 'Working…' : 'Reuse cached'}
          </button>
        </div>
      </div>
    </div>
  )
}

const overlayStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  background: 'rgba(15, 23, 42, 0.55)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 1000,
}

const panelStyle: React.CSSProperties = {
  background: '#fff',
  borderRadius: 12,
  border: '1px solid #e2e8f0',
  padding: 24,
  width: 480,
  maxWidth: '92vw',
  boxShadow: '0 12px 40px rgba(15, 23, 42, 0.18)',
}

const titleStyle: React.CSSProperties = {
  fontSize: 17,
  fontWeight: 600,
  margin: '0 0 12px',
  color: '#0f172a',
}

const bodyStyle: React.CSSProperties = {
  fontSize: 13,
  color: '#475569',
  margin: '0 0 8px',
  lineHeight: 1.55,
}

const metaStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#94a3b8',
  margin: '0 0 18px',
}

const actionsStyle: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  justifyContent: 'flex-end',
  marginTop: 8,
}

const primaryBtnStyle: React.CSSProperties = {
  padding: '8px 14px',
  background: '#6366f1',
  color: '#fff',
  border: 'none',
  borderRadius: 8,
  fontWeight: 600,
  fontSize: 13,
  cursor: 'pointer',
}

const secondaryBtnStyle: React.CSSProperties = {
  padding: '8px 14px',
  background: '#fff',
  color: '#0f172a',
  border: '1px solid #cbd5e1',
  borderRadius: 8,
  fontWeight: 600,
  fontSize: 13,
  cursor: 'pointer',
}

const ghostBtnStyle: React.CSSProperties = {
  padding: '8px 14px',
  background: 'transparent',
  color: '#64748b',
  border: 'none',
  borderRadius: 8,
  fontWeight: 500,
  fontSize: 13,
  cursor: 'pointer',
}
