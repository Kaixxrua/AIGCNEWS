import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { sendVisitBeacon } from './visitBeacon'

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

describe('visit beacon (pure visit-count semantics)', () => {
  beforeEach(() => {
    transport.post.mockReset()
    sessionStorage.clear()
  })

  it('posts once per tab session and guards subsequent sends', async () => {
    transport.post.mockResolvedValue({ data: { today_visits: 1, total_visits: 1 } })

    sendVisitBeacon()
    await flush()
    sendVisitBeacon()
    await flush()

    expect(transport.post).toHaveBeenCalledTimes(1)
    expect(transport.post).toHaveBeenCalledWith('/dashboard/visit')
  })

  it('does not set the guard when the post fails, so a later entry retries', async () => {
    transport.post.mockRejectedValueOnce(new Error('backend down'))
    sendVisitBeacon()
    await flush()

    transport.post.mockResolvedValue({ data: { today_visits: 1, total_visits: 1 } })
    sendVisitBeacon()
    await flush()

    expect(transport.post).toHaveBeenCalledTimes(2)
  })

  it('stays silent when sessionStorage is unavailable', async () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })

    sendVisitBeacon()
    await flush()

    expect(transport.post).not.toHaveBeenCalled()
    getItem.mockRestore()
  })
})
