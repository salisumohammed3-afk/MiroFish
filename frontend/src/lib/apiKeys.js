// Shared by the admin area's API keys tab and the API docs page.

export const ACCESS_LABEL = { read: 'Read only', write: 'Read and change' }

export const ACCESS_BLURB = {
  read: 'Can look at everything in Forecast, for every client. Cannot change anything.',
  write: 'Can look at everything, rename projects and ask finished forecasts questions, for every client. It can never change who has access.'
}

export function keyStatus (k, now = Date.now()) {
  if (k.revoked_at) return 'Cancelled'
  if (k.expires_at && Date.parse(k.expires_at) <= now) return 'Expired'
  return 'Active'
}

export function shownDate (iso, none) {
  return iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : none
}

export function pasteLines (origin, key) {
  return {
    claude: `claude mcp add --transport http forecast ${origin}/mcp --header "Authorization: Bearer ${key}"`,
    curl: `curl ${origin}/api/v1/projects -H "Authorization: Bearer ${key}"`
  }
}

export const API_ROUTES = [
  { how: 'GET', path: '/api/v1/companies', what: 'Every client company, with its id, name and slug.', needs: 'Read only' },
  { how: 'GET', path: '/api/v1/projects', what: 'Every project, newest first. Add ?company=<id> for one client.', needs: 'Read only' },
  { how: 'GET', path: '/api/v1/projects/<id>', what: 'One project with its analysis summary and ontology.', needs: 'Read only' },
  { how: 'GET', path: '/api/v1/simulations', what: 'Every simulation, newest first. Add ?project=<id> or ?company=<id>.', needs: 'Read only' },
  { how: 'GET', path: '/api/v1/simulations/<id>', what: 'One simulation in full, with the id of its latest report.', needs: 'Read only' },
  { how: 'GET', path: '/api/v1/reports', what: 'Every report, newest first. Add ?simulation=<id> for one simulation.', needs: 'Read only' },
  { how: 'GET', path: '/api/v1/reports/<id>', what: 'One report in full, with its text in Markdown.', needs: 'Read only' },
  { how: 'PATCH', path: '/api/v1/projects/<id>', what: 'Renames a project from { "name": "..." }. Nothing else changes.', needs: 'Read and change' },
  { how: 'POST', path: '/api/v1/simulations/<id>/ask', what: 'Asks a finished forecast a question from { "message": "..." }. Uses AI credit.', needs: 'Read and change' }
]
