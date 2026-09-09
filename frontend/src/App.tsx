import { useEffect, useState } from 'react'

import { fetchDatasets, type Dataset } from './api'

function App() {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchDatasets()
      .then(setDatasets)
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause))
      })
  }, [])

  return (
    <main>
      <h1>Metheon</h1>

      {error !== null && (
        <p role="alert" className="error">
          Could not load the datasets: {error}. Is the API running on port 8000?
        </p>
      )}

      {error === null && datasets === null && <p>Loading…</p>}

      {datasets !== null && datasets.length === 0 && (
        <p>No datasets yet.</p>
      )}

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
              <tr key={dataset.id}>
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
    </main>
  )
}

export default App
