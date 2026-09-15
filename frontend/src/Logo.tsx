/**
 * The mark: the M as an instrument's trace — a flat line, one spike, flat
 * again. Inline SVG so it takes the current colour where it is drawn
 * unfilled, and the accent where it is a tile. `public/favicon.svg` is
 * the same drawing.
 */
export function Logo({ size = 28, tile = true }: { size?: number; tile?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Metheon"
    >
      {tile && <rect width="48" height="48" rx="10" fill="var(--accent)" />}
      <polyline
        points="6,30 13,30 17,18 22,38 27,10 32,34 36,30 42,30"
        stroke={tile ? '#ffffff' : 'currentColor'}
        strokeWidth={size < 24 ? 4.5 : 3.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  )
}
