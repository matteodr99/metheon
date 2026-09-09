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

export function fetchEarthquakes(
  datasetId: number,
  filters: EarthquakeFilters,
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<Page<Earthquake>> {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  // An empty field means "no filter": sending it would be rejected as an
  // unparsable value rather than ignored.
  for (const [name, value] of Object.entries(filters)) {
    if (value !== '') {
      query.set(name, value)
    }
  }
  return getJson<Page<Earthquake>>(
    `/api/datasets/${datasetId}/earthquakes?${query.toString()}`,
    signal,
  )
}
