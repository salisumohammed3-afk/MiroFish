<template>
  <div class="panel">
    <div class="panel-header">
      <div>
        <h2>API keys</h2>
        <p class="panel-blurb">
          Keys let other tools, Claude and agents use Forecast on LangSync's behalf. Each key works for every client.
          Only LangSync admins can see this.
          <router-link to="/docs/api" class="docs-link">Read the API docs</router-link>
        </p>
      </div>
      <button v-if="!making" @click="making = true" class="action-btn primary">Make a key</button>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <div v-if="made" class="new-key">
      <h3>Your new key: {{ made.name }}</h3>
      <p>You will not see this key again. Copy it now.</p>
      <div class="copy-row">
        <code class="copy-text">{{ made.key }}</code>
        <button class="action-btn sm" @click="copy(made.key, 'key')">{{ copied === 'key' ? 'Copied' : 'Copy key' }}</button>
      </div>
      <p class="paste-label">To use it in Claude Code, run this:</p>
      <div class="copy-row">
        <code class="copy-text">{{ lines.claude }}</code>
        <button class="action-btn sm" @click="copy(lines.claude, 'claude')">{{ copied === 'claude' ? 'Copied' : 'Copy' }}</button>
      </div>
      <p class="paste-label">To try it from a terminal:</p>
      <div class="copy-row">
        <code class="copy-text">{{ lines.curl }}</code>
        <button class="action-btn sm" @click="copy(lines.curl, 'curl')">{{ copied === 'curl' ? 'Copied' : 'Copy' }}</button>
      </div>
      <button class="link-btn" @click="made = null">I have copied it</button>
    </div>

    <form v-if="making" class="inline-form" @submit.prevent="make">
      <input v-model="form.name" maxlength="80" placeholder="What it is for, like Claude on Sal's laptop" class="form-input wide" />
      <select v-model="form.access" class="form-input">
        <option value="read">{{ ACCESS_LABEL.read }}</option>
        <option value="write">{{ ACCESS_LABEL.write }}</option>
      </select>
      <label class="expiry">Expires <input v-model="form.expiresAt" type="date" class="form-input" /></label>
      <p class="form-note">{{ ACCESS_BLURB[form.access] }} Leave the date empty for a key that does not expire.</p>
      <div class="inline-actions">
        <button type="submit" class="action-btn primary" :disabled="busy === 'new' || !form.name.trim()">Make the key</button>
        <button type="button" class="action-btn" @click="making = false">Back</button>
      </div>
    </form>

    <div class="table-container">
      <table class="data-table plain-head">
        <thead>
          <tr><th>Key</th><th>Can do</th><th>Made by</th><th>Last used</th><th>Expires</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="6" class="empty-cell">Loading keys</td></tr>
          <tr v-else-if="rows.length === 0"><td colspan="6" class="empty-cell">No keys yet.</td></tr>
          <tr v-for="k in rows" :key="k.id" :class="{ faded: keyStatus(k) !== 'Active' }">
            <td>
              <div class="name-cell">{{ k.name }}</div>
              <div class="prefix">{{ k.prefix }}...</div>
            </td>
            <td>{{ ACCESS_LABEL[k.access] }}</td>
            <td>{{ k.created_by }}</td>
            <td class="date-cell">{{ shownDate(k.last_used_at, 'Never') }}</td>
            <td class="date-cell">{{ shownDate(k.expires_at, 'Never') }}</td>
            <td class="actions-cell">
              <span v-if="keyStatus(k) !== 'Active'" class="muted">{{ keyStatus(k) }}</span>
              <span v-else-if="confirming === k.id">
                <button class="action-btn danger sm" :disabled="busy === k.id" @click="cancel(k.id)">Cancel key</button>
                <button class="action-btn sm" @click="confirming = ''">Keep</button>
              </span>
              <button v-else class="action-btn sm" @click="confirming = k.id">Cancel</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { listApiKeys, createApiKey, cancelApiKey } from '../api/auth'
import { ACCESS_LABEL, ACCESS_BLURB, keyStatus, pasteLines, shownDate } from '../lib/apiKeys'

const emit = defineEmits(['changed'])

const rows = ref([])
const loading = ref(true)
const error = ref('')
const busy = ref('')
const making = ref(false)
const confirming = ref('')
const copied = ref('')
const made = ref(null)
const form = ref({ name: '', access: 'read', expiresAt: '' })

const lines = computed(() => made.value ? pasteLines(window.location.origin, made.value.key) : { claude: '', curl: '' })

const message = (e, fallback) => e?.response?.data?.error || fallback

onMounted(async () => {
  try {
    rows.value = (await listApiKeys()).data
  } catch (e) {
    error.value = message(e, 'Could not load the API keys.')
  } finally {
    loading.value = false
  }
})

async function make () {
  busy.value = 'new'
  error.value = ''
  try {
    const res = await createApiKey({ name: form.value.name, access: form.value.access, expiresAt: form.value.expiresAt || undefined })
    rows.value = [res.data.row, ...rows.value]
    made.value = { key: res.data.key, name: res.data.row.name }
    making.value = false
    form.value = { name: '', access: 'read', expiresAt: '' }
    emit('changed')
  } catch (e) {
    error.value = message(e, 'Could not make the key.')
  }
  busy.value = ''
}

async function cancel (id) {
  busy.value = id
  error.value = ''
  try {
    await cancelApiKey(id)
    rows.value = rows.value.map((r) => (r.id === id ? { ...r, revoked_at: new Date().toISOString() } : r))
    emit('changed')
  } catch (e) {
    error.value = message(e, 'Could not cancel the key.')
  }
  confirming.value = ''
  busy.value = ''
}

async function copy (text, which) {
  await navigator.clipboard.writeText(text)
  copied.value = which
  setTimeout(() => { if (copied.value === which) copied.value = '' }, 1500)
}
</script>

<style scoped>
.panel-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 24px; }
.panel-header h2 { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.5px; margin: 0; }
.panel-blurb { color: #6B7280; font-size: 0.9rem; margin: 6px 0 0; max-width: 640px; line-height: 1.5; }
.docs-link { color: #0099ff; font-weight: 600; text-decoration: none; margin-left: 4px; }
.docs-link:hover { text-decoration: underline; }

.action-btn { padding: 8px 16px; border: 1.5px solid #E5E7EB; border-radius: 4px; background: #FFFFFF; font-size: 0.85rem; font-weight: 500; font-family: inherit; cursor: pointer; transition: all 0.15s; white-space: nowrap; }
.action-btn:hover { border-color: #D1D5DB; background: #F9FAFB; }
.action-btn.primary { background: linear-gradient(135deg, #0099ff, #7C3AED); color: #FFF; border-color: transparent; }
.action-btn.primary:hover { opacity: 0.9; }
.action-btn.danger { color: #DC2626; border-color: #FCA5A5; }
.action-btn.sm { padding: 4px 10px; font-size: 0.8rem; margin-left: 4px; }
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.link-btn { background: none; border: none; color: #6B7280; font-family: inherit; font-weight: 600; cursor: pointer; padding: 0; margin-top: 14px; }
.link-btn:hover { color: #111827; }

.error-msg { color: #DC2626; font-size: 0.85rem; background: #FEF2F2; padding: 10px 14px; border-radius: 4px; border-left: 3px solid #DC2626; margin-bottom: 16px; }

.new-key { background: #F4F9FF; border: 1px solid #CFE0F2; border-radius: 6px; padding: 20px; margin-bottom: 24px; }
.new-key h3 { font-size: 1.05rem; font-weight: 600; margin: 0 0 4px; }
.new-key p { margin: 0; font-size: 0.9rem; color: #111827; }
.paste-label { font-weight: 600; margin-top: 14px !important; }
.copy-row { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
.copy-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; background: #FFF; border: 1px solid #E5E7EB; border-radius: 4px; padding: 8px 10px; font-size: 0.8rem; color: #111827; }

.inline-form { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 6px; padding: 20px; margin-bottom: 24px; }
.form-input { padding: 10px 14px; border: 1.5px solid #E5E7EB; border-radius: 4px; font-size: 0.9rem; font-family: inherit; background: #FAFAFA; }
.form-input:focus { outline: none; border-color: #0099ff; background: #FFF; }
.form-input.wide { flex: 1; min-width: 240px; }
.expiry { display: flex; align-items: center; gap: 8px; color: #6B7280; font-size: 0.9rem; }
.form-note { flex-basis: 100%; margin: 0; color: #6B7280; font-size: 0.82rem; }
.inline-actions { display: flex; gap: 8px; }

.table-container { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 6px; overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.data-table th { text-align: left; padding: 12px 16px; background: #F9FAFB; font-weight: 600; font-size: 0.82rem; color: #6B7280; border-bottom: 1px solid #E5E7EB; }
.data-table td { padding: 12px 16px; border-bottom: 1px solid #F3F4F6; color: #374151; vertical-align: middle; }
.data-table tr:last-child td { border-bottom: none; }
.name-cell { font-weight: 600; color: #111827; }
.prefix { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.78rem; color: #6B7280; margin-top: 2px; }
.date-cell { color: #6B7280; font-size: 0.85rem; white-space: nowrap; }
.empty-cell { text-align: center; color: #9CA3AF; padding: 40px 16px !important; }
.actions-cell { white-space: nowrap; text-align: right; }
.faded td { opacity: 0.6; }
.muted { color: #9CA3AF; font-size: 0.85rem; }

@media (max-width: 768px) {
  .panel-header { flex-direction: column; }
  .copy-row { flex-direction: column; align-items: stretch; }
}
</style>
