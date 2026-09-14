import { afterEach, describe, expect, it, vi } from 'vitest'

/**
 * VITE_API_URL is read when the module loads, so each test imports a fresh
 * copy of the client after setting the variable.
 */
async function freshClient() {
  vi.resetModules()
  return await import('./index')
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('the API base URL', () => {
  it('is empty in development, so requests stay same-origin', async () => {
    vi.stubEnv('VITE_API_URL', '')
    const seen: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      seen.push(String(input))
      return { ok: true, status: 200, json: async () => [] } as Response
    }))
    const { fetchDatasets } = await freshClient()

    await fetchDatasets()

    expect(seen).toEqual(['/api/datasets'])
  })

  it('prefixes every request when VITE_API_URL is set', async () => {
    vi.stubEnv('VITE_API_URL', 'https://metheon-api.koyeb.app')
    const seen: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      seen.push(String(input))
      return { ok: true, status: 200, json: async () => ({}) } as Response
    }))
    const { fetchDatasets, startIngestion, fetchAIStatus } = await freshClient()

    await fetchDatasets()
    await startIngestion(3)
    await fetchAIStatus()

    expect(seen).toEqual([
      'https://metheon-api.koyeb.app/api/datasets',
      'https://metheon-api.koyeb.app/api/datasets/3/ingest',
      'https://metheon-api.koyeb.app/api/ai',
    ])
  })

  it('tolerates a trailing slash in the variable', async () => {
    /** "https://host/" + "/api/x" must not become "https://host//api/x". */
    vi.stubEnv('VITE_API_URL', 'https://metheon-api.koyeb.app/')
    const seen: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      seen.push(String(input))
      return { ok: true, status: 200, json: async () => [] } as Response
    }))
    const { fetchDatasets } = await freshClient()

    await fetchDatasets()

    expect(seen).toEqual(['https://metheon-api.koyeb.app/api/datasets'])
  })
})
