import { useEffect, useState } from 'react'

import {
  fetchMatches,
  type Dataset,
  type EarthquakeFilters,
  type Match,
  type Matches,
} from '../api'

function magnitude(value: number | null, type: string | null): string {
  if (value === null) {
    return '—'
  }
  return `${value.toFixed(1)}${type ? ` ${type}` : ''}`
}

function signed(value: number, digits: number, unit = ''): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(digits)}${unit}`
}

function depth(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(0)} km`
}

/** Prefer a dataset from another agency: comparing two USGS datasets says little. */
function defaultOther(datasetId: number, others: Dataset[], datasets: Dataset[]): number | null {
  const mine = datasets.find((dataset) => dataset.id === datasetId)?.source.toLowerCase()
  const different = others.find((other) => other.source.toLowerCase() !== mine)
  return (different ?? others[0])?.id ?? null
}

function caption(matches: Matches, other: Dataset): string {
  const parts = [`${matches.matched} of ${matches.events} events also reported by ${other.name}`]
  if (matches.mean_distance_km !== null) {
    parts.push(`epicentres ${matches.mean_distance_km.toFixed(0)} km apart on average`)
  }
  if (matches.mean_abs_delta_magnitude !== null) {
    parts.push(`magnitudes differ by ${matches.mean_abs_delta_magnitude.toFixed(2)} on average`)
  }
  return parts.join(' · ')
}

export function ComparePanel({
  datasetId,
  datasets,
  filters,
  dataVersion = 0,
}: {
  datasetId: number
  /** Every dataset, this one included; the panel picks the candidates. */
  datasets: Dataset[]
  /** The applied filters: they narrow this dataset's side of the pairs. */
  filters: EarthquakeFilters
  dataVersion?: number
}) {
  const others = datasets.filter((dataset) => dataset.id !== datasetId)
  const [chosen, setChosen] = useState<number | null>(null)
  // The choice is kept only while it exists; a dataset gone from the list
  // (or a switch to the dataset it named) falls back to the default.
  const otherId = others.some((other) => other.id === chosen)
    ? chosen
    : defaultOther(datasetId, others, datasets)
  const other = others.find((candidate) => candidate.id === otherId) ?? null

  const query = JSON.stringify([datasetId, otherId, filters, dataVersion])
  const [result, setResult] = useState<{
    query: string
    matches: Matches | null
    error: string | null
  } | null>(null)
  const loading = otherId !== null && result?.query !== query
  const matches = result?.query === query ? result.matches : null
  const error = result?.query === query ? result.error : null

  useEffect(() => {
    if (otherId === null) {
      return
    }
    const controller = new AbortController()
    fetchMatches(datasetId, otherId, filters, controller.signal)
      .then((loaded) => {
        setResult({ query, matches: loaded, error: null })
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) {
          return
        }
        setResult({
          query,
          matches: null,
          error: cause instanceof Error ? cause.message : String(cause),
        })
      })
    return () => controller.abort()
  }, [datasetId, otherId, filters, dataVersion, query])

  if (others.length === 0) {
    return (
      <section className="compare">
        <div className="compare-bar">
          <span className="section-label">Compare</span>
          <span className="muted">Add a dataset from another agency to compare their reports.</span>
        </div>
      </section>
    )
  }

  return (
    <section className="compare">
      <div className="compare-bar">
        <span className="section-label">Compare</span>
        <label className="compare-with">
          <span>with</span>
          <select
            value={otherId ?? ''}
            onChange={(event) => setChosen(Number(event.target.value))}
          >
            {others.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.name} ({candidate.source})
              </option>
            ))}
          </select>
        </label>
        <span className="compare-caption">
          {error !== null
            ? `Could not compare: ${error}`
            : matches !== null && other !== null
              ? caption(matches, other)
              : loading
                ? 'comparing…'
                : ''}
        </span>
      </div>

      {matches !== null && other !== null && matches.pairs.length > 0 && (
        <div className="table-wrap">
          <table className="compare-table">
            <thead>
              <tr>
                <th>Time (UTC)</th>
                <th>Place</th>
                <th className="numeric">Magnitude</th>
                <th className="numeric">Δ mag</th>
                <th className="numeric">Δ time</th>
                <th className="numeric">Distance</th>
                <th className="numeric">Depth</th>
              </tr>
            </thead>
            <tbody>
              {matches.pairs.map((pair: Match) => (
                <tr key={pair.event.id}>
                  <td className="numeric">{pair.event.occurred_at.replace('T', ' ').slice(0, 19)}</td>
                  <td>
                    <span className="compare-side">{pair.event.place ?? '—'}</span>
                    <span className="compare-side muted">{pair.other.place ?? '—'}</span>
                  </td>
                  <td className="numeric">
                    <span className="compare-side">{magnitude(pair.event.magnitude, pair.event.magnitude_type)}</span>
                    <span className="compare-side muted">{magnitude(pair.other.magnitude, pair.other.magnitude_type)}</span>
                  </td>
                  <td className="numeric">
                    {pair.delta_magnitude === null ? '—' : signed(pair.delta_magnitude, 1)}
                  </td>
                  <td className="numeric">{signed(pair.delta_seconds, 1, ' s')}</td>
                  <td className="numeric">{pair.distance_km.toFixed(1)} km</td>
                  <td className="numeric">
                    <span className="compare-side">{depth(pair.event.depth_km)}</span>
                    <span className="compare-side muted">{depth(pair.other.depth_km)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted compare-legend">
            Each row: this dataset's report above, {other.name}'s below. Deltas are {other.name} minus this dataset.
          </p>
        </div>
      )}
    </section>
  )
}
