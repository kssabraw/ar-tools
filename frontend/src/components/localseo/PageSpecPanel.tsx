import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Download, FileJson, RefreshCw, Save } from 'lucide-react'
import { localSeoApi } from './api'
import type { PageSpec, PageSpecEnvelope, PageSpecSection } from './types'
import { downloadFile, outlineBtn, primaryBtn } from './shared'
import { Spinner } from './Spinner'

/**
 * The kept page spec for a keyword × location (docs/modules/local-seo-page-spec-plan-v1_0.md):
 * the page word band, per-section min/max bands and structure caps the writer
 * is held to, with provenance. Editable (min/max per section, page band) —
 * an edit sticks until "Rebuild" is pressed — and downloadable as JSON.
 *
 * Reading a spec never spends a paid call: it is built from the cached SERP
 * analysis + the client's reference layout, or falls back to the market's
 * standing target (flagged on the spec).
 */
export function PageSpecPanel({
  clientId, keyword, location, locationCode, defaultOpen = false,
}: {
  clientId: string
  keyword: string
  location: string
  locationCode?: number | null
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const queryClient = useQueryClient()
  const kw = keyword.trim()
  const loc = location.trim()
  const canLoad = !!clientId && kw.length > 0 && loc.length > 0
  const queryKey = ['local-seo-page-spec', clientId, kw, loc, locationCode ?? null]

  // The active spec (built + saved on first read; cache-only, no paid call).
  const query = useQuery<PageSpecEnvelope>({
    queryKey,
    queryFn: () => localSeoApi.getPageSpec(clientId, kw, loc, locationCode ?? null),
    enabled: open && canLoad,
    staleTime: 60_000,
  })
  const env = query.data ?? null

  // Unsaved edits are kept as overrides applied over the loaded spec at render
  // time (no effect-driven state copy), keyed by the spec version so a rebuild
  // or a save discards stale edits automatically.
  const [edits, setEdits] = useState<{ forId: string | null; total: Partial<PageSpec['total']>; sections: Record<number, Partial<PageSpecSection>> }>({ forId: null, total: {}, sections: {} })
  const editsApply = env && edits.forId === (env.id ?? null)
  const draft: PageSpec | null = env
    ? {
        ...env.spec,
        total: { ...env.spec.total, ...(editsApply ? edits.total : {}) },
        sections: env.spec.sections.map((s, i) => (editsApply && edits.sections[i] ? { ...s, ...edits.sections[i] } : s)),
      }
    : null
  const dirty = !!editsApply && (Object.keys(edits.total).length > 0 || Object.keys(edits.sections).length > 0)
  const [saving, setSaving] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const loading = query.isLoading || rebuilding
  const error = actionError ?? (query.error instanceof Error ? query.error.message : null)

  const load = async (rebuild = false) => {
    if (!canLoad) return
    if (!rebuild) { void query.refetch(); return }
    setRebuilding(true); setActionError(null)
    try {
      const res = await localSeoApi.rebuildPageSpec(clientId, { keyword: kw, location: loc, location_code: locationCode ?? null })
      queryClient.setQueryData(queryKey, res)
      setEdits({ forId: null, total: {}, sections: {} })
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Could not rebuild the page spec')
    } finally {
      setRebuilding(false)
    }
  }

  const save = async () => {
    if (!draft) return
    setSaving(true); setActionError(null)
    try {
      const res = await localSeoApi.editPageSpec(clientId, {
        keyword: kw, location: loc, location_code: locationCode ?? null, spec: draft,
      })
      queryClient.setQueryData(queryKey, res)
      setEdits({ forId: null, total: {}, sections: {} })
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Could not save the page spec')
    } finally {
      setSaving(false)
    }
  }

  const setSection = (idx: number, patch: Partial<PageSpecSection>) => {
    if (!env) return
    setEdits((e) => {
      const base = e.forId === (env.id ?? null) ? e : { forId: env.id ?? null, total: {}, sections: {} }
      return { ...base, sections: { ...base.sections, [idx]: { ...(base.sections[idx] || {}), ...patch } } }
    })
  }
  const setTotal = (patch: Partial<PageSpec['total']>) => {
    if (!env) return
    setEdits((e) => {
      const base = e.forId === (env.id ?? null) ? e : { forId: env.id ?? null, total: {}, sections: {} }
      return { ...base, total: { ...base.total, ...patch } }
    })
  }

  if (!canLoad) return null

  const spec = draft
  const sumMin = spec ? spec.sections.reduce((a, s) => a + (s.required ? s.min_words : 0), 0) : 0
  const sumMax = spec ? spec.sections.reduce((a, s) => a + s.max_words, 0) : 0
  const feasible = spec ? sumMin <= spec.total.max && sumMax >= spec.total.min : true
  const flags = spec?.provenance?.flags || []
  const ref = spec?.provenance?.reference

  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', background: '#f8fafc', border: 'none', borderBottom: open ? '1px solid #e2e8f0' : 'none', cursor: 'pointer', textAlign: 'left' }}
      >
        <FileJson size={16} color="#6366f1" />
        <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>Page spec</span>
        {spec && (
          <span style={{ fontSize: 12, color: '#64748b' }}>
            {spec.total.min}–{spec.total.max} words · {spec.sections.length} sections
            {spec.total.basis === 'fallback' ? ' · standing market target (no SERP measured)' : ' · from the competitor SERP'}
            {env?.edited_at ? ' · edited' : ''}
            {env?.version ? ` · v${env.version}` : ''}
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#94a3b8' }}>{open ? 'Hide' : 'Show'}</span>
      </button>

      {open && (
        <div style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {loading && !spec && <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, color: '#64748b' }}><Spinner size={14} /> Building the page spec…</div>}
          {error && <p style={{ fontSize: 13, color: '#dc2626', margin: 0 }}>{error}</p>}

          {spec && (
            <>
              {(flags.length > 0 || (ref && !ref.usable)) && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '10px 12px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e' }}>
                  <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                  <span>
                    {flags.includes('serp_target_missing') && 'No competitor SERP analysis is cached for this keyword — the band uses the market\'s standing target. Run an analysis (or generate the page) and rebuild to get the SERP-derived band. '}
                    {flags.includes('serp_too_few_pages') && 'Too few competitor pages were measured for a reliable target — using the standing target. '}
                    {flags.includes('serp_target_suspect') && 'The SERP-derived target fell outside the plausible range — using the standing target. '}
                    {ref && !ref.usable && `No usable reference page layout (${ref.reason || 'none on file'}) — the template layout is used. Add a reference local landing page on the client's Setup page to mirror the client's own structure.`}
                  </span>
                </div>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
                <Field label="Page minimum" value={spec.total.min} onChange={(v) => setTotal({ min: v })} />
                <Field label="Target" value={spec.total.target} onChange={(v) => setTotal({ target: v })} />
                <Field label="Page maximum" value={spec.total.max} onChange={(v) => setTotal({ max: v })} />
                <div style={{ fontSize: 12, color: '#64748b', alignSelf: 'end', paddingBottom: 6 }}>
                  Max {spec.structure.max_sections} sections · ≤{spec.structure.max_h3_per_h2} H3s per H2 · FAQ {spec.structure.faq.min}–{spec.structure.faq.max}
                </div>
              </div>

              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ color: '#64748b', textAlign: 'left' }}>
                      <th style={th}>Section</th><th style={th}>Intent</th><th style={th}>Min</th><th style={th}>Max</th><th style={th}>Blocks</th><th style={th}>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {spec.sections.map((s, i) => (
                      <tr key={s.key} style={{ borderTop: '1px solid #f1f5f9' }}>
                        <td style={td}>
                          <span style={{ fontFamily: 'monospace', color: '#0f172a' }}>{s.key}</span>
                          {!s.required && <span style={{ marginLeft: 6, fontSize: 10, color: '#94a3b8' }}>optional</span>}
                          {s.reference_heading && <div style={{ color: '#94a3b8', fontSize: 11 }}>{s.reference_heading}</div>}
                        </td>
                        <td style={td}>{s.intent}</td>
                        <td style={td}><input type="number" min={0} value={s.min_words} onChange={(e) => setSection(i, { min_words: Number(e.target.value) })} style={num} /></td>
                        <td style={td}><input type="number" min={0} value={s.max_words} onChange={(e) => setSection(i, { max_words: Number(e.target.value) })} style={num} /></td>
                        <td style={{ ...td, color: '#64748b' }}>{(s.blocks || []).map((b) => `${b.count}× ${b.type}${b.items ? ` (${b.items})` : ''}`).join(', ')}{s.subsections ? ` · ${s.subsections.min}–${s.subsections.max} sub-sections` : ''}</td>
                        <td style={{ ...td, color: '#94a3b8' }}>{s.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 12, color: feasible ? '#16a34a' : '#dc2626', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  {feasible ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
                  Required minimums {sumMin} · maximums {sumMax} vs page {spec.total.min}–{spec.total.max}
                  {!feasible && ' — infeasible: section bands must fit inside the page band'}
                </span>
                <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 8 }}>
                  <button style={outlineBtn} onClick={() => downloadFile(JSON.stringify(spec, null, 2), `page-spec-${kw.toLowerCase().replace(/\s+/g, '-')}.json`, 'application/json')}>
                    <Download size={13} /> JSON
                  </button>
                  <button style={outlineBtn} onClick={() => load(true)} disabled={loading} title="Rebuild from the current SERP analysis + reference layout (discards edits)">
                    <RefreshCw size={13} /> Rebuild
                  </button>
                  <button style={primaryBtn} onClick={save} disabled={!dirty || saving || !feasible}>
                    {saving ? <Spinner size={13} /> : <Save size={13} />} Save edits
                  </button>
                </span>
              </div>
              {ref?.usable && ref.url && (
                <p style={{ fontSize: 11, color: '#94a3b8', margin: 0 }}>
                  Layout from the client's {ref.page_type?.replace('_', ' ')} reference ({ref.total_words} words) · length from {spec.provenance.serp?.competitor_pages ? `${spec.provenance.serp.competitor_pages} competitor pages (avg ${spec.provenance.serp.avg_words})` : 'the standing market target'}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: '#64748b' }}>
      {label}
      <input type="number" min={0} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ ...num, width: '100%' }} />
    </label>
  )
}

const th = { padding: '6px 8px', fontWeight: 600 } as const
const td = { padding: '6px 8px', verticalAlign: 'top' } as const
const num = { width: 72, padding: '4px 6px', border: '1px solid #e2e8f0', borderRadius: 6, fontSize: 12 } as const

/** Compact target-vs-actual chip for a saved page row. */
export function LengthChip({ target, actual, status }: { target?: number | null; actual?: number | null; status?: string | null }) {
  if (actual == null || target == null) return null
  const tone = status === 'over_length'
    ? { bg: '#fef2f2', fg: '#dc2626', label: 'over' }
    : status === 'under_length'
      ? { bg: '#fffbeb', fg: '#d97706', label: 'under' }
      : { bg: '#f0fdf4', fg: '#16a34a', label: 'in band' }
  return (
    <span title={`${actual} words vs a target of ${target} — ${tone.label}`} style={{ fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4, background: tone.bg, color: tone.fg }}>
      {actual}/{target}w · {tone.label}
    </span>
  )
}

/** Per-client target-vs-actual rollup over saved pages (plan §5.6) — the drift
 *  table, so the next regression shows up here instead of in a page review. */
export function LengthSummary({ clientId }: { clientId: string }) {
  const { data } = useQuery({
    queryKey: ['local-seo-length-report', clientId],
    queryFn: () => localSeoApi.lengthReport(clientId),
    staleTime: 60_000,
  })
  if (!data || !data.with_spec) return null
  const pct = data.in_band_pct ?? 0
  const tone = pct >= 90 ? '#16a34a' : pct >= 70 ? '#d97706' : '#dc2626'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', padding: '10px 14px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, fontSize: 12, color: '#64748b' }}>
      <span style={{ fontWeight: 600, color: '#0f172a' }}>Length vs spec</span>
      <span><b style={{ color: tone }}>{data.in_band}</b> of {data.with_spec} in band ({pct}%)</span>
      {data.over_length > 0 && <span style={{ color: '#dc2626' }}>{data.over_length} over</span>}
      {data.under_length > 0 && <span style={{ color: '#d97706' }}>{data.under_length} under</span>}
      {data.avg_overage_pct != null && <span>avg {data.avg_overage_pct > 0 ? '+' : ''}{data.avg_overage_pct}% vs target</span>}
      {data.pages > data.with_spec && <span style={{ opacity: 0.7 }}>{data.pages - data.with_spec} pages predate specs</span>}
    </div>
  )
}
