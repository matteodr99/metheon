import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { IngestionPanel, POLL_INTERVAL_MS } from './IngestionPanel'
import { makeImportRun, mockFetch } from '../test/helpers'
import type { ImportRun } from '../api'

/**
 * A fetch stand-in whose import history the test can change between polls.
 * POST /ingest prepends a queued run, as the real API would.
 */
function mockImports(initial: ImportRun[]) {
  const state = { runs: initial, posts: 0, postError: null as string | null }

  const { calls } = mockFetch(() => null)
  // mockFetch routes /imports to a fixed list; this stand-in needs a live
  // one, so the routing is done here instead.
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, signal: init?.signal ?? undefined })
      if (init?.method === 'POST') {
        state.posts += 1
        if (state.postError !== null) {
          return {
            ok: false,
            status: 503,
            json: async () => ({ detail: state.postError }),
          } as Response
        }
        const queued = makeImportRun({ id: 99, status: 'queued', started_at: null, finished_at: null, fetched: 0, updated: 0 })
        state.runs = [queued, ...state.runs]
        return { ok: true, status: 202, json: async () => queued } as Response
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ dataset_id: 1, total: state.runs.length, limit: 5, offset: 0, filters: {}, items: state.runs }),
      } as Response
    }),
  )
  return { state, calls }
}

function historyReads(calls: { url: string }[]) {
  return calls.filter((call) => call.url.includes('/imports')).length
}

describe('showing the history', () => {
  it('says so when the dataset was never ingested', async () => {
    mockImports([])

    render(<IngestionPanel datasetId={1} onRunFinished={() => {}} />)

    expect(await screen.findByText('Never ingested.')).toBeInTheDocument()
  })

  it('summarises the latest run', async () => {
    mockImports([makeImportRun({ fetched: 2155, inserted: 3, updated: 2152 })])

    render(<IngestionPanel datasetId={1} onRunFinished={() => {}} />)

    expect(
      await screen.findByText('2155 fetched · 3 new · 2152 refreshed'),
    ).toBeInTheDocument()
  })

  it('mentions invalid features only when there were some', async () => {
    mockImports([makeImportRun({ fetched: 10, inserted: 8, updated: 0, invalid: 2 })])

    render(<IngestionPanel datasetId={1} onRunFinished={() => {}} />)

    expect(await screen.findByText(/2 invalid/)).toBeInTheDocument()
  })

  it('shows the reason a run failed', async () => {
    mockImports([makeImportRun({ status: 'failed', error: 'The USGS feed is not valid JSON' })])

    render(<IngestionPanel datasetId={1} onRunFinished={() => {}} />)

    expect(
      (await screen.findAllByText(/not valid JSON/)).length,
    ).toBeGreaterThan(0)
  })

  it('lists recent runs with their durations', async () => {
    mockImports([
      makeImportRun({ id: 2, started_at: '2026-09-11T09:00:00', finished_at: '2026-09-11T09:00:02.300' }),
      makeImportRun({ id: 1 }),
    ])

    render(<IngestionPanel datasetId={1} onRunFinished={() => {}} />)

    expect(await screen.findByText('2.3 s')).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(3) // header + 2
  })
})

describe('starting a run', () => {
  it('posts to the ingest endpoint and shows the queued run', async () => {
    const { state } = mockImports([])
    const user = userEvent.setup()

    render(<IngestionPanel datasetId={1} onRunFinished={() => {}} />)
    await user.click(await screen.findByRole('button', { name: 'Ingest now' }))

    expect(state.posts).toBe(1)
    expect(await screen.findByText('Queued, waiting for a worker')).toBeInTheDocument()
  })

  it('disables the button while a run is in flight', async () => {
    mockImports([makeImportRun({ status: 'processing', finished_at: null })])

    render(<IngestionPanel datasetId={1} onRunFinished={() => {}} />)

    const button = await screen.findByRole('button', { name: 'Ingesting…' })
    expect(button).toBeDisabled()
  })

  it('shows the reason when the API refuses', async () => {
    /** A 503 carries "detail"; the person must read it, not just the code. */
    const { state } = mockImports([])
    state.postError = 'Could not enqueue the import: redis down'
    const user = userEvent.setup()

    render(<IngestionPanel datasetId={1} onRunFinished={() => {}} />)
    await user.click(await screen.findByRole('button', { name: 'Ingest now' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('redis down')
    expect(screen.getByRole('button', { name: 'Ingest now' })).toBeEnabled()
  })
})

describe('when the API runs the ingestion inline', () => {
  it('reports the run finished straight away, since no poll will see it', async () => {
    /**
     * A deployment with no worker answers POST /ingest with the run
     * already completed. It was never active, so the active→final
     * transition the poll watches for never happens; the panel must
     * report it from the response itself.
     */
    const finished = makeImportRun({ id: 42, status: 'completed' })
    const state = { runs: [] as ImportRun[] }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === 'POST') {
          state.runs = [finished]
          return { ok: true, status: 200, json: async () => finished } as Response
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({ dataset_id: 1, total: state.runs.length, limit: 5, offset: 0, filters: {}, items: state.runs }),
        } as Response
      }),
    )
    const onRunFinished = vi.fn()
    const user = userEvent.setup()

    render(<IngestionPanel datasetId={1} onRunFinished={onRunFinished} />)
    await user.click(await screen.findByRole('button', { name: 'Ingest now' }))

    await screen.findByText(/2155 fetched/)
    expect(onRunFinished).toHaveBeenCalledTimes(1)
  })

  it('does not double-report a queued run', async () => {
    /** In queue mode the poll reports it; the response must not also. */
    const { state } = mockImports([])
    const onRunFinished = vi.fn()
    const user = userEvent.setup()

    render(<IngestionPanel datasetId={1} onRunFinished={onRunFinished} />)
    await user.click(await screen.findByRole('button', { name: 'Ingest now' }))
    await screen.findByText('Queued, waiting for a worker')

    expect(state.posts).toBe(1)
    expect(onRunFinished).not.toHaveBeenCalled()
  })
})

describe('polling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not poll while nothing is in flight', async () => {
    /** An idle dashboard must not hit the API every second and a half. */
    const { calls } = mockImports([makeImportRun()])

    render(<IngestionPanel datasetId={1} onRunFinished={() => {}} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    const after_load = historyReads(calls)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)
    })

    expect(historyReads(calls)).toBe(after_load)
  })

  it('polls while a run is in flight and stops when it finishes', async () => {
    const { state, calls } = mockImports([
      makeImportRun({ status: 'processing', finished_at: null }),
    ])
    const onRunFinished = vi.fn()

    render(<IngestionPanel datasetId={1} onRunFinished={onRunFinished} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    const before = historyReads(calls)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    })
    expect(historyReads(calls)).toBeGreaterThan(before)

    state.runs = [makeImportRun({ status: 'completed' })]
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    })
    expect(onRunFinished).toHaveBeenCalledTimes(1)

    const settled = historyReads(calls)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)
    })
    expect(historyReads(calls)).toBe(settled)
  })

  it('reports a finished run only once', async () => {
    const { state } = mockImports([
      makeImportRun({ status: 'queued', started_at: null, finished_at: null }),
    ])
    const onRunFinished = vi.fn()

    render(<IngestionPanel datasetId={1} onRunFinished={onRunFinished} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    state.runs = [makeImportRun({ status: 'completed' })]
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 4)
    })

    expect(onRunFinished).toHaveBeenCalledTimes(1)
  })

  it('does not report a run that was already finished on first load', async () => {
    /** Reloading the page is not an ingestion completing. */
    mockImports([makeImportRun({ status: 'completed' })])
    const onRunFinished = vi.fn()

    render(<IngestionPanel datasetId={1} onRunFinished={onRunFinished} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2)
    })

    expect(onRunFinished).not.toHaveBeenCalled()
  })
})

describe('refreshing the rest of the page', () => {
  it('is wired so a finished run bumps the browser data version', async () => {
    /**
     * The browser and summary read `dataVersion`; App increments it from
     * onRunFinished. This checks the contract from the panel's side: the
     * callback fires exactly when a run reaches a final state.
     */
    vi.useFakeTimers()
    try {
      const { state } = mockImports([
        makeImportRun({ status: 'processing', finished_at: null }),
      ])
      const seen: string[] = []

      render(
        <IngestionPanel datasetId={1} onRunFinished={() => seen.push('finished')} />,
      )
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      expect(seen).toEqual([])

      state.runs = [makeImportRun({ status: 'failed', error: 'boom' })]
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
      })

      expect(seen).toEqual(['finished'])
    } finally {
      vi.useRealTimers()
    }
  })
})
