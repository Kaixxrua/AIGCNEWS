import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

import { useChangePasswordForm } from './useChangePasswordForm'

type SubmitFn = (currentPassword: string, newPassword: string) => Promise<unknown>

describe('useChangePasswordForm', () => {
  let submit: Mock<SubmitFn>

  beforeEach(() => {
    submit = vi.fn<SubmitFn>().mockResolvedValue({ detail: 'ok' })
  })

  const makeForm = (onChanged?: () => Promise<void> | void) =>
    useChangePasswordForm({ submit, onChanged })

  it('rejects an empty current password without calling submit', async () => {
    const form = makeForm()
    form.currentPwd.value = '   '
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.currentPasswordRequired')
    expect(submit).not.toHaveBeenCalled()
  })

  it('rejects a weak new password', async () => {
    const form = makeForm()
    form.currentPwd.value = 'old-secret'
    form.password.value = '123'
    form.confirmPwd.value = '123'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.passwordMin')
    expect(submit).not.toHaveBeenCalled()
  })

  it('rejects mismatched password confirmation', async () => {
    const form = makeForm()
    form.currentPwd.value = 'old-secret'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass2'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.passwordMismatch')
    expect(submit).not.toHaveBeenCalled()
  })

  it('submits current and new password, marks done, and invokes onChanged on success', async () => {
    const onChanged = vi.fn()
    const form = makeForm(onChanged)
    form.currentPwd.value = 'old-secret'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'

    await form.handleSubmit()

    expect(submit).toHaveBeenCalledWith('old-secret', 'newpass1')
    expect(form.changeDone.value).toBe(true)
    expect(form.successMsg.value).toBe('auth.changeSuccess')
    expect(form.errorMsg.value).toBe('')
    expect(form.loading.value).toBe(false)
    expect(onChanged).toHaveBeenCalledTimes(1)
  })

  it('maps a 429 failure to the rate-limited message', async () => {
    submit.mockRejectedValue({ response: { status: 429 } })
    const form = makeForm()
    form.currentPwd.value = 'old-secret'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.rateLimited')
    expect(form.changeDone.value).toBe(false)
    expect(form.loading.value).toBe(false)
  })

  it('surfaces the backend detail message for other failures', async () => {
    submit.mockRejectedValue({ response: { status: 400, data: { detail: '当前密码错误' } } })
    const form = makeForm()
    form.currentPwd.value = 'wrong-secret'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('当前密码错误')
  })

  it('falls back to the generic failure message without details', async () => {
    submit.mockRejectedValue({})
    const form = makeForm()
    form.currentPwd.value = 'old-secret'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.changeFailed')
  })

  it('reset clears all form state', async () => {
    const form = makeForm()
    form.currentPwd.value = 'old-secret'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'
    await form.handleSubmit()
    expect(form.changeDone.value).toBe(true)

    form.reset()

    expect(form.currentPwd.value).toBe('')
    expect(form.password.value).toBe('')
    expect(form.confirmPwd.value).toBe('')
    expect(form.errorMsg.value).toBe('')
    expect(form.successMsg.value).toBe('')
    expect(form.changeDone.value).toBe(false)
    expect(form.loading.value).toBe(false)
  })
})
