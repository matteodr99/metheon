import { useEffect, useState } from 'react'

import { fetchDatasets, type Dataset } from './api'
import { EarthquakeBrowser } from './EarthquakeBrowser'

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
      <h1>Metheon</h1>

      {error !== null && (
        <p role="alert" className="error">
          Could not load the datasets: {error}. Is the API running on port 8000?
        </p>
      )}

      {error === null && datasets === null && <p>Loading…</p>}

      {datasets !== null && datasets.length === 0 && <p>No datasets yet.</p>}

      {datasets !== null && datasets.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Source</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((dataset) => (
              <tr
                key={dataset.id}
                className={dataset.id === selectedId ? 'selected' : undefined}
                onClick={() => setSelectedId(dataset.id)}
              >
                <td>{dataset.name}</td>
                <td>{dataset.source}</td>
                <td>
                  <span className={`status status-${dataset.status}`}>
                    {dataset.status}
                  </span>
                </td>
                <td>{new Date(dataset.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected !== null && (
        <>
          <h2>{selected.name}</h2>
          <EarthquakeBrowser datasetId={selected.id} />
        </>
      )}
    </main>
  )
}

export default App
