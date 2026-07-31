import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'
import type { VoiceCompliance } from './types'

/**
 * Deterministic brand-guide audit of a generated page.
 *
 * Sits next to the Content Gaps panel deliberately: both answer "what is wrong
 * with this page that the score doesn't tell you". The composite score measures
 * SEO and AEO only — a page can score 85 and still contradict the client's brand
 * guide on every paragraph, which is exactly how a batch of pages passed our
 * checks and failed the client's review.
 *
 * These findings come from Python string matching, not an LLM judge, so a
 * `critical` row means the forbidden word is definitely on the page.
 *
 * Renders nothing when the client has no guide on file (no audit was possible),
 * and a compact pass confirmation when the page is clean — a check that is only
 * visible when it fails looks broken the rest of the time.
 */
export function VoiceCompliancePanel({ compliance }: { compliance?: VoiceCompliance | null }) {
  if (!compliance) return null

  const violations = compliance.violations || []
  const criticals = violations.filter((v) => v.severity === 'critical')
  const warnings = violations.filter((v) => v.severity !== 'critical')

  if (compliance.passed || violations.length === 0) {
    return (
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px',
          border: '1px solid #dcfce7', background: '#f0fdf4', borderRadius: 12,
        }}
      >
        <CheckCircle2 size={16} color="#16a34a" />
        <span style={{ fontSize: 13, color: '#166534' }}>
          Checked against the client's brand voice guide and ICP — no violations found.
        </span>
      </div>
    )
  }

  const hasCritical = criticals.length > 0

  return (
    <div style={{ border: `1px solid ${hasCritical ? '#fecaca' : '#fde68a'}`, borderRadius: 12, overflow: 'hidden' }}>
      <div
        style={{
          background: hasCritical ? '#fef2f2' : '#fffbeb',
          padding: '16px 20px',
          borderBottom: `1px solid ${hasCritical ? '#fecaca' : '#fde68a'}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {hasCritical ? <XCircle size={16} color="#dc2626" /> : <AlertTriangle size={16} color="#d97706" />}
          <p style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>
            {hasCritical ? 'This page breaks the brand guide' : 'Brand guide notes'}
          </p>
        </div>
        <p style={{ fontSize: 12, color: '#64748b', margin: '6px 0 0' }}>
          {hasCritical
            ? 'Automatic rewrites could not clear these. Fix them before publishing — the terms below are forbidden by the client\'s own guide.'
            : 'The page is publishable, but these points drift from the client\'s written guide.'}
        </p>
      </div>
      <div>
        {[...criticals, ...warnings].map((violation, i) => (
          <div key={i} style={{ padding: '14px 20px', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
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
    </div>
  )
}

const CHECK_LABELS: Record<string, string> = {
  never_use_terms: 'Forbidden words used',
  must_use_terms: 'Required phrasing missing',
  person: 'Wrong grammatical person',
  cta_language: 'CTA wording off-guide',
}
