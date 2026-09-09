import { useEffect, useState } from 'react'

import { fetchDatasets, type Dataset } from './api'
import { EarthquakeBrowser } from './EarthquakeBrowser'
import { ThemeToggle } from './ThemeToggle'

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
        {dataset.source} · added {new Date(dataset.created_at).toLocaleDateString()}
      </span>
    </button>
  )
}

function App() {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchDatasets()
      .then((loaded) => {
        setDatasets(loaded)
        // With a single dataset, making the user click it first would be
        // ceremony; select it and show its events straight away.
        if (loaded.length === 1) {
          setSelectedId(loaded[0].id)
        }
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause))
      })
  }, [])

  const selected = datasets?.find((dataset) => dataset.id === selectedId) ?? null

  return (
    <main>
      <header className="masthead">
        <h1>Metheon</h1>
        <p>Public earthquake data from the USGS feeds</p>
        <ThemeToggle />
      </header>

      {error !== null && (
        <p role="alert" className="error">
          Could not load the datasets: {error}. Is the API running on port 8000?
        </p>
      )}

      {error === null && datasets === null && <p className="muted">Loading…</p>}

      {datasets !== null && datasets.length === 0 && (
        <p className="muted">No datasets yet.</p>
      )}

      {datasets !== null && datasets.length > 0 && (
        <>
          <p className="section-label">Datasets</p>
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
        </>
      )}

      {selected !== null && (
        <section className="panel">
          <h2>{selected.name}</h2>
          <EarthquakeBrowser datasetId={selected.id} />
        </section>
      )}
    </main>
  )
}

export default App
