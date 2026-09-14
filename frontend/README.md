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
API separately, as described in the project README. To talk to the Kind
cluster instead, set `VITE_API_PROXY=http://localhost:8080`.

The proxy is a development-only arrangement. A deployed build sets
`VITE_API_URL` at build time — every request is prefixed with it — and the
API lists the frontend's origin in `CORS_ORIGINS`. Both are empty locally.

`startIngestion` returns the run itself. With a worker it comes back
`queued` and the panel follows it; on a host with no worker
(`INGESTION_MODE=inline`) it comes back finished, and the panel reports it
straight away, since no poll would ever see it change.

## Structure

```text
src/
├── api/
│   └── index.ts            # Types and fetch helpers for the API
├── components/             # The dashboard, one component per concern,
│   ├── EarthquakeBrowser   #   each with its test beside it
│   ├── IngestionPanel
│   ├── InsightsPanel
│   ├── NewDatasetForm
│   ├── Summary
│   └── BarChart
├── theme/
│   ├── theme.ts            # Reading, storing and applying the choice
│   └── ThemeToggle.tsx     # Light / dark / system
├── test/
│   ├── setup.ts            # jest-dom matchers, cleanup between tests
│   └── helpers.ts          # Fixtures and the fetch stand-in
├── App.tsx                 # Dataset list, selection, refresh wiring
├── main.tsx
└── index.css               # Design tokens and all styling
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

## Ingestion from the dashboard

`IngestionPanel` starts a run with `POST /ingest` and shows the latest run
and the recent history from `GET /imports`. While a run is `queued` or
`processing` the history is polled every `POLL_INTERVAL_MS`; an idle
dashboard does not poll at all. When a run reaches a final state the panel
calls `onRunFinished` exactly once, and `App` bumps a `dataVersion` that the
browser and the summary include in their query key, so the table, the charts
and the dataset badge all re-read. A run already finished when the page loads
does not count as finishing.

The API explains refusals in a `detail` field; the client surfaces it, so a
queue outage reads as the reason rather than as a bare 503.

## Creating datasets

`NewDatasetForm` reads the registered sources from `GET /api/sources` into a
menu, preselecting the first so the form cannot fail for a reason the person
cannot see, and posts to `POST /api/datasets`. An empty description is sent
as absent rather than as an empty string. On success the form clears and
`App` re-reads the list and selects the new dataset; a refusal — an unknown
source is a `422` naming the known ones — is shown with the API's reason and
the form keeps its values.

With this, nothing in the project needs a terminal any more.

## Insights

`InsightsPanel` asks `GET /api/ai` once and shows nothing more than a note
when no key is configured. When one is, a button asks
`GET /api/datasets/{id}/insights` with the current filters — never on its
own, because every call is metered and a reader changing filters should not
pay for an analysis they did not ask for.

An answer is kept with the view it described. Change the filters or the
data and it stops matching, so it disappears rather than sitting under
numbers it no longer explains; return to the same view and it is back
without another call.

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

## Styling and themes

Plain CSS in `index.css`, no framework. Colours, spacing, radii and shadows
are custom properties, so both themes come from the same rules rather than
from hardcoded values sprinkled through the file.

The theme has three states: light, dark, and following the system. The dark
palette is therefore declared twice — once under `prefers-color-scheme` for
the system default, which an explicit light choice must override, and once
under `[data-theme='dark']` for an explicit choice, which must win over a
light system.

`system` removes the attribute rather than resolving it, so the page keeps
following the OS if that changes while the tab is open. The choice is kept in
`localStorage` and re-applied by a small inline script in `index.html` before
the first paint, so a dark-theme reader never sees a white flash.
