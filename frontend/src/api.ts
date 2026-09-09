// The dev server proxies /api to the backend, so requests are same-origin
// and no base URL is needed. See vite.config.ts.

export type DatasetStatus =
  | 'pending'
  | 'queued'
  | 'processing'
  | 'completed'
  | 'failed'

export interface Dataset {
  id: number
  name: string
  source: string
  description: string | null
  created_at: string
  status: DatasetStatus
}

export async function fetchDatasets(): Promise<Dataset[]> {
  const response = await fetch('/api/datasets')
  if (!response.ok) {
    throw new Error(`The API answered ${response.status}`)
  }
  return response.json()
}
