import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, RefreshCw, Save, Send } from 'lucide-react'
import { api } from '../lib/api'

// Weekly Pulse — the copy-paste client update ("done last week / on tap this
// week"), generated weekly per client and shown here for STAFF to deliver
// (paste into their own email/message and personalize). Never auto-sent.
// Rows purge server-side after ~2 weeks.

interface Pulse {
  body: string
  // At-a-glance bullet version (null on rows generated before the list view
  // shipped — the toggle falls back to the narrative until a regenerate).
  body_list?: string | null
  week_start?: string
  created_at?: string
  // True once a staff member has saved a manual edit — protects the pulse from
  // being overwritten by the weekly auto-generation or an unforced regenerate.
  edited?: boolean
}

export function WeeklyPulse({ clientId }: { clientId: string }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [view, setView] = useState<'email' | 'list'>('email')
  const { data, isLoading } = useQuery<Pulse>({
    queryKey: ['client-pulse', clientId],
    queryFn: () => api.get<Pulse>(`/clients/${clientId}/pulse`),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })
  const regen = useMutation({
    mutationFn: (force: boolean) =>
      api.post<Pulse>(`/clients/${clientId}/pulse/regenerate`, { force }),
    onSuccess: (fresh) => qc.setQueryData(['client-pulse', clientId], fresh),
  })

  // Regenerate replaces the pulse with a fresh rewrite. If the pulse was
  // manually edited, confirm first (and force past the server-side guard).
  const doRegenerate = () => {
    if (data?.edited &&
        !window.confirm('This replaces your saved edits with a fresh version. Continue?')) {
      return
    }
    regen.mutate(Boolean(data?.edited))
  }
  const save = useMutation({
    mutationFn: () =>
      api.put<Pulse>(`/clients/${clientId}/pulse`, view === 'list' ? { body_list: draft } : { body: draft }),
    onSuccess: (fresh) => qc.setQueryData(['client-pulse', clientId], fresh),
  })

  // The active view's text: List falls back to the narrative for pre-upgrade
  // rows (regenerate fills body_list). Copy follows whichever view is shown.
  const activeText = view === 'list' ? (data?.body_list || data?.body || '') : (data?.body || '')

  // Editable draft, reseeded whenever the stored text or the view changes
  // (a regenerate/save replaces the server copy → the editor follows it).
  const [draft, setDraft] = useState('')
  useEffect(() => {
    setDraft(activeText)
  }, [activeText])
  const dirty = draft !== activeText

  const copy = async () => {
    if (!draft) return
    try {
      await navigator.clipboard.writeText(draft)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      /* clipboard denied — the text is selectable below */
    }
  }

  return (
    <section style={wrap}>
      <button style={header} onClick={() => setOpen((o) => !o)}>
        <Send size={15} style={{ color: '#4f46e5' }} />
        <span style={{ fontWeight: 700, color: '#0f172a', fontSize: 14 }}>Weekly Pulse</span>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>
          — copy-paste client update (done last week / on tap this week)
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#4f46e5', fontWeight: 600 }}>
          {open ? 'Hide' : 'Show'}
        </span>
      </button>
      {open && (
        <div style={{ padding: '0 14px 14px' }}>
          {isLoading ? (
            <div style={{ fontSize: 13, color: '#94a3b8', padding: '8px 0' }}>Building…</div>
          ) : data?.body ? (
            <>
              <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
                <button style={view === 'email' ? viewChipOn : viewChip} onClick={() => setView('email')}>
                  Email
                </button>
                <button style={view === 'list' ? viewChipOn : viewChip} onClick={() => setView('list')}>
                  List
                </button>
                {view === 'list' && !data.body_list && (
                  <span style={{ fontSize: 11, color: '#94a3b8', alignSelf: 'center' }}>
                    (list version generates on the next Regenerate)
                  </span>
                )}
              </div>
              <textarea
                style={bodyBox}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                spellCheck
                aria-label="Weekly pulse text — edit before copying"
              />
              <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                <button style={primaryBtn} onClick={copy}>
                  {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : 'Copy to clipboard'}
                </button>
                <button
                  style={dirty && !save.isPending ? saveBtn : saveBtnDisabled}
                  disabled={!dirty || save.isPending}
                  onClick={() => save.mutate()}
                >
                  {save.isSuccess && !dirty ? <Check size={14} /> : <Save size={14} />}{' '}
                  {save.isPending ? 'Saving…' : save.isSuccess && !dirty ? 'Saved' : 'Save'}
                </button>
                <button style={ghostBtn} disabled={regen.isPending} onClick={doRegenerate}>
                  <RefreshCw size={13} style={regen.isPending ? { animation: 'spin 1s linear infinite' } : undefined} />
                  {regen.isPending ? 'Regenerating…' : 'Regenerate'}
                </button>
                {data.edited && (
                  <span style={editedBadge} title="Your saved edits won't be overwritten by the weekly refresh.">
                    edited — protected
                  </span>
                )}
                {data.week_start && (
                  <span style={{ fontSize: 11.5, color: '#94a3b8' }}>
                    week of {data.week_start} · edit &amp; Save, or Copy into your email and personalize the greeting
                  </span>
                )}
              </div>
            </>
          ) : (
            <div style={{ fontSize: 13, color: '#94a3b8', padding: '8px 0' }}>No pulse yet.</div>
          )}
        </div>
      )}
    </section>
  )
}

const wrap: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 12, background: '#fff', marginBottom: 16,
}
const header: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
  padding: '12px 14px', background: 'transparent', border: 'none', cursor: 'pointer',
}
const bodyBox: React.CSSProperties = {
  margin: 0, padding: '12px 14px', background: '#f8fafc', border: '1px solid #e2e8f0',
  borderRadius: 10, fontSize: 12.5, lineHeight: 1.55, color: '#0f172a',
  whiteSpace: 'pre-wrap', fontFamily: 'inherit',
  width: '100%', boxSizing: 'border-box', minHeight: 180, maxHeight: 360,
  resize: 'vertical', display: 'block',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px',
  fontSize: 12.5, fontWeight: 600, color: '#fff', background: '#4f46e5',
  border: 'none', borderRadius: 8, cursor: 'pointer',
}
const saveBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px',
  fontSize: 12.5, fontWeight: 600, color: '#fff', background: '#16a34a',
  border: 'none', borderRadius: 8, cursor: 'pointer',
}
const saveBtnDisabled: React.CSSProperties = {
  ...saveBtn, background: '#e2e8f0', color: '#94a3b8', cursor: 'default',
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px',
  fontSize: 12.5, fontWeight: 600, color: '#4f46e5', background: '#eef2ff',
  border: 'none', borderRadius: 8, cursor: 'pointer',
}
const editedBadge: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#166534', background: '#dcfce7',
  border: '1px solid #bbf7d0', borderRadius: 999, padding: '2px 8px',
}
const viewChip: React.CSSProperties = {
  padding: '4px 12px', fontSize: 12, fontWeight: 600, color: '#64748b',
  background: '#f1f5f9', border: '1px solid #e2e8f0', borderRadius: 999, cursor: 'pointer',
}
const viewChipOn: React.CSSProperties = {
  ...viewChip, color: '#fff', background: '#4f46e5', borderColor: '#4f46e5',
}
