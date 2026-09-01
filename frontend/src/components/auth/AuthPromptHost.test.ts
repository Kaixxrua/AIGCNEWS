import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AuthPromptHost from './AuthPromptHost.vue'

const promptBox = vi.hoisted(() => ({ current: null as null | Record<string, any> }))
const authBox = vi.hoisted(() => ({ current: null as null | { status: 'initializing' | 'authenticated' | 'anonymous' | 'degraded'; logoutInProgress: boolean; ensureInitialized: ReturnType<typeof vi.fn> } }))

vi.mock('@/composables/useLoginPrompt', async () => {
  const { ref } = await import('vue')
  promptBox.current = {
    isOpen: ref(false),
    redirectTarget: ref('/'),
    rememberLoginRedirect: vi.fn(),
    requestLogin: vi.fn(),
    closeLoginPrompt: vi.fn(),
    consumeLoginRedirect: vi.fn(() => '/'),
  }
  return { useLoginPrompt: () => promptBox.current }
})

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  authBox.current = reactive({ status: 'authenticated' as const, logoutInProgress: false, ensureInitialized: vi.fn() })
  return { useAuthStore: () => authBox.current }
})

const i18n = createI18n({
  legacy: false,
  locale: 'en-US',
  messages: { 'en-US': { auth: { verificationFailed: 'Verification failed', retryVerification: 'Verify again' } } },
})

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/register', component: { template: '<div />' } },
    { path: '/mcp', meta: { requiresAuth: true }, component: { template: '<div />' } },
  ],
})

const stubs = {
  LoginDialog: {
    name: 'LoginDialog',
    props: ['modelValue', 'redirect'],
    emits: ['update:modelValue', 'success', 'switch-to-register'],
    template: '<div class="login-dialog-stub" />',
  },
  RegisterDialog: {
    name: 'RegisterDialog',
    props: ['modelValue'],
    emits: ['update:modelValue', 'success', 'switch-to-login'],
    template: '<div class="register-dialog-stub" />',
  },
}

const mountHost = () => mount(AuthPromptHost, {
  global: { plugins: [router, createPinia(), i18n], stubs },
})

const prompt = () => promptBox.current as Record<string, any>
const auth = () => authBox.current as { status: 'initializing' | 'authenticated' | 'anonymous' | 'degraded'; logoutInProgress: boolean; ensureInitialized: ReturnType<typeof vi.fn> }

beforeEach(async () => {
  prompt().isOpen.value = false
  prompt().redirectTarget.value = '/'
  prompt().rememberLoginRedirect.mockClear()
  prompt().requestLogin.mockClear()
  prompt().closeLoginPrompt.mockClear()
  prompt().consumeLoginRedirect.mockReset()
  prompt().consumeLoginRedirect.mockReturnValue('/')
  auth().status = 'authenticated'
  auth().logoutInProgress = false
  auth().ensureInitialized.mockReset().mockResolvedValue(undefined)
  await router.push('/')
})

describe('AuthPromptHost', () => {
  it('consumes the root login target and navigates there after modal success', async () => {
    prompt().isOpen.value = true
    prompt().redirectTarget.value = '/mcp'
    prompt().consumeLoginRedirect.mockReturnValue('/mcp')
    const wrapper = mountHost()

    const loginDialog = wrapper.findComponent({ name: 'LoginDialog' })
    expect(loginDialog.props('redirect')).toBe('/mcp')
    loginDialog.vm.$emit('success')
    await flushPromises()

    expect(prompt().consumeLoginRedirect).toHaveBeenCalledOnce()
    expect(prompt().closeLoginPrompt).toHaveBeenCalledOnce()
    expect(router.currentRoute.value.fullPath).toBe('/mcp')
    wrapper.unmount()
  })

  it('does not stack a registration dialog over the standalone registration page', async () => {
    await router.push('/register')
    const wrapper = mountHost()
    wrapper.findComponent({ name: 'LoginDialog' }).vm.$emit('switch-to-register')
    await flushPromises()

    expect(wrapper.findComponent({ name: 'LoginDialog' }).props('modelValue')).toBe(false)
    expect(wrapper.findComponent({ name: 'RegisterDialog' }).props('modelValue')).toBe(false)
    wrapper.unmount()
  })

  it('keeps login and registration dialogs mutually exclusive', async () => {
    const wrapper = mountHost()
    wrapper.findComponent({ name: 'LoginDialog' }).vm.$emit('switch-to-register')
    await flushPromises()
    expect(wrapper.findComponent({ name: 'RegisterDialog' }).props('modelValue')).toBe(true)

    prompt().isOpen.value = true
    await flushPromises()

    expect(wrapper.findComponent({ name: 'LoginDialog' }).props('modelValue')).toBe(true)
    expect(wrapper.findComponent({ name: 'RegisterDialog' }).props('modelValue')).toBe(false)
    wrapper.unmount()
  })

  it('exposes a root recovery action when auth verification is degraded', async () => {
    auth().status = 'degraded'
    const wrapper = mountHost()

    const retry = document.body.querySelector('[role="alert"] button') as HTMLButtonElement
    expect(retry).toBeTruthy()
    retry.click()
    await flushPromises()

    expect(auth().ensureInitialized).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('continues to the protected target after a degraded retry confirms the stored session', async () => {
    auth().status = 'degraded'
    auth().ensureInitialized.mockImplementation(async () => { auth().status = 'authenticated' })
    prompt().redirectTarget.value = '/mcp?source=retry#setup'
    prompt().consumeLoginRedirect.mockReturnValue('/mcp?source=retry#setup')
    const wrapper = mountHost()

    ;(document.body.querySelector('[role="alert"] button') as HTMLButtonElement).click()
    await flushPromises()

    expect(prompt().consumeLoginRedirect).toHaveBeenCalledOnce()
    expect(router.currentRoute.value.fullPath).toBe('/mcp?source=retry#setup')
    wrapper.unmount()
  })

  it('opens login after a degraded retry confirms the stored session is anonymous', async () => {
    auth().status = 'degraded'
    auth().ensureInitialized.mockImplementation(async () => { auth().status = 'anonymous' })
    prompt().redirectTarget.value = '/mcp?source=retry#setup'
    const wrapper = mountHost()

    ;(document.body.querySelector('[role="alert"] button') as HTMLButtonElement).click()
    await flushPromises()

    expect(prompt().requestLogin).toHaveBeenCalledWith('/mcp?source=retry#setup')
    wrapper.unmount()
  })

  it('moves an expired protected session home and requests login for the protected target', async () => {
    await router.push('/mcp')
    const wrapper = mountHost()

    auth().status = 'anonymous'
    await flushPromises()

    expect(prompt().requestLogin).toHaveBeenCalledWith('/mcp')
    expect(router.currentRoute.value.fullPath).toBe('/')
    wrapper.unmount()
  })

  it('does not reopen login during an explicit logout from a protected route', async () => {
    await router.push('/mcp')
    const wrapper = mountHost()

    auth().logoutInProgress = true
    auth().status = 'anonymous'
    await flushPromises()

    expect(prompt().requestLogin).not.toHaveBeenCalled()
    expect(router.currentRoute.value.fullPath).toBe('/mcp')
    wrapper.unmount()
  })
})
