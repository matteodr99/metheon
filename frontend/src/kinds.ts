/**
 * What the dashboard says about each kind of event.
 *
 * A dataset holds events of one kind, and `magnitude` is the number that
 * kind is measured by — a seismic scale, hectares, knots. The API is
 * indifferent; the labels are not. A kind not listed here still works,
 * with neutral words.
 */
export interface KindLabels {
  /** Plural, for captions: "Wildfires". */
  plural: string
  /** What the magnitude column is called: "Area", "Wind". */
  measure: string
  /** Decimals when showing a magnitude. */
  decimals: number
  /** Whether events of this kind carry a depth worth a column. */
  depth: boolean
}

const KINDS: Record<string, KindLabels> = {
  earthquake: { plural: 'Earthquakes', measure: 'Magnitude', decimals: 1, depth: true },
  wildfire: { plural: 'Wildfires', measure: 'Area', decimals: 0, depth: false },
  storm: { plural: 'Storms', measure: 'Wind', decimals: 0, depth: false },
  volcano: { plural: 'Volcanoes', measure: 'Measure', decimals: 1, depth: false },
  flood: { plural: 'Floods', measure: 'Measure', decimals: 1, depth: false },
  landslide: { plural: 'Landslides', measure: 'Measure', decimals: 1, depth: false },
  sea_ice: { plural: 'Sea ice', measure: 'Area', decimals: 0, depth: false },
  drought: { plural: 'Droughts', measure: 'Measure', decimals: 1, depth: false },
  dust: { plural: 'Dust and haze', measure: 'Measure', decimals: 1, depth: false },
  temperature: { plural: 'Temperature extremes', measure: 'Measure', decimals: 1, depth: false },
  manmade: { plural: 'Manmade events', measure: 'Measure', decimals: 1, depth: false },
  snow: { plural: 'Snow', measure: 'Measure', decimals: 1, depth: false },
  water_color: { plural: 'Water colour', measure: 'Measure', decimals: 1, depth: false },
}

export function labelsFor(kind: string): KindLabels {
  return (
    KINDS[kind] ?? {
      plural: kind.replace('_', ' '),
      measure: 'Measure',
      decimals: 1,
      depth: false,
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
