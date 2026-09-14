import { useEffect, useState } from 'react'

import { createDataset, fetchSources, type Dataset, type Source } from '../api'

export function NewDatasetForm({
  onCreated,
}: {
  /** Called with the dataset the API returned. */
  onCreated: (dataset: Dataset) => void
}) {
  const [sources, setSources] = useState<Source[] | null>(null)
  const [sourcesError, setSourcesError] = useState<string | null>(null)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [source, setSource] = useState('')
  const [kind, setKind] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchSources(controller.signal)
      .then((loaded) => {
        setSources(loaded)
        // Preselect the first source: a menu with nothing chosen would make
        // the form fail on submit for a reason the person cannot see.
        if (loaded.length > 0) {
          setSource((current) => current || loaded[0].key)
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setSourcesError(cause instanceof Error ? cause.message : String(cause))
        }
      })
    return () => controller.abort()
  }, [])

  // A source that serves one kind decides it; one that serves several
  // asks. The menu appears only then, preselected like the source menu.
  const kinds = sources?.find((entry) => entry.key === source)?.kinds ?? []
  const asksForKind = kinds.length > 1
  const chosenKind = kinds.includes(kind) ? kind : (kinds[0] ?? '')

  const canSubmit =
    !submitting && name.trim() !== '' && source !== '' && sources !== null

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!canSubmit) {
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const created = await createDataset({
        name: name.trim(),
        source,
        // An empty description is sent as absent, not as an empty string.
        ...(description.trim() === '' ? {} : { description: description.trim() }),
        // The kind travels only when there was a choice to make.
        ...(asksForKind ? { kind: chosenKind } : {}),
      })
      setName('')
      setDescription('')
      onCreated(created)
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <details className="new-dataset">
      <summary>New dataset</summary>
      <form className="new-dataset-form" onSubmit={submit}>
        <label>
          <span>Name</span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Terremoti Italia"
            required
          />
        </label>
        <label>
          <span>Source</span>
          <select
            value={source}
            onChange={(event) => setSource(event.target.value)}
            disabled={sources === null}
          >
            {sources === null && <option value="">Loading…</option>}
            {sources?.map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.name}
              </option>
            ))}
          </select>
        </label>
        {asksForKind && (
          <label>
            <span>Kind</span>
            <select value={chosenKind} onChange={(event) => setKind(event.target.value)}>
              {kinds.map((entry) => (
                <option key={entry} value={entry}>
                  {entry.replace('_', ' ')}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="wide">
          <span>Description (optional)</span>
          <input
            type="text"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <div className="filter-actions">
          <button type="submit" disabled={!canSubmit}>
            {submitting ? 'Creating…' : 'Create'}
          </button>
        </div>
      </form>

      {sourcesError !== null && (
        <p role="alert" className="error">
          Could not load the sources: {sourcesError}
        </p>
      )}
      {error !== null && (
        <p role="alert" className="error">
          Could not create the dataset: {error}
        </p>
      )}
    </details>
  )
}
