import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import type { TeamUser } from '../lib/types'
import { UserPlus, Trash2, KeyRound, Mail, Check, X } from 'lucide-react'

function roleLabel(role: TeamUser['role']): string {
  return role === 'admin' ? 'Admin' : 'VA'
}

// Where invite / reset-email links land the user. Must be in Supabase's
// redirect allowlist. Uses the current app origin so it's correct per deploy.
const PW_REDIRECT = `${window.location.origin}/set-password`

export function Team() {
  const qc = useQueryClient()
  const { user } = useAuth()
  const myId = user?.id

  const [inviteEmail, setInviteEmail] = useState('')
  const [removeId, setRemoveId] = useState<string | null>(null)
  const [pwOpenId, setPwOpenId] = useState<string | null>(null)
  const [pwValue, setPwValue] = useState('')
  // Transient confirmation for actions that don't change the list (reset/set pw).
  const [flash, setFlash] = useState<{ id: string; msg: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const showFlash = (id: string, msg: string) => {
    setFlash({ id, msg })
    setTimeout(() => setFlash((f) => (f?.id === id ? null : f)), 4000)
  }

  const { data: users = [], isLoading } = useQuery<TeamUser[]>({
    queryKey: ['users'],
    queryFn: () => api.get<TeamUser[]>('/users'),
  })

  const inviteMutation = useMutation({
    mutationFn: (email: string) =>
      api.post('/users/invite', { email, role: 'team_member', redirect_to: PW_REDIRECT }),
    onSuccess: (_d, email) => {
      setInviteEmail('')
      setError(null)
      qc.invalidateQueries({ queryKey: ['users'] })
      showFlash('invite', `Invite sent to ${email}`)
    },
    onError: (e: Error) => setError(e.message),
  })

  const removeMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/users/${id}`),
    onSuccess: () => {
      setRemoveId(null)
      qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const resetMutation = useMutation({
    mutationFn: (id: string) => api.post(`/users/${id}/password-reset`, { redirect_to: PW_REDIRECT }),
    onSuccess: (_d, id) => showFlash(id, 'Reset email sent'),
    onError: (e: Error) => setError(e.message),
  })

  const setPwMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      api.post(`/users/${id}/password`, { password }),
    onSuccess: (_d, vars) => {
      setPwOpenId(null)
      setPwValue('')
      showFlash(vars.id, 'Password updated')
    },
    onError: (e: Error) => setError(e.message),
  })

  const canInvite = /\S+@\S+\.\S+/.test(inviteEmail)

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <div style={{ marginBottom: 8 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Team</h1>
        <p style={{ color: '#64748b', fontSize: 13, margin: '6px 0 0' }}>
          Invite VAs, remove access, and help them reset their passwords.
        </p>
      </div>

      {/* Invite */}
      <div style={cardStyle}>
        <div style={{ fontWeight: 600, fontSize: 14, color: '#0f172a', marginBottom: 12 }}>Add a VA</div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (canInvite) inviteMutation.mutate(inviteEmail.trim())
          }}
          style={{ display: 'flex', gap: 8, alignItems: 'center' }}
        >
          <input
            type="email"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            placeholder="va@example.com"
            style={inputStyle}
          />
          <button type="submit" disabled={!canInvite || inviteMutation.isPending} style={primaryBtn}>
            <UserPlus size={15} /> {inviteMutation.isPending ? 'Sending…' : 'Send invite'}
          </button>
        </form>
        <p style={{ color: '#94a3b8', fontSize: 12, margin: '10px 0 0' }}>
          The VA receives an email invite to set their own password and sign in.
        </p>
        {flash?.id === 'invite' && (
          <div style={{ color: '#16a34a', fontSize: 13, marginTop: 8 }}>{flash.msg}</div>
        )}
      </div>

      {error && (
        <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', color: '#dc2626', borderRadius: 8, padding: '10px 14px', fontSize: 13, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Members */}
      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading team…</div>
      ) : (
        <div style={cardStyle}>
          {users.map((u, i) => {
            const isSelf = u.id === myId
            return (
              <div
                key={u.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                  padding: '14px 0',
                  borderTop: i === 0 ? 'none' : '1px solid #f1f5f9',
                  flexWrap: 'wrap',
                }}
              >
                <div style={{ minWidth: 220 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600, fontSize: 14, color: '#0f172a' }}>
                      {u.full_name || u.email}
                    </span>
                    <span style={u.role === 'admin' ? adminBadge : vaBadge}>{roleLabel(u.role)}</span>
                    {isSelf && <span style={{ fontSize: 12, color: '#94a3b8' }}>(you)</span>}
                  </div>
                  {u.full_name && (
                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{u.email}</div>
                  )}
                </div>

                {!isSelf && (
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    {flash?.id === u.id && (
                      <span style={{ fontSize: 12, color: '#16a34a' }}>{flash.msg}</span>
                    )}

                    {pwOpenId === u.id ? (
                      <form
                        onSubmit={(e) => {
                          e.preventDefault()
                          if (pwValue.length >= 8) setPwMutation.mutate({ id: u.id, password: pwValue })
                        }}
                        style={{ display: 'flex', gap: 6, alignItems: 'center' }}
                      >
                        <input
                          type="text"
                          value={pwValue}
                          onChange={(e) => setPwValue(e.target.value)}
                          placeholder="New password (min 8)"
                          autoFocus
                          style={{ ...inputStyle, width: 200 }}
                        />
                        <button
                          type="submit"
                          disabled={pwValue.length < 8 || setPwMutation.isPending}
                          style={{ ...iconBtn, color: '#16a34a', borderColor: '#86efac' }}
                          title="Save password"
                        >
                          <Check size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => { setPwOpenId(null); setPwValue('') }}
                          style={iconBtn}
                          title="Cancel"
                        >
                          <X size={14} />
                        </button>
                      </form>
                    ) : removeId === u.id ? (
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <span style={{ fontSize: 12, color: '#dc2626' }}>Remove {u.email}?</span>
                        <button
                          onClick={() => removeMutation.mutate(u.id)}
                          disabled={removeMutation.isPending}
                          style={{ ...iconBtn, color: '#dc2626', borderColor: '#fca5a5' }}
                          title="Confirm remove"
                        >
                          <Check size={14} />
                        </button>
                        <button onClick={() => setRemoveId(null)} style={iconBtn} title="Cancel">
                          <X size={14} />
                        </button>
                      </div>
                    ) : (
                      <>
                        <button
                          onClick={() => { setError(null); resetMutation.mutate(u.id) }}
                          disabled={resetMutation.isPending}
                          style={textBtn}
                          title="Email a password-reset link"
                        >
                          <Mail size={13} /> Reset email
                        </button>
                        <button
                          onClick={() => { setError(null); setPwOpenId(u.id); setPwValue('') }}
                          style={textBtn}
                          title="Set a new password directly"
                        >
                          <KeyRound size={13} /> Set password
                        </button>
                        <button
                          onClick={() => { setError(null); setRemoveId(u.id) }}
                          style={{ ...textBtn, color: '#dc2626' }}
                          title="Remove user"
                        >
                          <Trash2 size={13} /> Remove
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
const inputStyle: React.CSSProperties = { flex: 1, padding: '8px 12px', border: '1px solid #cbd5e1', borderRadius: 8, fontSize: 13, color: '#0f172a', outline: 'none', minWidth: 220 }
const primaryBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap' }
const iconBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', padding: '6px', background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: 6, cursor: 'pointer' }
const textBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 5, padding: '6px 10px', background: '#fff', color: '#475569', border: '1px solid #e2e8f0', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 500 }
const vaBadge: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#4338ca', background: '#eef2ff', padding: '2px 8px', borderRadius: 999 }
const adminBadge: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#0369a1', background: '#e0f2fe', padding: '2px 8px', borderRadius: 999 }
