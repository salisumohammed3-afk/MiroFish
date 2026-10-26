import { h } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Process from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'
import LoginView from '../views/LoginView.vue'
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
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: { guest: true }
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
  const { authState, isSuperAdmin, refreshProfile } = await import('../store/auth')

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
