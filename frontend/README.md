# Metheon frontend

React + TypeScript dashboard for the Metheon API, built with Vite.

Setup and usage are documented in the [project README](../README.md); this
file only covers what is specific to the frontend.

## Requirements

Node 20.19.5, pinned in `.nvmrc` at the repository root. With nvm:

```bash
nvm use
```

## Commands

Run from this directory:

```bash
npm install       # once
npm run dev       # dev server on http://localhost:5173
npm run build     # type-check and build into dist/
npm run lint      # oxlint
npm test          # vitest, once
npm run test:watch
```

## Talking to the API

`vite.config.ts` proxies `/api` to `http://127.0.0.1:8000`, so the browser
sees a single origin and the backend needs no CORS configuration. Start the
API separately, as described in the project README.

The proxy is a development-only arrangement. How the built frontend reaches
the API once deployed is a separate decision, not made yet.

## Structure

```text
src/
├── api.ts                  # Types and fetch helpers for the API
├── App.tsx                 # Dataset list and selection
├── EarthquakeBrowser.tsx   # Filters, table and pagination
├── Summary.tsx             # Tiles and charts for the current filters
├── BarChart.tsx            # Hand-written SVG bar chart
│                           # index.css holds the design tokens
├── index.css
├── main.tsx
└── test/
    ├── setup.ts            # jest-dom matchers, cleanup between tests
    └── helpers.ts          # Fixtures and the fetch stand-in
```

## Tests

Vitest with Testing Library, in jsdom. `fetch` is always replaced, so the
suite never reaches a backend and needs nothing running:

```bash
npm test
```

The interesting cases are the ones that are easy to get wrong: filters apply
on submit rather than per keystroke, a slow response cannot replace a newer
one, and the caption counts the page on screen rather than the one being
fetched.

## Charts

`BarChart` is about seventy lines of SVG rather than a charting library. The
API already returns the aggregated numbers, so there is nothing to compute in
the browser, and one bar chart does not pay for a dependency tree.

Only the bars live in the SVG. Its viewBox is stretched to the container
width, which rectangles survive but glyphs do not: text drawn inside was
smeared into an unreadable blur, so the labels are plain HTML underneath, on
the same grid.

Because of that stretch, a chart of two or three bars would show slabs rather
than bars, so `minSlots` reserves a minimum width per bar and leaves the
spare slots empty. The by-type chart passes `minSlots={0}`: it has few
categories with long names, and padding it out squeezed the labels into
ellipses.

## Styling

Plain CSS in `index.css`, no framework. Colours, spacing, radii and shadows
are custom properties defined once for light and redefined under
`prefers-color-scheme: dark`, so both themes come from the same rules rather
than from hardcoded values sprinkled through the file.
