import { useCallback, useEffect, useState } from 'react'

import { deleteDataset, fetchDatasets, type Dataset } from './api'
import { EventBrowser } from './components/EventBrowser'
import { IngestionPanel } from './components/IngestionPanel'
import { NewDatasetForm } from './components/NewDatasetForm'
import { ThemeToggle } from './theme/ThemeToggle'
import { timeAgo } from './time'

function DatasetCard({
  dataset,
  selected,
  onSelect,
}: {
  dataset: Dataset
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className="dataset-card"
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="dataset-card-top">
        <span className="dataset-name">{dataset.name}</span>
        <span className={`status status-${dataset.status}`}>
          {dataset.status}
        </span>
      </span>
      <span className="dataset-meta">
        {dataset.source} · {dataset.kind.replace('_', ' ')} ·{' '}
        {dataset.last_ingested_at === null
          ? 'never ingested'
          : `ingested ${timeAgo(dataset.last_ingested_at)}`}
      </span>
    </button>
  )
}

function App() {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Bumped when a run finishes, so the browser below re-reads its data.
  const [dataVersion, setDataVersion] = useState(0)

  const loadDatasets = useCallback((selectFirst: boolean) => {
    fetchDatasets()
      .then((loaded) => {
        setDatasets(loaded)
        // With a single dataset, making the user click it first would be
        // ceremony; select it and show its events straight away.
        if (selectFirst && loaded.length === 1) {
          setSelectedId(loaded[0].id)
        }
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause))
      })
  }, [])

  useEffect(() => {
    loadDatasets(true)
  }, [loadDatasets])

  // A finished run changes the dataset's status badge and its events, so
  // both the list and the browser are refreshed.
  const handleRunFinished = useCallback(() => {
    loadDatasets(false)
    setDataVersion((version) => version + 1)
  }, [loadDatasets])

  // A new dataset is what the person wants to look at next.
  const handleCreated = useCallback(
    (created: Dataset) => {
      loadDatasets(false)
      setSelectedId(created.id)
    },
    [loadDatasets],
  )

  const selected = datasets?.find((dataset) => dataset.id === selectedId) ?? null

  const [deleteError, setDeleteError] = useState<string | null>(null)
  async function handleDelete(dataset: Dataset) {
    // The one irreversible action in the dashboard: it asks, and says
    // what goes with the dataset.
    if (!window.confirm(`Delete "${dataset.name}" with all its events and its import history?`)) {
      return
    }
    setDeleteError(null)
    try {
      await deleteDataset(dataset.id)
      // The panel closes on its own: the selection is derived from the
      // list, and the list no longer has this dataset.
      loadDatasets(false)
    } catch (cause: unknown) {
      setDeleteError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  return (
    <main>
      <header className="masthead">
        <h1>Metheon</h1>
        <p>Public natural-event data, agency by agency</p>
        <ThemeToggle />
      </header>

      {error !== null && (
        <p role="alert" className="error">
          Could not load the datasets: {error}. Is the API running on port 8000?
        </p>
      )}

      {error === null && datasets === null && <p className="muted">Loading…</p>}

      {datasets !== null && (
        <>
          <p className="section-label">Datasets</p>
          {datasets.length === 0 && <p className="muted">No datasets yet.</p>}
          {datasets.length > 0 && (
            <div className="datasets">
              {datasets.map((dataset) => (
                <DatasetCard
                  key={dataset.id}
                  dataset={dataset}
                  selected={dataset.id === selectedId}
                  onSelect={() => setSelectedId(dataset.id)}
                />
              ))}
            </div>
          )}
          <NewDatasetForm onCreated={handleCreated} />
        </>
      )}

      {selected !== null && (
        <section className="panel">
          <div className="panel-head">
            <h2>{selected.name}</h2>
            <button type="button" className="danger" onClick={() => handleDelete(selected)}>
              Delete dataset
            </button>
          </div>
          {deleteError !== null && (
            <p role="alert" className="error">
              Could not delete the dataset: {deleteError}
            </p>
          )}
          <IngestionPanel datasetId={selected.id} onRunFinished={handleRunFinished} />
          <EventBrowser
            datasetId={selected.id}
            datasets={datasets ?? []}
            dataVersion={dataVersion}
          />
        </section>
      )}
    </main>
  )
}

export default App
