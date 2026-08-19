import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

import { useChangePasswordForm } from './useChangePasswordForm'

type SubmitFn = (emailCode: string, newPassword: string) => Promise<unknown>
type SendOtpFn = () => Promise<unknown>

describe('useChangePasswordForm', () => {
  let submit: Mock<SubmitFn>
  let sendOtp: Mock<SendOtpFn>

  beforeEach(() => {
    submit = vi.fn<SubmitFn>().mockResolvedValue({ detail: 'ok' })
    sendOtp = vi.fn<SendOtpFn>().mockResolvedValue({ detail: 'sent' })
  })

  const makeForm = (onChanged?: () => Promise<void> | void) =>
    useChangePasswordForm({ submit, sendOtp, onChanged })

  it('rejects an invalid otp without calling submit', async () => {
    const form = makeForm()
    form.otp.value = '123'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.invalidOtp')
    expect(submit).not.toHaveBeenCalled()
  })

  it('rejects a weak new password', async () => {
    const form = makeForm()
    form.otp.value = '123456'
    form.password.value = '123'
    form.confirmPwd.value = '123'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.passwordMin')
    expect(submit).not.toHaveBeenCalled()
  })

  it('rejects mismatched password confirmation', async () => {
    const form = makeForm()
    form.otp.value = '123456'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass2'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.passwordMismatch')
    expect(submit).not.toHaveBeenCalled()
  })

  it('submits code and new password, marks done, and invokes onChanged on success', async () => {
    const onChanged = vi.fn()
    const form = makeForm(onChanged)
    form.otp.value = '123456'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'

    await form.handleSubmit()

    expect(submit).toHaveBeenCalledWith('123456', 'newpass1')
    expect(form.changeDone.value).toBe(true)
    expect(form.successMsg.value).toBe('auth.changeSuccess')
    expect(form.errorMsg.value).toBe('')
    expect(form.loading.value).toBe(false)
    expect(onChanged).toHaveBeenCalledTimes(1)
  })

  it('maps a 429 failure to the rate-limited message', async () => {
    submit.mockRejectedValue({ response: { status: 429 } })
    const form = makeForm()
    form.otp.value = '123456'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.rateLimited')
    expect(form.changeDone.value).toBe(false)
    expect(form.loading.value).toBe(false)
  })

  it('surfaces the backend detail message for other failures', async () => {
    submit.mockRejectedValue({ response: { status: 400, data: { detail: '验证码错误或已过期' } } })
    const form = makeForm()
    form.otp.value = '000000'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('验证码错误或已过期')
  })

  it('falls back to the generic failure message without details', async () => {
    submit.mockRejectedValue({})
    const form = makeForm()
    form.otp.value = '123456'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.changeFailed')
  })

  it('sends otp, starts countdown, and shows the sent hint', async () => {
    const form = makeForm()

    await form.handleSendOtp()

    expect(sendOtp).toHaveBeenCalledTimes(1)
    expect(form.countdown.value).toBeGreaterThan(0)
    expect(form.otpBtnDisabled.value).toBe(true)
    expect(form.successMsg.value).toBe('auth.changeOtpSent')
    expect(form.errorMsg.value).toBe('')
    expect(form.otpLoading.value).toBe(false)
  })

  it('maps a 429 send-otp failure to the rate-limited message without countdown', async () => {
    sendOtp.mockRejectedValue({ response: { status: 429 } })
    const form = makeForm()

    await form.handleSendOtp()

    expect(form.errorMsg.value).toBe('auth.rateLimited')
    expect(form.countdown.value).toBe(0)
    expect(form.otpBtnDisabled.value).toBe(false)
  })

  it('reset clears all form state', async () => {
    const form = makeForm()
    form.otp.value = '123456'
    form.password.value = 'newpass1'
    form.confirmPwd.value = 'newpass1'
    await form.handleSubmit()
    expect(form.changeDone.value).toBe(true)

    form.reset()

    expect(form.otp.value).toBe('')
    expect(form.password.value).toBe('')
    expect(form.confirmPwd.value).toBe('')
    expect(form.errorMsg.value).toBe('')
    expect(form.successMsg.value).toBe('')
    expect(form.changeDone.value).toBe(false)
    expect(form.loading.value).toBe(false)
    expect(form.otpLoading.value).toBe(false)
    expect(form.countdown.value).toBe(0)
  })
})
