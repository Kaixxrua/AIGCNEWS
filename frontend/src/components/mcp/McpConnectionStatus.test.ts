import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import i18n from '@/i18n'
import type { TokenConnectionStatus, TokenConnectionWatch } from '@/composables/useTokenConnectionWatch'
import McpConnectionStatus from './McpConnectionStatus.vue'

type ConnectionPatch = { lastUsedAt?: string | null; fresh?: boolean; slow?: boolean; clientLabel?: string | null }

const buildConnection = (status: TokenConnectionStatus, patch: ConnectionPatch = {}) => ({
  status: ref<TokenConnectionStatus>(status),
  lastUsedAt: ref<string | null>(patch.lastUsedAt ?? null),
  fresh: ref(patch.fresh ?? false),
  slow: ref(patch.slow ?? false),
  checking: ref(false),
  clientLabel: ref<string | null>(patch.clientLabel ?? null),
  start: vi.fn(),
  startNew: vi.fn(),
  nudge: vi.fn(),
  checkNow: vi.fn(),
  stop: vi.fn(),
  dispose: vi.fn(),
})

const mounted: VueWrapper[] = []
// 挂到 document 上：jsdom 给游离节点算的样式会缓存，v-show 切换后 isVisible 读到的还是旧值。
const mountStatus = (connection: ReturnType<typeof buildConnection>, props: Record<string, unknown> = {}, slots: Record<string, string> = {}) => {
  const wrapper = mount(McpConnectionStatus, {
    props: { connection: connection as unknown as TokenConnectionWatch, ...props },
    slots,
    global: { plugins: [i18n] },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  return wrapper
}

const tipsList = (wrapper: VueWrapper) => wrapper.get('.token-connection-tips')
const tipsToggle = (wrapper: VueWrapper) => wrapper.get('[data-connection-action="tips"]')

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  i18n.global.locale.value = 'zh-CN'
})

describe('McpConnectionStatus', () => {
  it('renders nothing before a token is handed out', () => {
    const wrapper = mountStatus(buildConnection('idle'))
    expect(wrapper.find('.token-connection').exists()).toBe(false)
  })

  it('waits for the Agent after the prompt is copied and checks again on request', async () => {
    const connection = buildConnection('waiting')
    const wrapper = mountStatus(connection)

    const text = wrapper.get('[role="status"]')
    expect(text.text()).toContain('等待 Agent 完成配置…')
    expect(text.text()).toContain('把提示词粘给你的 Agent')
    expect(tipsList(wrapper).isVisible()).toBe(false)

    await wrapper.get('[data-connection-action="check"]').trigger('click')
    expect(connection.checkNow).toHaveBeenCalledOnce()

    connection.checking.value = true
    await nextTick()
    expect(wrapper.get('[data-connection-action="check"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-connection-action="check"]').text()).toBe('检查中…')
  })

  it('names the client that was just authorized, and stays generic when it gave no name', async () => {
    const connection = buildConnection('authorized', { clientLabel: 'Claude Code' })
    const wrapper = mountStatus(connection)

    expect(wrapper.get('.token-connection').attributes('data-connection')).toBe('authorized')
    expect(wrapper.text()).toContain('Claude Code 已获授权，等它连上…')
    expect(wrapper.find('[data-connection-action="check"]').exists()).toBe(true)

    connection.clientLabel.value = 'MCP OAuth'
    await nextTick()
    expect(wrapper.text()).toContain('已授权，等客户端连上…')

    connection.clientLabel.value = 'x'.repeat(80)
    await nextTick()
    expect(wrapper.text()).toContain(`${'x'.repeat(39)}… 已获授权`)
  })

  it('confirms the new client with its time, drops the actions and shows the slot', () => {
    const lastUsedAt = '2026-10-05T12:00:05Z'
    const connection = buildConnection('connected', { fresh: true, lastUsedAt, slow: true, clientLabel: 'Cursor' })
    const wrapper = mountStatus(connection, {}, { default: '<p class="quota">每 24 小时 200 次</p>' })

    const time = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(Date.parse(lastUsedAt))
    expect(wrapper.text()).toContain('已接入')
    expect(wrapper.text()).toContain(`Cursor 在 ${time} 连上了 AIGC Radar。`)
    expect(wrapper.get('.token-connection-extra .quota').text()).toBe('每 24 小时 200 次')
    expect(wrapper.find('.token-connection-actions').exists()).toBe(false)
    expect(tipsList(wrapper).isVisible()).toBe(false)
  })

  it('says the client connected without a name when OAuth registration gave none', () => {
    const lastUsedAt = '2026-10-05T12:00:05Z'
    const wrapper = mountStatus(buildConnection('connected', { fresh: true, lastUsedAt, clientLabel: 'MCP OAuth' }))

    const time = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(Date.parse(lastUsedAt))
    expect(wrapper.text()).toContain(`客户端在 ${time} 连上了 AIGC Radar。`)
  })

  it('opens the Agent tips on demand, wired up for screen readers', async () => {
    const wrapper = mountStatus(buildConnection('waiting'))

    expect(tipsToggle(wrapper).attributes('aria-expanded')).toBe('false')
    expect(tipsToggle(wrapper).attributes('aria-controls')).toBe(tipsList(wrapper).attributes('id'))
    await tipsToggle(wrapper).trigger('click')

    expect(tipsToggle(wrapper).attributes('aria-expanded')).toBe('true')
    expect(tipsList(wrapper).isVisible()).toBe(true)
    const tips = tipsList(wrapper).findAll('li').map((item) => item.text())
    expect(tips).toHaveLength(4)
    expect(tips[0]).toContain('claude mcp login aigc-news')
    expect(tips[1]).toContain('现在这个账号')
    expect(tips[2]).toContain('重启客户端')
    expect(tips[3]).toContain('「手动配置」')
  })

  it('waits for a manual configuration with its own wording and tips', async () => {
    const connection = buildConnection('waiting')
    const wrapper = mountStatus(connection, { variant: 'manual' })

    expect(wrapper.text()).toContain('等待客户端连接…')
    expect(wrapper.text()).toContain('把配置填进客户端并重启它')
    await tipsToggle(wrapper).trigger('click')
    const tips = tipsList(wrapper).findAll('li').map((item) => item.text())
    expect(tips).toHaveLength(4)
    expect(tips[0]).toContain('重启客户端')
    expect(tips[1]).toContain('合法的 JSON')
    expect(tips.join('')).not.toContain('第 3 步')

    const lastUsedAt = '2026-10-05T12:00:05Z'
    connection.lastUsedAt.value = lastUsedAt
    connection.fresh.value = true
    connection.status.value = 'connected'
    await nextTick()
    const time = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(Date.parse(lastUsedAt))
    expect(wrapper.text()).toContain('已连接')
    expect(wrapper.text()).toContain(`客户端在 ${time} 用这枚 Token 连上了 AIGC Radar。`)
  })

  it('opens the tips by itself after a long wait, but not again once the user closed them', async () => {
    const connection = buildConnection('waiting')
    const wrapper = mountStatus(connection)

    connection.slow.value = true
    await nextTick()
    expect(tipsList(wrapper).isVisible()).toBe(true)

    await tipsToggle(wrapper).trigger('click')
    expect(tipsList(wrapper).isVisible()).toBe(false)
    connection.status.value = 'paused'
    await nextTick()
    expect(tipsList(wrapper).isVisible()).toBe(false)
  })

  it('shows the tips straight away once checking has stopped', () => {
    const agent = mountStatus(buildConnection('paused'))
    expect(agent.get('.token-connection').attributes('data-connection')).toBe('paused')
    expect(agent.text()).toContain('还没检测到接入')
    expect(tipsList(agent).isVisible()).toBe(true)

    const manual = mountStatus(buildConnection('paused'), { variant: 'manual' })
    expect(manual.text()).toContain('还没检测到连接')
    expect(tipsList(manual).isVisible()).toBe(true)
  })

  it('tells returning dsh users how long ago their reused token was used', () => {
    const lastUsedAt = new Date(Date.now() - 3 * 3_600_000).toISOString()
    const wrapper = mountStatus(buildConnection('connected', { lastUsedAt }), { variant: 'dsh' })

    expect(wrapper.get('.token-connection').attributes('data-connection')).toBe('seen')
    expect(wrapper.text()).toContain('以前连上过')
    expect(wrapper.text()).toContain(new Intl.RelativeTimeFormat('zh-CN', { numeric: 'auto' }).format(-3, 'hour'))
    expect(wrapper.find('[data-connection-action="check"]').exists()).toBe(true)
  })

  it('says a dsh token is gone and offers nothing to retry', () => {
    const wrapper = mountStatus(buildConnection('gone'), { variant: 'dsh' })

    expect(wrapper.text()).toContain('这枚 Token 已失效')
    expect(wrapper.text()).toContain('刷新页面后再复制一次')
    expect(wrapper.find('.token-connection-actions').exists()).toBe(false)
  })

  it('leaves announcing to the surrounding live region when asked', () => {
    const wrapper = mountStatus(buildConnection('waiting'), { live: false })
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })

  it('speaks English with the dsh tips, including the npm scope', async () => {
    i18n.global.locale.value = 'en-US'
    const wrapper = mountStatus(buildConnection('waiting', { slow: true }), { variant: 'dsh' })

    expect(wrapper.text()).toContain('Waiting for dsh to connect…')
    const tips = tipsList(wrapper).findAll('li').map((item) => item.text())
    expect(tips[0]).toContain('npx @deepseek-ai/dsh web')
    expect(tips[3]).toContain(i18n.global.t('dsh.wizard.tokenRotate'))
  })
})
