import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { fetchPaperByArxiv, fetchPaperDetail } from './paperApi'

describe('Paper API transport contract', () => {
  beforeEach(() => {
    transport.get.mockReset()
  })

  it('returns paper data on success, null when the paper does not exist, and an error when the request fails', async () => {
    const paper = { id: 'paper-1', source: 'arxiv', title: 'Paper' }
    transport.get.mockResolvedValueOnce({ data: paper })
    await expect(fetchPaperDetail('paper-1')).resolves.toEqual(paper)
    expect(transport.get).toHaveBeenLastCalledWith('/papers/paper-1')

    transport.get.mockResolvedValueOnce({ data: undefined })
    await expect(fetchPaperDetail('empty')).resolves.toBeNull()

    transport.get.mockRejectedValueOnce({ response: { status: 404, data: { detail: "Paper 'missing' not found" } } })
    await expect(fetchPaperDetail('missing')).resolves.toBeNull()

    const failure = new Error('network unavailable')
    transport.get.mockRejectedValueOnce(failure)
    await expect(fetchPaperDetail('failed')).rejects.toBe(failure)

    transport.get.mockRejectedValueOnce({ response: { status: 503 } })
    await expect(fetchPaperDetail('unavailable')).rejects.toEqual({ response: { status: 503 } })
  })

  it('looks a paper up by its arXiv id: null when the site has no such paper, an error when the request fails', async () => {
    const paper = { id: 'doc-1', source: 'arxiv', title: 'Raven', arxiv_id: '2609.33439' }
    transport.get.mockResolvedValueOnce({ data: paper })
    await expect(fetchPaperByArxiv('2609.33439')).resolves.toEqual(paper)
    expect(transport.get).toHaveBeenLastCalledWith('/papers/arxiv/2609.33439')

    transport.get.mockRejectedValueOnce({ response: { status: 404, data: { detail: "Paper 'arXiv:2609.00001' not found" } } })
    await expect(fetchPaperByArxiv('2609.00001')).resolves.toBeNull()

    transport.get.mockResolvedValueOnce({ data: '' })
    await expect(fetchPaperByArxiv('2609.00002')).resolves.toBeNull()

    const outage = { response: { status: 502 } }
    transport.get.mockRejectedValueOnce(outage)
    await expect(fetchPaperByArxiv('2609.00003')).rejects.toBe(outage)

    const offline = new Error('network unavailable')
    transport.get.mockRejectedValueOnce(offline)
    await expect(fetchPaperByArxiv('2609.00004')).rejects.toBe(offline)
  })
})
