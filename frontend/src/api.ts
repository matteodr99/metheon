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
    throw new Error(`The API answered ${response.status}`)
  }
  return response.json()
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
