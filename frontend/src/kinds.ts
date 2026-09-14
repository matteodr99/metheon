/**
 * What the dashboard says about each kind of event.
 *
 * A dataset holds events of one kind, and `magnitude` is the number that
 * kind is measured by — a seismic scale, hectares, knots. The API is
 * indifferent; the labels are not. A kind not listed here still works,
 * with neutral words.
 */
import type { MatchWindow } from './api'

export interface KindLabels {
  /** Plural, for captions: "Wildfires". */
  plural: string
  /** What the magnitude column is called: "Area", "Wind". */
  measure: string
  /** Decimals when showing a magnitude. */
  decimals: number
  /** Whether events of this kind carry a depth worth a column. */
  depth: boolean
  /**
   * How close two agencies' reports must be to count as one event. A
   * quake is an instant; a fire or a storm is reported over days, and two
   * curators can date its start a day apart.
   */
  match: MatchWindow
}

const INSTANT: MatchWindow = { windowSeconds: 60, radiusKm: 100 }
const DAYS: MatchWindow = { windowSeconds: 3 * 24 * 3600, radiusKm: 50 }

const KINDS: Record<string, KindLabels> = {
  earthquake: { plural: 'Earthquakes', measure: 'Magnitude', decimals: 1, depth: true, match: INSTANT },
  wildfire: { plural: 'Wildfires', measure: 'Area', decimals: 0, depth: false, match: DAYS },
  storm: { plural: 'Storms', measure: 'Wind', decimals: 0, depth: false, match: { windowSeconds: DAYS.windowSeconds, radiusKm: 300 } },
  volcano: { plural: 'Volcanoes', measure: 'Measure', decimals: 1, depth: false, match: DAYS },
  flood: { plural: 'Floods', measure: 'Measure', decimals: 1, depth: false, match: { windowSeconds: DAYS.windowSeconds, radiusKm: 200 } },
  landslide: { plural: 'Landslides', measure: 'Measure', decimals: 1, depth: false, match: DAYS },
  sea_ice: { plural: 'Sea ice', measure: 'Area', decimals: 0, depth: false, match: DAYS },
  drought: { plural: 'Droughts', measure: 'Measure', decimals: 1, depth: false, match: { windowSeconds: 7 * 24 * 3600, radiusKm: 500 } },
  dust: { plural: 'Dust and haze', measure: 'Measure', decimals: 1, depth: false, match: DAYS },
  temperature: { plural: 'Temperature extremes', measure: 'Measure', decimals: 1, depth: false, match: DAYS },
  manmade: { plural: 'Manmade events', measure: 'Measure', decimals: 1, depth: false, match: DAYS },
  snow: { plural: 'Snow', measure: 'Measure', decimals: 1, depth: false, match: DAYS },
  water_color: { plural: 'Water colour', measure: 'Measure', decimals: 1, depth: false, match: DAYS },
}

export function labelsFor(kind: string): KindLabels {
  return (
    KINDS[kind] ?? {
      plural: kind.replace('_', ' '),
      measure: 'Measure',
      decimals: 1,
      depth: false,
      match: DAYS,
    }
  )
}

/** A magnitude with its unit, or a dash: the feed legitimately omits it. */
export function formatMeasure(
  value: number | null,
  unit: string | null,
  kind: string,
): string {
  if (value === null) {
    return '—'
  }
  return `${value.toFixed(labelsFor(kind).decimals)}${unit ? ` ${unit}` : ''}`
}
