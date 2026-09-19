import { useEffect, useState } from 'react'

import { fetchSources, type Source } from '../api'

/**
 * Where the data comes from and on what terms, at the foot of the dashboard.
 *
 * Read from `/api/sources` rather than written here: the registry in
 * `backend/app/ingestion/sources.py` is the one place a source's homepage,
 * licence and credit line are spelled, and a copy in the front end would
 * drift the day a source is added or removed. Sources whose licence asks
 * for a credit (CC BY and its equivalents) show it in the words the
 * licence asks for; the public-domain ones are linked all the same.
 */
export function DataSources() {
  const [sources, setSources] = useState<Source[] | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchSources(controller.signal)
      .then(setSources)
      // Attribution that cannot be loaded is not an error the person can
      // act on; the footer simply stays empty until the API answers.
      .catch(() => undefined)
    return () => controller.abort()
  }, [])

  if (sources === null || sources.length === 0) {
    return null
  }

  return (
    <footer className="data-sources" aria-labelledby="data-sources-title">
      <p className="section-label" id="data-sources-title">
        Data sources
      </p>
      <ul>
        {sources.map((source) => (
          <li key={source.key}>
            <a href={source.homepage} rel="noopener noreferrer">
              {source.name}
            </a>
            <span className="muted"> · {source.licence}</span>
            {source.credit !== null && (
              <span className="muted">
                {' '}
                · data: {source.credit}
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="muted small">
        The code is MIT; the data stays under each agency&apos;s own terms, and the
        agencies that ask to be credited are credited as they ask.
      </p>
    </footer>
  )
}
