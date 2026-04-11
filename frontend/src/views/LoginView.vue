<template>
  <div class="auth-container">
    <nav class="navbar">
      <div class="nav-brand">
        <span class="brand-lang">Lang</span><span class="brand-sync">Sync</span>
        <span class="brand-forecast">Forecast</span>
      </div>
    </nav>

    <div class="auth-content">
      <div class="auth-card">
        <!-- Normal login -->
        <template v-if="!mustChangePassword">
          <div class="auth-header">
            <h1 class="auth-title">Sign in</h1>
            <p class="auth-subtitle">Access your predictive intelligence workspace</p>
          </div>

          <form @submit.prevent="handleLogin" class="auth-form">
            <div class="form-group">
              <label class="form-label">Email</label>
              <input
                v-model="email"
                type="email"
                class="form-input"
                placeholder="you@company.com"
                required
                :disabled="loading"
              />
            </div>

            <div class="form-group">
              <label class="form-label">Password</label>
              <input
                v-model="password"
                type="password"
                class="form-input"
                placeholder="Enter your password"
                required
                :disabled="loading"
              />
            </div>

            <div v-if="error" class="error-msg">{{ error }}</div>

            <button type="submit" class="submit-btn" :disabled="loading">
              <span v-if="loading" class="spinner"></span>
              {{ loading ? 'Signing in...' : 'Sign in' }}
            </button>
          </form>
        </template>

        <!-- Forced password change -->
        <template v-else>
          <div class="auth-header">
            <div class="change-badge">First Login</div>
            <h1 class="auth-title">Set your password</h1>
            <p class="auth-subtitle">Your admin created a temporary password. Please choose your own password to continue.</p>
          </div>

          <form @submit.prevent="handleChangePassword" class="auth-form">
            <div class="form-group">
              <label class="form-label">New Password</label>
              <input
                v-model="newPassword"
                type="password"
                class="form-input"
                placeholder="Choose a strong password (min 8 characters)"
                required
                minlength="8"
                :disabled="loading"
              />
            </div>

            <div class="form-group">
              <label class="form-label">Confirm Password</label>
              <input
                v-model="confirmNewPassword"
                type="password"
                class="form-input"
                placeholder="Repeat your new password"
                required
                :disabled="loading"
              />
            </div>

            <div v-if="error" class="error-msg">{{ error }}</div>

            <button type="submit" class="submit-btn" :disabled="loading">
              <span v-if="loading" class="spinner"></span>
              {{ loading ? 'Updating...' : 'Set password & continue' }}
            </button>
          </form>
        </template>
      </div>

      <div class="auth-decoration">
        <img src="../assets/logo/langsync-logo.png" alt="LangSync" class="auth-logo" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { signInWithEmail, refreshProfile, currentUser } from '../store/auth'
import { changePassword } from '../api/auth'

const router = useRouter()
const route = useRoute()
const email = ref('')
const password = ref('')
const newPassword = ref('')
const confirmNewPassword = ref('')
const error = ref('')
const loading = ref(false)
const mustChangePassword = ref(false)

const handleLogin = async () => {
  error.value = ''
  loading.value = true
  try {
    await signInWithEmail(email.value, password.value)
    await refreshProfile()

    if (currentUser.value?.must_change_password) {
      mustChangePassword.value = true
    } else {
      const redirect = route.query.redirect || '/'
      router.push(redirect)
    }
  } catch (err) {
    error.value = err.message || 'Invalid email or password'
  } finally {
    loading.value = false
  }
}

const handleChangePassword = async () => {
  error.value = ''
  if (newPassword.value !== confirmNewPassword.value) {
    error.value = 'Passwords do not match.'
    return
  }
  if (newPassword.value.length < 8) {
    error.value = 'Password must be at least 8 characters.'
    return
  }
  loading.value = true
  try {
    await changePassword({ new_password: newPassword.value })
    await refreshProfile()
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } catch (err) {
    error.value = err.response?.data?.error || err.message || 'Failed to update password'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-container {
  min-height: 100vh;
  background: #FFFFFF;
  font-family: 'Avenir Next', 'Inter', system-ui, -apple-system, sans-serif;
}

.navbar {
  height: 60px;
  background: #0F0F0F;
  color: #FFFFFF;
  display: flex;
  align-items: center;
  padding: 0 40px;
}

.nav-brand { font-weight: 700; letter-spacing: -0.5px; font-size: 1.25rem; }
.brand-lang { color: #818CF8; }
.brand-sync { color: #A78BFA; }
.brand-forecast { color: #FFFFFF; margin-left: 6px; font-weight: 500; opacity: 0.7; }

.auth-content {
  max-width: 1000px;
  margin: 0 auto;
  padding: 80px 40px;
  display: flex;
  gap: 80px;
  align-items: flex-start;
}

.auth-card { flex: 1; max-width: 420px; }
.auth-header { margin-bottom: 40px; }

.auth-title {
  font-size: 2.5rem;
  font-weight: 600;
  letter-spacing: -1px;
  margin: 0 0 8px;
}

.auth-subtitle { color: #6B7280; font-size: 1rem; margin: 0; line-height: 1.5; }
.auth-form { display: flex; flex-direction: column; gap: 20px; }
.form-group { display: flex; flex-direction: column; gap: 6px; }

.form-label {
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: #374151;
}

.form-input {
  padding: 12px 16px;
  border: 1.5px solid #E5E7EB;
  border-radius: 4px;
  font-size: 1rem;
  font-family: inherit;
  transition: border-color 0.2s;
  background: #FAFAFA;
}

.form-input:focus { outline: none; border-color: #5B5FE5; background: #FFFFFF; }

.error-msg {
  color: #DC2626;
  font-size: 0.9rem;
  background: #FEF2F2;
  padding: 10px 14px;
  border-radius: 4px;
  border-left: 3px solid #DC2626;
}

.submit-btn {
  background: linear-gradient(135deg, #4F46E5, #7C3AED);
  color: #FFFFFF;
  border: none;
  padding: 14px;
  border-radius: 4px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 4px;
}

.submit-btn:hover:not(:disabled) { opacity: 0.9; }
.submit-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #FFFFFF;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

.change-badge {
  display: inline-block;
  background: linear-gradient(135deg, #D97706, #F59E0B);
  color: #FFFFFF;
  padding: 4px 12px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.5px;
  border-radius: 2px;
  margin-bottom: 16px;
}

@keyframes spin { to { transform: rotate(360deg); } }

.auth-decoration {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
  padding-top: 20px;
}

.auth-logo {
  max-width: 280px;
  width: 100%;
  height: auto;
  opacity: 0.9;
}

@media (max-width: 768px) {
  .auth-content { flex-direction: column; padding: 40px 20px; gap: 40px; }
  .auth-card { max-width: 100%; }
  .auth-decoration { display: none; }
}
</style>
