import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { monitorApi } from './monitorApi'
import { createEmptyMcpForm, createGithubCrawlForm, createProviderForm } from '@/features/monitor/monitorModel'

describe('Monitor API contract', () => {
  beforeEach(() => Object.values(transport).forEach((mock) => mock.mockReset()))

  it('preserves read endpoints, pagination, and response defaults', async () => {
    transport.get.mockResolvedValueOnce({ data: {} })
    await expect(monitorApi.fetchTasks(2, 25)).resolves.toEqual({ items: [], total: 0, page: 2, page_size: 25 })
    expect(transport.get).toHaveBeenCalledWith('/monitor/tasks', { params: { page: 2, page_size: 25 } })

    transport.get.mockResolvedValueOnce({ data: { running: false } })
    await monitorApi.fetchSchedulerStatus()
    expect(transport.get).toHaveBeenLastCalledWith('/ops/scheduler/status')
    transport.get.mockResolvedValueOnce({ data: { items: null } })
    await expect(monitorApi.fetchMcpServers()).resolves.toEqual([])
  })

  it('normalizes the MCP tool call metrics section with safe defaults', async () => {
    transport.get.mockResolvedValueOnce({ data: {} })
    await expect(monitorApi.fetchMcpToolCalls()).resolves.toEqual({ since: '', total_calls: 0, tools: {} })
    expect(transport.get).toHaveBeenLastCalledWith('/monitor/metrics')

    const tools = { get_top_items: { calls: 3, last_called_at: '2026-08-04T01:00:00+00:00' } }
    transport.get.mockResolvedValueOnce({
      data: { mcp_tool_calls: { since: '2026-08-04T00:00:00+00:00', total_calls: 3, tools } },
    })
    await expect(monitorApi.fetchMcpToolCalls()).resolves.toEqual({
      since: '2026-08-04T00:00:00+00:00', total_calls: 3, tools,
    })
  })

  it('never sends masked provider secrets and preserves explicit clear semantics', async () => {
    transport.put.mockResolvedValue({ data: { provider: 'openai' } })
    const form = createProviderForm({
      provider: 'openai', base_url: 'https://api.test', model_name: 'model', api_key_configured: true,
      api_key_masked: 'sk-***', updated_at: null,
    })
    await monitorApi.saveProviderConfig(form)
    expect(transport.put).toHaveBeenCalledWith('/ops/provider-config', {
      provider: 'openai', base_url: 'https://api.test', model_name: 'model', api_key: null, clear_api_key: false,
    })
    expect(JSON.stringify(transport.put.mock.calls)).not.toContain('sk-***')
    form.clear_api_key = true
    await monitorApi.saveProviderConfig(form)
    expect(transport.put).toHaveBeenLastCalledWith('/ops/provider-config', expect.objectContaining({ api_key: null, clear_api_key: true }))
  })

  it('preserves MCP create/update payloads, secret behavior, and 30 second test timeout', async () => {
    transport.post.mockResolvedValue({ data: { id: 1 } })
    const form = createEmptyMcpForm()
    form.server_key = 'docs'
    form.display_name = 'Docs'
    form.url = 'https://mcp.test'
    await monitorApi.saveMcpServer(form)
    expect(transport.post).toHaveBeenCalledWith('/ops/mcp-servers', expect.objectContaining({
      transport: 'streamable_http', auth_token: null, clear_auth_token: false,
    }))

    form.id = 1
    form.clear_auth_token = true
    transport.put.mockResolvedValue({ data: { id: 1 } })
    await monitorApi.saveMcpServer(form)
    expect(transport.put).toHaveBeenCalledWith('/ops/mcp-servers/1', expect.objectContaining({ auth_token: null, clear_auth_token: true }))

    transport.post.mockResolvedValue({ data: { status: 'success' } })
    await monitorApi.testMcpServer(1)
    expect(transport.post).toHaveBeenLastCalledWith('/ops/mcp-servers/1/test', null, { timeout: 30_000 })
  })

  it('preserves operation endpoint request shapes', async () => {
    transport.post.mockResolvedValue({ data: {} })
    await monitorApi.ingestSource('news')
    expect(transport.post).toHaveBeenLastCalledWith('/ops/ingest-source', null, { params: { source: 'news', limit: 20 } })
    await monitorApi.syncData(true)
    expect(transport.post).toHaveBeenLastCalledWith('/ops/ingest', { limit: 20, force: true })
    await monitorApi.ingestByDate('2026-07-20')
    expect(transport.post).toHaveBeenLastCalledWith('/ops/ingest-by-date', { target_date: '2026-07-20', limit: 30 })
  })

  it('preserves GitHub crawl trigger payload, snake_case mapping, and extended timeout', async () => {
    transport.post.mockResolvedValue({ data: { status: 'queued' } })
    const form = { ...createGithubCrawlForm('2026-08-04'), pushedAfter: '2025-07-09' }
    await monitorApi.crawlGithubProjects(form)
    expect(transport.post).toHaveBeenCalledWith('/ops/github-projects/crawl', {
      min_stars: 500, max_stars: 0, created_start: '2008-01-01', created_end: '2026-08-04',
      pushed_after: '2025-07-09', limit: 5000, enrich: true, dry_run: false,
    }, { timeout: 180_000 })

    await monitorApi.crawlGithubProjects({ ...createGithubCrawlForm('2026-08-04'), createdEnd: '', pushedAfter: '' })
    expect(transport.post).toHaveBeenLastCalledWith('/ops/github-projects/crawl',
      expect.objectContaining({ created_end: null, pushed_after: null }), { timeout: 180_000 })
  })

  it('omits empty GitHub crawl status query params', async () => {
    transport.get.mockResolvedValue({ data: { status: 'idle' } })
    await monitorApi.fetchGithubCrawlStatus()
    expect(transport.get).toHaveBeenLastCalledWith('/ops/github-projects/crawl/status', undefined)

    await monitorApi.fetchGithubCrawlStatus({ channel: 'admin_crawl_x', first_seen_after: '', min_stars: 600 })
    expect(transport.get).toHaveBeenLastCalledWith('/ops/github-projects/crawl/status', {
      params: { channel: 'admin_crawl_x', min_stars: 600 },
    })
  })
})
