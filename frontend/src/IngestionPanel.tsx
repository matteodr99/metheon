import { useEffect, useRef, useState } from 'react'

import { fetchImports, isActive, startIngestion, type ImportRun } from './api'

const HISTORY_SIZE = 5

/** How often the history is re-read while a run is in flight. */
export const POLL_INTERVAL_MS = 1500

function formatTime(iso: string | null): string {
  if (iso === null) {
    return '—'
  }
  return iso.replace('T', ' ').slice(0, 19)
}

function duration(run: ImportRun): string {
  if (run.started_at === null || run.finished_at === null) {
    return '—'
  }
  const ms = Date.parse(run.finished_at) - Date.parse(run.started_at)
  return `${(ms / 1000).toFixed(1)} s`
}

function describe(run: ImportRun): string {
  switch (run.status) {
    case 'queued':
      return 'Queued, waiting for a worker'
    case 'processing':
      return 'Processing'
    case 'completed':
      return `${run.fetched} fetched · ${run.inserted} new · ${run.updated} refreshed` +
        (run.invalid > 0 ? ` · ${run.invalid} invalid` : '')
    case 'failed':
      return run.error ?? 'Failed'
  }
}

export function IngestionPanel({
  datasetId,
  onRunFinished,
}: {
  datasetId: number
  /** Called once when a run that was in flight reaches a final state. */
  onRunFinished: () => void
}) {
  const [runs, setRuns] = useState<ImportRun[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  // Whether the latest run was active at the previous read. A transition
  // from active to final is what triggers the refresh, and only once.
  const wasActive = useRef(false)

  const latest = runs?.[0] ?? null
  const active = latest !== null && isActive(latest)

  useEffect(() => {
    const controller = new AbortController()

    function load() {
      fetchImports(datasetId, HISTORY_SIZE, controller.signal)
        .then((page) => {
          setRuns(page.items)
          setError(null)
          const nowActive = page.items[0] !== undefined && isActive(page.items[0])
          if (wasActive.current && !nowActive) {
            onRunFinished()
          }
          wasActive.current = nowActive
        })
        .catch((cause: unknown) => {
          if (!controller.signal.aborted) {
            setError(cause instanceof Error ? cause.message : String(cause))
          }
        })
    }

    load()
    // Polling only while something is in flight: an idle dashboard must not
    // hit the API every second and a half for nothing.
    const timer = active ? setInterval(load, POLL_INTERVAL_MS) : null

    return () => {
      controller.abort()
      if (timer !== null) {
        clearInterval(timer)
      }
    }
  }, [datasetId, active, onRunFinished])

  async function ingest() {
    setStarting(true)
    setError(null)
    try {
      await startIngestion(datasetId)
      // Re-read straight away so the queued run shows up without waiting
      // for the next poll; the effect then takes over.
      const page = await fetchImports(datasetId, HISTORY_SIZE)
      setRuns(page.items)
      wasActive.current = page.items[0] !== undefined && isActive(page.items[0])
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setStarting(false)
    }
  }

  return (
    <section className="ingestion">
      <div className="ingestion-bar">
        <button type="button" onClick={ingest} disabled={starting || active}>
          {active ? 'Ingesting…' : 'Ingest now'}
        </button>
        {latest !== null && (
          <span className="ingestion-latest">
            <span className={`status status-${latest.status}`}>{latest.status}</span>
            <span className="muted">{describe(latest)}</span>
          </span>
        )}
        {latest === null && runs !== null && (
          <span className="muted">Never ingested.</span>
        )}
      </div>

      {error !== null && (
        <p role="alert" className="error">
          Could not start the ingestion: {error}
        </p>
      )}

      {runs !== null && runs.length > 0 && (
        <details className="ingestion-history">
          <summary>Recent runs</summary>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Queued (UTC)</th>
                  <th>Status</th>
                  <th className="numeric">Fetched</th>
                  <th className="numeric">New</th>
                  <th className="numeric">Refreshed</th>
                  <th className="numeric">Invalid</th>
                  <th className="numeric">Duration</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td className="numeric">{formatTime(run.queued_at)}</td>
                    <td>
                      <span className={`status status-${run.status}`}>{run.status}</span>
                      {run.error !== null && (
                        <span className="run-error"> {run.error}</span>
                      )}
                    </td>
                    <td className="numeric">{run.fetched}</td>
                    <td className="numeric">{run.inserted}</td>
                    <td className="numeric">{run.updated}</td>
                    <td className="numeric">{run.invalid}</td>
                    <td className="numeric">{duration(run)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  )
}
