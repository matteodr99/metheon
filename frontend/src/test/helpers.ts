import { vi } from 'vitest'

import type { Dataset, Earthquake, ImportRun, Page, Source, Summary } from '../api'

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

export function makeSummary(overrides: Partial<Summary> = {}): Summary {
  return {
    dataset_id: 1,
    filters: {},
    total: 1,
    magnitude: { min: 2.3, max: 2.3, average: 2.3, unknown: 0 },
    occurred_at: { first: '2026-09-09T10:54:00', last: '2026-09-09T10:54:00' },
    by_event_type: [{ event_type: 'earthquake', count: 1 }],
    by_day: [{ day: '2026-09-09', count: 1 }],
    ...overrides,
  }
}

export function makeImportRun(overrides: Partial<ImportRun> = {}): ImportRun {
  return {
    id: 1,
    dataset_id: 1,
    status: 'completed',
    feed_url: 'https://example.invalid/feed',
    queued_at: '2026-09-11T09:10:50',
    started_at: '2026-09-11T09:10:50.500',
    finished_at: '2026-09-11T09:10:51.200',
    fetched: 2155,
    valid: 2155,
    invalid: 0,
    inserted: 0,
    updated: 2155,
    invalid_sample: null,
    error: null,
    ...overrides,
  }
}

export function makeSource(overrides: Partial<Source> = {}): Source {
  return {
    key: 'usgs',
    name: 'USGS Earthquake Hazards Program',
    default_feed_url: 'https://example.invalid/usgs.geojson',
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
  method?: string
  body?: unknown
}

/**
 * Replace global fetch. `respond` receives the requested URL and returns the
 * body to serve, or a promise for it, so a test can control the ordering.
 */
export function mockFetch(
  respond: (url: string, init?: RequestInit) => unknown | Promise<unknown>,
  {
    ok = true,
    status = 200,
    summary = makeSummary(),
    imports = [] as ImportRun[],
    ai = { configured: false, model: '' },
    sources = [makeSource()] as Source[],
  } = {},
) {
  const calls: FetchCall[] = []

  const implementation = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      let parsedBody: unknown
      if (typeof init?.body === 'string') {
        try {
          parsedBody = JSON.parse(init.body)
        } catch {
          parsedBody = init.body
        }
      }
      calls.push({ url, signal: init?.signal ?? undefined, method, body: parsedBody })
      // The summary and ingestion panels are rendered alongside the table,
      // so they fetch too. Serving them here keeps every test from having to
      // route URLs it does not care about; pass `summary` or `imports` to
      // control them.
      let body: unknown
      if (url === '/api/ai') {
        body = ai
      } else if (url.includes('/summary')) {
        body = summary
      } else if (url.includes('/imports')) {
        body = { dataset_id: 1, total: imports.length, limit: 5, offset: 0, filters: {}, items: imports }
      } else if (url === '/api/sources') {
        body = sources
      } else {
        body = await respond(url, init)
      }
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
