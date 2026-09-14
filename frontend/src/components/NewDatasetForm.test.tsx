import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { NewDatasetForm } from './NewDatasetForm'
import { makeDataset, makeSource, mockFetch } from '../test/helpers'

/** Serve POST /api/datasets with what the API would return, or refuse it. */
function mockCreate({ refuse }: { refuse?: { status: number; detail: string } } = {}) {
  const created = makeDataset({ id: 7, name: 'created' })
  const { calls, implementation } = mockFetch(
    (url, init) => {
      if (url === '/api/datasets' && init?.method === 'POST') {
        return created
      }
      return []
    },
    { sources: [makeSource({ key: 'usgs', name: 'USGS' }), makeSource({ key: 'ingv', name: 'INGV' })] },
  )
  if (refuse !== undefined) {
    implementation.mockImplementation(async (input, init) => {
      const url = String(input)
      calls.push({ url, method: init?.method ?? 'GET' })
      if (init?.method === 'POST') {
        return { ok: false, status: refuse.status, json: async () => ({ detail: refuse.detail }) } as Response
      }
      return { ok: true, status: 200, json: async () => [makeSource()] } as Response
    })
  }
  return { calls, created }
}

async function openForm() {
  const user = userEvent.setup()
  await user.click(screen.getByText('New dataset'))
  return user
}

describe('the sources menu', () => {
  it('lists the registered sources', async () => {
    mockCreate()
    render(<NewDatasetForm onCreated={() => {}} />)
    await openForm()

    expect(await screen.findByRole('option', { name: 'USGS' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'INGV' })).toBeInTheDocument()
  })

  it('preselects the first source', async () => {
    /** A menu with nothing chosen would fail on submit for an invisible reason. */
    mockCreate()
    render(<NewDatasetForm onCreated={() => {}} />)
    await openForm()
    await screen.findByRole('option', { name: 'USGS' })

    expect(screen.getByRole('combobox')).toHaveValue('usgs')
  })

  it('reports when the sources cannot be loaded', async () => {
    mockFetch(() => null, { ok: false, status: 500 })
    // mockFetch serves /api/sources itself; make that path fail instead.
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }) as Response))
    render(<NewDatasetForm onCreated={() => {}} />)
    await openForm()

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the sources')
    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled()
  })
})

describe('creating a dataset', () => {
  it('posts the name, the chosen source and the description', async () => {
    const { calls } = mockCreate()
    render(<NewDatasetForm onCreated={() => {}} />)
    const user = await openForm()
    await screen.findByRole('option', { name: 'USGS' })

    await user.type(screen.getByLabelText('Name'), 'Terremoti Italia')
    await user.selectOptions(screen.getByRole('combobox'), 'ingv')
    await user.type(screen.getByLabelText('Description (optional)'), 'Italian events')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => {
      expect(calls.some((call) => call.method === 'POST')).toBe(true)
    })
    const post = calls.find((call) => call.method === 'POST')
    expect(post?.url).toBe('/api/datasets')
    expect(post?.body).toEqual({
      name: 'Terremoti Italia',
      source: 'ingv',
      description: 'Italian events',
    })
  })

  it('leaves the description out when it is empty', async () => {
    /** The API treats an absent description as null; an empty string is not that. */
    const { calls } = mockCreate()
    render(<NewDatasetForm onCreated={() => {}} />)
    const user = await openForm()
    await screen.findByRole('option', { name: 'USGS' })

    await user.type(screen.getByLabelText('Name'), 'Quakes')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => {
      expect(calls.some((call) => call.method === 'POST')).toBe(true)
    })
    const post = calls.find((call) => call.method === 'POST')
    expect(post?.body).toEqual({ name: 'Quakes', source: 'usgs' })
  })

  it('hands the created dataset to the caller and clears the form', async () => {
    const { created } = mockCreate()
    const onCreated = vi.fn()
    render(<NewDatasetForm onCreated={onCreated} />)
    const user = await openForm()
    await screen.findByRole('option', { name: 'USGS' })

    await user.type(screen.getByLabelText('Name'), 'Quakes')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith(created)
    })
    expect(screen.getByLabelText('Name')).toHaveValue('')
  })

  it('cannot be submitted without a name', async () => {
    mockCreate()
    render(<NewDatasetForm onCreated={() => {}} />)
    await openForm()
    await screen.findByRole('option', { name: 'USGS' })

    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled()
  })

  it('trims the name', async () => {
    const { calls } = mockCreate()
    render(<NewDatasetForm onCreated={() => {}} />)
    const user = await openForm()
    await screen.findByRole('option', { name: 'USGS' })

    await user.type(screen.getByLabelText('Name'), '  Quakes  ')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => {
      expect(calls.find((call) => call.method === 'POST')?.body).toMatchObject({ name: 'Quakes' })
    })
  })

  it("shows the API's reason when it refuses", async () => {
    /** A 422 names the unknown source; the person must read that. */
    mockCreate({ refuse: { status: 422, detail: "Unknown source 'meteorites'. Known sources: ingv, usgs" } })
    const onCreated = vi.fn()
    render(<NewDatasetForm onCreated={onCreated} />)
    const user = await openForm()
    await screen.findByRole('option')

    await user.type(screen.getByLabelText('Name'), 'Rocks')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    expect(await screen.findByRole('alert')).toHaveTextContent("Unknown source 'meteorites'")
    expect(onCreated).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Name')).toHaveValue('Rocks')
  })
})

describe('the kind', () => {
  function mockWithKinds() {
    const created = makeDataset({ id: 7, name: 'created', kind: 'storm' })
    const { calls } = mockFetch(
      (url, init) => (url === '/api/datasets' && init?.method === 'POST' ? created : []),
      {
        sources: [
          makeSource({ key: 'usgs', name: 'USGS', kinds: ['earthquake'] }),
          makeSource({ key: 'eonet', name: 'EONET', kinds: ['wildfire', 'storm', 'sea_ice'] }),
        ],
      },
    )
    return calls
  }

  it('is not asked for when the source serves one kind', async () => {
    const calls = mockWithKinds()
    const user = userEvent.setup()
    render(<NewDatasetForm onCreated={vi.fn()} />)
    await screen.findByRole('option', { name: 'USGS' })

    expect(screen.queryByLabelText('Kind')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Name'), 'Quakes')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    const posted = calls.find((call) => call.method === 'POST')!
    expect(posted.body).toEqual({ name: 'Quakes', source: 'usgs' })
  })

  it('appears, preselected, when the source serves several, and is sent', async () => {
    const calls = mockWithKinds()
    const user = userEvent.setup()
    render(<NewDatasetForm onCreated={vi.fn()} />)
    await screen.findByRole('option', { name: 'EONET' })

    await user.selectOptions(screen.getByLabelText('Source'), 'eonet')
    const kindMenu = screen.getByLabelText('Kind')
    expect(kindMenu).toHaveValue('wildfire')
    expect(screen.getByRole('option', { name: 'sea ice' })).toBeInTheDocument()

    await user.selectOptions(kindMenu, 'storm')
    await user.type(screen.getByLabelText('Name'), 'Storms')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    expect(calls.find((call) => call.method === 'POST')!.body).toEqual({
      name: 'Storms',
      source: 'eonet',
      kind: 'storm',
    })
  })

  it('goes away again when the source changes back', async () => {
    mockWithKinds()
    const user = userEvent.setup()
    render(<NewDatasetForm onCreated={vi.fn()} />)
    await screen.findByRole('option', { name: 'EONET' })

    await user.selectOptions(screen.getByLabelText('Source'), 'eonet')
    await user.selectOptions(screen.getByLabelText('Source'), 'usgs')

    expect(screen.queryByLabelText('Kind')).not.toBeInTheDocument()
  })
})
