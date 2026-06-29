import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Check, Circle, Sparkles, Loader2 } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

interface Engagement { id: string; status: string; autonomy_level: string }
interface Readiness { voice_approved: boolean; icp_ready: boolean; ready: boolean }

export function OnboardingWizard() {
  const { id: clientId } = useParams<{ id: string }>()
  const qc = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })
  const { data: engagement } = useQuery<Engagement | null>({
    queryKey: ['engagement', clientId],
    queryFn: () => api.get<Engagement | null>(`/clients/${clientId}/engagement`),
    enabled: Boolean(clientId),
  })
  const { data: readiness } = useQuery<Readiness>({
    queryKey: ['onboarding-readiness', clientId],
    queryFn: () => api.get<Readiness>(`/clients/${clientId}/onboarding-readiness`),
    enabled: Boolean(clientId),
  })

  const start = useMutation({
    mutationFn: () => api.post<Engagement>(`/clients/${clientId}/engagements`, { autonomy_level: 'assisted' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['engagement', clientId] }),
  })
  const advance = useMutation({
    mutationFn: () => api.post<Engagement>(`/engagements/${engagement?.id}/transition`, { to_status: 'intake' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['engagement', clientId] }),
  })

  const businessDone = Boolean(client?.gbp || client?.website_analysis_status === 'complete')
  const steps = [
    { key: 'business', label: 'Business profile', hint: 'GBP and/or website connected', done: businessDone, to: `/clients/${clientId}/edit` },
    { key: 'voice', label: 'Approve brand voice', hint: 'Set or accept the tone used across tools', done: Boolean(readiness?.voice_approved), to: `/clients/${clientId}/brand-voice` },
    { key: 'icp', label: 'Approve ICP', hint: 'Ideal customer profile / differentiators on file', done: Boolean(readiness?.icp_ready), to: `/clients/${clientId}/icp` },
    { key: 'targets', label: 'Add keywords & targets', hint: 'Optional now — feeds the trackers', done: false, optional: true, to: `/clients/${clientId}/keyword-portal` },
  ]

  const onboarding = !engagement || engagement.status === 'onboarding'

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '24px 20px' }}>
      <Link to={`/clients/${clientId}`} style={backLink}><ArrowLeft size={16} /> Back to workspace</Link>

      <header style={{ margin: '12px 0 20px' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Onboarding</h1>
        <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>
          Get <strong>{client?.name ?? 'this client'}</strong> ready for a managed engagement.
        </p>
      </header>

      {!engagement && (
        <div style={{ ...box, textAlign: 'center', padding: '28px 20px', marginBottom: 18 }}>
          <p style={{ fontSize: 14, color: '#475569', margin: '0 0 16px' }}>Start the engagement to begin onboarding.</p>
          <button onClick={() => start.mutate()} disabled={start.isPending} style={primaryBtn}>
            {start.isPending ? <Loader2 size={15} /> : <Sparkles size={15} />} Begin onboarding
          </button>
        </div>
      )}

      {engagement && !onboarding && (
        <div style={{ ...box, marginBottom: 18, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <span style={{ fontSize: 14, color: '#0f172a' }}>
            <Check size={15} color="#15803d" /> Onboarding complete — engagement is in <strong>{engagement.status}</strong>.
          </span>
          <Link to={`/clients/${clientId}/strategy`} style={openLink}>Strategy <ArrowRight size={14} /></Link>
        </div>
      )}

      <div style={{ display: 'grid', gap: 10, marginBottom: 18, opacity: engagement ? 1 : 0.55 }}>
        {steps.map((s, i) => (
          <Link key={s.key} to={engagement ? s.to : '#'} style={{ ...row, pointerEvents: engagement ? 'auto' : 'none' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              {s.done
                ? <Check size={18} color="#15803d" />
                : <Circle size={18} color="#cbd5e1" />}
              <span>
                <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>
                  {i + 1}. {s.label}{s.optional && <span style={{ color: '#94a3b8', fontWeight: 500 }}> · optional</span>}
                </span>
                <span style={{ display: 'block', fontSize: 12, color: '#64748b' }}>{s.hint}</span>
              </span>
            </span>
            <ArrowRight size={15} color="#94a3b8" />
          </Link>
        ))}
      </div>

      {engagement && onboarding && (
        <div style={box}>
          <button
            onClick={() => advance.mutate()}
            disabled={!readiness?.ready || advance.isPending}
            style={{ ...primaryBtn, width: '100%', justifyContent: 'center', opacity: !readiness?.ready || advance.isPending ? 0.5 : 1, cursor: !readiness?.ready ? 'not-allowed' : 'pointer' }}
          >
            {advance.isPending ? <Loader2 size={15} /> : <ArrowRight size={15} />} Complete onboarding → Intake
          </button>
          {!readiness?.ready && (
            <p style={{ fontSize: 12, color: '#94a3b8', textAlign: 'center', margin: '8px 0 0' }}>
              Approve brand voice and ICP to continue.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

const backLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b', textDecoration: 'none' }
const box: React.CSSProperties = { padding: '14px 16px', borderRadius: 12, border: '1px solid #e2e8f0', background: '#fff' }
const row: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '12px 14px', borderRadius: 10, border: '1px solid #e2e8f0', background: '#fff', textDecoration: 'none' }
const primaryBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderRadius: 10, border: 'none', background: '#6366f1', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer' }
const openLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 13, fontWeight: 600, color: '#6366f1', textDecoration: 'none' }
