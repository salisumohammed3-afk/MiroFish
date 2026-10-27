<template>
  <div class="docs-page">
    <nav class="navbar">
      <div class="nav-brand">
        <span class="brand-lang">Lang</span><span class="brand-sync">Sync</span>
        <span class="brand-forecast">Forecast</span>
      </div>
      <div class="nav-actions">
        <router-link to="/" class="nav-link">Dashboard</router-link>
        <router-link :to="{ path: '/admin', query: { tab: 'apikeys' } }" class="nav-link">API keys</router-link>
      </div>
    </nav>

    <main class="docs">
      <h1>Forecast API</h1>
      <p class="lead">
        Other tools, Claude and agents can use Forecast with an API key from the admin area. Every key works for every client.
        A read only key can look at everything; a read and change key can also rename projects and ask finished forecasts questions.
        No key can change who has access, build a knowledge map or start a simulation.
      </p>

      <h2>Connect Claude</h2>
      <p>In Claude Code, run this once with your key:</p>
      <pre>{{ claudeLine }}</pre>
      <p>
        Claude then has these tools: list_companies, list_projects, get_project, list_simulations, get_simulation, list_reports
        and get_report, plus rename_project and ask_forecast for a read and change key.
      </p>

      <h2>Call it directly</h2>
      <p>Send the key in the Authorization header. Answers are JSON, with the result under "data".</p>
      <pre>{{ curlLine }}</pre>
      <div class="table-container">
        <table>
          <thead><tr><th>Request</th><th>What it does</th><th>Key needed</th></tr></thead>
          <tbody>
            <tr v-for="r in API_ROUTES" :key="r.how + r.path">
              <td class="mono">{{ r.how }} {{ r.path }}</td>
              <td>{{ r.what }}</td>
              <td class="nowrap">{{ r.needs }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2>When something is refused</h2>
      <p>
        Every refusal comes back as { "error": "..." } in plain words. 401 means the key is missing, wrong, cancelled, expired or
        for another product. 403 means a read only key tried to change something. 429 means more than 120 requests in a minute.
        503 means the key could not be checked just then, so try again.
      </p>
    </main>
  </div>
</template>

<script setup>
import { API_ROUTES } from '../lib/apiKeys'

const base = window.location.origin
const key = 'lsk_forecast_...'
const claudeLine = `claude mcp add --transport http forecast ${base}/mcp --header "Authorization: Bearer ${key}"`
const curlLine = `curl ${base}/api/v1/projects -H "Authorization: Bearer ${key}"`
</script>

<style scoped>
.docs-page { min-height: 100vh; background: #F9FAFB; font-family: 'Avenir Next', 'Inter', system-ui, -apple-system, sans-serif; color: #111827; }
.navbar { height: 60px; background: #0F0F0F; color: #FFFFFF; display: flex; justify-content: space-between; align-items: center; padding: 0 40px; }
.nav-brand { font-weight: 700; letter-spacing: -0.5px; font-size: 1.25rem; display: flex; align-items: center; gap: 8px; }
.brand-lang { color: #7cc4ff; }
.brand-sync { color: #A78BFA; }
.brand-forecast { color: #FFFFFF; margin-left: 6px; font-weight: 500; opacity: 0.7; }
.nav-actions { display: flex; gap: 20px; }
.nav-link { color: #FFFFFF; text-decoration: none; font-size: 0.9rem; opacity: 0.8; }
.nav-link:hover { opacity: 1; }

.docs { max-width: 820px; margin: 0 auto; padding: 40px 24px 80px; }
h1 { font-size: 2rem; font-weight: 700; letter-spacing: -0.5px; margin: 0; }
h2 { font-size: 1.2rem; font-weight: 600; margin: 36px 0 8px; }
p { font-size: 0.95rem; line-height: 1.6; margin: 0 0 8px; }
.lead { color: #6B7280; margin-top: 10px; }
pre { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 6px; padding: 12px 14px; font-size: 0.8rem; overflow-x: auto; margin: 8px 0 12px; }

.table-container { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 6px; overflow-x: auto; margin-top: 16px; }
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
th { text-align: left; padding: 12px 16px; background: #F9FAFB; font-weight: 600; font-size: 0.82rem; color: #6B7280; border-bottom: 1px solid #E5E7EB; }
td { padding: 12px 16px; border-bottom: 1px solid #F3F4F6; vertical-align: top; }
tr:last-child td { border-bottom: none; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; white-space: nowrap; }
.nowrap { white-space: nowrap; }

@media (max-width: 768px) {
  .navbar { padding: 0 16px; }
  .docs { padding: 28px 16px 60px; }
}
</style>
