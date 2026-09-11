// The dev server proxies /api to the backend, so requests are same-origin
// and no base URL is needed. See vite.config.ts.

export type DatasetStatus =
  | 'pending'
  | 'queued'
  | 'processing'
  | 'completed'
  | 'failed'

export interface Dataset {
  id: number
  name: string
  source: string
  description: string | null
  created_at: string
  status: DatasetStatus
}

export interface Earthquake {
  id: number
  external_id: string
  magnitude: number | null
  magnitude_type: string | null
  place: string | null
  event_type: string | null
  occurred_at: string
  longitude: number
  latitude: number
  depth_km: number | null
  tsunami: boolean
  significance: number | null
  url: string | null
}

export interface Page<T> {
  dataset_id: number
  total: number
  limit: number
  offset: number
  filters: Record<string, string | number>
  items: T[]
}

/** The filters the earthquakes endpoint accepts, as typed in the form. */
export interface EarthquakeFilters {
  min_magnitude: string
  max_magnitude: string
  start_time: string
  end_time: string
  event_type: string
}

export const EMPTY_FILTERS: EarthquakeFilters = {
  min_magnitude: '',
  max_magnitude: '',
  start_time: '',
  end_time: '',
  event_type: '',
}

export type ImportStatus = 'queued' | 'processing' | 'completed' | 'failed'

export interface ImportRun {
  id: number
  dataset_id: number
  status: ImportStatus
  feed_url: string
  queued_at: string
  started_at: string | null
  finished_at: string | null
  fetched: number
  valid: number
  invalid: number
  inserted: number
  updated: number
  invalid_sample: string | null
  error: string | null
}

/** A run still in flight: the history must keep being polled. */
export function isActive(run: ImportRun): boolean {
  return run.status === 'queued' || run.status === 'processing'
}

export interface Summary {
  dataset_id: number
  filters: Record<string, string | number>
  total: number
  magnitude: {
    min: number | null
    max: number | null
    average: number | null
    unknown: number
  }
  occurred_at: { first: string | null; last: string | null }
  by_event_type: { event_type: string | null; count: number }[]
  by_day: { day: string; count: number }[]
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
  if (!response.ok) {
    throw new Error(await describeFailure(response))
  }
  return response.json()
}

async function postJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { method: 'POST', signal })
  if (!response.ok) {
    throw new Error(await describeFailure(response))
  }
  return response.json()
}

/**
 * The API explains refusals in a `detail` field. Surfacing it turns "503"
 * into "Could not enqueue the import: Redis is down", which is what a
 * person needs to read.
 */
async function describeFailure(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (body && typeof body.detail === 'string') {
      return `The API answered ${response.status}: ${body.detail}`
    }
  } catch {
    // Not JSON; fall through to the bare status.
  }
  return `The API answered ${response.status}`
}

export function fetchDatasets(signal?: AbortSignal): Promise<Dataset[]> {
  return getJson<Dataset[]>('/api/datasets', signal)
}

export function fetchSummary(
  datasetId: number,
  filters: EarthquakeFilters,
  signal?: AbortSignal,
): Promise<Summary> {
  return getJson<Summary>(
    `/api/datasets/${datasetId}/earthquakes/summary?${queryFor(filters)}`,
    signal,
  )
}

export function fetchEarthquakes(
  datasetId: number,
  filters: EarthquakeFilters,
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<Page<Earthquake>> {
  const query = queryFor(filters, {
    limit: String(limit),
    offset: String(offset),
  })
  return getJson<Page<Earthquake>>(
    `/api/datasets/${datasetId}/earthquakes?${query}`,
    signal,
  )
}

/**
 * Turn the form into a query string. An empty field means "no filter":
 * sending it would be rejected as an unparsable value rather than ignored.
 */
function queryFor(
  filters: EarthquakeFilters,
  extra: Record<string, string> = {},
): string {
  const query = new URLSearchParams(extra)
  for (const [name, value] of Object.entries(filters)) {
    if (value !== '') {
      query.set(name, value)
    }
  }
  return query.toString()
}

export function fetchImports(
  datasetId: number,
  limit: number,
  signal?: AbortSignal,
): Promise<Page<ImportRun>> {
  return getJson<Page<ImportRun>>(
    `/api/datasets/${datasetId}/imports?limit=${limit}&offset=0`,
    signal,
  )
}

export function startIngestion(
  datasetId: number,
  signal?: AbortSignal,
): Promise<{ import_id: number; dataset_id: number; status: ImportStatus }> {
  return postJson(`/api/datasets/${datasetId}/ingest`, signal)
}
