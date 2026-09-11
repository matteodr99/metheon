import { describe, expect, it, vi } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import App from './App'
import { makeDataset, makeEarthquake, makePage, mockFetch } from './test/helpers'

function respondWith(datasets: ReturnType<typeof makeDataset>[]) {
  return (url: string) => {
    if (url === '/api/datasets') {
      return datasets
    }
    return makePage([makeEarthquake({ place: 'an event' })])
  }
}

describe('the dataset list', () => {
  it('shows each dataset with its status', async () => {
    mockFetch(respondWith([makeDataset({ name: 'Quakes', status: 'failed' })]))

    render(<App />)

    // The name also appears in the heading of the selected dataset, so the
    // assertion is scoped to the card to stay unambiguous.
    const card = await screen.findByRole('button', { name: /Quakes/ })
    expect(within(card).getByText('failed')).toBeInTheDocument()
  })

  it('marks the selected dataset as pressed', async () => {
    mockFetch(respondWith([makeDataset({ name: 'Quakes' })]))

    render(<App />)

    const card = await screen.findByRole('button', { name: /Quakes/ })
    expect(card).toHaveAttribute('aria-pressed', 'true')
  })

  it('says so when there are none', async () => {
    mockFetch(respondWith([]))

    render(<App />)

    expect(await screen.findByText('No datasets yet.')).toBeInTheDocument()
  })

  it('reports a failing request', async () => {
    mockFetch(() => null, { ok: false, status: 502 })

    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The API answered 502',
    )
  })
})

describe('selecting a dataset', () => {
  it('opens the only dataset without a click', async () => {
    /** Making the user click the single row would be pure ceremony. */
    mockFetch(respondWith([makeDataset({ name: 'Quakes' })]))

    render(<App />)

    expect(await screen.findByText('an event')).toBeInTheDocument()
  })

  it('waits for a choice when there are several', async () => {
    mockFetch(
      respondWith([
        makeDataset({ id: 1, name: 'Quakes' }),
        makeDataset({ id: 2, name: 'Volcanoes' }),
      ]),
    )

    render(<App />)
    await screen.findByText('Volcanoes')

    expect(screen.queryByText('an event')).not.toBeInTheDocument()
  })

  it('opens the dataset that was clicked', async () => {
    const { calls } = mockFetch(
      respondWith([
        makeDataset({ id: 1, name: 'Quakes' }),
        makeDataset({ id: 2, name: 'Volcanoes' }),
      ]),
    )
    const user = userEvent.setup()

    render(<App />)
    await user.click(await screen.findByRole('button', { name: /Volcanoes/ }))

    expect(await screen.findByText('an event')).toBeInTheDocument()
    expect(
      calls.some((call) => call.url.startsWith('/api/datasets/2/earthquakes')),
    ).toBe(true)
  })
})

describe('after an ingestion finishes', () => {
  it('re-reads the events, the summary and the dataset list', async () => {
    /**
     * A finished run changes the stored data and the dataset badge, so the
     * browser below and the cards above must both fetch again. This checks
     * the wiring from the panel's callback through App to the browser.
     */
    vi.useFakeTimers()
    try {
      const { POLL_INTERVAL_MS } = await import('./IngestionPanel')
      const { makeImportRun } = await import('./test/helpers')
      const state = {
        runs: [makeImportRun({ status: 'processing', finished_at: null })],
      }
      const calls: string[] = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL) => {
          const url = String(input)
          calls.push(url)
          let body: unknown
          if (url === '/api/datasets') {
            body = [makeDataset({ name: 'Quakes' })]
          } else if (url.includes('/imports')) {
            body = { dataset_id: 1, total: 1, limit: 5, offset: 0, filters: {}, items: state.runs }
          } else if (url.includes('/summary')) {
            const { makeSummary } = await import('./test/helpers')
            body = makeSummary()
          } else {
            body = makePage([makeEarthquake({ place: 'an event' })])
          }
          return { ok: true, status: 200, json: async () => body } as Response
        }),
      )

      render(<App />)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      const count = (needle: string) => calls.filter((url) => url.includes(needle)).length
      const exact = (target: string) => calls.filter((url) => url === target).length
      const eventsBefore = count('/earthquakes?')
      const summaryBefore = count('/summary')
      const datasetsBefore = exact('/api/datasets')
      expect(eventsBefore).toBeGreaterThan(0)

      state.runs = [makeImportRun({ status: 'completed' })]
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
      })

      expect(count('/earthquakes?')).toBeGreaterThan(eventsBefore)
      expect(count('/summary')).toBeGreaterThan(summaryBefore)
      expect(exact('/api/datasets')).toBeGreaterThan(datasetsBefore)
    } finally {
      vi.useRealTimers()
    }
  })
})
