import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AiOpsPanel from './AiOpsPanel.vue'
import { api } from '@/services/http/apiClient'

vi.mock('@/services/http/apiClient', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))
const run = { id: 'run-1', trigger: 'manual', status: 'running', started_at: '2026-09-20T00:00:00Z' }
describe('AI operations console', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(api.get).mockImplementation(async (path) => ({ data: path.endsWith('/runs')
      ? { items: [run], config: { enabled: false, interval_minutes: 15 } }
      : { ...run, events: [{ at: run.started_at, kind: 'tool_result', title: 'health', data: { status: 'ok' } }], report: '' } }))
  })
  afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })
  it('shows live evidence, prevents duplicate starts, stops polling when closed', async () => {
    const wrapper = mount(AiOpsPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('证据已记录')
    expect(wrapper.text()).toContain('依赖健康')
    const start = wrapper.findAll('button').find(b => b.text().includes('立即巡检'))!
    expect(start.attributes('disabled')).toBeDefined()
    await vi.advanceTimersByTimeAsync(2000)
    expect(api.get).toHaveBeenCalledTimes(4)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(4000)
    expect(api.get).toHaveBeenCalledTimes(4)
  })
  it('renders model output as text, never executable HTML', async () => {
    vi.mocked(api.get).mockImplementation(async (path) => ({ data: path.endsWith('/runs')
      ? { items: [{ ...run, status: 'completed' }], config: { enabled: false, interval_minutes: 15 } }
      : { ...run, status: 'completed', events: [], report: '<img src=x onerror=alert(1)>' } }))
    const wrapper = mount(AiOpsPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
    expect(wrapper.find('img').exists()).toBe(false)
    wrapper.unmount()
  })
  it('saves explicit recovery revocation and shows admitted action results', async () => {
    vi.mocked(api.get).mockImplementation(async (path) => ({ data: path.endsWith('/runs')
      ? { items: [run], config: { enabled: true, interval_minutes: 15, recovery_enabled: true } }
      : { ...run, events: [{ at: run.started_at, kind: 'action_result', title: '公共资讯补跑', data: { status: 'scheduled' } }], report: '' } }))
    const wrapper = mount(AiOpsPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('有限自愈')
    expect(wrapper.text()).toContain('执行结果')
    await wrapper.findAll('input[type="checkbox"]')[1]!.setValue(false)
    await wrapper.get('[aria-label="保存巡检计划"]').trigger('click')
    await flushPromises()
    expect(api.put).toHaveBeenCalledWith('/ops/ai/config', { enabled: true, interval_minutes: 15, recovery_enabled: false })
    wrapper.unmount()
  })
})
