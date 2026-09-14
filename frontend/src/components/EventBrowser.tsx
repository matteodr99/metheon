import { useCallback, useEffect, useState } from 'react'

import {
  EMPTY_FILTERS,
  fetchEvents,
  type BoundingBox,
  type Dataset,
  depthOf,
  type EventFilters,
  type Event,
  type Page,
} from '../api'
import { ComparePanel } from './ComparePanel'
import { EventMap } from './EventMap'
import { InsightsPanel } from './InsightsPanel'
import { SummaryPanel } from './Summary'
import { formatMeasure, labelsFor } from '../kinds'

// Attributes worth a glance in the table: an alert level, who reported it,
// where. The rest — numbers, texts, ids — stays in the API.
const DETAIL_KEYS = ['alert_level', 'network', 'country', 'category']

function details(attributes: Record<string, unknown>): string {
  return DETAIL_KEYS.map((key) => attributes[key])
    .filter((value): value is string => typeof value === 'string' && value !== '')
    .join(' · ')
}

const PAGE_SIZE = 25

export function EventBrowser({
  datasetId,
  datasets = [],
  dataVersion = 0,
}: {
  datasetId: number
  /** Every dataset, for the comparison; the browser itself shows one. */
  datasets?: Dataset[]
  /** Changes when the stored data changed, forcing a re-read. */
  dataVersion?: number
}) {
  // `form` is what the user is typing; `applied` is what the last request
  // used. Keeping them apart avoids a request per keystroke.
  // The dataset's kind names the measure and decides the columns; a
  // browser handed no datasets (the tests, mostly) assumes earthquakes.
  const kind = datasets.find((dataset) => dataset.id === datasetId)?.kind ?? 'earthquake'
  const labels = labelsFor(kind)

  // What the Compare panel is set to, so the insights can speak of it too.
  const [otherId, setOtherId] = useState<number | null>(null)
  const handleOtherChange = useCallback((id: number | null) => setOtherId(id), [])
  const comparison = otherId === null ? null : { otherId, window: labels.match }

  const [form, setForm] = useState<EventFilters>(EMPTY_FILTERS)
  const [applied, setApplied] = useState<EventFilters>(EMPTY_FILTERS)
  const [offset, setOffset] = useState(0)

  // The result carries the query it answers. Loading is then derived rather
  // than tracked in its own flag, which cannot drift out of step with what
  // is on screen.
  const query = JSON.stringify([datasetId, applied, offset, dataVersion])
  const [result, setResult] = useState<{
    query: string
    page: Page<Event> | null
    error: string | null
  } | null>(null)

  const loading = result?.query !== query
  const page = result?.page ?? null
  const error = result?.query === query ? result.error : null

  useEffect(() => {
    // Aborting on change stops a slow earlier response from landing after a
    // newer one and showing results that do not match the filters.
    const controller = new AbortController()

    fetchEvents(datasetId, applied, PAGE_SIZE, offset, controller.signal)
      .then((loaded) => {
        setResult({ query, page: loaded, error: null })
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) {
          return
        }
        setResult({
          query,
          page: null,
          error: cause instanceof Error ? cause.message : String(cause),
        })
      })

    return () => controller.abort()
  }, [datasetId, applied, offset, dataVersion, query])

  function update(name: keyof EventFilters, value: string) {
    setForm((current) => ({ ...current, [name]: value }))
  }

  function apply(event: React.FormEvent) {
    event.preventDefault()
    // Back to the first page: the current offset may be past the end of the
    // narrower result.
    setOffset(0)
    setApplied(form)
  }

  function reset() {
    setForm(EMPTY_FILTERS)
    setApplied(EMPTY_FILTERS)
    setOffset(0)
  }

  // The map's button is an explicit action like Apply, so it applies at
  // once rather than only filling the fields; the other filters being
  // typed come along, as they would on submit.
  function filterToView(box: BoundingBox) {
    const next = { ...form, ...box }
    setForm(next)
    setApplied(next)
    setOffset(0)
  }

  // Derived from the page on screen, never from the pending offset: while a
  // new page loads the old rows are still displayed, and a caption counting
  // the requested range would describe rows nobody can see.
  const total = page?.total ?? 0
  const shown = page?.items.length ?? 0
  const shownFrom = page === null || shown === 0 ? 0 : page.offset + 1
  const shownTo = page === null ? 0 : page.offset + shown

  return (
    <section>
      <form className="filters" onSubmit={apply}>
        <label>
          <span>Min {labels.measure.toLowerCase()}</span>
          <input
            type="number"
            step="0.1"
            value={form.min_magnitude}
            onChange={(event) => update('min_magnitude', event.target.value)}
          />
        </label>
        <label>
          <span>Max {labels.measure.toLowerCase()}</span>
          <input
            type="number"
            step="0.1"
            value={form.max_magnitude}
            onChange={(event) => update('max_magnitude', event.target.value)}
          />
        </label>
        <label>
          <span>From</span>
          <input
            type="datetime-local"
            value={form.start_time}
            onChange={(event) => update('start_time', event.target.value)}
          />
        </label>
        <label>
          <span>To</span>
          <input
            type="datetime-local"
            value={form.end_time}
            onChange={(event) => update('end_time', event.target.value)}
          />
        </label>
        <label>
          <span>Event type</span>
          <input
            type="text"
            placeholder={kind}
            value={form.event_type}
            onChange={(event) => update('event_type', event.target.value)}
          />
        </label>
        <label>
          <span>Min latitude</span>
          <input
            type="number"
            step="0.0001"
            min="-90"
            max="90"
            value={form.min_latitude}
            onChange={(event) => update('min_latitude', event.target.value)}
          />
        </label>
        <label>
          <span>Max latitude</span>
          <input
            type="number"
            step="0.0001"
            min="-90"
            max="90"
            value={form.max_latitude}
            onChange={(event) => update('max_latitude', event.target.value)}
          />
        </label>
        <label>
          <span>Min longitude</span>
          <input
            type="number"
            step="0.0001"
            min="-180"
            max="180"
            value={form.min_longitude}
            onChange={(event) => update('min_longitude', event.target.value)}
          />
        </label>
        <label>
          <span>Max longitude</span>
          <input
            type="number"
            step="0.0001"
            min="-180"
            max="180"
            value={form.max_longitude}
            onChange={(event) => update('max_longitude', event.target.value)}
          />
        </label>
        <div className="filter-actions">
          <button type="submit">Apply</button>
          <button type="button" onClick={reset}>
            Reset
          </button>
        </div>
      </form>

      {/* Given the applied filters, not the ones being typed, so the
          numbers always describe the table below. */}
      <SummaryPanel datasetId={datasetId} kind={kind} filters={applied} dataVersion={dataVersion} />
      <EventMap
        datasetId={datasetId}
        kind={kind}
        filters={applied}
        dataVersion={dataVersion}
        onFilterToView={filterToView}
      />
      <InsightsPanel
        datasetId={datasetId}
        filters={applied}
        comparison={comparison}
        dataVersion={dataVersion}
      />
      <ComparePanel
        datasetId={datasetId}
        datasets={datasets}
        filters={applied}
        dataVersion={dataVersion}
        onOtherChange={handleOtherChange}
      />

      {error !== null && (
        <p role="alert" className="error">
          Could not load the events: {error}
        </p>
      )}

      {error === null && (
        <p className="summary">
          {total === 0
            ? 'No events match these filters.'
            : `Showing ${shownFrom}–${shownTo} of ${total}`}
          {loading && ' · loading…'}
        </p>
      )}

      {page !== null && page.items.length > 0 && (
        <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time (UTC)</th>
              <th className="numeric">{labels.measure}</th>
              <th>Place</th>
              <th>Type</th>
              {labels.depth && <th className="numeric">Depth</th>}
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((event) => (
              <tr key={event.id}>
                <td className="numeric">
                  {event.occurred_at.replace('T', ' ').slice(0, 19)}
                </td>
                <td className="numeric">
                  {formatMeasure(event.magnitude, event.magnitude_unit, kind)}
                </td>
                <td>
                  {event.url === null ? (
                    event.title
                  ) : (
                    <a href={event.url} target="_blank" rel="noreferrer">
                      {event.title}
                    </a>
                  )}
                </td>
                <td>{event.event_type}</td>
                {labels.depth && (
                  <td className="numeric">
                    {depthOf(event.attributes) === null
                      ? '—'
                      : `${depthOf(event.attributes)!.toFixed(1)} km`}
                  </td>
                )}
                <td className="muted">{details(event.attributes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}

      <div className="pagination">
        <button
          type="button"
          disabled={loading || offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </button>
        <button
          type="button"
          disabled={loading || offset + PAGE_SIZE >= total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Next
        </button>
      </div>
    </section>
  )
}
