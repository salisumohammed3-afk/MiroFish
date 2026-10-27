import { describe, expect, it } from 'vitest'
import { ACCESS_LABEL, keyStatus, pasteLines, shownDate, API_ROUTES } from '../apiKeys'

describe('API keys screen helpers', () => {
  it('labels access in plain words', () => {
    expect(ACCESS_LABEL).toEqual({ read: 'Read only', write: 'Read and change' })
  })

  it('tells active, cancelled and expired keys apart', () => {
    const now = Date.parse('2026-10-27T12:00:00Z')
    expect(keyStatus({ revoked_at: null, expires_at: null }, now)).toBe('Active')
    expect(keyStatus({ revoked_at: '2026-10-01T00:00:00Z', expires_at: null }, now)).toBe('Cancelled')
    expect(keyStatus({ revoked_at: null, expires_at: '2026-10-27T11:59:59Z' }, now)).toBe('Expired')
    expect(keyStatus({ revoked_at: null, expires_at: '2026-10-28T00:00:00Z' }, now)).toBe('Active')
  })

  it('gives the Claude and curl lines for a new key', () => {
    const lines = pasteLines('https://forecast.langsync.ai', 'lsk_forecast_abc')
    expect(lines.claude).toBe('claude mcp add --transport http forecast https://forecast.langsync.ai/mcp --header "Authorization: Bearer lsk_forecast_abc"')
    expect(lines.curl).toBe('curl https://forecast.langsync.ai/api/v1/projects -H "Authorization: Bearer lsk_forecast_abc"')
  })

  it('shows dates the British way, or a word when there is none', () => {
    expect(shownDate('2026-12-31T23:59:59Z', 'Never')).toBe('31 Dec 2026')
    expect(shownDate(null, 'Never')).toBe('Never')
  })

  it('lists every route the docs page describes, with the key each needs', () => {
    expect(API_ROUTES.filter((r) => r.needs === 'Read and change').map((r) => `${r.how} ${r.path}`)).toEqual([
      'PATCH /api/v1/projects/<id>',
      'POST /api/v1/simulations/<id>/ask',
    ])
    expect(API_ROUTES.length).toBe(9)
  })

  it('uses no dashes or middle dots in its copy', () => {
    const copy = JSON.stringify({ ACCESS_LABEL, API_ROUTES })
    expect(copy).not.toMatch(/[–—·]/)
  })
})
