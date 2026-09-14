import { useEffect, useState } from 'react'

import {
  fetchAIStatus,
  fetchInsights,
  type AIStatus,
  type EventFilters,
  type Insights,
} from '../api'

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null
  }
  return (
    <div className="insights-list">
      <h4>{title}</h4>
      <ul>
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

export function InsightsPanel({
  datasetId,
  filters,
  dataVersion = 0,
}: {
  datasetId: number
  filters: EventFilters
  dataVersion?: number
}) {
  const [status, setStatus] = useState<AIStatus | null>(null)
  // Insights are requested, never fetched on their own: each one is a call
  // to a metered model, and a reader changing filters should not pay for
  // an analysis they did not ask for.
  //
  // An answer is kept with the view it describes. When the filters or the
  // data change, the view key changes and the old answer simply stops
  // matching — shown for nothing, never left to mislead.
  const view = JSON.stringify([datasetId, filters, dataVersion])
  const [answer, setAnswer] = useState<{
    view: string
    insights: Insights | null
    error: string | null
  } | null>(null)
  const [loading, setLoading] = useState(false)

  const insights = answer?.view === view ? answer.insights : null
  const error = answer?.view === view ? answer.error : null

  useEffect(() => {
    const controller = new AbortController()
    fetchAIStatus(controller.signal)
      .then(setStatus)
      .catch(() => {
        if (!controller.signal.aborted) {
          setStatus({ configured: false, model: '' })
        }
      })
    return () => controller.abort()
  }, [])

  async function analyse() {
    setLoading(true)
    try {
      const result = await fetchInsights(datasetId, filters)
      setAnswer({ view, insights: result, error: null })
    } catch (cause: unknown) {
      setAnswer({
        view,
        insights: null,
        error: cause instanceof Error ? cause.message : String(cause),
      })
    } finally {
      setLoading(false)
    }
  }

  if (status === null) {
    return null
  }

  if (!status.configured) {
    return (
      <section className="insights insights-off">
        <p className="section-label">AI insights</p>
        <p className="muted">
          Not configured. Set <code>GEMINI_API_KEY</code> for the API to enable
          them; everything else works without it.
        </p>
      </section>
    )
  }

  return (
    <section className="insights">
      <div className="insights-bar">
        <p className="section-label">AI insights</p>
        <button type="button" onClick={analyse} disabled={loading}>
          {loading ? 'Analysing…' : insights ? 'Analyse again' : 'Analyse this view'}
        </button>
        <span className="muted insights-model">{status.model}</span>
      </div>

      {error !== null && (
        <p role="alert" className="error">
          Could not get insights: {error}
        </p>
      )}

      {insights !== null && (
        <div className="insights-body">
          <p className="insights-summary">{insights.summary}</p>
          <List title="Key trends" items={insights.key_trends} />
          <List title="Anomalies" items={insights.anomalies} />
          <List title="Recommendations" items={insights.recommendations} />
        </div>
      )}
    </section>
  )
}
