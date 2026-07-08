import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { supabase } from '../lib/supabase'
import type { Profile, UserRole } from '../lib/types'

interface AuthContextValue {
  session: Session | null
  user: User | null
  profile: Profile | null
  role: UserRole | null
  isAdmin: boolean
  // Senior operator (staff or admin) — everything except user/team management.
  isStaff: boolean
  // External read-only viewer.
  isClient: boolean
  // Any internal user (not a read-only client).
  isInternal: boolean
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchProfile(s: Session | null) {
      if (!s?.user) {
        setProfile(null)
        return
      }
      const { data } = await supabase
        .from('profiles')
        .select('id, role, full_name')
        .eq('id', s.user.id)
        .single()
      setProfile((data as Profile) ?? null)
    }

    supabase.auth.getSession().then(async ({ data }) => {
      setSession(data.session)
      await fetchProfile(data.session)
      setLoading(false)
    })
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session)
      void fetchProfile(session)
    })
    return () => subscription.unsubscribe()
  }, [])

  async function signIn(email: string, password: string) {
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
  }

  async function signOut() {
    await supabase.auth.signOut()
  }

  const role = profile?.role ?? null
  const isAdmin = role === 'admin'
  const isStaff = role === 'admin' || role === 'staff'
  const isClient = role === 'client'
  const isInternal = role != null && role !== 'client'

  return (
    <AuthContext.Provider
      value={{
        session,
        user: session?.user ?? null,
        profile,
        role,
        isAdmin,
        isStaff,
        isClient,
        isInternal,
        loading,
        signIn,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
