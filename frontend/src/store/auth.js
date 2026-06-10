import { reactive, computed } from 'vue'
import { supabase } from '../lib/supabase'
import service from '../api/index'

const state = reactive({
  session: null,
  profile: null,
  loading: true,
  initialized: false,
})

export const authState = state

export const isAuthenticated = computed(() => !!state.session)
export const currentUser = computed(() => state.profile)
export const isSuperAdmin = computed(() => state.profile?.role === 'super_admin')
export const isAdmin = computed(() => ['super_admin', 'admin'].includes(state.profile?.role))
export const userCompany = computed(() => state.profile?.company)

async function fetchProfile() {
  if (!state.session) {
    state.profile = null
    return
  }
  try {
    const res = await service.get('/api/auth/me')
    state.profile = res.data
  } catch (err) {
    console.error('Failed to fetch profile:', err)
    state.profile = null
  }
}

export async function initAuth() {
  if (!supabase) {
    state.loading = false
    state.initialized = true
    return
  }

  const { data: { session } } = await supabase.auth.getSession()
  state.session = session
  if (session) {
    await fetchProfile()
  }
  state.loading = false
  state.initialized = true

  supabase.auth.onAuthStateChange(async (_event, session) => {
    state.session = session
    if (session) {
      await fetchProfile()
    } else {
      state.profile = null
    }
  })
}

// Email one-time-code sign-in. We never create a user from the login screen
// (shouldCreateUser: false) — accounts are provisioned by an admin first.
export async function requestOtp(email) {
  if (!supabase) throw new Error('Auth not configured')
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { shouldCreateUser: false },
  })
  // Don't reveal whether an account exists: only surface genuine failures like
  // rate limiting. "No such account" resolves quietly so the UI always advances
  // to the code step with a neutral message.
  if (error && (error.status === 429 || /rate/i.test(error.code || ''))) {
    throw error
  }
}

export async function verifyOtp(email, token) {
  if (!supabase) throw new Error('Auth not configured')
  const { data, error } = await supabase.auth.verifyOtp({ email, token: token.trim(), type: 'email' })
  if (error) throw error
  return data
}

export async function signOut() {
  if (!supabase) return
  await supabase.auth.signOut()
  state.session = null
  state.profile = null
}

export async function refreshProfile() {
  await fetchProfile()
}
