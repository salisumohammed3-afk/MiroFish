<template>
  <!--
    The sign-in page in the shared LangSync product kit's look (the same door as
    Answer Map, Prompt Review, Pods, Cut Room and the hub). The kit is React, so
    this is the same layout and values rebuilt in Vue with plain CSS. Only the
    look is the kit's: signing in is still Forecast's own Supabase email code on
    the shared LangSync Platform database (store/auth.js), unchanged.
  -->
  <main class="kit-login">
    <!-- Left: the door. -->
    <section class="door">
      <div class="kit-rise" style="animation-delay: 40ms">
        <img src="/langsync-lockup.png" alt="LangSync" height="32" class="lockup" />
      </div>

      <div class="door-middle">
        <div class="door-inner">
          <p class="kit-rise eyebrow" style="animation-delay: 120ms">Welcome back</p>
          <h1 class="kit-rise kit-display title" style="animation-delay: 180ms">
            Sign in to<br />{{ PRODUCT.name }}
          </h1>
          <p class="kit-rise lead" style="animation-delay: 240ms">
            Enter your email and we will send you a code that signs you in. No password to remember.
          </p>

          <div class="kit-rise form-wrap" style="animation-delay: 300ms">
            <!-- Step 2: the emailed code -->
            <form v-if="step === 'code'" class="stack" @submit.prevent="handleVerifyCode()">
              <div class="sent-box">
                <p>
                  We sent a six-digit code to <span class="strong">{{ email.trim() }}</span> if it has a
                  Forecast account. Enter it below.
                </p>
              </div>

              <input
                ref="codeRef"
                :value="code"
                class="field code-field"
                inputmode="numeric"
                autocomplete="one-time-code"
                pattern="[0-9]*"
                maxlength="6"
                placeholder="000000"
                @input="onCodeInput"
              />

              <p v-if="error" class="error">{{ error }}</p>

              <button type="submit" class="primary" :disabled="loading || code.length !== 6">
                {{ loading ? 'Checking…' : 'Sign in' }}
              </button>

              <div class="links">
                <button type="button" class="link muted" :disabled="loading" @click="backToEmail">
                  Use a different email
                </button>
                <button type="button" class="link brand" :disabled="loading || resendIn > 0" @click="resendCode">
                  {{ resendIn > 0 ? `Resend code in ${resendIn}s` : 'Resend code' }}
                </button>
              </div>
            </form>

            <!-- Step 1: the email -->
            <form v-else class="stack" @submit.prevent="handleRequestCode">
              <label class="label">
                <span>Email</span>
                <input
                  v-model="email"
                  type="email"
                  class="field email-field"
                  placeholder="you@company.com"
                  autocomplete="email"
                  autofocus
                  required
                />
              </label>

              <p v-if="error" class="error">{{ error }}</p>

              <button type="submit" class="primary" :disabled="loading">
                {{ loading ? 'Sending code…' : 'Email me a sign-in code' }}
              </button>
            </form>
          </div>
        </div>
      </div>

      <p class="kit-rise foot" style="animation-delay: 420ms">
        Access is by invitation. Ask your LangSync contact to be added.
      </p>
    </section>

    <!-- Right: a calm branded panel (wide screens only). -->
    <aside class="panel field-texture">
      <div class="glow glow-blue"></div>
      <div class="glow glow-violet"></div>
      <div class="panel-inner">
        <div class="panel-copy">
          <div class="kit-rise pill" style="animation-delay: 260ms">
            <!-- The Forecast icon from the hub (langsync-hub product-icon.tsx):
                 a line so far, then the projection, white on the Forecast accent. -->
            <span class="mark" aria-hidden="true">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 17.5 8 12.5l4 2.5 4-5.5" />
                <path d="M16 9.5 21 4" stroke-dasharray="1.6 2.4" />
                <circle cx="16" cy="9.5" r="1.3" fill="currentColor" />
                <path d="M3 21h18" />
              </svg>
            </span>
            LangSync {{ PRODUCT.name }}
          </div>
          <h2 class="kit-rise kit-display panel-title" style="animation-delay: 340ms">
            {{ PRODUCT.tagline }}
          </h2>
          <p class="kit-rise panel-lead" style="animation-delay: 420ms">
            {{ PRODUCT.loginBlurb }}
          </p>
        </div>
      </div>
    </aside>
  </main>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { requestOtp, verifyOtp, refreshProfile } from '../store/auth'

// Name and tagline as in the hub (langsync-hub src/lib/config.ts).
const PRODUCT = {
  name: 'Forecast',
  tagline: 'Forecast anything you can measure, from your own data.',
  loginBlurb:
    'Upload your own documents, run a simulation of how people are likely to respond, and get a report on what to expect.',
}

const router = useRouter()
const route = useRoute()
const step = ref('email')
const email = ref('')
const code = ref('')
const error = ref('')
const loading = ref(false)
const resendIn = ref(0)
const codeRef = ref(null)

let resendTimer = null
const startResendCooldown = () => {
  resendIn.value = 30
  clearInterval(resendTimer)
  resendTimer = setInterval(() => {
    resendIn.value -= 1
    if (resendIn.value <= 0) clearInterval(resendTimer)
  }, 1000)
}

const handleRequestCode = async () => {
  error.value = ''
  loading.value = true
  try {
    await requestOtp(email.value.trim())
    step.value = 'code'
    code.value = ''
    startResendCooldown()
    await nextTick()
    codeRef.value?.focus()
  } catch (err) {
    error.value = err.status === 429
      ? 'Too many requests. Wait a moment and try again.'
      : (err.message || 'Could not send a code. Try again.')
  } finally {
    loading.value = false
  }
}

const resendCode = async () => {
  if (resendIn.value > 0) return
  await handleRequestCode()
}

// Digits only, six at most; the sixth digit signs in straight away.
const onCodeInput = (e) => {
  const v = e.target.value.replace(/\D/g, '').slice(0, 6)
  code.value = v
  e.target.value = v
  if (v.length === 6 && !loading.value) handleVerifyCode()
}

const handleVerifyCode = async () => {
  if (code.value.length !== 6) return
  error.value = ''
  loading.value = true
  try {
    await verifyOtp(email.value.trim(), code.value)
    await refreshProfile()
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } catch (err) {
    error.value = 'That code is invalid or expired. Check the code or request a new one.'
  } finally {
    loading.value = false
  }
}

const backToEmail = () => {
  step.value = 'email'
  code.value = ''
  error.value = ''
  clearInterval(resendTimer)
  resendIn.value = 0
}
</script>

<style scoped>
/* The kit's values (brand.css and the kit login page), as plain CSS. */
.kit-login {
  --ink: #0b1220;
  --muted: #5b6472;
  --line: #e9edf3;
  --brand: #0099ff;
  --brand-ink: #0b64a8;
  --bad: #c0392b;
  min-height: 100vh;
  display: grid;
  background: #ffffff;
  color: var(--ink);
  font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
  font-size: 16px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
.kit-display {
  font-family: 'Outfit', system-ui, -apple-system, sans-serif;
}

/* Left */
.door {
  display: flex;
  flex-direction: column;
  padding: 32px 28px;
}
.lockup { height: 32px; width: auto; display: block; }
.door-middle { flex: 1; display: grid; place-items: center; }
.door-inner { width: 100%; max-width: 380px; }
.eyebrow {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
  margin-bottom: 12px;
}
.title {
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--ink);
  line-height: 1.05;
  font-size: 40px;
  margin: 0;
}
.lead {
  font-size: 15px;
  color: var(--muted);
  margin-top: 16px;
  line-height: 1.625;
}
.form-wrap { margin-top: 32px; }
.stack { display: flex; flex-direction: column; gap: 12px; }
.label { display: block; }
.label > span { font-size: 13px; font-weight: 600; color: var(--ink); }
.field {
  width: 100%;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: #ffffff;
  color: var(--ink);
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.field:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 4px rgba(0, 153, 255, 0.1);
}
.email-field {
  margin-top: 6px;
  padding: 12px 16px;
  font-size: 15px;
  line-height: 1.5;
}
.email-field::placeholder { color: rgba(91, 100, 114, 0.6); }
.code-field {
  padding: 14px 16px;
  text-align: center;
  font-size: 26px;
  font-weight: 600;
  letter-spacing: 0.5em;
  line-height: 1.5;
}
.code-field::placeholder { color: rgba(91, 100, 114, 0.3); letter-spacing: 0.5em; }
.sent-box {
  border-radius: 16px;
  border: 1px solid var(--line);
  background: #f6f9fe;
  padding: 16px 20px;
}
.sent-box p { font-size: 14px; color: var(--muted); line-height: 1.625; }
.strong { font-weight: 600; color: var(--ink); }
.error { font-size: 13px; color: var(--bad); }
.primary {
  width: 100%;
  border: none;
  border-radius: 12px;
  background: var(--brand);
  padding: 12px 0;
  font-family: inherit;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.5;
  color: #ffffff;
  cursor: pointer;
  box-shadow: 0 6px 18px rgba(0, 153, 255, 0.28);
  transition: background-color 0.15s;
}
.primary:hover:not(:disabled) { background: var(--brand-ink); }
.primary:disabled { opacity: 0.6; cursor: default; }
.links {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 4px;
}
.link {
  background: none;
  border: none;
  padding: 0;
  font-family: inherit;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
}
.link.muted { color: var(--muted); }
.link.muted:hover:not(:disabled) { color: var(--ink); }
.link.brand { color: var(--brand-ink); }
.link.brand:hover:not(:disabled) { text-decoration: underline; }
.link:disabled { opacity: 0.5; cursor: default; }
.foot { font-size: 12px; color: rgba(91, 100, 114, 0.8); }

/* Right */
.panel {
  display: none;
  position: relative;
  overflow: hidden;
  background-color: #f6f9fe;
  border-left: 1px solid var(--line);
}
.field-texture {
  background-image: radial-gradient(rgba(11, 18, 32, 0.04) 1px, transparent 1px);
  background-size: 22px 22px;
  background-position: -1px -1px;
}
.glow { position: absolute; border-radius: 9999px; filter: blur(64px); }
.glow-blue {
  right: -96px;
  top: -96px;
  width: 440px;
  height: 440px;
  opacity: 0.7;
  background: radial-gradient(circle, #cfe8ff, transparent 62%);
}
.glow-violet {
  right: 40px;
  bottom: -120px;
  width: 360px;
  height: 360px;
  opacity: 0.6;
  background: radial-gradient(circle, #e4dcff, transparent 62%);
}
.panel-inner {
  position: relative;
  height: 100%;
  display: grid;
  place-items: center;
  padding: 0 64px;
}
.panel-copy { max-width: 380px; }
.pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-radius: 9999px;
  background: #ffffff;
  border: 1px solid var(--line);
  padding: 5.5px 12px 5.5px 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--brand-ink);
  line-height: 1.5;
}
.mark {
  display: inline-grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  background: #e64980;
  color: #ffffff;
}
.panel-title {
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--ink);
  font-size: 30px;
  line-height: 1.15;
  margin-top: 20px;
}
.panel-lead {
  font-size: 15px;
  color: var(--muted);
  margin-top: 16px;
  line-height: 1.625;
}

/* Entrance, as the kit's rise. */
@keyframes kit-rise {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
.kit-rise {
  opacity: 0;
  animation: kit-rise 0.6s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}
@media (prefers-reduced-motion: reduce) {
  .kit-rise { animation: none; opacity: 1; }
}

@media (min-width: 640px) {
  .door { padding: 32px 56px; }
  .title { font-size: 46px; }
}
@media (min-width: 1024px) {
  .kit-login { grid-template-columns: 1.05fr 1fr; }
  .panel { display: block; }
}
</style>
