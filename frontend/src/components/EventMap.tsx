import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import { labelsFor } from '../kinds'
import {
  fetchPoints,
  type BoundingBox,
  type EventFilters,
  type Point,
} from '../api'

// The tiles come from OpenStreetMap's own servers, which allow light use
// with this attribution. Swapping providers is a matter of this one URL.
const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

/**
 * Marker radius in pixels, by where the magnitude sits in the range of
 * the points drawn: the smallest event 3px, the largest 16px, whatever the
 * unit — a seismic scale, hectares, knots. Unmeasured events stay small.
 */
function markerRadius(magnitude: number | null, low: number, high: number): number {
  if (magnitude === null) {
    return 2
  }
  if (high <= low) {
    return 8
  }
  const position = Math.min(Math.max((magnitude - low) / (high - low), 0), 1)
  return 3 + position * 13
}

function magnitudeRange(points: Point[]): [number, number] {
  const measured = points.map((point) => point[2]).filter((m): m is number => m !== null)
  if (measured.length === 0) {
    return [0, 0]
  }
  return [Math.min(...measured), Math.max(...measured)]
}

/** The applied box, or null when any side is missing: half a box is no box. */
function boxOf(filters: EventFilters): L.LatLngBoundsLiteral | null {
  const south = Number(filters.min_latitude)
  const north = Number(filters.max_latitude)
  const west = Number(filters.min_longitude)
  const east = Number(filters.max_longitude)
  const sides = [filters.min_latitude, filters.max_latitude, filters.min_longitude, filters.max_longitude]
  if (sides.some((side) => side === '')) {
    return null
  }
  return [
    [south, west],
    [north, east],
  ]
}

// One shared empty array: a fresh one per render would re-run the effects
// that draw the markers on every render.
const NO_POINTS: Point[] = []

/** Four decimals: about ten metres, and short enough to read in a field. */
function degrees(value: number): string {
  return value.toFixed(4)
}

export function EventMap({
  datasetId,
  kind = 'earthquake',
  filters,
  dataVersion = 0,
  onFilterToView,
}: {
  datasetId: number
  /** The dataset's kind: colours the markers and names the measure. */
  kind?: string
  /** The applied filters: what the table shows, so the map shows the same. */
  filters: EventFilters
  dataVersion?: number
  /** Called with the visible area when the reader wants to filter to it. */
  onFilterToView: (box: BoundingBox) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const markers = useRef<L.LayerGroup | null>(null)
  const frame = useRef<L.Rectangle | null>(null)

  const query = JSON.stringify([datasetId, filters, dataVersion])
  const [result, setResult] = useState<{
    query: string
    points: Point[]
    total: number
    error: string | null
  } | null>(null)

  const loading = result?.query !== query
  const error = result?.query === query ? result.error : null
  const points = result?.points ?? NO_POINTS
  const total = result?.total ?? 0

  // Leaflet owns the DOM inside the container; React never renders into
  // it. Created once per mount and removed on unmount, so a re-render
  // never builds a second map over the first.
  useEffect(() => {
    if (container.current === null) {
      return
    }
    const created = L.map(container.current, { worldCopyJump: true })
    created.setView([20, 0], 2)
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: 18 }).addTo(created)
    markers.current = L.layerGroup().addTo(created)
    map.current = created
    return () => {
      created.remove()
      map.current = null
      markers.current = null
      frame.current = null
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchPoints(datasetId, filters, controller.signal)
      .then((loaded) => {
        setResult({ query, points: loaded.points, total: loaded.total, error: null })
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) {
          return
        }
        setResult({
          query,
          points: [],
          total: 0,
          error: cause instanceof Error ? cause.message : String(cause),
        })
      })
    return () => controller.abort()
  }, [datasetId, filters, dataVersion, query])

  // Redraw the markers whenever the points change. The endpoint sends
  // [longitude, latitude]; Leaflet wants [latitude, longitude].
  useEffect(() => {
    const layer = markers.current
    if (layer === null) {
      return
    }
    layer.clearLayers()
    const [low, high] = magnitudeRange(points)
    const labels = labelsFor(kind)
    for (const [longitude, latitude, magnitude, id] of points) {
      L.circleMarker([latitude, longitude], {
        radius: markerRadius(magnitude, low, high),
        className: `map-marker kind-${kind}`,
        weight: 1,
        fillOpacity: 0.35,
      })
        .bindPopup(
          magnitude === null
            ? `Event ${id}, ${labels.measure.toLowerCase()} unknown`
            : `${labels.measure} ${magnitude.toFixed(labels.decimals)}`,
        )
        .addTo(layer)
    }
  }, [points, kind])

  // Outline the applied box and bring it into view. Keyed on the filters
  // alone: a reload of the points must not redraw the frame or move the map.
  useEffect(() => {
    const current = map.current
    if (current === null) {
      return
    }
    frame.current?.remove()
    frame.current = null
    const box = boxOf(filters)
    if (box !== null) {
      frame.current = L.rectangle(box, {
        className: 'map-frame',
        weight: 1,
        fill: false,
        dashArray: '4 4',
      }).addTo(current)
      current.fitBounds(box, { padding: [16, 16] })
    }
  }, [filters])

  // Without a box, fit the points once they are known, so a dataset opens
  // on its own region rather than on a world map with a cluster somewhere.
  useEffect(() => {
    const current = map.current
    if (current === null || boxOf(filters) !== null || points.length === 0) {
      return
    }
    current.fitBounds(
      points.map(([longitude, latitude]) => [latitude, longitude] as [number, number]),
      { padding: [16, 16], maxZoom: 6 },
    )
  }, [filters, points])

  function filterToView() {
    const current = map.current
    if (current === null) {
      return
    }
    const bounds = current.getBounds()
    onFilterToView({
      min_latitude: degrees(Math.max(bounds.getSouth(), -90)),
      max_latitude: degrees(Math.min(bounds.getNorth(), 90)),
      min_longitude: degrees(Math.max(bounds.getWest(), -180)),
      max_longitude: degrees(Math.min(bounds.getEast(), 180)),
    })
  }

  return (
    <figure className="map">
      <div className="map-bar">
        <span className="section-label">Map</span>
        <span className="map-caption">
          {error !== null
            ? `Could not load the map: ${error}`
            : loading
              ? 'loading…'
              : points.length < total
                ? `${points.length} strongest of ${total} events`
                : `${total} events`}
        </span>
        <button type="button" onClick={filterToView}>
          Filter to this view
        </button>
      </div>
      <div ref={container} className="map-canvas" aria-label="Map of the matching earthquakes" />
    </figure>
  )
}
