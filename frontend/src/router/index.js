import { h } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Process from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'
import LoginView from '../views/LoginView.vue'
import LoginHandOff from '../views/LoginHandOff.vue'
import NotInUseView from '../views/NotInUseView.vue'
import { startPassKeepAlive } from '../lib/hub'
import AdminView from '../views/AdminView.vue'

// Shown to staff while the hub's client lock is on for a client that has no
// Forecast company. Names nobody.
const NotAClient = {
  render: () => h('div', { style: 'min-height:100vh;display:grid;place-items:center;text-align:center;padding:24px' }, [
    h('div', [
      h('h1', { style: 'font-size:26px;font-weight:600;margin-bottom:12px' }, 'This client does not use Forecast'),
      h('p', [h('a', { href: 'https://hub.langsync.ai', style: 'text-decoration:underline' }, 'Back to the hub')])
    ])
  ])
}

const routes = [
  {
    path: '/not-a-client',
    name: 'NotAClient',
    component: NotAClient,
    meta: { requiresAuth: true }
  },
  // Signing in happens at the hub: /login only hands over to it.
  {
    path: '/login',
    name: 'Login',
    component: LoginHandOff
  },
  // The old emailed code form, at a hidden address until 3 Nov 2026.
  {
    path: '/login/code',
    name: 'LoginCode',
    component: LoginView,
    meta: { guest: true }
  },
  // Signed into the hub, but Forecast is not theirs.
  {
    path: '/not-in-use',
    name: 'NotInUse',
    component: NotInUseView
  },
  {
    path: '/',
    name: 'Home',
    component: Home,
    meta: { requiresAuth: true }
  },
  {
    path: '/process/:projectId',
    name: 'Process',
    component: Process,
    props: true,
    meta: { requiresAuth: true }
  },
  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    component: SimulationView,
    props: true,
    meta: { requiresAuth: true }
  },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    component: SimulationRunView,
    props: true,
    meta: { requiresAuth: true }
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: ReportView,
    props: true,
    meta: { requiresAuth: true }
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    component: InteractionView,
    props: true,
    meta: { requiresAuth: true }
  },
  {
    path: '/admin',
    name: 'Admin',
    component: AdminView,
    meta: { requiresAuth: true, requiresAdmin: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to, from, next) => {
  const { authState, isSuperAdmin, refreshProfile, ensureHubSession } = await import('../store/auth')
  const { onLangsync } = await import('../lib/hub')

  // Wait for auth initialization
  if (!authState.initialized) {
    await new Promise(resolve => {
      const check = setInterval(() => {
        if (authState.initialized) {
          clearInterval(check)
          resolve()
        }
      }, 50)
    })
  }

  // One sign-in: every page that needs a sign-in goes through the hub's pass
  // first (store/auth.js ensureHubSession).
  if (to.meta.requiresAuth) {
    const door = await ensureHubSession(to.fullPath)
    if (door === 'away') return next(false)
    if (door === 'not-in-use') return next({ name: 'NotInUse' })
    if (door === 'stuck') {
      return onLangsync()
        ? next({ name: 'Login', query: { stuck: '1', redirect: to.fullPath } })
        : next({ name: 'LoginCode', query: { redirect: to.fullPath } })
    }
    if (door === 'error') return next({ name: 'Login', query: { error: '1', redirect: to.fullPath } })
  }

  const isLoggedIn = !!authState.session

  // Client lock (set by the hub on .langsync.ai). The server narrows staff to
  // the locked company; refresh the profile whenever the cookie changes so
  // the screen follows it on every route change.
  const lockCookie = (document.cookie.match(/(?:^|;\s*)ls_client_lock=([^;]*)/) || [])[1] || ''
  if (isLoggedIn && lockCookie !== authState.lockCookie) {
    authState.lockCookie = lockCookie
    await refreshProfile()
  }
  const lock = isLoggedIn ? authState.profile?.client_lock : null
  if (lock && !lock.uses_product && to.name !== 'NotAClient') {
    return next({ name: 'NotAClient' })
  }
  if (to.name === 'NotAClient' && !(lock && !lock.uses_product)) {
    return next({ name: 'Home' })
  }

  if (to.meta.requiresAuth && !isLoggedIn) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }

  if (to.meta.guest && isLoggedIn) {
    return next({ name: 'Home' })
  }

  if (to.meta.requiresAdmin && !isSuperAdmin.value) {
    return next({ name: 'Home' })
  }

  next()
})

export default router

// Keeps the hub pass fresh while a page is open, and checks it again when the
// tab comes back into view: signed out in the hub (or removed there), and the
// next look at Forecast goes back through the hub.
startPassKeepAlive(async () => {
  const { authState, ensureHubSession } = await import('../store/auth')
  const route = router.currentRoute.value
  if (!authState.session || !route.meta.requiresAuth) return
  const door = await ensureHubSession(route.fullPath, { force: true })
  if (door === 'not-in-use') router.replace({ name: 'NotInUse' })
})
