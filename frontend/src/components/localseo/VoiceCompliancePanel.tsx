import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'
import type { VoiceCompliance, VoiceDimension } from './types'

/**
 * The brand-voice scorecard for a generated page.
 *
 * Deliberately its own headline score rather than a slice of the SEO composite.
 * A single weighted engine cannot move a composite enough to matter — a page
 * scoring 40 on voice would still read "good" overall — and burying voice
 * inside an SEO number is what let it be ignored in the first place.
 *
 * Two layers, in order of how much you can trust them:
 *  - the deterministic violations (Python string matching, so a forbidden word
 *    found here is a fact, not an opinion)
 *  - the eight scored dimensions, judged by the scorer against the client's
 *    written guide, each with a quote from the page as evidence
 *
 * Renders nothing when the client has no guide on file — there was nothing to
 * score against, and an empty scorecard would imply the page was checked.
 */
export function VoiceCompliancePanel({ compliance }: { compliance?: VoiceCompliance | null }) {
  if (!compliance) return null

  const violations = compliance.violations || []
  const criticals = violations.filter((v) => v.severity === 'critical')
  const warnings = violations.filter((v) => v.severity !== 'critical')
  const dimensions = Object.entries(compliance.dimensions || {})
    .filter(([, d]) => typeof d.score === 'number')
    .sort((a, b) => (a[1].score ?? 100) - (b[1].score ?? 100))

  const score = compliance.score
  const band = compliance.band || 'not_scored'
  const tone = BAND_TONE[band] || BAND_TONE.not_scored
  const clean = criticals.length === 0 && (score === null || score === undefined || score >= 80)

  return (
    <div style={{ border: `1px solid ${tone.border}`, borderRadius: 12, overflow: 'hidden' }}>
      {/* Headline */}
      <div style={{ background: tone.bg, padding: '16px 20px', borderBottom: `1px solid ${tone.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {clean
            ? <CheckCircle2 size={18} color={tone.fg} />
            : criticals.length
              ? <XCircle size={18} color={tone.fg} />
              : <AlertTriangle size={18} color={tone.fg} />}
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>
              Brand voice{typeof score === 'number' ? ` — ${Math.round(score)}/100` : ''}
            </p>
            <p style={{ fontSize: 12, color: '#64748b', margin: '2px 0 0' }}>{tone.label}</p>
          </div>
          {typeof score === 'number' && (
            <span
              style={{
                fontSize: 22, fontWeight: 700, color: tone.fg, fontVariantNumeric: 'tabular-nums',
              }}
            >
              {Math.round(score)}
            </span>
          )}
        </div>
        <p style={{ fontSize: 11, color: '#94a3b8', margin: '10px 0 0' }}>
          Measured against this client's own brand guide and ICP. Scored separately from the SEO
          score — a page can rank well and still not sound like them.
        </p>
      </div>

      {/* Deterministic findings first — these are facts, not judgements */}
      {violations.length > 0 && (
        <div>
          {[...criticals, ...warnings].map((violation, i) => (
            <div key={i} style={{ padding: '12px 20px', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span
                  style={{
                    fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999,
                    background: violation.severity === 'critical' ? '#fef2f2' : '#fffbeb',
                    color: violation.severity === 'critical' ? '#dc2626' : '#d97706',
                  }}
                >
                  {violation.severity === 'critical' ? 'Must fix' : 'Review'}
                </span>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>
                  {CHECK_LABELS[violation.check] || violation.check}
                </span>
              </div>
              <p style={{ fontSize: 12, color: '#475569', margin: 0 }}>{violation.message}</p>
              {violation.detail && (
                <p style={{ fontSize: 11, color: '#94a3b8', margin: '4px 0 0' }}>{violation.detail}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Per-dimension breakdown — worst first, so the fix list reads top-down */}
      {dimensions.length > 0 && (
        <div style={{ borderTop: '1px solid #f1f5f9', padding: '4px 0' }}>
          {dimensions.map(([key, dimension]) => (
            <DimensionRow key={key} dimension={dimension} />
          ))}
        </div>
      )}
    </div>
  )
}

function DimensionRow({ dimension }: { dimension: VoiceDimension }) {
  const score = dimension.score ?? 0
  const colour = score >= 80 ? '#16a34a' : score >= 60 ? '#d97706' : '#dc2626'
  const notes = [...(dimension.issues || []), ...(dimension.recommendations || [])]

  return (
    <div style={{ padding: '10px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 13, color: '#0f172a', flex: 1 }}>{dimension.label}</span>
        <div style={{ width: 120, height: 6, background: '#f1f5f9', borderRadius: 999, overflow: 'hidden' }}>
          <div style={{ width: `${Math.max(0, Math.min(100, score))}%`, height: '100%', background: colour }} />
        </div>
        <span
          style={{
            fontSize: 12, fontWeight: 600, color: colour, width: 30, textAlign: 'right',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {Math.round(score)}
        </span>
      </div>
      {score < 80 && notes.length > 0 && (
        <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
          {notes.slice(0, 3).map((note, i) => (
            <li key={i} style={{ fontSize: 12, color: '#64748b' }}>{note}</li>
          ))}
        </ul>
      )}
      {score < 80 && dimension.evidence && (
        <p style={{ fontSize: 11, color: '#94a3b8', margin: '4px 0 0', fontStyle: 'italic' }}>
          “{dimension.evidence}”
        </p>
      )}
      {dimension.capped_by_check && (
        <p style={{ fontSize: 11, color: '#dc2626', margin: '4px 0 0' }}>
          Capped — the automatic check found a {CHECK_LABELS[dimension.capped_by_check]?.toLowerCase()
            || dimension.capped_by_check} problem on the page.
        </p>
      )}
    </div>
  )
}

const BAND_TONE: Record<string, { bg: string; border: string; fg: string; label: string }> = {
  on_voice: { bg: '#f0fdf4', border: '#dcfce7', fg: '#16a34a', label: 'Sounds like this client.' },
  mostly_on_voice: {
    bg: '#f0fdf4', border: '#dcfce7', fg: '#16a34a',
    label: 'Mostly on voice — minor drift worth a read.',
  },
  drifting: {
    bg: '#fffbeb', border: '#fde68a', fg: '#d97706',
    label: 'Drifting from the guide. Review before publishing.',
  },
  off_voice: {
    bg: '#fef2f2', border: '#fecaca', fg: '#dc2626',
    label: 'This does not sound like the client. Automatic rewrites could not fix it.',
  },
  not_scored: {
    bg: '#f8fafc', border: '#e2e8f0', fg: '#64748b',
    label: 'Checked against the guide, but the scorecard could not be produced.',
  },
}

const CHECK_LABELS: Record<string, string> = {
  never_use_terms: 'Forbidden words used',
  must_use_terms: 'Required phrasing missing',
  person: 'Wrong grammatical person',
  cta_language: 'CTA wording off-guide',
}
