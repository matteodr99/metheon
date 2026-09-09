import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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
    // assertion is scoped to the row to stay unambiguous.
    const status = await screen.findByText('failed')
    const row = status.closest('tr')
    expect(row).not.toBeNull()
    expect(within(row as HTMLTableRowElement).getByText('Quakes')).toBeInTheDocument()
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
    await user.click(await screen.findByText('Volcanoes'))

    expect(await screen.findByText('an event')).toBeInTheDocument()
    expect(
      calls.some((call) => call.url.startsWith('/api/datasets/2/earthquakes')),
    ).toBe(true)
  })
})
