import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'
import { FileText } from 'lucide-react'

// Landing screen for Supabase invite / password-recovery email links. The link
// establishes a session (parsed from the URL by the supabase client), so an
// authenticated user lands here with no password set — this lets them choose one.
export function SetPassword() {
  const { session, loading } = useAuth()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    setSaving(true)
    try {
      const { error: updateError } = await supabase.auth.updateUser({ password })
      if (updateError) throw updateError
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not set password.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={wrap}>
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 28 }}>
          <FileText size={24} color="#6366f1" />
          <span style={{ fontWeight: 700, fontSize: 20, color: '#0f172a' }}>AR Tools</span>
        </div>

        {loading ? (
          <p style={{ fontSize: 14, color: '#64748b' }}>Verifying your link…</p>
        ) : !session ? (
          <>
            <h1 style={h1Style}>Link invalid or expired</h1>
            <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 20px' }}>
              This password link is no longer valid. Ask an admin to send a new invite or
              reset email, or sign in if you already have a password.
            </p>
            <Link to="/login" style={{ ...btnStyle, display: 'block', textAlign: 'center', textDecoration: 'none' }}>
              Go to sign in
            </Link>
          </>
        ) : (
          <>
            <h1 style={h1Style}>Set your password</h1>
            <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 24px' }}>
              Choose a password to finish setting up your account.
            </p>
            <form onSubmit={handleSubmit}>
              <label style={labelStyle}>New password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoFocus
                style={inputStyle}
                placeholder="At least 8 characters"
              />
              <label style={{ ...labelStyle, marginTop: 14 }}>Confirm password</label>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                style={inputStyle}
              />
              {error && (
                <div style={{ marginTop: 12, padding: '10px 12px', background: '#fef2f2', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>
                  {error}
                </div>
              )}
              <button type="submit" disabled={saving} style={btnStyle}>
                {saving ? 'Saving…' : 'Set password & continue'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}

const wrap: React.CSSProperties = { minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8fafc', fontFamily: 'system-ui, sans-serif' }
const card: React.CSSProperties = { background: '#fff', borderRadius: 12, padding: '40px 36px', width: 360, boxShadow: '0 4px 24px rgba(0,0,0,0.08)', border: '1px solid #e2e8f0' }
const h1Style: React.CSSProperties = { fontSize: 18, fontWeight: 600, color: '#0f172a', margin: '0 0 6px' }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 13, fontWeight: 500, color: '#374151', marginBottom: 6 }
const inputStyle: React.CSSProperties = { width: '100%', padding: '9px 12px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, outline: 'none', boxSizing: 'border-box', color: '#0f172a' }
const btnStyle: React.CSSProperties = { marginTop: 20, width: '100%', padding: '10px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 14, cursor: 'pointer' }
