import { useEffect, useState } from 'react'

import {
  EMPTY_FILTERS,
  fetchEarthquakes,
  type Earthquake,
  type EarthquakeFilters,
  type Page,
} from './api'

const PAGE_SIZE = 25

function formatMagnitude(earthquake: Earthquake): string {
  // The feed legitimately omits the magnitude; showing 0 would be a lie.
  if (earthquake.magnitude === null) {
    return '—'
  }
  const type = earthquake.magnitude_type ?? ''
  return `${earthquake.magnitude.toFixed(1)}${type ? ` ${type}` : ''}`
}

export function EarthquakeBrowser({ datasetId }: { datasetId: number }) {
  // `form` is what the user is typing; `applied` is what the last request
  // used. Keeping them apart avoids a request per keystroke.
  const [form, setForm] = useState<EarthquakeFilters>(EMPTY_FILTERS)
  const [applied, setApplied] = useState<EarthquakeFilters>(EMPTY_FILTERS)
  const [offset, setOffset] = useState(0)

  // The result carries the query it answers. Loading is then derived rather
  // than tracked in its own flag, which cannot drift out of step with what
  // is on screen.
  const query = JSON.stringify([datasetId, applied, offset])
  const [result, setResult] = useState<{
    query: string
    page: Page<Earthquake> | null
    error: string | null
  } | null>(null)

  const loading = result?.query !== query
  const page = result?.page ?? null
  const error = result?.query === query ? result.error : null

  useEffect(() => {
    // Aborting on change stops a slow earlier response from landing after a
    // newer one and showing results that do not match the filters.
    const controller = new AbortController()

    fetchEarthquakes(datasetId, applied, PAGE_SIZE, offset, controller.signal)
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
  }, [datasetId, applied, offset, query])

  function update(name: keyof EarthquakeFilters, value: string) {
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
          Min magnitude
          <input
            type="number"
            step="0.1"
            value={form.min_magnitude}
            onChange={(event) => update('min_magnitude', event.target.value)}
          />
        </label>
        <label>
          Max magnitude
          <input
            type="number"
            step="0.1"
            value={form.max_magnitude}
            onChange={(event) => update('max_magnitude', event.target.value)}
          />
        </label>
        <label>
          From
          <input
            type="datetime-local"
            value={form.start_time}
            onChange={(event) => update('start_time', event.target.value)}
          />
        </label>
        <label>
          To
          <input
            type="datetime-local"
            value={form.end_time}
            onChange={(event) => update('end_time', event.target.value)}
          />
        </label>
        <label>
          Event type
          <input
            type="text"
            placeholder="earthquake"
            value={form.event_type}
            onChange={(event) => update('event_type', event.target.value)}
          />
        </label>
        <div className="filter-actions">
          <button type="submit">Apply</button>
          <button type="button" onClick={reset}>
            Reset
          </button>
        </div>
      </form>

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
        <table>
          <thead>
            <tr>
              <th>Time (UTC)</th>
              <th>Magnitude</th>
              <th>Place</th>
              <th>Type</th>
              <th>Depth</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((earthquake) => (
              <tr key={earthquake.id}>
                <td>{earthquake.occurred_at.replace('T', ' ').slice(0, 19)}</td>
                <td>{formatMagnitude(earthquake)}</td>
                <td>
                  {earthquake.url === null ? (
                    earthquake.place
                  ) : (
                    <a href={earthquake.url} target="_blank" rel="noreferrer">
                      {earthquake.place}
                    </a>
                  )}
                </td>
                <td>{earthquake.event_type}</td>
                <td>
                  {earthquake.depth_km === null
                    ? '—'
                    : `${earthquake.depth_km.toFixed(1)} km`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
