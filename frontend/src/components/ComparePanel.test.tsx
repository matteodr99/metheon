import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { EMPTY_FILTERS } from '../api'
import { ComparePanel } from './ComparePanel'
import {
  makeDataset,
  makeMatch,
  makeMatchedEvent,
  makeMatches,
  mockFetch,
  urlsOf,
} from '../test/helpers'

const USGS = makeDataset({ id: 1, name: 'Global Earthquakes', source: 'USGS' })
const INGV = makeDataset({ id: 2, name: 'Terremoti Italia', source: 'ingv' })
const USGS_TOO = makeDataset({ id: 3, name: 'US Quakes', source: 'usgs' })

function renderPanel(datasets = [USGS, INGV], filters = EMPTY_FILTERS, options = {}) {
  const { calls } = mockFetch(() => null, options)
  render(<ComparePanel datasetId={1} datasets={datasets} filters={filters} />)
  return { calls }
}

describe('choosing what to compare with', () => {
  it('needs a second dataset', () => {
    const { calls } = renderPanel([USGS])

    expect(screen.getByText(/Add a dataset of earthquakes from another agency/)).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })

  it('prefers a dataset from another agency', async () => {
    const { calls } = renderPanel([USGS_TOO, USGS, INGV])

    await waitFor(() => expect(calls).toHaveLength(1))

    expect(urlsOf(calls)[0]).toBe('/api/datasets/1/events/matches?other=2&window_seconds=60&radius_km=100')
    expect(screen.getByRole('combobox')).toHaveValue('2')
  })

  it('never offers the dataset itself', async () => {
    const { calls } = renderPanel([USGS, INGV])
    await waitFor(() => expect(calls).toHaveLength(1))

    expect(screen.queryByRole('option', { name: /Global Earthquakes/ })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Terremoti Italia (ingv)' })).toBeInTheDocument()
  })

  it('re-requests when another dataset is picked', async () => {
    const { calls } = renderPanel([USGS, INGV, USGS_TOO])
    await waitFor(() => expect(calls).toHaveLength(1))

    await userEvent.selectOptions(screen.getByRole('combobox'), '3')

    await waitFor(() => {
      expect(urlsOf(calls).at(-1)).toBe('/api/datasets/1/events/matches?other=3&window_seconds=60&radius_km=100')
    })
  })

  it('sends the applied filters, which narrow this side', async () => {
    const { calls } = renderPanel([USGS, INGV], { ...EMPTY_FILTERS, min_magnitude: '5' })

    await waitFor(() => expect(calls).toHaveLength(1))

    expect(urlsOf(calls)[0]).toBe('/api/datasets/1/events/matches?other=2&window_seconds=60&radius_km=100&min_magnitude=5')
  })
})

describe('kinds', () => {
  it('offers only datasets of the same kind', async () => {
    const fires = makeDataset({ id: 4, name: 'Fires', source: 'eonet', kind: 'wildfire' })
    const { calls } = renderPanel([USGS, fires, INGV])
    await waitFor(() => expect(calls).toHaveLength(1))

    expect(screen.queryByRole('option', { name: /Fires/ })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Terremoti Italia (ingv)' })).toBeInTheDocument()
  })

  it('gives fires days and kilometres, not the seconds a quake gets', async () => {
    const fires = makeDataset({ id: 4, name: 'Fires', source: 'eonet', kind: 'wildfire' })
    const gdacs = makeDataset({ id: 5, name: 'GDACS fires', source: 'gdacs', kind: 'wildfire' })
    const { calls } = mockFetch(() => null)
    render(<ComparePanel datasetId={4} datasets={[fires, gdacs]} filters={EMPTY_FILTERS} />)

    await waitFor(() => expect(calls).toHaveLength(1))

    expect(urlsOf(calls)[0]).toBe('/api/datasets/4/events/matches?other=5&window_seconds=259200&radius_km=50')
  })

  it('says what kind is missing when nothing can be compared', () => {
    const fires = makeDataset({ id: 4, name: 'Fires', source: 'eonet', kind: 'wildfire' })
    mockFetch(() => null)
    render(<ComparePanel datasetId={4} datasets={[USGS, fires]} filters={EMPTY_FILTERS} />)

    expect(screen.getByText(/Add a dataset of wildfires from another agency/)).toBeInTheDocument()
  })

  it('labels the measure and drops the depth for a kind without one', async () => {
    const fires = makeDataset({ id: 4, name: 'Fires', source: 'eonet', kind: 'wildfire' })
    const gdacs = makeDataset({ id: 5, name: 'GDACS fires', source: 'gdacs', kind: 'wildfire' })
    mockFetch(() => null, {
      matches: makeMatches([
        makeMatch({
          event: makeMatchedEvent({ title: 'Fire in Namibia', magnitude: 5747, magnitude_unit: 'hectares', attributes: {} }),
          other: makeMatchedEvent({ id: 9, title: 'Namibia fire', magnitude: 5900, magnitude_unit: 'hectares', attributes: {} }),
          delta_magnitude: 153,
        }),
      ]),
    })
    render(<ComparePanel datasetId={4} datasets={[fires, gdacs]} filters={EMPTY_FILTERS} />)

    const row = (await screen.findByText('Fire in Namibia')).closest('tr')!
    expect(screen.getByRole('columnheader', { name: 'Area' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Depth' })).not.toBeInTheDocument()
    expect(row).toHaveTextContent('5747 hectares')
    expect(row).toHaveTextContent('+153')
    expect(screen.getByText(/positions 30 km apart/)).toBeInTheDocument()
    expect(screen.getByText(/areas differ by 0.3 on average/)).toBeInTheDocument()
  })

  it('says a time gap in hours or days once it is no longer an instant', async () => {
    const fires = makeDataset({ id: 4, name: 'Fires', source: 'eonet', kind: 'wildfire' })
    const gdacs = makeDataset({ id: 5, name: 'GDACS fires', source: 'gdacs', kind: 'wildfire' })
    mockFetch(() => null, {
      matches: makeMatches([
        makeMatch({ event: makeMatchedEvent({ id: 1, title: 'a' }), delta_seconds: -18000 }),
        makeMatch({ event: makeMatchedEvent({ id: 2, title: 'b' }), delta_seconds: 3 * 86400 }),
        makeMatch({ event: makeMatchedEvent({ id: 3, title: 'c' }), delta_seconds: 90 }),
      ]),
    })
    render(<ComparePanel datasetId={4} datasets={[fires, gdacs]} filters={EMPTY_FILTERS} />)

    expect((await screen.findByText('a')).closest('tr')).toHaveTextContent('-5.0 h')
    expect(screen.getByText('b').closest('tr')).toHaveTextContent('+3.0 d')
    expect(screen.getByText('c').closest('tr')).toHaveTextContent('+90.0 s')
  })
})

describe('showing the pairs', () => {
  it('sums up the comparison in a sentence', async () => {
    renderPanel([USGS, INGV], EMPTY_FILTERS, {
      matches: makeMatches([makeMatch()], { events: 4, matched: 1, unmatched: 3 }),
    })

    expect(
      await screen.findByText(
        '1 of 4 events also reported by Terremoti Italia · epicentres 30 km apart on average · magnitudes differ by 0.27 on average',
      ),
    ).toBeInTheDocument()
  })

  it('leaves the means out when there are no pairs', async () => {
    renderPanel([USGS, INGV], EMPTY_FILTERS, { matches: makeMatches([]) })

    expect(await screen.findByText('0 of 4 events also reported by Terremoti Italia')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('puts both reports in one row, with the deltas as other minus this', async () => {
    renderPanel([USGS, INGV], EMPTY_FILTERS, { matches: makeMatches([makeMatch()]) })

    const row = (await screen.findByText('Isangel, Vanuatu')).closest('tr')!
    expect(row).toHaveTextContent('Vanuatu Islands [Sea: Vanuatu]')
    expect(row).toHaveTextContent('5.6 mww')
    expect(row).toHaveTextContent('5.9 mwp')
    expect(row).toHaveTextContent('+0.3')
    expect(row).toHaveTextContent('+6.7 s')
    expect(row).toHaveTextContent('33.3 km')
    expect(row).toHaveTextContent('10 km')
    expect(row).toHaveTextContent('68 km')
  })

  it('shows a negative time delta as such', async () => {
    renderPanel([USGS, INGV], EMPTY_FILTERS, {
      matches: makeMatches([makeMatch({ delta_seconds: -0.1, delta_magnitude: -0.2 })]),
    })

    const row = (await screen.findByText('Isangel, Vanuatu')).closest('tr')!
    expect(row).toHaveTextContent('-0.1 s')
    expect(row).toHaveTextContent('-0.2')
  })

  it('shows a dash where a magnitude is missing', async () => {
    renderPanel([USGS, INGV], EMPTY_FILTERS, {
      matches: makeMatches([
        makeMatch({
          event: makeMatchedEvent({ magnitude: null, magnitude_unit: null }),
          delta_magnitude: null,
        }),
      ]),
    })

    const row = (await screen.findByText('Isangel, Vanuatu')).closest('tr')!
    expect(row.querySelectorAll('td')[3]).toHaveTextContent('—')
  })

  it('reports a failing request', async () => {
    mockFetch(() => ({ detail: 'The database is unavailable' }), { ok: false, status: 503 })
    render(<ComparePanel datasetId={1} datasets={[USGS, INGV]} filters={EMPTY_FILTERS} />)

    expect(await screen.findByText(/Could not compare/)).toBeInTheDocument()
  })
})
