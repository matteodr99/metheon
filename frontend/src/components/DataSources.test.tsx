import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { makeSource } from '../test/helpers'
import { DataSources } from './DataSources'

const INGV = makeSource({
  key: 'ingv',
  name: 'INGV Istituto Nazionale di Geofisica e Vulcanologia',
  homepage: 'https://data.ingv.it',
  licence: 'CC BY 4.0',
  credit: 'INGV (Istituto Nazionale di Geofisica e Vulcanologia)',
})

function serveSources(body: unknown, ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok,
      status: ok ? 200 : 503,
      json: async () => body,
    })),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('DataSources', () => {
  it('links every source the API lists to its homepage', async () => {
    serveSources([makeSource(), INGV])
    render(<DataSources />)

    const usgs = await screen.findByRole('link', { name: 'USGS Earthquake Hazards Program' })
    expect(usgs.getAttribute('href')).toBe('https://earthquake.usgs.gov')
    expect(
      screen.getByRole('link', { name: 'INGV Istituto Nazionale di Geofisica e Vulcanologia' }).getAttribute('href'),
    ).toBe('https://data.ingv.it')
  })

  it('shows the credit line for a source whose licence asks for one, and none otherwise', async () => {
    serveSources([makeSource(), INGV])
    render(<DataSources />)

    await screen.findByRole('link', { name: INGV.name })
    expect(screen.getByText(/data: INGV \(Istituto Nazionale di Geofisica e Vulcanologia\)/)).toBeInTheDocument()
    expect(screen.getByText(/CC BY 4\.0/)).toBeInTheDocument()
    expect(screen.getByText(/public domain/)).toBeInTheDocument()
    expect(screen.queryAllByText(/data: /)).toHaveLength(1)
  })

  it('is generated from the API, not from a list of its own', async () => {
    // A source the front end has never heard of still appears: the
    // registry is the only copy.
    serveSources([makeSource({ key: 'new', name: 'A New Agency', homepage: 'https://new.example', licence: 'CC0' })])
    render(<DataSources />)

    expect((await screen.findByRole('link', { name: 'A New Agency' })).getAttribute('href')).toBe('https://new.example')
  })

  it('renders nothing while loading, with no sources, or when the API fails', async () => {
    serveSources([], false)
    const { container } = render(<DataSources />)

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
