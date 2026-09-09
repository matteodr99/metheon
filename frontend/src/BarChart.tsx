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

export function BarChart({
  bars,
  title,
  emptyMessage = 'Nothing to plot.',
}: {
  bars: Bar[]
  title: string
  emptyMessage?: string
}) {
  if (bars.length === 0) {
    return <p className="chart-empty">{emptyMessage}</p>
  }

  const max = Math.max(...bars.map((bar) => bar.value))
  const width = bars.length * SLOT_WIDTH
  const labelEvery = Math.ceil(bars.length / MAX_LABELS)

  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <svg
        viewBox={`0 0 ${width} ${PLOT_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={title}
      >
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
      <div className="bar-labels" aria-hidden="true">
        {bars.map((bar, index) => (
          <span key={bar.label}>
            {index % labelEvery === 0 ? bar.label : ''}
          </span>
        ))}
      </div>
    </figure>
  )
}
