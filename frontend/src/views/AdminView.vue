<template>
  <div class="admin-container">
    <nav class="navbar">
      <div class="nav-brand">
        <span class="brand-lang">Lang</span><span class="brand-sync">Sync</span>
        <span class="brand-forecast">Forecast</span>
        <span class="admin-badge">Admin</span>
      </div>
      <div class="nav-actions">
        <router-link to="/" class="nav-link">Dashboard</router-link>
        <button @click="handleSignOut" class="nav-link sign-out-btn">Sign out</button>
      </div>
    </nav>

    <div class="admin-content">
      <div class="admin-sidebar">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="sidebar-item"
          :class="{ active: activeTab === tab.id }"
          @click="activeTab = tab.id"
        >
          <span class="tab-icon">{{ tab.icon }}</span>
          {{ tab.label }}
        </button>
      </div>

      <div class="admin-main">
        <!-- Companies -->
        <div v-if="activeTab === 'companies'" class="panel">
          <div class="panel-header">
            <h2>Companies</h2>
            <button @click="showCreateCompany = true" class="action-btn primary">+ New Company</button>
          </div>

          <div v-if="showCreateCompany" class="inline-form">
            <input v-model="newCompany.name" placeholder="Company name" class="form-input" />
            <input v-model="newCompany.slug" placeholder="slug (lowercase, no spaces)" class="form-input" />
            <div class="inline-actions">
              <button @click="handleCreateCompany" class="action-btn primary" :disabled="saving">Create</button>
              <button @click="showCreateCompany = false" class="action-btn">Cancel</button>
            </div>
          </div>

          <div class="table-container">
            <table class="data-table">
              <thead>
                <tr><th>Name</th><th>Slug</th><th>Created</th><th>Actions</th></tr>
              </thead>
              <tbody>
                <tr v-for="c in companies" :key="c.id">
                  <td class="name-cell">{{ c.name }}</td>
                  <td><code>{{ c.slug }}</code></td>
                  <td class="date-cell">{{ formatDate(c.created_at) }}</td>
                  <td>
                    <button @click="confirmDelete('company', c)" class="action-btn danger sm">Delete</button>
                  </td>
                </tr>
                <tr v-if="companies.length === 0">
                  <td colspan="4" class="empty-cell">No companies yet</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Users -->
        <div v-if="activeTab === 'users'" class="panel">
          <div class="panel-header">
            <h2>Users</h2>
            <div class="header-actions">
              <select v-model="userFilter" class="filter-select" @change="loadUsers">
                <option value="">All companies</option>
                <option v-for="c in companies" :key="c.id" :value="c.id">{{ c.name }}</option>
              </select>
              <button @click="showCreateUser = true" class="action-btn primary">+ Create User</button>
            </div>
          </div>

          <div v-if="showCreateUser" class="create-user-form">
            <h3>Create New User</h3>
            <p class="form-hint">The user will be asked to change their password on first login.</p>
            <div class="form-grid">
              <div class="form-group">
                <label class="form-label">Name</label>
                <input v-model="newUser.display_name" placeholder="Full name" class="form-input" />
              </div>
              <div class="form-group">
                <label class="form-label">Email</label>
                <input v-model="newUser.email" type="email" placeholder="user@company.com" class="form-input" />
              </div>
              <div class="form-group">
                <label class="form-label">Temporary Password</label>
                <div class="password-row">
                  <input v-model="newUser.password" :type="showPassword ? 'text' : 'password'" placeholder="Min 8 characters" class="form-input" />
                  <button @click="showPassword = !showPassword" class="toggle-pw" type="button">{{ showPassword ? 'Hide' : 'Show' }}</button>
                  <button @click="generatePassword" class="toggle-pw" type="button">Generate</button>
                </div>
              </div>
              <div class="form-group">
                <label class="form-label">Company</label>
                <select v-model="newUser.company_id" class="form-input">
                  <option value="">Select company</option>
                  <option v-for="c in companies" :key="c.id" :value="c.id">{{ c.name }}</option>
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">Access Level</label>
                <select v-model="newUser.role" class="form-input">
                  <option value="member">Member — can create and run simulations</option>
                  <option value="admin">Admin — can also manage company users</option>
                  <option value="viewer">Viewer — read-only access</option>
                </select>
              </div>
            </div>
            <div v-if="createError" class="error-msg">{{ createError }}</div>
            <div v-if="createSuccess" class="success-msg">
              User created! Share these credentials:<br>
              <strong>Email:</strong> {{ createSuccess.email }}<br>
              <strong>Password:</strong> {{ createSuccess.password }}
            </div>
            <div class="form-actions">
              <button @click="handleCreateUser" class="action-btn primary" :disabled="saving">
                {{ saving ? 'Creating...' : 'Create User' }}
              </button>
              <button @click="closeCreateUser" class="action-btn">Close</button>
            </div>
          </div>

          <div class="table-container">
            <table class="data-table">
              <thead>
                <tr><th>Name</th><th>Email</th><th>Company</th><th>Role</th><th>Status</th><th>Actions</th></tr>
              </thead>
              <tbody>
                <tr v-for="u in users" :key="u.id">
                  <td class="name-cell">{{ u.display_name || '—' }}</td>
                  <td>{{ u.email }}</td>
                  <td>{{ u.companies?.name || 'Unassigned' }}</td>
                  <td>
                    <select
                      :value="u.role"
                      @change="handleUpdateUser(u.id, { role: $event.target.value })"
                      class="inline-select"
                    >
                      <option value="super_admin">Super Admin</option>
                      <option value="admin">Admin</option>
                      <option value="member">Member</option>
                      <option value="viewer">Viewer</option>
                    </select>
                  </td>
                  <td>
                    <span class="status-pill" :class="u.is_active ? 'active' : 'inactive'">
                      {{ u.is_active ? 'Active' : 'Disabled' }}
                    </span>
                    <span v-if="u.must_change_password" class="status-pill pending">Temp password</span>
                  </td>
                  <td class="actions-cell">
                    <select
                      :value="u.company_id || ''"
                      @change="handleUpdateUser(u.id, { company_id: $event.target.value || null })"
                      class="inline-select"
                    >
                      <option value="">Unassigned</option>
                      <option v-for="c in companies" :key="c.id" :value="c.id">{{ c.name }}</option>
                    </select>
                    <button
                      @click="handleUpdateUser(u.id, { is_active: !u.is_active })"
                      class="action-btn sm"
                      :class="u.is_active ? 'danger' : 'primary'"
                    >{{ u.is_active ? 'Disable' : 'Enable' }}</button>
                  </td>
                </tr>
                <tr v-if="users.length === 0">
                  <td colspan="6" class="empty-cell">No users found</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- Confirm modal -->
    <div v-if="confirmModal" class="modal-overlay" @click.self="confirmModal = null">
      <div class="modal-card">
        <h3>Confirm Delete</h3>
        <p>Are you sure you want to delete <strong>{{ confirmModal.name }}</strong>? This cannot be undone.</p>
        <div class="modal-actions">
          <button @click="executeDelete" class="action-btn danger">Delete</button>
          <button @click="confirmModal = null" class="action-btn">Cancel</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { signOut } from '../store/auth'
import { useRouter } from 'vue-router'
import {
  listCompanies, createCompany, deleteCompany,
  listUsers, createUser, updateUser,
} from '../api/auth'

const router = useRouter()

const tabs = [
  { id: 'companies', label: 'Companies', icon: '◆' },
  { id: 'users', label: 'Users', icon: '◇' },
]
const activeTab = ref('companies')

const companies = ref([])
const users = ref([])
const userFilter = ref('')
const saving = ref(false)
const confirmModal = ref(null)

const showCreateCompany = ref(false)
const newCompany = ref({ name: '', slug: '' })

const showCreateUser = ref(false)
const showPassword = ref(false)
const createError = ref('')
const createSuccess = ref(null)
const newUser = ref({ display_name: '', email: '', password: '', company_id: '', role: 'member' })

const formatDate = (d) => d ? new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'

const generatePassword = () => {
  const chars = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
  let pw = ''
  for (let i = 0; i < 12; i++) pw += chars[Math.floor(Math.random() * chars.length)]
  newUser.value.password = pw
  showPassword.value = true
}

const loadCompanies = async () => {
  try { companies.value = (await listCompanies()).data } catch (e) { console.error(e) }
}

const loadUsers = async () => {
  try { users.value = (await listUsers(userFilter.value || undefined)).data } catch (e) { console.error(e) }
}

onMounted(() => {
  loadCompanies()
  loadUsers()
})

const handleCreateCompany = async () => {
  if (!newCompany.value.name || !newCompany.value.slug) return
  saving.value = true
  try {
    await createCompany(newCompany.value)
    newCompany.value = { name: '', slug: '' }
    showCreateCompany.value = false
    await loadCompanies()
  } catch (e) {
    alert(e.response?.data?.error || e.message)
  } finally { saving.value = false }
}

const handleCreateUser = async () => {
  createError.value = ''
  createSuccess.value = null
  const u = newUser.value
  if (!u.display_name || !u.email || !u.password || !u.company_id) {
    createError.value = 'All fields are required.'
    return
  }
  if (u.password.length < 8) {
    createError.value = 'Password must be at least 8 characters.'
    return
  }
  saving.value = true
  try {
    await createUser(u)
    createSuccess.value = { email: u.email, password: u.password }
    newUser.value = { display_name: '', email: '', password: '', company_id: u.company_id, role: 'member' }
    await loadUsers()
  } catch (e) {
    createError.value = e.response?.data?.error || e.message
  } finally { saving.value = false }
}

const closeCreateUser = () => {
  showCreateUser.value = false
  createError.value = ''
  createSuccess.value = null
  newUser.value = { display_name: '', email: '', password: '', company_id: '', role: 'member' }
}

const handleUpdateUser = async (userId, updates) => {
  try {
    await updateUser(userId, updates)
    await loadUsers()
  } catch (e) { alert(e.response?.data?.error || e.message) }
}

const confirmDelete = (type, item) => {
  confirmModal.value = { type, id: item.id, name: item.name || item.email }
}

const executeDelete = async () => {
  if (!confirmModal.value) return
  try {
    if (confirmModal.value.type === 'company') {
      await deleteCompany(confirmModal.value.id)
      await loadCompanies()
    }
  } catch (e) { alert(e.message) }
  confirmModal.value = null
}

const handleSignOut = async () => {
  await signOut()
  router.push('/login')
}
</script>

<style scoped>
.admin-container {
  min-height: 100vh;
  background: #F9FAFB;
  font-family: 'Avenir Next', 'Inter', system-ui, -apple-system, sans-serif;
}

.navbar {
  height: 60px;
  background: #0F0F0F;
  color: #FFFFFF;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 40px;
}

.nav-brand { font-weight: 700; letter-spacing: -0.5px; font-size: 1.25rem; display: flex; align-items: center; gap: 8px; }
.brand-lang { color: #818CF8; }
.brand-sync { color: #A78BFA; }
.brand-forecast { color: #FFFFFF; margin-left: 6px; font-weight: 500; opacity: 0.7; }

.admin-badge {
  background: linear-gradient(135deg, #4F46E5, #7C3AED);
  color: #FFF;
  font-size: 0.65rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 2px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.nav-actions { display: flex; align-items: center; gap: 20px; }
.nav-link { color: #FFFFFF; text-decoration: none; font-size: 0.9rem; opacity: 0.8; transition: opacity 0.2s; }
.nav-link:hover { opacity: 1; }
.sign-out-btn { background: none; border: none; cursor: pointer; font-family: inherit; }

.admin-content {
  display: flex;
  max-width: 1400px;
  margin: 0 auto;
  min-height: calc(100vh - 60px);
}

.admin-sidebar {
  width: 220px;
  background: #FFFFFF;
  border-right: 1px solid #E5E7EB;
  padding: 20px 0;
  flex-shrink: 0;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 12px 24px;
  border: none;
  background: none;
  font-size: 0.95rem;
  font-family: inherit;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}

.sidebar-item:hover { background: #F9FAFB; color: #111827; }
.sidebar-item.active { color: #4F46E5; background: rgba(79, 70, 229, 0.06); border-right: 2px solid #4F46E5; font-weight: 600; }
.tab-icon { font-size: 0.8rem; }

.admin-main {
  flex: 1;
  padding: 32px 40px;
  overflow-x: auto;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.panel-header h2 { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.5px; margin: 0; }
.header-actions { display: flex; gap: 12px; align-items: center; }

.action-btn {
  padding: 8px 16px;
  border: 1.5px solid #E5E7EB;
  border-radius: 4px;
  background: #FFFFFF;
  font-size: 0.85rem;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}

.action-btn:hover { border-color: #D1D5DB; background: #F9FAFB; }
.action-btn.primary { background: linear-gradient(135deg, #4F46E5, #7C3AED); color: #FFF; border-color: transparent; }
.action-btn.primary:hover { opacity: 0.9; }
.action-btn.danger { color: #DC2626; border-color: #FCA5A5; }
.action-btn.danger:hover { background: #FEF2F2; }
.action-btn.sm { padding: 4px 10px; font-size: 0.8rem; }
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.inline-form {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  flex-wrap: wrap;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 20px;
  margin-bottom: 24px;
}

.inline-form .form-input {
  padding: 10px 14px;
  border: 1.5px solid #E5E7EB;
  border-radius: 4px;
  font-size: 0.9rem;
  font-family: inherit;
  min-width: 180px;
  background: #FAFAFA;
}

.inline-form .form-input:focus { outline: none; border-color: #5B5FE5; background: #FFF; }
.inline-actions { display: flex; gap: 8px; }

.create-user-form {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 28px;
  margin-bottom: 24px;
}

.create-user-form h3 { font-size: 1.1rem; font-weight: 600; margin: 0 0 4px; }
.form-hint { color: #6B7280; font-size: 0.85rem; margin: 0 0 20px; }

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}

.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-label { font-size: 0.78rem; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; color: #374151; }

.create-user-form .form-input {
  padding: 10px 14px;
  border: 1.5px solid #E5E7EB;
  border-radius: 4px;
  font-size: 0.9rem;
  font-family: inherit;
  background: #FAFAFA;
  width: 100%;
}

.create-user-form .form-input:focus { outline: none; border-color: #5B5FE5; background: #FFF; }

.password-row { display: flex; gap: 8px; align-items: center; }
.password-row .form-input { flex: 1; }

.toggle-pw {
  padding: 6px 10px;
  border: 1px solid #E5E7EB;
  border-radius: 3px;
  background: #FFF;
  font-size: 0.78rem;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  color: #5B5FE5;
  font-weight: 500;
}

.toggle-pw:hover { background: #F9FAFB; }

.form-actions { display: flex; gap: 8px; margin-top: 4px; }

.error-msg {
  color: #DC2626;
  font-size: 0.85rem;
  background: #FEF2F2;
  padding: 10px 14px;
  border-radius: 4px;
  border-left: 3px solid #DC2626;
  margin-bottom: 16px;
}

.success-msg {
  color: #059669;
  font-size: 0.85rem;
  background: #ECFDF5;
  padding: 14px;
  border-radius: 4px;
  border-left: 3px solid #059669;
  margin-bottom: 16px;
  line-height: 1.7;
}

.filter-select {
  padding: 8px 12px;
  border: 1.5px solid #E5E7EB;
  border-radius: 4px;
  font-size: 0.85rem;
  font-family: inherit;
  background: #FFFFFF;
}

.table-container {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  overflow: hidden;
}

.data-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }

.data-table th {
  text-align: left;
  padding: 12px 16px;
  background: #F9FAFB;
  font-weight: 600;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #6B7280;
  border-bottom: 1px solid #E5E7EB;
}

.data-table td {
  padding: 12px 16px;
  border-bottom: 1px solid #F3F4F6;
  color: #374151;
  vertical-align: middle;
}

.data-table tr:last-child td { border-bottom: none; }
.name-cell { font-weight: 600; color: #111827; }
.date-cell { color: #6B7280; font-size: 0.85rem; }
.empty-cell { text-align: center; color: #9CA3AF; padding: 40px 16px !important; }
.actions-cell { white-space: nowrap; }

code {
  background: rgba(79, 70, 229, 0.06);
  padding: 2px 6px;
  border-radius: 2px;
  font-size: 0.85em;
  color: #4F46E5;
}

.inline-select {
  padding: 4px 8px;
  border: 1px solid #E5E7EB;
  border-radius: 3px;
  font-size: 0.85rem;
  font-family: inherit;
  background: #FFF;
  margin-right: 6px;
}

.status-pill {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 0.78rem;
  font-weight: 600;
  margin-right: 4px;
}

.status-pill.active { background: #ECFDF5; color: #059669; }
.status-pill.inactive { background: #FEF2F2; color: #DC2626; }
.status-pill.pending { background: #FFF7ED; color: #D97706; }

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-card {
  background: #FFF;
  border-radius: 8px;
  padding: 32px;
  max-width: 420px;
  width: 100%;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}

.modal-card h3 { font-size: 1.2rem; margin: 0 0 12px; }
.modal-card p { color: #6B7280; margin: 0 0 24px; line-height: 1.5; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; }

@media (max-width: 768px) {
  .admin-content { flex-direction: column; }
  .admin-sidebar { width: 100%; border-right: none; border-bottom: 1px solid #E5E7EB; display: flex; overflow-x: auto; padding: 0; }
  .sidebar-item { padding: 12px 16px; white-space: nowrap; }
  .sidebar-item.active { border-right: none; border-bottom: 2px solid #4F46E5; }
  .admin-main { padding: 24px 16px; }
  .form-grid { grid-template-columns: 1fr; }
  .header-actions { flex-direction: column; gap: 8px; }
}
</style>
