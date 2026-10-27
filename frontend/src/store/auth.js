import { reactive, computed } from 'vue'
import { supabase } from '../lib/supabase'
import service from '../api/index'
import {
  askServer, clearTrips, goToHub, hubLogoutUrl, onLangsync, sessionVia, setSessionVia,
} from '../lib/hub'

const state = reactive({
  session: null,
  profile: null,
  loading: true,
  initialized: false,
  passChecked: 0, // when the hub pass last confirmed this session (ms)
  lockCookie: null, // last ls_client_lock value the profile was fetched with
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
    state.lockCookie = (document.cookie.match(/(?:^|;\s*)ls_client_lock=([^;]*)/) || [])[1] || ''
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
    options: { shouldCreateUser: false, emailRedirectTo: window.location.origin },
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
  // The old code form, kept as a fallback until 3 Nov 2026.
  setSessionVia('code')
  state.session = data.session
  return data
}

// Signing out here signs out everywhere: this browser's Forecast session
// ends now (only this one: the sign-in is shared with other products), then
// the hub ends its own session and removes the pass from every langsync.ai
// address, and comes back to Forecast's front door.
export async function signOut() {
  if (supabase) await supabase.auth.signOut({ scope: 'local' }).catch(() => {})
  setSessionVia('')
  clearTrips()
  state.session = null
  state.profile = null
  state.passChecked = 0
  if (!onLangsync()) return false
  window.location.assign(hubLogoutUrl(`${window.location.origin}/`))
  return true
}

// The front door, run before every page that needs a sign-in.
//
// A page opens when:
//   - the hub's pass is valid, names Forecast, and belongs to someone with an
//     active Forecast profile; a Forecast session is made or kept for them; or
//   - the session came from the old code form (hidden at /login/code until
//     3 Nov 2026).
// Returns 'ok', 'away' (off to the hub), 'not-in-use', 'stuck' or 'error'.
//
// The answer is reused for a minute between pages; the tab coming back into
// view always asks again, so signing out in the hub reaches Forecast at once.
const RECHECK_MS = 60 * 1000
let inflight = null
export async function ensureHubSession(fullPath, { force = false } = {}) {
  if (!supabase) return 'error'
  // Off langsync.ai (a vercel or local address) the pass cannot be read:
  // only the code form works there.
  if (!onLangsync()) return state.session ? 'ok' : 'stuck'
  if (state.session && sessionVia() === 'code') return 'ok'
  if (!force && state.session && Date.now() - (state.passChecked || 0) < RECHECK_MS) return 'ok'
  if (inflight) return inflight
  inflight = (async () => {
    const have = state.session?.user?.email || ''
    const a = await askServer(have)
    if (a.status === 401) {
      return goToHub(`${window.location.origin}${fullPath}`) ? 'away' : 'stuck'
    }
    if (a.status === 403) {
      if (state.session) await supabase.auth.signOut({ scope: 'local' }).catch(() => {})
      setSessionVia('')
      state.session = null
      state.profile = null
      clearTrips()
      return 'not-in-use'
    }
    if (a.state === 'ok' && state.session) {
      state.passChecked = Date.now()
      setSessionVia('pass')
      clearTrips()
      return 'ok'
    }
    if (a.state === 'session' && a.access_token) {
      if (state.session) await supabase.auth.signOut({ scope: 'local' }).catch(() => {})
      const { data, error } = await supabase.auth.setSession({
        access_token: a.access_token,
        refresh_token: a.refresh_token,
      })
      if (error || !data.session) return 'error'
      setSessionVia('pass')
      state.session = data.session
      state.passChecked = Date.now()
      await fetchProfile()
      clearTrips()
      return 'ok'
    }
    return 'error'
  })()
  try {
    return await inflight
  } finally {
    inflight = null
  }
}

export async function refreshProfile() {
  await fetchProfile()
}
