import { vi } from 'vitest'

import type {
  Dataset,
  Event,
  ImportRun,
  Match,
  MatchedEvent,
  Matches,
  Page,
  Point,
  Points,
  Source,
  Summary,
} from '../api'

export function makeDataset(overrides: Partial<Dataset> = {}): Dataset {
  return {
    id: 1,
    name: 'Global Earthquakes',
    source: 'USGS',
    description: null,
    created_at: '2026-09-09T08:08:12',
    status: 'completed',
    kind: 'earthquake',
    ...overrides,
  }
}

export function makeEvent(overrides: Partial<Event> = {}): Event {
  return {
    id: 1,
    external_id: 'eq1',
    title: 'somewhere',
    event_type: 'earthquake',
    occurred_at: '2026-09-09T10:54:00',
    ended_at: null,
    source_updated_at: null,
    longitude: 0,
    latitude: 0,
    geometry: null,
    magnitude: 2.3,
    magnitude_unit: 'ml',
    attributes: { depth_km: 15.4, tsunami: false, significance: 10 },
    url: null,
    ...overrides,
  }
}

export function makePage(
  items: Event[],
  overrides: Partial<Page<Event>> = {},
): Page<Event> {
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

export function makeMatchedEvent(overrides: Partial<MatchedEvent> = {}): MatchedEvent {
  return {
    id: 1,
    external_id: 'us1',
    title: 'Isangel, Vanuatu',
    occurred_at: '2026-09-10T03:11:52',
    longitude: 169.98,
    latitude: -19.85,
    magnitude: 5.6,
    magnitude_unit: 'mww',
    attributes: { depth_km: 10, tsunami: false },
    ...overrides,
  }
}

export function makeMatch(overrides: Partial<Match> = {}): Match {
  return {
    event: makeMatchedEvent(),
    other: makeMatchedEvent({
      id: 2,
      external_id: 'ingv1',
      title: 'Vanuatu Islands [Sea: Vanuatu]',
      occurred_at: '2026-09-10T03:11:59',
      magnitude: 5.9,
      magnitude_unit: 'mwp',
      attributes: { depth_km: 68, tsunami: false },
    }),
    delta_seconds: 6.7,
    distance_km: 33.3,
    delta_magnitude: 0.3,
    ...overrides,
  }
}

export function makeMatches(pairs: Match[] = [], overrides: Partial<Matches> = {}): Matches {
  return {
    dataset_id: 1,
    other_id: 2,
    window_seconds: 60,
    radius_km: 100,
    limit: 50,
    filters: {},
    events: 4,
    matched: pairs.length,
    unmatched: 4 - pairs.length,
    mean_abs_delta_seconds: pairs.length === 0 ? null : 3.4,
    mean_distance_km: pairs.length === 0 ? null : 29.7,
    mean_abs_delta_magnitude: pairs.length === 0 ? null : 0.27,
    pairs,
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
    kinds: ['earthquake'],
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
    // A list of points, or the whole body when a test needs `total` to
    // differ from the number of points.
    points = [] as Point[] | Points,
    matches = makeMatches() as Matches,
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
      } else if (url.includes('/matches')) {
        body = matches
      } else if (url.includes('/points')) {
        body = Array.isArray(points)
          ? { dataset_id: 1, total: points.length, limit: 5000, filters: {}, points }
          : points
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
