import { describe, expect, it, vi } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import App from './App'
import { deferred, makeDataset, makeEvent, makePage, mockFetch } from './test/helpers'

function respondWith(datasets: ReturnType<typeof makeDataset>[]) {
  return (url: string) => {
    if (url === '/api/datasets') {
      return datasets
    }
    return makePage([makeEvent({ title: 'an event' })])
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
      calls.some((call) => call.url.startsWith('/api/datasets/2/events')),
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
      const { POLL_INTERVAL_MS } = await import('./components/IngestionPanel')
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
          } else if (url === '/api/sources') {
            body = []
          } else if (url.includes('/imports')) {
            body = { dataset_id: 1, total: 1, limit: 5, offset: 0, filters: {}, items: state.runs }
          } else if (url.includes('/summary')) {
            const { makeSummary } = await import('./test/helpers')
            body = makeSummary()
          } else {
            body = makePage([makeEvent({ title: 'an event' })])
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
      const eventsBefore = count('/events?')
      const summaryBefore = count('/summary')
      const datasetsBefore = exact('/api/datasets')
      expect(eventsBefore).toBeGreaterThan(0)

      state.runs = [makeImportRun({ status: 'completed' })]
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
      })

      expect(count('/events?')).toBeGreaterThan(eventsBefore)
      expect(count('/summary')).toBeGreaterThan(summaryBefore)
      expect(exact('/api/datasets')).toBeGreaterThan(datasetsBefore)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('creating a dataset from the dashboard', () => {
  it('adds it to the list and selects it', async () => {
    const { makeSource } = await import('./test/helpers')
    const listed = [makeDataset({ id: 1, name: 'Quakes' })]
    const created = makeDataset({ id: 2, name: 'Terremoti Italia', source: 'ingv' })
    const { implementation } = mockFetch(() => [])
    implementation.mockImplementation(async (input, init) => {
      const url = String(input)
      let body: unknown
      if (url === '/api/datasets' && init?.method === 'POST') {
        listed.push(created)
        body = created
      } else if (url === '/api/datasets') {
        body = [...listed]
      } else if (url === '/api/sources') {
        body = [makeSource({ key: 'ingv', name: 'INGV' })]
      } else if (url.includes('/summary')) {
        const { makeSummary } = await import('./test/helpers')
        body = makeSummary()
      } else if (url.includes('/imports')) {
        body = { dataset_id: 2, total: 0, limit: 5, offset: 0, filters: {}, items: [] }
      } else if (url.includes('/matches')) {
        const { makeMatches } = await import('./test/helpers')
        body = makeMatches()
      } else if (url.includes('/points')) {
        body = { dataset_id: 2, total: 0, limit: 5000, filters: {}, points: [] }
      } else {
        body = makePage([makeEvent({ title: 'an event' })])
      }
      return { ok: true, status: 200, json: async () => body } as Response
    })
    const user = userEvent.setup()

    render(<App />)
    await screen.findByRole('button', { name: /Quakes/ })
    await user.click(screen.getByText('New dataset'))
    await screen.findByRole('option', { name: 'INGV' })
    await user.type(screen.getByLabelText('Name'), 'Terremoti Italia')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    const card = await screen.findByRole('button', { name: /Terremoti Italia/ })
    expect(card).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Terremoti Italia')
    // With a second dataset the comparison has something to compare with,
    // and it is the other one: the browser was handed the whole list.
    expect(
      await screen.findByRole('option', { name: 'Quakes (USGS)' }),
    ).toBeInTheDocument()
  })
})

describe('while the API wakes up', () => {
  it('explains the wait after a few seconds, and stops once the data arrives', async () => {
    vi.useFakeTimers()
    const pending = deferred<unknown>()
    mockFetch((url) => (url === '/api/datasets' ? pending.promise : makePage([])))
    try {
      render(<App />)

      expect(screen.getByText('Loading…')).toBeInTheDocument()
      await act(async () => {
        vi.advanceTimersByTime(2900)
      })
      expect(screen.getByText('Loading…')).toBeInTheDocument()
      await act(async () => {
        vi.advanceTimersByTime(200)
      })
      expect(screen.getByText(/Waking up the API/)).toBeInTheDocument()

      // Two datasets, so none is opened on its own and nothing else loads.
      await act(async () => {
        pending.resolve([makeDataset({ id: 1, name: 'Quakes' }), makeDataset({ id: 2, name: 'Fires' })])
      })
      expect(screen.queryByText(/Waking up the API/)).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: /Quakes/ })).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('never appears when the API answers at once', async () => {
    mockFetch(respondWith([makeDataset({ name: 'Quakes' })]))

    render(<App />)

    await screen.findByRole('button', { name: /Quakes/ })
    expect(screen.queryByText(/Waking up/)).not.toBeInTheDocument()
  })
})

describe('the masthead', () => {
  it('wears the mark and links back to the landing', async () => {
    mockFetch(respondWith([]))

    render(<App />)

    const home = await screen.findByRole('link', { name: 'Metheon home' })
    expect(home).toHaveAttribute('href', '/')
    expect(within(home).getByRole('img', { name: 'Metheon' })).toBeInTheDocument()
  })
})

describe('what a card says about ingestion', () => {
  it('says when the data last arrived, or that it never did', async () => {
    vi.useFakeTimers({ now: new Date('2026-09-15T12:00:00Z'), toFake: ['Date'] })
    try {
      mockFetch(
        respondWith([
          makeDataset({ id: 1, name: 'Fresh', last_ingested_at: '2026-09-15T10:00:00' }),
          makeDataset({ id: 2, name: 'Empty', last_ingested_at: null }),
        ]),
      )

      render(<App />)

      const fresh = await screen.findByRole('button', { name: /Fresh/ })
      expect(within(fresh).getByText(/ingested 2 h ago/)).toBeInTheDocument()
      const empty = screen.getByRole('button', { name: /Empty/ })
      expect(within(empty).getByText(/never ingested/)).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('deleting a dataset', () => {
  function mockWithDelete(datasets: ReturnType<typeof makeDataset>[], { refuse = false } = {}) {
    const listed = [...datasets]
    const { calls, implementation } = mockFetch(() => [])
    implementation.mockImplementation(async (input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      calls.push({ url, method })
      if (method === 'DELETE') {
        if (refuse) {
          return { ok: false, status: 503, json: async () => ({ detail: 'The database is unavailable' }) } as Response
        }
        const id = Number(url.split('/').at(-1))
        listed.splice(listed.findIndex((dataset) => dataset.id === id), 1)
        return { ok: true, status: 204, json: async () => { throw new Error('no body') } } as unknown as Response
      }
      let body: unknown = []
      if (url === '/api/datasets') {
        body = [...listed]
      } else if (url.includes('/summary')) {
        const { makeSummary } = await import('./test/helpers')
        body = makeSummary()
      } else if (url.includes('/imports')) {
        body = { dataset_id: 1, total: 0, limit: 5, offset: 0, filters: {}, items: [] }
      } else if (url.includes('/points')) {
        body = { dataset_id: 1, total: 0, limit: 5000, filters: {}, points: [] }
      } else if (url.includes('/matches')) {
        const { makeMatches } = await import('./test/helpers')
        body = makeMatches()
      } else if (url === '/api/sources' || url === '/api/ai') {
        body = url === '/api/ai' ? { configured: false, model: '' } : []
      } else {
        body = makePage([makeEvent({ title: 'an event' })])
      }
      return { ok: true, status: 200, json: async () => body } as Response
    })
    return calls
  }

  it('asks first, then removes the dataset and closes its panel', async () => {
    const calls = mockWithDelete([makeDataset({ id: 1, name: 'Quakes' }), makeDataset({ id: 2, name: 'Fires', kind: 'wildfire' })])
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    try {
      render(<App />)
      await user.click(await screen.findByRole('button', { name: /Quakes/ }))
      await screen.findByRole('heading', { level: 2 })

      await user.click(screen.getByRole('button', { name: 'Delete dataset' }))

      expect(confirm).toHaveBeenCalledWith(expect.stringContaining('"Quakes"'))
      expect(calls.some((call) => call.method === 'DELETE' && call.url === '/api/datasets/1')).toBe(true)
      expect(await screen.findByRole('button', { name: /Fires/ })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Quakes/ })).not.toBeInTheDocument()
      expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument()
    } finally {
      confirm.mockRestore()
    }
  })

  it('does nothing when the person changes their mind', async () => {
    const calls = mockWithDelete([makeDataset({ id: 1, name: 'Quakes' })])
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    try {
      render(<App />)
      await screen.findByRole('heading', { level: 2 })

      await user.click(screen.getByRole('button', { name: 'Delete dataset' }))

      expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
      expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Quakes')
    } finally {
      confirm.mockRestore()
    }
  })

  it("shows the API's reason when it refuses", async () => {
    mockWithDelete([makeDataset({ id: 1, name: 'Quakes' })], { refuse: true })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    try {
      render(<App />)
      await screen.findByRole('heading', { level: 2 })

      await user.click(screen.getByRole('button', { name: 'Delete dataset' }))

      expect(await screen.findByRole('alert')).toHaveTextContent('Could not delete the dataset: The API answered 503: The database is unavailable')
      expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Quakes')
    } finally {
      confirm.mockRestore()
    }
  })
})
