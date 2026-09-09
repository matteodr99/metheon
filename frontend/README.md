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
npm install     # once
npm run dev     # dev server on http://localhost:5173
npm run build   # type-check and build into dist/
npm run lint    # oxlint
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
├── api.ts       # Types and fetch helpers for the API
├── App.tsx      # The dashboard
├── index.css
└── main.tsx
```

There are no tests yet: the current view is thin enough that there is nothing
worth asserting. They belong with the first real logic.
