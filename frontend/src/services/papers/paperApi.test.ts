import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { fetchPaperDetail } from './paperApi'

describe('Paper API transport contract', () => {
  beforeEach(() => {
    transport.get.mockReset()
  })

  it('returns paper data on success and null for empty or failed detail requests', async () => {
    const paper = { id: 'paper-1', source: 'arxiv', title: 'Paper' }
    transport.get.mockResolvedValueOnce({ data: paper })
    await expect(fetchPaperDetail('paper-1')).resolves.toEqual(paper)
    expect(transport.get).toHaveBeenLastCalledWith('/papers/paper-1')

    transport.get.mockResolvedValueOnce({ data: undefined })
    await expect(fetchPaperDetail('missing')).resolves.toBeNull()

    transport.get.mockRejectedValueOnce(new Error('network unavailable'))
    await expect(fetchPaperDetail('failed')).resolves.toBeNull()
  })
})
