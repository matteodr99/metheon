import { describe, expect, it } from 'vitest'

import { EMPTY_FILTERS, fetchDatasets, fetchEarthquakes } from './api'
import { makeEarthquake, makePage, mockFetch } from './test/helpers'

describe('fetchDatasets', () => {
  it('requests the datasets endpoint', async () => {
    const { calls } = mockFetch(() => [])

    await fetchDatasets()

    expect(calls[0].url).toBe('/api/datasets')
  })

  it('throws with the status when the API refuses', async () => {
    mockFetch(() => null, { ok: false, status: 503 })

    await expect(fetchDatasets()).rejects.toThrow('The API answered 503')
  })
})

describe('fetchEarthquakes', () => {
  const page = makePage([makeEarthquake()])

  it('sends the dataset, the limit and the offset', async () => {
    const { calls } = mockFetch(() => page)

    await fetchEarthquakes(7, EMPTY_FILTERS, 25, 50)

    expect(calls[0].url).toBe('/api/datasets/7/earthquakes?limit=25&offset=50')
  })

  it('omits filters left empty', async () => {
    /** An empty field means "no filter"; sending it would be a 422. */
    const { calls } = mockFetch(() => page)

    await fetchEarthquakes(1, EMPTY_FILTERS, 25, 0)

    expect(calls[0].url).not.toContain('min_magnitude')
    expect(calls[0].url).not.toContain('event_type')
  })

  it('sends the filters that were set', async () => {
    const { calls } = mockFetch(() => page)

    await fetchEarthquakes(
      1,
      { ...EMPTY_FILTERS, min_magnitude: '4', event_type: 'quarry blast' },
      25,
      0,
    )

    const url = new URL(calls[0].url, 'http://localhost')
    expect(url.searchParams.get('min_magnitude')).toBe('4')
    expect(url.searchParams.get('event_type')).toBe('quarry blast')
  })

  it('encodes a value containing spaces', async () => {
    const { calls } = mockFetch(() => page)

    await fetchEarthquakes(
      1,
      { ...EMPTY_FILTERS, event_type: 'quarry blast' },
      25,
      0,
    )

    expect(calls[0].url).toContain('event_type=quarry+blast')
  })

  it('throws with the status when the API refuses', async () => {
    mockFetch(() => null, { ok: false, status: 422 })

    await expect(
      fetchEarthquakes(1, EMPTY_FILTERS, 25, 0),
    ).rejects.toThrow('The API answered 422')
  })
})
