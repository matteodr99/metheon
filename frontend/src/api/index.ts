// In development the dev server proxies /api to the backend, so requests
// are same-origin and the base is empty (see vite.config.ts). A deployed
// build lives on another domain than the API and sets VITE_API_URL at
// build time; the backend then needs that origin in CORS_ORIGINS.
const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '')

function api(path: string): string {
  return `${API_BASE}${path}`
}

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
  /** What kind of thing its events are; one kind per dataset. */
  kind: string
  /** When its latest completed run finished; null before the first. */
  last_ingested_at: string | null
}

/** What only one kind or source has: depth and network for a quake, and so on. */
export type Attributes = Record<string, unknown>

export interface Event {
  id: number
  external_id: string
  /** What the source calls it: a place for a quake, a name for a storm. */
  title: string | null
  event_type: string | null
  occurred_at: string
  ended_at: string | null
  source_updated_at: string | null
  longitude: number
  latitude: number
  geometry: Record<string, unknown> | null
  /** The number this kind of event is measured by, in `magnitude_unit`. */
  magnitude: number | null
  magnitude_unit: string | null
  attributes: Attributes
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

/** The filters the events endpoint accepts, as typed in the form. */
export interface EventFilters {
  min_magnitude: string
  max_magnitude: string
  start_time: string
  end_time: string
  event_type: string
  min_latitude: string
  max_latitude: string
  min_longitude: string
  max_longitude: string
}

export const EMPTY_FILTERS: EventFilters = {
  min_magnitude: '',
  max_magnitude: '',
  start_time: '',
  end_time: '',
  event_type: '',
  min_latitude: '',
  max_latitude: '',
  min_longitude: '',
  max_longitude: '',
}

/** The four bounding-box filters, as the map hands them over. */
export type BoundingBox = Pick<
  EventFilters,
  'min_latitude' | 'max_latitude' | 'min_longitude' | 'max_longitude'
>

/** `[longitude, latitude, magnitude, id]`, as the points endpoint sends it. */
/** The depth of a quake, when the source gave one; attributes are untyped. */
export function depthOf(attributes: Attributes): number | null {
  const depth = attributes.depth_km
  return typeof depth === 'number' ? depth : null
}

export type Point = [number, number, number | null, number]

export interface MatchedEvent {
  id: number
  external_id: string
  title: string | null
  occurred_at: string
  longitude: number
  latitude: number
  magnitude: number | null
  magnitude_unit: string | null
  attributes: Attributes
}

export interface Match {
  event: MatchedEvent
  other: MatchedEvent
  /** Other minus event. */
  delta_seconds: number
  distance_km: number
  /** Other minus event; null when either side has no magnitude. */
  delta_magnitude: number | null
}

export interface Matches {
  dataset_id: number
  other_id: number
  window_seconds: number
  radius_km: number
  limit: number
  filters: Record<string, string | number>
  events: number
  matched: number
  unmatched: number
  mean_abs_delta_seconds: number | null
  mean_distance_km: number | null
  mean_abs_delta_magnitude: number | null
  pairs: Match[]
}

export interface Points {
  dataset_id: number
  total: number
  limit: number
  filters: Record<string, string | number>
  points: Point[]
}

export interface Source {
  key: string
  name: string
  default_feed_url: string
  /** The kinds of event it serves; a dataset gets one of them. */
  kinds: string[]
}

export interface DatasetCreate {
  name: string
  source: string
  description?: string
  /** Required only when the source serves several kinds. */
  kind?: string
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

export interface AIStatus {
  configured: boolean
  model: string
}

export interface Insights {
  dataset_id: number
  filters: Record<string, string | number>
  model: string
  summary: string
  key_trends: string[]
  anomalies: string[]
  recommendations: string[]
  /** How another agency's reports compare; empty unless one was asked for. */
  agency_comparison: string
  other_id: number | null
}

/** What to compare the dataset with, when asking for insights. */
export interface Comparison {
  otherId: number
  window: MatchWindow
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
  const response = await fetch(api(url), { signal })
  if (!response.ok) {
    throw new Error(await describeFailure(response))
  }
  return response.json()
}

async function postJson<T>(
  url: string,
  signal?: AbortSignal,
  payload?: unknown,
): Promise<T> {
  const response = await fetch(api(url), {
    method: 'POST',
    signal,
    ...(payload === undefined
      ? {}
      : {
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }),
  })
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
  filters: EventFilters,
  signal?: AbortSignal,
): Promise<Summary> {
  return getJson<Summary>(
    `/api/datasets/${datasetId}/events/summary?${queryFor(filters)}`,
    signal,
  )
}

export function fetchEvents(
  datasetId: number,
  filters: EventFilters,
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<Page<Event>> {
  const query = queryFor(filters, {
    limit: String(limit),
    offset: String(offset),
  })
  return getJson<Page<Event>>(
    `/api/datasets/${datasetId}/events?${query}`,
    signal,
  )
}

export function fetchPoints(
  datasetId: number,
  filters: EventFilters,
  signal?: AbortSignal,
): Promise<Points> {
  return getJson<Points>(
    `/api/datasets/${datasetId}/events/points?${queryFor(filters)}`,
    signal,
  )
}

export interface MatchWindow {
  /** How far apart in time two reports of one event may be. */
  windowSeconds: number
  /** How far apart in space. */
  radiusKm: number
}

export function fetchMatches(
  datasetId: number,
  otherId: number,
  filters: EventFilters,
  window: MatchWindow,
  signal?: AbortSignal,
): Promise<Matches> {
  const query = queryFor(filters, {
    other: String(otherId),
    window_seconds: String(window.windowSeconds),
    radius_km: String(window.radiusKm),
  })
  return getJson<Matches>(
    `/api/datasets/${datasetId}/events/matches?${query}`,
    signal,
  )
}

/**
 * Turn the form into a query string. An empty field means "no filter":
 * sending it would be rejected as an unparsable value rather than ignored.
 */
function queryFor(
  filters: EventFilters,
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

/**
 * Start an ingestion and get the run back. With a worker the run comes
 * back `queued` and must be followed; without one (INGESTION_MODE=inline)
 * it comes back already finished.
 */
export function startIngestion(
  datasetId: number,
  signal?: AbortSignal,
): Promise<ImportRun> {
  return postJson<ImportRun>(`/api/datasets/${datasetId}/ingest`, signal)
}

/** Delete a dataset with its events and history. Resolves on 204. */
export async function deleteDataset(datasetId: number, signal?: AbortSignal): Promise<void> {
  const response = await fetch(api(`/api/datasets/${datasetId}`), { method: 'DELETE', signal })
  if (!response.ok) {
    throw new Error(await describeFailure(response))
  }
}

export function fetchSources(signal?: AbortSignal): Promise<Source[]> {
  return getJson<Source[]>('/api/sources', signal)
}

export function createDataset(
  payload: DatasetCreate,
  signal?: AbortSignal,
): Promise<Dataset> {
  return postJson<Dataset>('/api/datasets', signal, payload)
}

export function fetchAIStatus(signal?: AbortSignal): Promise<AIStatus> {
  return getJson<AIStatus>('/api/ai', signal)
}

export function fetchInsights(
  datasetId: number,
  filters: EventFilters,
  comparison: Comparison | null = null,
  signal?: AbortSignal,
): Promise<Insights> {
  const query = queryFor(
    filters,
    comparison === null
      ? {}
      : {
          other: String(comparison.otherId),
          window_seconds: String(comparison.window.windowSeconds),
          radius_km: String(comparison.window.radiusKm),
        },
  )
  return getJson<Insights>(`/api/datasets/${datasetId}/insights?${query}`, signal)
}
