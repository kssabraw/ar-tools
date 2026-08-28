import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Info, Loader2, Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { ACCENT, btn, card, denyReason, input } from './shared'
import type { CityRow, PlanIssue, PlanResponse, ServiceRow, ServiceVariation, Website } from './shared'
import { ContentPlanEditor } from './ContentPlanEditor'
import { api } from '../../lib/api'

// Fold a pre-generalization service (equipment `brands`) into the current
// `variations` shape so an older stored catalog edits cleanly and its next save
// migrates it forward. A row already carrying `variations` wins; `brands` is
// dropped either way so the two never double up at the backend parser.
function normalizeService(row: ServiceRow): ServiceRow {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { brands, ...rest } = row
  if (rest.variations) return rest
  if (brands?.length) return { ...rest, variations: brands.map((b) => ({ label: b, kind: 'brand' as const })) }
  return rest
}

// Plan review (PRD §6.2). Two rules shape this screen:
//
//  * A blocking issue is either a planning *error* — wrong, fix the catalog —
//    or a scale *gate*, which is a judgement about size and clears with a named
//    sign-off. The screen has to make that difference obvious, because only one
//    of them has a button.
//  * Every non-CORE page shows the trigger that matched it. A reviewer must be
//    able to see *why* a page was proposed, not just that it was.

interface Props {
  website: Website
  plan: PlanResponse | undefined
  perms: { isStaff: boolean; isAdmin: boolean; frozen: boolean }
}

export function PlanTab({ website, plan, perms }: Props) {
  const qc = useQueryClient()
  const stored = website.config as { catalog?: ServiceRow[]; cities?: CityRow[] }
  const [services, setServices] = useState<ServiceRow[]>((stored.catalog ?? []).map(normalizeService))
  const [cities, setCities] = useState<CityRow[]>(stored.cities ?? [])
  const [acked, setAcked] = useState<Set<string>>(new Set())

  // Re-seed when the stored catalog arrives or changes underneath us.
  useEffect(() => {
    setServices((stored.catalog ?? []).map(normalizeService))
    setCities(stored.cities ?? [])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(stored.catalog), JSON.stringify(stored.cities)])

  const deny = denyReason('staff', perms)
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['website', website.id] })
    void qc.invalidateQueries({ queryKey: ['website-plan', website.id] })
  }

  const build = useMutation({
    mutationFn: () => api.post(`/websites/${website.id}/plan`, { catalog: services, cities }),
    onSuccess: invalidate,
  })

  const approve = useMutation({
    mutationFn: () => api.post(`/websites/${website.id}/plan/approve`, {
      acknowledge: [...acked],
      override_conflicts: [...acked].includes('portfolio_conflict'),
    }),
    onSuccess: invalidate,
  })

  const issues = [...(plan?.plan.issues ?? []), ...(plan?.conflicts ?? [])]
  const blockers = issues.filter((i) => i.blocking)
  const unsigned = blockers.filter((i) => !(i.acknowledgeable && acked.has(i.kind)))
  const advisories = issues.filter((i) => !i.blocking)

  const toggleAck = (kind: string) => setAcked((prev) => {
    const next = new Set(prev)
    if (next.has(kind)) next.delete(kind); else next.add(kind)
    return next
  })

  // A geo site is planned from its catalog × cities; an informational site has
  // no such half — its inventory is entirely its blog content plan. Both site
  // families can carry a blog, so the content plan shows for all.
  const isGeo = website.site_type === 'local_business' || website.site_type === 'lead_gen'

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      {isGeo && (
        <>
          <div style={card}>
            <strong style={{ fontSize: 14, color: '#0f172a' }}>Service catalog</strong>
            <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 12px' }}>
              The billable jobs, in the client's own words. Never imported from GBP categories —
              a category is a taxonomy label and a service is a billable job, and wiring one into
              the other produces the wrong page inventory. Unticking <em>In matrix</em> gives a
              service its own page but no service × city pages.
            </p>
            <ServiceEditor rows={services} onChange={setServices} disabled={Boolean(deny)} />
          </div>

          <div style={card}>
            <strong style={{ fontSize: 14, color: '#0f172a' }}>Cities</strong>
            <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 12px' }}>
              One location page each, plus a service × city page per matrix service. A single-city
              business gets neither — its service pages geo-target the one city instead. Only
              neighborhoods that pass the Maps entity test belong here.
            </p>
            <CityEditor rows={cities} onChange={setCities} disabled={Boolean(deny)} />
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              onClick={() => build.mutate()}
              disabled={Boolean(deny) || build.isPending || services.length === 0}
              title={deny ?? (services.length === 0 ? 'Add at least one service — Plan Silo consumes a service list, it does not invent one.' : undefined)}
              style={{ ...btn(deny || services.length === 0 ? '#e2e8f0' : ACCENT, deny || services.length === 0 ? '#94a3b8' : '#fff') }}
            >
              {build.isPending ? <Loader2 size={14} className="spin" /> : null}
              {plan?.plan.pages.length ? 'Rebuild plan' : 'Build plan'}
            </button>
            {plan?.plan.pages.length ? (
              <span style={{ fontSize: 12, color: '#64748b' }}>
                {plan.plan.pages.length} pages · {plan.plan.matrix_count} matrix
              </span>
            ) : null}
          </div>
          {build.error && <ErrorNote message={(build.error as Error).message} />}
        </>
      )}

      {/* The blog content plan — its Save/seed rebuild the plan, which is the
          whole build for an informational site and the blog half for a geo one. */}
      <ContentPlanEditor website={website} perms={perms} />

      {plan && plan.plan.pages.length > 0 && (
        <>
          {blockers.length > 0 && (
            <div style={{ ...card, borderColor: '#fecaca', background: '#fef2f2' }}>
              <strong style={{ fontSize: 14, color: '#b91c1c', display: 'flex', alignItems: 'center', gap: 6 }}>
                <AlertTriangle size={15} /> Blocks approval
              </strong>
              <div style={{ display: 'grid', gap: 10, marginTop: 10 }}>
                {blockers.map((issue, i) => (
                  <IssueRow key={`${issue.kind}-${i}`} issue={issue} acked={acked.has(issue.kind)}
                            onToggle={() => toggleAck(issue.kind)} disabled={Boolean(deny)}
                            adminOnly={issue.kind === 'portfolio_conflict'} isAdmin={perms.isAdmin} />
                ))}
              </div>
            </div>
          )}

          {advisories.length > 0 && (
            <div style={{ ...card, borderColor: '#fed7aa', background: '#fffbeb' }}>
              <strong style={{ fontSize: 14, color: '#b45309', display: 'flex', alignItems: 'center', gap: 6 }}>
                <Info size={15} /> Advisory
              </strong>
              <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: 12, color: '#92400e' }}>
                {advisories.map((issue, i) => <li key={i}>{issue.detail}</li>)}
              </ul>
            </div>
          )}

          <div style={card}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <strong style={{ fontSize: 14, color: '#0f172a' }}>Proposed pages</strong>
              {plan.approved ? (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#15803d', fontWeight: 600 }}>
                  <CheckCircle2 size={14} /> Approved
                  {plan.approval.acknowledged?.length ? ` · signed off: ${plan.approval.acknowledged.join(', ')}` : ''}
                </span>
              ) : (
                <button
                  onClick={() => approve.mutate()}
                  disabled={Boolean(deny) || unsigned.length > 0 || approve.isPending}
                  title={deny ?? (unsigned.length > 0 ? 'Clear or sign off every blocking issue first.' : undefined)}
                  style={{ ...btn(deny || unsigned.length > 0 ? '#e2e8f0' : '#15803d', deny || unsigned.length > 0 ? '#94a3b8' : '#fff') }}
                >
                  {approve.isPending ? <Loader2 size={14} className="spin" /> : <ShieldCheck size={14} />}
                  Approve plan
                </button>
              )}
            </div>
            {approve.error && <ErrorNote message={(approve.error as Error).message} />}

            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: '#64748b' }}>
                  <th style={th}>Tier</th><th style={th}>Path</th><th style={th}>Type</th>
                  <th style={th}>Why it was proposed</th><th style={th}>Links</th>
                </tr>
              </thead>
              <tbody>
                {plan.plan.pages.map((p) => (
                  <tr key={p.path} style={{ borderTop: '1px solid #f1f5f9' }}>
                    <td style={td}>{p.tier}</td>
                    <td style={{ ...td, fontFamily: 'ui-monospace, monospace' }}>{p.path}</td>
                    <td style={td}>{p.page_type}</td>
                    <td style={{ ...td, color: p.is_core ? '#15803d' : p.is_core_conditional ? '#0369a1' : '#64748b' }}>
                      {p.trigger}
                    </td>
                    <td style={td}>{plan.plan.links_per_index[p.path] ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

const th: React.CSSProperties = { padding: '6px 8px', fontWeight: 600 }
const td: React.CSSProperties = { padding: '6px 8px', verticalAlign: 'top' }

function ErrorNote({ message }: { message: string }) {
  return (
    <div style={{ padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
      {message}
    </div>
  )
}

function IssueRow({ issue, acked, onToggle, disabled, adminOnly, isAdmin }: {
  issue: PlanIssue; acked: boolean; onToggle: () => void
  disabled: boolean; adminOnly: boolean; isAdmin: boolean
}) {
  const blocked = adminOnly && !isAdmin
  return (
    <div style={{ fontSize: 12, color: '#7f1d1d' }}>
      <div>{issue.detail}</div>
      {issue.acknowledgeable ? (
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 4, cursor: disabled || blocked ? 'not-allowed' : 'pointer' }}
               title={blocked ? 'A property-vs-client overlap needs an admin to override.' : undefined}>
          <input type="checkbox" checked={acked} onChange={onToggle} disabled={disabled || blocked} />
          <span style={{ fontWeight: 600 }}>
            Sign this off {blocked ? '(admins only)' : ''}
          </span>
        </label>
      ) : (
        <div style={{ marginTop: 2, fontStyle: 'italic' }}>
          Not overridable — fix the catalog. A published slug is immutable, so a wrong URL
          costs a permanent redirect rather than an edit.
        </div>
      )}
    </div>
  )
}

function ServiceEditor({ rows, onChange, disabled }: {
  rows: ServiceRow[]; onChange: (r: ServiceRow[]) => void; disabled: boolean
}) {
  const update = (i: number, patch: Partial<ServiceRow>) =>
    onChange(rows.map((r, j) => (i === j ? { ...r, ...patch } : r)))

  return (
    <div style={{ display: 'grid', gap: 6 }}>
      {rows.map((row, i) => (
        <div key={i} style={{ display: 'grid', gap: 5 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 2fr auto auto auto', gap: 6, alignItems: 'center' }}>
            <input style={input} placeholder="Service name" value={row.name} disabled={disabled}
                   onChange={(e) => update(i, { name: e.target.value })} />
            <input style={input} placeholder="Short description (nav, cards, index)" value={row.teaser ?? ''} disabled={disabled}
                   onChange={(e) => update(i, { teaser: e.target.value })} />
            <select style={{ ...input, width: 150 }} value={row.parent_slug ?? ''} disabled={disabled}
                    onChange={(e) => update(i, { parent_slug: e.target.value || null })}>
              <option value="">Top-level</option>
              {rows.filter((r, j) => j !== i && !r.parent_slug && r.name).map((r, j) => (
                <option key={j} value={slugify(r.slug || r.name)}>under {r.name}</option>
              ))}
            </select>
            <label style={{ fontSize: 11, color: '#475569', display: 'inline-flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}>
              <input type="checkbox" checked={row.include_in_matrix !== false} disabled={disabled}
                     onChange={(e) => update(i, { include_in_matrix: e.target.checked })} />
              In matrix
            </label>
            <button onClick={() => onChange(rows.filter((_, j) => j !== i))} disabled={disabled}
                    style={{ ...btn('#fff', '#b91c1c'), padding: '6px 8px' }} title="Remove">
              <Trash2 size={13} />
            </button>
          </div>
          {/* Service variations: a top-level service can auto-generate child
              pages at /{service}/{modifier}/. A "type" modifier becomes a
              sub-service (Oak Tree Removal); a "brand" modifier a brand × service
              page (Carrier AC Repair). Sub-services take none — that depth is the
              hyper-local escalation, not a variation cell. */}
          {!row.parent_slug && (
            <VariationEditor
              variations={row.variations ?? []}
              onChange={(variations) => update(i, { variations })}
              disabled={disabled}
            />
          )}
        </div>
      ))}
      <button onClick={() => onChange([...rows, { name: '', order: (rows.length + 1) * 10, include_in_matrix: true }])}
              disabled={disabled} style={{ ...btn('#fff', ACCENT), justifySelf: 'start' }}>
        <Plus size={13} /> Add service
      </button>
    </div>
  )
}

function VariationEditor({ variations, onChange, disabled }: {
  variations: ServiceVariation[]; onChange: (v: ServiceVariation[]) => void; disabled: boolean
}) {
  const update = (i: number, patch: Partial<ServiceVariation>) =>
    onChange(variations.map((v, j) => (i === j ? { ...v, ...patch } : v)))

  return (
    <div style={{ display: 'grid', gap: 4, paddingLeft: 8, borderLeft: '2px solid #f1f5f9' }}>
      {variations.length > 0 && (
        <span style={{ fontSize: 11, color: '#94a3b8' }}>
          Service variations — each becomes a page at /{'{service}'}/{'{modifier}'}/
        </span>
      )}
      {variations.map((v, i) => (
        <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 120px auto', gap: 6, alignItems: 'center' }}>
          <input style={{ ...input, fontSize: 12 }}
                 placeholder={v.kind === 'brand' ? 'Brand — e.g. Carrier' : 'Variation — e.g. Oak Tree Removal'}
                 value={v.label} disabled={disabled}
                 onChange={(e) => update(i, { label: e.target.value })} />
          <select style={{ ...input, fontSize: 12, width: 120 }} value={v.kind} disabled={disabled}
                  onChange={(e) => update(i, { kind: e.target.value as ServiceVariation['kind'] })}
                  title="Type = a narrower service (sub-service). Brand = equipment brand.">
            <option value="type">Type</option>
            <option value="brand">Brand</option>
          </select>
          <button onClick={() => onChange(variations.filter((_, j) => j !== i))} disabled={disabled}
                  style={{ ...btn('#fff', '#b91c1c'), padding: '5px 7px' }} title="Remove variation">
            <Trash2 size={12} />
          </button>
        </div>
      ))}
      <button onClick={() => onChange([...variations, { label: '', kind: 'type' }])} disabled={disabled}
              style={{ ...btn('#fff', ACCENT), justifySelf: 'start', padding: '4px 9px', fontSize: 12 }}>
        <Plus size={11} /> Add variation
      </button>
    </div>
  )
}

function CityEditor({ rows, onChange, disabled }: {
  rows: CityRow[]; onChange: (r: CityRow[]) => void; disabled: boolean
}) {
  const update = (i: number, patch: Partial<CityRow>) =>
    onChange(rows.map((r, j) => (i === j ? { ...r, ...patch } : r)))

  return (
    <div style={{ display: 'grid', gap: 6 }}>
      {rows.map((row, i) => (
        <div key={i} style={{ display: 'grid', gridTemplateColumns: '1.4fr 2fr auto', gap: 6, alignItems: 'center' }}>
          <input style={input} placeholder="City" value={row.name} disabled={disabled}
                 onChange={(e) => update(i, { name: e.target.value })} />
          <input style={input} placeholder="Neighborhoods, comma separated (optional)"
                 value={(row.neighborhoods ?? []).map((n) => n.name).join(', ')} disabled={disabled}
                 onChange={(e) => update(i, {
                   neighborhoods: e.target.value.split(',').map((s) => s.trim()).filter(Boolean).map((name) => ({ name })),
                 })} />
          <button onClick={() => onChange(rows.filter((_, j) => j !== i))} disabled={disabled}
                  style={{ ...btn('#fff', '#b91c1c'), padding: '6px 8px' }} title="Remove">
            <Trash2 size={13} />
          </button>
        </div>
      ))}
      <button onClick={() => onChange([...rows, { name: '' }])} disabled={disabled}
              style={{ ...btn('#fff', ACCENT), justifySelf: 'start' }}>
        <Plus size={13} /> Add city
      </button>
    </div>
  )
}

const slugify = (v: string) => v.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

