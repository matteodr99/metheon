export interface Bar {
  label: string
  value: number
}

// Only the bars live in the SVG, and its viewBox is stretched to the
// container width. Text is not drawn there: a non-uniform stretch distorts
// glyphs into an unreadable smear, while rectangles survive it unharmed.
// The labels are plain HTML underneath, laid out on the same grid.
const SLOT_WIDTH = 4
const BAR_WIDTH = 3
const PLOT_HEIGHT = 60

/**
 * Show at most this many labels: past that they overlap and become
 * unreadable, so only every nth one is drawn.
 */
const MAX_LABELS = 12

/**
 * The viewBox is stretched to the container, so with two or three bars each
 * one would balloon into a slab. Reserving a minimum number of slots keeps
 * them a sensible width; the spare slots are simply left empty.
 *
 * It is a default, not a rule: a chart of a few categories with long names
 * wants the full width for its labels instead.
 */
const DEFAULT_MIN_SLOTS = 8

export function BarChart({
  bars,
  title,
  emptyMessage = 'Nothing to plot.',
  minSlots = DEFAULT_MIN_SLOTS,
}: {
  bars: Bar[]
  title: string
  emptyMessage?: string
  minSlots?: number
}) {
  if (bars.length === 0) {
    return <p className="chart-empty">{emptyMessage}</p>
  }

  const max = Math.max(...bars.map((bar) => bar.value))
  const slots = Math.max(bars.length, minSlots)
  const width = slots * SLOT_WIDTH
  const labelEvery = Math.ceil(bars.length / MAX_LABELS)

  return (
    <figure className="chart">
      <figcaption>
        {title}
        <span className="chart-peak">peak {max}</span>
      </figcaption>
      <svg
        viewBox={`0 0 ${width} ${PLOT_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={title}
      >
        {/* Quarter gridlines give the bars a scale to be read against.
            vector-effect keeps them one pixel thick despite the stretch. */}
        {[0.25, 0.5, 0.75].map((fraction) => (
          <line
            key={fraction}
            x1={0}
            x2={width}
            y1={PLOT_HEIGHT * fraction}
            y2={PLOT_HEIGHT * fraction}
            className="gridline"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <line
          x1={0}
          x2={width}
          y1={PLOT_HEIGHT}
          y2={PLOT_HEIGHT}
          className="baseline"
          vectorEffect="non-scaling-stroke"
        />
        {bars.map((bar, index) => {
          // A non-zero count always gets a visible sliver, so "one event"
          // never looks the same as "no events".
          const barHeight =
            bar.value === 0 || max === 0
              ? 0
              : Math.max(1, (bar.value / max) * PLOT_HEIGHT)

          return (
            <rect
              key={bar.label}
              x={index * SLOT_WIDTH + (SLOT_WIDTH - BAR_WIDTH) / 2}
              y={PLOT_HEIGHT - barHeight}
              width={BAR_WIDTH}
              height={barHeight}
              className="bar"
            >
              <title>{`${bar.label}: ${bar.value}`}</title>
            </rect>
          )
        })}
      </svg>
      <div
        className="bar-labels"
        aria-hidden="true"
        style={{ gridTemplateColumns: `repeat(${slots}, 1fr)` }}
      >
        {bars.map((bar, index) => (
          <span key={bar.label}>
            {index % labelEvery === 0 ? bar.label : ''}
          </span>
        ))}
      </div>
    </figure>
  )
}
