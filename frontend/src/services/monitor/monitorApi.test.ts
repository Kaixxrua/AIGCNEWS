import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { monitorApi } from './monitorApi'
import { createEmptyMcpForm, createEmptySchedulerJobConfigForm, createEmptyXCredentialForm, createGithubCrawlForm, createProviderForm } from '@/features/monitor/monitorModel'

const schedulerConfig = {
  job_id: 'ingest:arxiv',
  name: 'arXiv ingestion',
  start_time: '08:00',
  end_time: '20:00',
  interval_minutes: 120,
  enabled: true,
}

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

  it('preserves scheduler config list and update endpoints', async () => {
    transport.get.mockResolvedValueOnce({ data: { items: [schedulerConfig] } })
    await expect(monitorApi.fetchSchedulerConfigs()).resolves.toEqual([schedulerConfig])
    expect(transport.get).toHaveBeenLastCalledWith('/ops/scheduler/config')

    transport.get.mockResolvedValueOnce({ data: {} })
    await expect(monitorApi.fetchSchedulerConfigs()).resolves.toEqual([])

    transport.put.mockResolvedValueOnce({ data: { item: schedulerConfig, message: '定时任务 ingest:arxiv 配置已保存并即时生效。' } })
    const form = createEmptySchedulerJobConfigForm(schedulerConfig)
    await expect(monitorApi.saveSchedulerConfig(form)).resolves.toEqual({
      item: schedulerConfig,
      message: '定时任务 ingest:arxiv 配置已保存并即时生效。',
    })
    expect(transport.put).toHaveBeenLastCalledWith(
      '/ops/scheduler/config/ingest%3Aarxiv',
      { start_time: '08:00', end_time: '20:00', interval_minutes: 120, enabled: true },
    )
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
      api_key_masked: 'sk-***', updated_at: null, reasoning_effort: 'high',
    })
    expect(form.reasoning_effort).toBe('high')
    await monitorApi.saveProviderConfig(form)
    expect(transport.put).toHaveBeenCalledWith('/ops/provider-config', {
      provider: 'openai', base_url: 'https://api.test', model_name: 'model', api_key: null, clear_api_key: false,
      reasoning_effort: 'high',
    })
    expect(JSON.stringify(transport.put.mock.calls)).not.toContain('sk-***')
    form.clear_api_key = true
    await monitorApi.saveProviderConfig(form)
    expect(transport.put).toHaveBeenLastCalledWith('/ops/provider-config', expect.objectContaining({ api_key: null, clear_api_key: true }))
  })

  it('preserves custom reasoning effort tiers and only normalizes case, whitespace and length', () => {
    expect(createProviderForm(null).reasoning_effort).toBe('')
    expect(createProviderForm({
      provider: 'openai', base_url: '', model_name: '', api_key_configured: false,
      api_key_masked: null, updated_at: null, reasoning_effort: 'xhigh',
    }).reasoning_effort).toBe('xhigh')
    // 与后端同一归一：trim + 小写 + 截断 32 列宽
    expect(createProviderForm({
      provider: 'openai', base_url: '', model_name: '', api_key_configured: false,
      api_key_masked: null, updated_at: null, reasoning_effort: ' High ',
    }).reasoning_effort).toBe('high')
    expect(createProviderForm({
      provider: 'openai', base_url: '', model_name: '', api_key_configured: false,
      api_key_masked: null, updated_at: null, reasoning_effort: 'x'.repeat(40),
    }).reasoning_effort).toBe('x'.repeat(32))
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

  it('preserves X watch account endpoints, payload mapping, and 30 second test timeout', async () => {
    const xAccount = {
      id: 3, screen_name: 'openai', display_name: 'OpenAI', note: '', enabled: true,
      sort_order: 1, last_test_status: 'success', last_test_message: '', last_test_at: null,
      created_at: null, updated_at: null,
    }
    transport.get.mockResolvedValue({ data: { items: [xAccount] } })
    await expect(monitorApi.fetchXWatchAccounts()).resolves.toEqual([xAccount])
    expect(transport.get).toHaveBeenLastCalledWith('/ops/x-watch-accounts')

    transport.get.mockResolvedValue({ data: {} })
    await expect(monitorApi.fetchXWatchAccounts()).resolves.toEqual([])

    transport.post.mockResolvedValue({ data: xAccount })
    const form = {
      id: null, screen_name: 'openai', display_name: 'OpenAI', note: '官方', enabled: true, sort_order: 1,
    }
    await monitorApi.saveXWatchAccount(form)
    expect(transport.post).toHaveBeenLastCalledWith('/ops/x-watch-accounts', {
      screen_name: 'openai', display_name: 'OpenAI', note: '官方', enabled: true, sort_order: 1,
    })

    transport.put.mockResolvedValue({ data: xAccount })
    await monitorApi.saveXWatchAccount({ ...form, id: 3 })
    expect(transport.put).toHaveBeenLastCalledWith('/ops/x-watch-accounts/3',
      expect.objectContaining({ screen_name: 'openai', sort_order: 1 }))

    await monitorApi.testXWatchAccount(3)
    expect(transport.post).toHaveBeenLastCalledWith('/ops/x-watch-accounts/3/test', null, { timeout: 30_000 })

    transport.delete.mockResolvedValue({ data: { deleted: true, id: 3 } })
    await monitorApi.deleteXWatchAccount(3)
    expect(transport.delete).toHaveBeenLastCalledWith('/ops/x-watch-accounts/3')
  })

  it('preserves X credential endpoints, safe secret payloads, and 30 second test timeout', async () => {
    const credential = {
      id: 7,
      display_name: 'Primary X',
      note: 'main cookie pair',
      enabled: true,
      sort_order: 0,
      auth_token_configured: true,
      auth_token_masked: 'auth****oken',
      ct0_configured: true,
      ct0_masked: 'ct0****token',
      last_test_status: 'succeeded',
      last_test_message: 'OK',
      last_test_at: null,
      created_at: null,
      updated_at: null,
    }
    transport.get.mockResolvedValue({ data: { items: [credential] } })
    await expect(monitorApi.fetchXCredentials()).resolves.toEqual([credential])
    expect(transport.get).toHaveBeenLastCalledWith('/ops/x-credentials')

    transport.get.mockResolvedValue({ data: {} })
    await expect(monitorApi.fetchXCredentials()).resolves.toEqual([])

    transport.post.mockResolvedValue({ data: credential })
    const form = createEmptyXCredentialForm()
    form.display_name = 'Primary X'
    form.note = 'main cookie pair'
    form.auth_token = 'auth-secret'
    form.ct0 = 'ct0-secret'
    await monitorApi.saveXCredential(form)
    expect(transport.post).toHaveBeenLastCalledWith('/ops/x-credentials', {
      display_name: 'Primary X', note: 'main cookie pair', enabled: true, sort_order: 0,
      auth_token: 'auth-secret', ct0: 'ct0-secret',
    })

    form.id = 7
    form.auth_token = ''
    form.ct0 = ''
    transport.put.mockResolvedValue({ data: credential })
    await monitorApi.saveXCredential(form)
    expect(transport.put).toHaveBeenLastCalledWith('/ops/x-credentials/7', {
      display_name: 'Primary X', note: 'main cookie pair', enabled: true, sort_order: 0,
      auth_token: null, ct0: null,
    })
    expect(JSON.stringify(transport.put.mock.calls)).not.toContain('auth****oken')
    expect(JSON.stringify(transport.put.mock.calls)).not.toContain('ct0****token')

    transport.post.mockResolvedValue({ data: { status: 'succeeded', message: 'OK', credential } })
    await monitorApi.testXCredential(7)
    expect(transport.post).toHaveBeenLastCalledWith('/ops/x-credentials/7/test', null, { timeout: 30_000 })

    transport.delete.mockResolvedValue({ data: { deleted: true, id: 7 } })
    await monitorApi.deleteXCredential(7)
    expect(transport.delete).toHaveBeenLastCalledWith('/ops/x-credentials/7')
  })
  it('preserves GitHub crawl payloads and long request timeout', async () => {
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

  it('reads enrichment status and triggers enrichment with concurrency without touching succeeded rows', async () => {
    transport.get.mockResolvedValue({ data: { eligible: 100, succeeded: 95, failed: 3, pending: 2 } })
    await expect(monitorApi.fetchGithubEnrichmentStatus()).resolves.toEqual({ eligible: 100, succeeded: 95, failed: 3, pending: 2 })
    expect(transport.get).toHaveBeenLastCalledWith('/ops/github-projects/enrichment-status')

    transport.post.mockResolvedValue({ data: { status: 'queued', message: 'ok' } })
    await expect(monitorApi.triggerGithubEnrichment(3, 5)).resolves.toEqual({ status: 'queued', message: 'ok' })
    expect(transport.post).toHaveBeenLastCalledWith('/ops/github-projects/enrich', {
      limit: 3, force: false, dry_run: false, retry_failed: true, refresh_changed: false, concurrency: 5,
    })

    transport.post.mockResolvedValue({ data: { status: 'cancelling', message: 'stopping' } })
    await expect(monitorApi.cancelGithubEnrichment()).resolves.toEqual({ status: 'cancelling', message: 'stopping' })
    expect(transport.post).toHaveBeenLastCalledWith('/ops/github-projects/enrich-cancel')
  })
})
