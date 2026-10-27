<template>
  <!--
    Signing in happens at the hub now. This page only hands over to it and
    comes back to the page that was asked for. The old code form is at
    /login/code until 3 Nov 2026 as a fallback.
  -->
  <main class="door">
    <div class="box">
      <img src="/langsync-lockup.png" alt="LangSync" height="28" class="lockup" />
      <h1>{{ title }}</h1>
      <p>{{ lead }}</p>
      <a v-if="!error" :href="target" class="primary">Continue</a>
      <a v-else href="" class="primary" @click.prevent="reload">Reload</a>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { hubPassUrl, onLangsync, PRODUCT_NAME } from '../lib/hub'

const route = useRoute()
const router = useRouter()
const want = String(route.query.redirect || '/')
const path = want.startsWith('/') && !want.startsWith('//') && !want.startsWith('/login') ? want : '/'
const target = hubPassUrl(`${window.location.origin}${path}`)
const stuck = route.query.stuck === '1'
const error = route.query.error === '1'

const title = computed(() =>
  error ? 'Could not check your access just now'
    : stuck ? 'We could not confirm your sign-in'
      : 'Continuing via LangSync')
const lead = computed(() =>
  error ? 'Reload the page in a moment.'
    : stuck ? `Your browser came back from the LangSync hub without a sign-in for ${PRODUCT_NAME}. Try once more.`
      : `You sign in to ${PRODUCT_NAME} with your LangSync hub account.`)

const reload = () => window.location.assign(path)

onMounted(() => {
  // Off langsync.ai the hub's pass cannot be read: only the code form works.
  if (!onLangsync()) return router.replace({ path: '/login/code', query: { redirect: path } })
  if (!stuck && !error) window.location.replace(target)
})
</script>

<style scoped>
.door {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px 16px;
  background: #ffffff;
  color: #0b1220;
  font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
}
.box { max-width: 420px; text-align: center; }
.lockup { height: 28px; width: auto; display: inline-block; }
h1 {
  font-family: 'Outfit', system-ui, -apple-system, sans-serif;
  font-weight: 700;
  letter-spacing: -0.03em;
  font-size: 28px;
  line-height: 1.15;
  margin: 32px 0 0;
}
p { font-size: 15px; color: #5b6472; margin: 12px 0 0; line-height: 1.6; }
.primary {
  display: inline-block;
  margin-top: 24px;
  border-radius: 8px;
  background: #0099ff;
  padding: 8px 16px;
  font-size: 13.5px;
  font-weight: 600;
  color: #ffffff;
  text-decoration: none;
}
</style>
