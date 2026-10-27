// One sign-in across LangSync: the hub is the front door.
//
// The hub (hub.langsync.ai) is the only place anyone signs in. It gives the
// browser a 15-minute signed pass (the cookie ls_pass on .langsync.ai, which
// only servers can read). Forecast's own server checks the pass and turns it
// into a normal Forecast session (backend: /api/auth/hub-session).
//
// No valid pass: the browser goes to the hub's /pass, which comes straight
// back if they are signed into the hub (no page shown), or shows the hub
// sign-in first. Signing out anywhere goes through the hub's /logout.
//
// The old emailed code form stays at the hidden address /login/code until
// 3 Nov 2026. A session made there is marked "code" and is left alone.
//
// Contract: langsync-hub docs/superpowers/specs/2026-10-27-single-sign-on-design.md

export const HUB = 'https://hub.langsync.ai'
export const HUB_ID = 'forecast'
export const PRODUCT_NAME = 'Forecast'
export const NOT_IN_USE_MESSAGE = `Your company does not use ${PRODUCT_NAME} yet. Ask your LangSync contact.`

const VIA_KEY = 'ls_sso_via' // localStorage: 'pass' or 'code'
const TRY_KEY = 'ls_sso_try' // sessionStorage: trips to the hub in the last few seconds

export const onLangsync = () => {
  const h = window.location.hostname
  return h === 'langsync.ai' || h.endsWith('.langsync.ai')
}

export const hubPassUrl = (next) =>
  `${HUB}/pass?${new URLSearchParams({ product: HUB_ID, next })}`

export const hubLogoutUrl = (next) => `${HUB}/logout?${new URLSearchParams({ next })}`

export const sessionVia = () => {
  try { return localStorage.getItem(VIA_KEY) || '' } catch { return '' }
}
export const setSessionVia = (v) => {
  try { v ? localStorage.setItem(VIA_KEY, v) : localStorage.removeItem(VIA_KEY) } catch { /* private window */ }
}

// Coming back twice in a row still without a pass means something is wrong
// (a blocked cookie, a wrong address), so it stops at a page instead of going
// round in circles. One trip that ends at the hub sign-in is normal.
const readTrips = () => {
  try {
    const t = JSON.parse(sessionStorage.getItem(TRY_KEY) || 'null')
    return t && Date.now() - t.at < 15000 ? t.n : 0
  } catch { return 0 }
}
export const clearTrips = () => { try { sessionStorage.removeItem(TRY_KEY) } catch { /* ignore */ } }

/** Off to the hub for a fresh pass, coming back to `next` (a full address). Returns false when stuck. */
export function goToHub(next) {
  const n = readTrips()
  if (n >= 2) { clearTrips(); return false }
  try { sessionStorage.setItem(TRY_KEY, JSON.stringify({ n: n + 1, at: Date.now() })) } catch { /* ignore */ }
  window.location.assign(hubPassUrl(next))
  return true
}

/** Asks this product's server about the pass. `have` is the email of the session already held. */
export async function askServer(have) {
  const q = have ? `?${new URLSearchParams({ have })}` : ''
  try {
    const r = await fetch(`/api/auth/hub-session${q}`, { credentials: 'same-origin', cache: 'no-store' })
    const body = await r.json().catch(() => ({}))
    return { status: r.status, ...body }
  } catch {
    return { status: 0, state: 'error' }
  }
}

// Keeps the hub pass fresh while a page is open, so a save after a long
// stretch never meets a run-out sign-in. Every ten minutes, and when the tab
// comes back into view, the browser quietly asks the hub for a new pass.
const EVERY = 10 * 60 * 1000
let keepAliveOn = false
export function startPassKeepAlive(onBack) {
  if (keepAliveOn || !onLangsync()) return
  keepAliveOn = true
  let last = Date.now()
  const url = hubPassUrl(`${window.location.origin}/icon.png`)
  const refresh = () => {
    last = Date.now()
    return fetch(url, { mode: 'no-cors', credentials: 'include', cache: 'no-store' }).catch(() => {})
  }
  window.setInterval(refresh, EVERY)
  // Back in view: a fresh pass first (if due), then the check.
  const back = async () => {
    if (document.visibilityState !== 'visible') return
    if (Date.now() - last > EVERY / 2) await refresh()
    onBack?.()
  }
  document.addEventListener('visibilitychange', back)
  window.addEventListener('focus', back)
}
