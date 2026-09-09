import { vi } from 'vitest'

import type { Dataset, Earthquake, Page } from '../api'

export function makeDataset(overrides: Partial<Dataset> = {}): Dataset {
  return {
    id: 1,
    name: 'Global Earthquakes',
    source: 'USGS',
    description: null,
    created_at: '2026-09-09T08:08:12',
    status: 'completed',
    ...overrides,
  }
}

export function makeEarthquake(overrides: Partial<Earthquake> = {}): Earthquake {
  return {
    id: 1,
    external_id: 'eq1',
    magnitude: 2.3,
    magnitude_type: 'ml',
    place: 'somewhere',
    event_type: 'earthquake',
    occurred_at: '2026-09-09T10:54:00',
    longitude: 0,
    latitude: 0,
    depth_km: 15.4,
    tsunami: false,
    significance: 10,
    url: null,
    ...overrides,
  }
}

export function makePage(
  items: Earthquake[],
  overrides: Partial<Page<Earthquake>> = {},
): Page<Earthquake> {
  return {
    dataset_id: 1,
    total: items.length,
    limit: 25,
    offset: 0,
    filters: {},
    items,
    ...overrides,
  }
}

/** A promise whose resolution the test controls, for ordering requests. */
export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((resolveIt, rejectIt) => {
    resolve = resolveIt
    reject = rejectIt
  })
  return { promise, resolve, reject }
}

interface FetchCall {
  url: string
  signal?: AbortSignal
}

/**
 * Replace global fetch. `respond` receives the requested URL and returns the
 * body to serve, or a promise for it, so a test can control the ordering.
 */
export function mockFetch(
  respond: (url: string) => unknown | Promise<unknown>,
  { ok = true, status = 200 } = {},
) {
  const calls: FetchCall[] = []

  const implementation = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, signal: init?.signal ?? undefined })
      const body = await respond(url)
      if (init?.signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError')
      }
      return {
        ok,
        status,
        json: async () => body,
      } as Response
    },
  )

  vi.stubGlobal('fetch', implementation)
  return { calls, implementation }
}

/** Every URL requested so far, for asserting what was and was not sent. */
export function urlsOf(calls: FetchCall[]): string[] {
  return calls.map((call) => call.url)
}
