import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { EMPTY_FILTERS, type Point } from '../api'
import { mockFetch, urlsOf } from '../test/helpers'

// Leaflet draws into the DOM with layout measurements jsdom does not have.
// A recording stand-in lets the tests assert what was asked of it —
// which markers, where, which bounds — which is what the component owns.
const leaflet = vi.hoisted(() => {
  const record = {
    markers: [] as { latlng: [number, number]; radius: number; popup: string }[],
    rectangles: [] as unknown[],
    fits: [] as unknown[],
    cleared: 0,
    removed: 0,
    bounds: { south: -10.123456, north: 95, west: -190, east: 20.5 },
  }
  const layer = () => ({
    addTo() {
      return this
    },
    remove() {},
  })
  const L = {
    map: () => ({
      setView() {},
      fitBounds(bounds: unknown) {
        record.fits.push(bounds)
      },
      getBounds: () => ({
        getSouth: () => record.bounds.south,
        getNorth: () => record.bounds.north,
        getWest: () => record.bounds.west,
        getEast: () => record.bounds.east,
      }),
      remove() {
        record.removed += 1
      },
    }),
    tileLayer: () => layer(),
    layerGroup: () => ({
      ...layer(),
      clearLayers() {
        record.cleared += 1
      },
    }),
    circleMarker: (latlng: [number, number], options: { radius: number }) => {
      const marker = { latlng, radius: options.radius, popup: '' }
      record.markers.push(marker)
      return {
        bindPopup(text: string) {
          marker.popup = text
          return this
        },
        addTo() {
          return this
        },
      }
    },
    rectangle: (bounds: unknown) => {
      record.rectangles.push(bounds)
      return layer()
    },
  }
  return { record, L }
})

vi.mock('leaflet', () => ({ default: leaflet.L }))

import { EarthquakeMap } from './EarthquakeMap'

const { record } = leaflet

beforeEach(() => {
  record.markers.length = 0
  record.rectangles.length = 0
  record.fits.length = 0
  record.cleared = 0
  record.removed = 0
})

const ROME: Point = [12.5, 41.9, 3.0, 1]
const TOKYO: Point = [139.7, 35.7, 5.0, 2]
const UNKNOWN: Point = [0, 0, null, 3]

function renderMap(points: Point[], filters = EMPTY_FILTERS, total = points.length) {
  const onFilterToView = vi.fn()
  const { calls } = mockFetch(() => null, {
    points: { dataset_id: 1, total, limit: 5000, filters: {}, points },
  })
  render(
    <EarthquakeMap datasetId={1} filters={filters} onFilterToView={onFilterToView} />,
  )
  return { calls, onFilterToView }
}

describe('loading the points', () => {
  it('asks the points endpoint with the applied filters', async () => {
    const { calls } = renderMap([], { ...EMPTY_FILTERS, min_magnitude: '4', max_latitude: '50' })

    await screen.findByText('0 events')

    expect(urlsOf(calls)).toEqual([
      '/api/datasets/1/earthquakes/points?min_magnitude=4&max_latitude=50',
    ])
  })

  it('reports an error instead of an empty map', async () => {
    mockFetch(() => ({ detail: 'The database is unavailable' }), { ok: false, status: 503 })
    render(<EarthquakeMap datasetId={1} filters={EMPTY_FILTERS} onFilterToView={vi.fn()} />)

    expect(await screen.findByText(/Could not load the map/)).toBeInTheDocument()
  })
})

describe('drawing', () => {
  it('places one marker per point, latitude first as Leaflet wants it', async () => {
    renderMap([ROME, TOKYO])

    await waitFor(() => {
      expect(record.markers.map((marker) => marker.latlng)).toEqual([
        [41.9, 12.5],
        [35.7, 139.7],
      ])
    })
  })

  it('sizes a marker by magnitude and keeps the unmeasured small', async () => {
    renderMap([ROME, TOKYO, UNKNOWN])

    await waitFor(() => expect(record.markers).toHaveLength(3))

    const [rome, tokyo, unknown] = record.markers
    expect(tokyo.radius).toBeGreaterThan(rome.radius)
    expect(unknown.radius).toBeLessThan(rome.radius)
    expect(rome.popup).toBe('M 3.0')
    expect(unknown.popup).toMatch(/magnitude unknown/)
  })

  it('clears the old markers before drawing the new ones', async () => {
    renderMap([ROME])

    await waitFor(() => expect(record.markers).toHaveLength(1))

    // Once for the initial empty state, once for the loaded points.
    expect(record.cleared).toBeGreaterThanOrEqual(1)
  })

  it('says when the limit cut the weaker events', async () => {
    renderMap([TOKYO], EMPTY_FILTERS, 7300)

    expect(await screen.findByText('1 strongest of 7300 events')).toBeInTheDocument()
  })

  it('fits the view to the points when no box is applied', async () => {
    renderMap([ROME, TOKYO])

    await waitFor(() => {
      expect(record.fits.at(-1)).toEqual([
        [41.9, 12.5],
        [35.7, 139.7],
      ])
    })
    expect(record.rectangles).toHaveLength(0)
  })

  it('outlines the applied box and brings it into view', async () => {
    renderMap([ROME], {
      ...EMPTY_FILTERS,
      min_latitude: '36',
      max_latitude: '47',
      min_longitude: '6',
      max_longitude: '19',
    })

    const box = [
      [36, 6],
      [47, 19],
    ]
    await waitFor(() => expect(record.rectangles).toEqual([box]))
    expect(record.fits.at(-1)).toEqual(box)
  })

  it('treats a partial box as no box', async () => {
    renderMap([ROME], { ...EMPTY_FILTERS, min_latitude: '36' })

    await waitFor(() => expect(record.markers).toHaveLength(1))

    expect(record.rectangles).toHaveLength(0)
  })

  it('removes the map on unmount', async () => {
    mockFetch(() => null)
    const { unmount } = render(
      <EarthquakeMap datasetId={1} filters={EMPTY_FILTERS} onFilterToView={vi.fn()} />,
    )

    unmount()

    expect(record.removed).toBe(1)
  })
})

describe('filtering to the view', () => {
  it('hands over the visible bounds, rounded to four decimals', async () => {
    record.bounds = { south: -10.123456, north: 45.6789012, west: -0.00004, east: 20.5 }
    const { onFilterToView } = renderMap([])
    await screen.findByText('0 events')

    await userEvent.click(screen.getByRole('button', { name: 'Filter to this view' }))

    expect(onFilterToView).toHaveBeenCalledWith({
      min_latitude: '-10.1235',
      max_latitude: '45.6789',
      min_longitude: '-0.0000',
      max_longitude: '20.5000',
    })
  })

  it('clamps every side to the globe when the view runs past it', async () => {
    // Zoomed out, Leaflet reports latitudes beyond the poles and, with
    // world copies, longitudes beyond the antimeridian; the API would refuse them.
    record.bounds = { south: -95, north: 95, west: -190, east: 200 }
    const { onFilterToView } = renderMap([])
    await screen.findByText('0 events')

    await userEvent.click(screen.getByRole('button', { name: 'Filter to this view' }))

    expect(onFilterToView).toHaveBeenCalledWith({
      min_latitude: '-90.0000',
      max_latitude: '90.0000',
      min_longitude: '-180.0000',
      max_longitude: '180.0000',
    })
  })
})
