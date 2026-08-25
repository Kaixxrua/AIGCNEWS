import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

import { useRegisterForm } from './useRegisterForm'

type PostFn = (url: string, payload: Record<string, string>) => Promise<unknown>

describe('useRegisterForm', () => {
  let post: Mock<PostFn>
  let login: Mock<(e: string, p: string) => Promise<unknown>>
  let onSuccess: Mock<() => void>

  beforeEach(() => {
    vi.useFakeTimers()
    post = vi.fn<PostFn>().mockResolvedValue({})
    login = vi.fn().mockResolvedValue({})
    onSuccess = vi.fn()
  })

  const makeForm = () => useRegisterForm({ post, login, onSuccess })

  it('rejects mismatched passwords without calling post', async () => {
    const form = makeForm()
    form.email.value = 'a@b.com'
    form.otp.value = '123456'
    form.password.value = 'secret1234'
    form.confirmPwd.value = 'different'
    form.agreedToTerms.value = true

    await form.handleRegister()

    expect(form.errorMsg.value).toBe('auth.passwordMismatch')
    expect(post).not.toHaveBeenCalled()
  })

  it('requires agreeing to the terms', async () => {
    const form = makeForm()
    form.email.value = 'a@b.com'
    form.otp.value = '123456'
    form.password.value = 'secret1234'
    form.confirmPwd.value = 'secret1234'
    form.agreedToTerms.value = false

    await form.handleRegister()

    expect(form.errorMsg.value).toBe('auth.mustAgree')
    expect(post).not.toHaveBeenCalled()
  })

  it('registers, auto-logs in, then invokes onSuccess after the redirect delay', async () => {
    const form = makeForm()
    form.email.value = 'a@b.com'
    form.otp.value = '123456'
    form.password.value = 'secret1234'
    form.confirmPwd.value = 'secret1234'
    form.agreedToTerms.value = true

    await form.handleRegister()

    expect(post).toHaveBeenCalledWith('/auth/register', { email: 'a@b.com', email_code: '123456', password: 'secret1234' })
    expect(login).toHaveBeenCalledWith('a@b.com', 'secret1234')
    expect(form.successMsg.value).toBe('auth.registerSuccess')
    // 延迟前不调用
    expect(onSuccess).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(900)
    expect(onSuccess).toHaveBeenCalledTimes(1)
  })

  it('surfaces the register failure message when post rejects', async () => {
    post.mockRejectedValue(new Error('boom'))
    const form = makeForm()
    form.email.value = 'a@b.com'
    form.otp.value = '123456'
    form.password.value = 'secret1234'
    form.confirmPwd.value = 'secret1234'
    form.agreedToTerms.value = true

    await form.handleRegister()

    expect(form.errorMsg.value).toBeTruthy()
    expect(login).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(900)
    expect(onSuccess).not.toHaveBeenCalled()
  })
})
