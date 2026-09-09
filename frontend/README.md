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
