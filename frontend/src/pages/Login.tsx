import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { FileText } from 'lucide-react'

export function Login() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await signIn(email, password)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#f8fafc',
      fontFamily: 'system-ui, sans-serif',
    }}>
      <div style={{
        background: '#fff',
        borderRadius: 12,
        padding: '40px 36px',
        width: 360,
        boxShadow: '0 4px 24px rgba(0,0,0,0.08)',
        border: '1px solid #e2e8f0',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 28 }}>
          <FileText size={24} color="#6366f1" />
          <span style={{ fontWeight: 700, fontSize: 20, color: '#0f172a' }}>AR Tools</span>
        </div>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: '#0f172a', margin: '0 0 6px' }}>Sign in</h1>
        <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 24px' }}>Internal content platform</p>
        <form onSubmit={handleSubmit}>
          <label style={labelStyle}>Email</label>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
            style={inputStyle}
            placeholder="you@agency.com"
          />
          <label style={{ ...labelStyle, marginTop: 14 }}>Password</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            style={inputStyle}
          />
          {error && (
            <div style={{ marginTop: 12, padding: '10px 12px', background: '#fef2f2', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>
              {error}
            </div>
          )}
          <button type="submit" disabled={loading} style={btnStyle}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 500,
  color: '#374151',
  marginBottom: 6,
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '9px 12px',
  border: '1px solid #d1d5db',
  borderRadius: 8,
  fontSize: 14,
  outline: 'none',
  boxSizing: 'border-box',
  color: '#0f172a',
}

const btnStyle: React.CSSProperties = {
  marginTop: 20,
  width: '100%',
  padding: '10px',
  background: '#6366f1',
  color: '#fff',
  border: 'none',
  borderRadius: 8,
  fontWeight: 600,
  fontSize: 14,
  cursor: 'pointer',
}
