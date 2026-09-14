import { useEffect, useState } from 'react'

import { fetchSummary, type EventFilters, type Summary } from '../api'
import { BarChart, type Bar } from './BarChart'
import { labelsFor } from '../kinds'

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}</span>
    </div>
  )
}

function magnitudeRange(summary: Summary, decimals: number): string {
  const { min, max } = summary.magnitude
  if (min === null || max === null) {
    return '—'
  }
  return `${min.toFixed(decimals)} – ${max.toFixed(decimals)}`
}

/** "2026-09-08" reads better as "09-08" once the year is on every bar. */
function shortDay(day: string): string {
  return day.slice(5)
}

export function SummaryPanel({
  datasetId,
  kind = 'earthquake',
  filters,
  dataVersion = 0,
}: {
  datasetId: number
  /** The dataset's kind: it names the measure the tiles describe. */
  kind?: string
  filters: EventFilters
  dataVersion?: number
}) {
  const labels = labelsFor(kind)
  const query = JSON.stringify([datasetId, filters, dataVersion])
  const [result, setResult] = useState<{
    query: string
    summary: Summary | null
  } | null>(null)

  useEffect(() => {
    const controller = new AbortController()

    fetchSummary(datasetId, filters, controller.signal)
      .then((summary) => setResult({ query, summary }))
      .catch(() => {
        if (!controller.signal.aborted) {
          // The table below reports the failure; a second alert for the same
          // outage would be noise.
          setResult({ query, summary: null })
        }
      })

    return () => controller.abort()
  }, [datasetId, filters, dataVersion, query])

  const summary = result?.query === query ? result.summary : null
  if (summary === null) {
    return null
  }

  const dayBars: Bar[] = summary.by_day.map((row) => ({
    label: shortDay(row.day),
    value: row.count,
  }))
  const typeBars: Bar[] = summary.by_event_type.map((row) => ({
    label: row.event_type ?? 'unknown',
    value: row.count,
  }))

  return (
    <section className="summary-panel">
      <div className="tiles">
        <Tile label="Events" value={String(summary.total)} />
        <Tile
          label={`${labels.measure} range`}
          value={magnitudeRange(summary, labels.decimals)}
        />
        <Tile
          label={`Average ${labels.measure.toLowerCase()}`}
          value={
            summary.magnitude.average === null
              ? '—'
              : summary.magnitude.average.toFixed(Math.max(labels.decimals, 1))
          }
        />
        <Tile
          label={`Without ${labels.measure.toLowerCase()}`}
          value={String(summary.magnitude.unknown)}
        />
      </div>

      <div className="charts">
        <BarChart
          bars={dayBars}
          title="Events per day (UTC)"
          emptyMessage="No events to plot."
        />
        <BarChart
          bars={typeBars}
          title="Events by type"
          emptyMessage="No events to plot."
          // A handful of categories with long names: padding the chart out
          // would squeeze the labels into ellipses.
          minSlots={0}
        />
      </div>
    </section>
  )
}
