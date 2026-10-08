import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { reactive } from 'vue'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import McpOAuthAuthorizeView from './McpOAuthAuthorizeView.vue'

const api = vi.hoisted(() => ({
  preview: vi.fn(),
  decide: vi.fn(),
  navigate: vi.fn(),
}))
const prompt = vi.hoisted(() => ({ requestLogin: vi.fn() }))
const frame = vi.hoisted(() => ({ framed: false }))
const authStore = vi.hoisted(() => ({ current: null as null | Record<string, unknown> }))

vi.mock('@/services/mcp/mcpOAuthApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/mcp/mcpOAuthApi')>()),
  previewMcpOAuthAuthorization: api.preview,
  decideMcpOAuthAuthorization: api.decide,
  navigateToMcpClient: api.navigate,
}))
vi.mock('@/features/mcp/mcpOAuthConsent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/features/mcp/mcpOAuthConsent')>()),
  isFramed: () => frame.framed,
}))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => prompt }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => authStore.current }))

const REDIRECT_URI = 'http://localhost:33418/callback'
const REQUEST = {
  response_type: 'code',
  client_id: 'aigc_oc_client',
  redirect_uri: REDIRECT_URI,
  state: 'st/at e',
  code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
  code_challenge_method: 'S256',
  scope: 'projects:favorites:read tracking:read',
  resource: 'https://aigcnews.cn/api/mcp/oauth',
}
/** 客户端用 URLSearchParams 拼出来的原始地址：/ 和 : 都被转义成 %2F、%3A。 */
const CLIENT_URL = `/oauth/authorize?${new URLSearchParams({ ...REQUEST, prompt: 'consent' }).toString()}`

const READY = {
  status: 'ready',
  client: { client_id: 'aigc_oc_client', client_name: 'Claude Code (aigc-radar)', registered_at: '2026-10-06T00:00:00Z' },
  redirect_uri: REDIRECT_URI,
  redirect: { kind: 'loopback', host: 'localhost' },
  scopes: ['projects:favorites:read', 'tracking:read'],
  resource: 'https://aigcnews.cn/api/mcp/oauth',
}

const axiosError = (status: number, data: unknown) => ({ isAxiosError: true, response: { status, data } })

const makeAuthStore = (status = 'authenticated') => reactive({
  status,
  token: status === 'authenticated' ? 'session-1' : null,
  user: status === 'authenticated' ? { user_id: 7, email: 'reader@example.com', username: 'reader', role: 'user' } : null,
  ensureInitialized: vi.fn().mockResolvedValue(undefined),
  invalidateSession: vi.fn(),
})

let wrapper: VueWrapper | null = null

const mountAt = async (url: string): Promise<{ router: Router; view: VueWrapper }> => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/oauth/authorize', name: 'oauth-authorize', component: McpOAuthAuthorizeView }],
  })
  await router.push(url)
  wrapper = mount({ template: '<RouterView />' }, { global: { plugins: [router, i18n], stubs: { LocaleToggle: true } } })
  await flushPromises()
  return { router, view: wrapper }
}

const store = () => authStore.current as ReturnType<typeof makeAuthStore>
const card = (view: VueWrapper) => view.get('[data-testid="mcp-oauth-card"]')

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
  frame.framed = false
  authStore.current = makeAuthStore()
  api.preview.mockReset().mockResolvedValue(READY)
  api.decide.mockReset()
  api.navigate.mockReset()
  prompt.requestLogin.mockReset()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  i18n.global.locale.value = 'zh-CN'
})

describe('MCP OAuth consent page', () => {
  it('shows who is asking, where it returns to and what it gets, from the request forwarded as is', async () => {
    const { view } = await mountAt(CLIENT_URL)

    // 只转发授权请求字段，prompt 之类的其他参数按 RFC 6749 忽略
    expect(api.preview).toHaveBeenCalledExactlyOnceWith(REQUEST)
    expect(view.get('[data-testid="mcp-oauth-client"]').text()).toBe('Claude Code (aigc-radar)')
    expect(card(view).text()).toContain('名称由客户端自己填写，本站无法核实')
    expect(card(view).text()).toContain('当前账号：reader')
    expect(view.get('[data-testid="mcp-oauth-return"]').text()).toBe('授权后回到这台电脑上的客户端（localhost）。')
    expect(view.findAll('[data-testid="mcp-oauth-grants"] li').map((item) => item.text())).toEqual([
      '以你的身份使用 AIGC Radar MCP 的检索工具，调用次数计入你的 MCP 额度',
      '读取你收藏的项目',
      '读取你的情报追踪',
    ])
    expect(card(view).text()).not.toContain('mcpOAuth.')
  })

  it('rewrites the address in vue-router encoding so a third-party sign-in can come back to it', async () => {
    const { router } = await mountAt(CLIENT_URL)

    const fullPath = router.currentRoute.value.fullPath
    expect(fullPath).not.toMatch(/%2F/i)
    expect(fullPath).not.toContain('prompt=')
    expect(router.currentRoute.value.query).toEqual(REQUEST)
    // 后端 safe_internal_redirect 拒收 %2F；重写后的地址原样能过
    expect(fullPath.startsWith('/oauth/authorize?')).toBe(true)
  })

  it('asks an anonymous visitor to sign in once and returns to the rewritten address', async () => {
    authStore.current = makeAuthStore('anonymous')
    const { router, view } = await mountAt(CLIENT_URL)

    expect(api.preview).not.toHaveBeenCalled()
    expect(card(view).text()).toContain('登录后继续授权')
    expect(prompt.requestLogin).toHaveBeenCalledOnce()
    const target = prompt.requestLogin.mock.calls[0]![0] as string
    expect(target).toBe(router.currentRoute.value.fullPath)
    expect(target).not.toMatch(/%2F/i)

    await view.get('[data-testid="mcp-oauth-login"]').trigger('click')
    expect(prompt.requestLogin).toHaveBeenCalledTimes(2)

    // 登录成功后（会话与令牌换新）读取授权请求
    Object.assign(store(), { status: 'authenticated', token: 'session-2', user: { user_id: 7, email: 'reader@example.com', username: null } })
    await flushPromises()
    expect(api.preview).toHaveBeenCalledOnce()
    expect(card(view).text()).toContain('当前账号：reader@example.com')
  })

  it('waits for the session check before reading the request', async () => {
    authStore.current = makeAuthStore('initializing')
    const { view } = await mountAt(CLIENT_URL)

    expect(store().ensureInitialized).toHaveBeenCalled()
    expect(card(view).text()).toContain('正在确认登录状态')
    expect(api.preview).not.toHaveBeenCalled()

    Object.assign(store(), { status: 'authenticated', token: 'session-1', user: { user_id: 7, email: null, username: 'reader' } })
    await flushPromises()
    expect(api.preview).toHaveBeenCalledOnce()
  })

  it('approves, sends the browser back to the client and keeps a link to open it again', async () => {
    const redirectTo = `${REDIRECT_URI}?code=abc&state=st%2Fat%20e&iss=https%3A%2F%2Faigcnews.cn`
    api.decide.mockResolvedValue({ status: 'approved', redirect_to: redirectTo })
    const { view } = await mountAt(CLIENT_URL)

    await view.get('[data-testid="mcp-oauth-approve"]').trigger('click')
    await flushPromises()

    expect(api.decide).toHaveBeenCalledExactlyOnceWith(REQUEST, 'approve')
    expect(api.navigate).toHaveBeenCalledExactlyOnceWith(redirectTo)
    expect(card(view).text()).toContain('已同意，正在回到客户端')
    expect(view.get('[data-testid="mcp-oauth-open-client"]').attributes('href')).toBe(redirectTo)

    // 已经在跳回客户端：会话再变也不重新读取同一个授权请求
    Object.assign(store(), { token: 'session-2' })
    await flushPromises()
    expect(api.preview).toHaveBeenCalledOnce()
  })

  it('denies and tells the client', async () => {
    const redirectTo = `${REDIRECT_URI}?error=access_denied&state=x`
    api.decide.mockResolvedValue({ status: 'denied', redirect_to: redirectTo })
    const { view } = await mountAt(CLIENT_URL)

    await view.get('[data-testid="mcp-oauth-deny"]').trigger('click')
    await flushPromises()

    expect(api.decide).toHaveBeenCalledExactlyOnceWith(REQUEST, 'deny')
    expect(api.navigate).toHaveBeenCalledExactlyOnceWith(redirectTo)
    expect(card(view).text()).toContain('已拒绝，正在通知客户端')
  })

  it('ignores a second click while the decision is in flight', async () => {
    let resolve!: (value: unknown) => void
    api.decide.mockReturnValue(new Promise((done) => { resolve = done }))
    const { view } = await mountAt(CLIENT_URL)

    await view.get('[data-testid="mcp-oauth-approve"]').trigger('click')
    expect(view.get('[data-testid="mcp-oauth-approve"]').attributes('disabled')).toBeDefined()
    await view.get('[data-testid="mcp-oauth-deny"]').trigger('click')
    expect(api.decide).toHaveBeenCalledOnce()

    resolve({ status: 'approved', redirect_to: `${REDIRECT_URI}?code=abc` })
    await flushPromises()
    expect(api.navigate).toHaveBeenCalledOnce()
  })

  it('never follows a return address that does not start with the callback it sent', async () => {
    api.decide.mockResolvedValue({ status: 'approved', redirect_to: 'https://evil.example/cb?code=abc' })
    const { view } = await mountAt(CLIENT_URL)

    await view.get('[data-testid="mcp-oauth-approve"]').trigger('click')
    await flushPromises()

    expect(api.navigate).not.toHaveBeenCalled()
    expect(view.get('[data-testid="mcp-oauth-error"]').text()).toBe('回调地址与客户端登记的不一致，为了安全已停止授权。')
  })

  it('shows an error the client should hear about and returns it only when the user clicks', async () => {
    const redirectTo = `${REDIRECT_URI}?error=invalid_target&error_description=x&iss=https%3A%2F%2Faigcnews.cn`
    api.preview.mockResolvedValue({ status: 'error', error: 'invalid_target', error_description: '…', redirect_to: redirectTo, redirect: READY.redirect })
    const { view } = await mountAt(CLIENT_URL)

    expect(view.get('[data-testid="mcp-oauth-error"]').text()).toBe('客户端请求的不是本站的 MCP 服务。')
    expect(card(view).text()).toContain('错误代码：invalid_target')
    expect(api.navigate).not.toHaveBeenCalled()

    await view.get('[data-testid="mcp-oauth-back"]').trigger('click')
    expect(api.navigate).toHaveBeenCalledExactlyOnceWith(redirectTo)
    expect(card(view).text()).toContain('正在把错误带回客户端')
  })

  it('offers no way back to the client when its error return address is not the callback', async () => {
    api.preview.mockResolvedValue({ status: 'error', error: 'invalid_request', error_description: '…', redirect_to: 'javascript:alert(1)', redirect: READY.redirect })
    const { view } = await mountAt(CLIENT_URL)

    expect(view.get('[data-testid="mcp-oauth-error"]').text()).toContain('授权请求不完整或格式不对')
    expect(view.find('[data-testid="mcp-oauth-back"]').exists()).toBe(false)
  })

  it('stops on an unknown client without a way back or a retry', async () => {
    api.preview.mockRejectedValue(axiosError(400, { error: 'invalid_client', error_description: '客户端未注册或注册已失效' }))
    const { view } = await mountAt(CLIENT_URL)

    expect(view.get('[data-testid="mcp-oauth-error"]').text()).toBe('这个客户端没有登记，或者登记已失效。请回到 MCP 客户端重新发起连接。')
    expect(card(view).text()).toContain('错误代码：invalid_client')
    expect(view.find('[data-testid="mcp-oauth-back"]').exists()).toBe(false)
    expect(view.findAll('button').map((button) => button.text())).not.toContain('重试')
  })

  it('lets the user retry when the service is busy or unreachable', async () => {
    api.preview.mockRejectedValueOnce(axiosError(429, { error: 'temporarily_unavailable', error_description: '请求过于频繁' }))
    const { view } = await mountAt(CLIENT_URL)
    expect(view.get('[data-testid="mcp-oauth-error"]').text()).toBe('授权服务暂时不可用或请求过于频繁，请稍后再试。')

    api.preview.mockRejectedValueOnce(new Error('Network Error'))
    await view.findAll('button').find((button) => button.text() === '重试')!.trigger('click')
    await flushPromises()
    expect(view.get('[data-testid="mcp-oauth-error"]').text()).toBe('授权没有完成，请稍后再试。')
    expect(card(view).text()).not.toContain('错误代码')

    await view.findAll('button').find((button) => button.text() === '重试')!.trigger('click')
    await flushPromises()
    expect(api.preview).toHaveBeenCalledTimes(3)
    expect(view.get('[data-testid="mcp-oauth-client"]').text()).toBe('Claude Code (aigc-radar)')
  })

  it('goes back to sign-in when the session has expired', async () => {
    api.preview.mockRejectedValue(axiosError(401, { detail: '登录已过期' }))
    const { view } = await mountAt(CLIENT_URL)

    expect(card(view).text()).toContain('登录后继续授权')
  })

  it('switches account by dropping the session and asking for a new sign-in on this page', async () => {
    const { router, view } = await mountAt(CLIENT_URL)

    await view.findAll('button').find((button) => button.text() === '换个账号')!.trigger('click')
    expect(store().invalidateSession).toHaveBeenCalledOnce()
    expect(prompt.requestLogin).toHaveBeenCalledExactlyOnceWith(router.currentRoute.value.fullPath)
  })

  it.each([
    ['without a client', `/oauth/authorize?${new URLSearchParams({ ...REQUEST, client_id: '' })}`],
    ['without a callback', '/oauth/authorize?response_type=code&client_id=aigc_oc_client'],
    ['with a repeated parameter', `${CLIENT_URL}&redirect_uri=https%3A%2F%2Fevil.example%2Fcb`],
  ])('rejects a request %s before asking anyone to sign in', async (_, url) => {
    authStore.current = makeAuthStore('anonymous')
    const { view } = await mountAt(url)

    expect(view.get('[data-testid="mcp-oauth-error"]').text()).toContain('授权请求不完整或格式不对')
    expect(prompt.requestLogin).not.toHaveBeenCalled()
    expect(api.preview).not.toHaveBeenCalled()
  })

  it('refuses to show the consent buttons inside a frame', async () => {
    frame.framed = true
    const { view } = await mountAt(CLIENT_URL)

    expect(card(view).text()).toContain('授权页不能嵌在其他网页里打开')
    expect(view.find('[data-testid="mcp-oauth-approve"]').exists()).toBe(false)
    expect(api.preview).not.toHaveBeenCalled()
  })

  it('speaks English', async () => {
    i18n.global.locale.value = 'en-US'
    const { view } = await mountAt(CLIENT_URL)

    expect(view.get('[data-testid="mcp-oauth-return"]').text()).toBe('Afterwards you go back to the client on this computer (localhost).')
    expect(view.get('[data-testid="mcp-oauth-approve"]').text()).toBe('Allow')
    expect(card(view).text()).not.toContain('mcpOAuth.')
  })
})
