import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { trackingApi } from './trackingApi'

const refused = (data: unknown) =>
  new AxiosError('Request failed with status code 403', 'ERR_BAD_REQUEST', undefined, undefined, {
    status: 403,
    data,
  } as AxiosResponse)

describe('tracking export API', () => {
  beforeEach(() => transport.get.mockReset())

  it('downloads the file as a Blob named by the server', async () => {
    const blob = new Blob(['issue_date'], { type: 'text/csv' })
    transport.get.mockResolvedValueOnce({
      data: blob,
      headers: { 'content-disposition': 'attachment; filename="aigcnews-tracking-2026-10-06.csv"' },
    })
    await expect(trackingApi.exportHistory('csv')).resolves.toEqual({
      blob,
      filename: 'aigcnews-tracking-2026-10-06.csv',
    })
    expect(transport.get).toHaveBeenCalledWith('/tracking/export', { params: { format: 'csv' }, responseType: 'blob' })
    // 读不到响应头时用通用文件名
    transport.get.mockResolvedValueOnce({ data: blob, headers: new AxiosHeaders() })
    await expect(trackingApi.exportHistory('json')).resolves.toEqual({ blob, filename: 'aigcnews-tracking.json' })
  })

  it('turns a Blob error body back into JSON so the reason can be shown', async () => {
    transport.get.mockRejectedValueOnce(refused(new Blob(['{"detail":"membership_required"}'])))
    await expect(trackingApi.exportHistory('csv')).rejects.toMatchObject({
      response: { status: 403, data: { detail: 'membership_required' } },
    })
    const body = new Blob(['<html>bad gateway</html>'])
    transport.get.mockRejectedValueOnce(refused(body))
    await expect(trackingApi.exportHistory('csv')).rejects.toMatchObject({ response: { data: body } })
  })
})
