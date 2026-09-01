import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

import { useEmailChangeForm } from './useEmailChangeForm'

type SubmitFn = (newEmail: string, currentCode: string, newCode: string) => Promise<unknown>
type SendCurrentFn = () => Promise<unknown>
type SendNewFn = (newEmail: string) => Promise<unknown>

describe('useEmailChangeForm', () => {
  let submit: Mock<SubmitFn>
  let sendCurrentOtp: Mock<SendCurrentFn>
  let sendNewOtp: Mock<SendNewFn>

  beforeEach(() => {
    submit = vi.fn<SubmitFn>().mockResolvedValue({ email: 'newbox@example.com' })
    sendCurrentOtp = vi.fn<SendCurrentFn>().mockResolvedValue({ detail: 'sent' })
    sendNewOtp = vi.fn<SendNewFn>().mockResolvedValue({ detail: 'sent' })
  })

  const makeForm = (onChanged?: (result?: unknown) => Promise<void> | void) =>
    useEmailChangeForm({ submit, sendCurrentOtp, sendNewOtp, onChanged })

  it('rejects an invalid new email before sending its code', async () => {
    const form = makeForm()
    form.newEmail.value = 'not-an-email'

    await form.handleSendNewOtp()

    expect(form.errorMsg.value).toBe('auth.invalidEmail')
    expect(sendNewOtp).not.toHaveBeenCalled()
    form.reset()
  })

  it('keeps the new-email code button disabled until the address is valid', async () => {
    const form = makeForm()
    expect(form.newOtpBtnDisabled.value).toBe(true)

    form.newEmail.value = 'newbox@example.com'
    await form.handleSendNewOtp()

    expect(sendNewOtp).toHaveBeenCalledWith('newbox@example.com')
    expect(form.newOtpCountdown.value).toBeGreaterThan(0)
    expect(form.newOtpBtnDisabled.value).toBe(true)
    expect(form.successMsg.value).toBe('auth.emailChangeNewOtpSent')
    expect(form.errorMsg.value).toBe('')
    form.reset()
    expect(form.newOtpCountdown.value).toBe(0)
  })

  it('sends the current-email code with its own independent countdown', async () => {
    const form = makeForm()

    await form.handleSendCurrentOtp()

    expect(sendCurrentOtp).toHaveBeenCalledTimes(1)
    expect(form.currentOtpCountdown.value).toBeGreaterThan(0)
    expect(form.currentOtpBtnDisabled.value).toBe(true)
    expect(form.successMsg.value).toBe('auth.emailChangeCurrentOtpSent')
    // 两个倒计时互不干扰
    expect(form.newOtpCountdown.value).toBe(0)
    form.reset()
  })

  it('maps a 429 send failure to the rate-limited message without starting the countdown', async () => {
    sendCurrentOtp.mockRejectedValue({ response: { status: 429 } })
    const form = makeForm()

    await form.handleSendCurrentOtp()

    expect(form.errorMsg.value).toBe('auth.rateLimited')
    expect(form.currentOtpCountdown.value).toBe(0)
    expect(form.currentOtpBtnDisabled.value).toBe(false)
  })

  it('rejects an invalid new email on submit without calling submit', async () => {
    const form = makeForm()
    form.newEmail.value = 'nope'
    form.currentCode.value = '111111'
    form.newCode.value = '222222'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.invalidEmail')
    expect(submit).not.toHaveBeenCalled()
  })

  it('rejects malformed codes on submit without calling submit', async () => {
    const form = makeForm()
    form.newEmail.value = 'newbox@example.com'
    form.currentCode.value = '11111'
    form.newCode.value = '222222'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.invalidOtp')
    expect(submit).not.toHaveBeenCalled()
  })

  it('submits both codes, runs onChanged, then marks done and clears countdowns', async () => {
    const projection = { email: 'newbox@example.com', email_verified: true }
    submit.mockResolvedValue(projection)
    const onChanged = vi.fn()
    const form = makeForm(onChanged)
    form.newEmail.value = 'newbox@example.com'
    form.currentCode.value = '111111'
    form.newCode.value = '222222'
    await form.handleSendCurrentOtp()
    await form.handleSendNewOtp()

    await form.handleSubmit()

    expect(submit).toHaveBeenCalledWith('newbox@example.com', '111111', '222222')
    expect(onChanged).toHaveBeenCalledTimes(1)
    expect(onChanged).toHaveBeenCalledWith(projection)
    expect(form.changeDone.value).toBe(true)
    expect(form.successMsg.value).toBe('auth.emailChangeSuccess')
    expect(form.errorMsg.value).toBe('')
    expect(form.loading.value).toBe(false)
    expect(form.currentOtpCountdown.value).toBe(0)
    expect(form.newOtpCountdown.value).toBe(0)
  })

  it('maps a 429 confirm failure to the rate-limited message', async () => {
    submit.mockRejectedValue({ response: { status: 429 } })
    const form = makeForm()
    form.newEmail.value = 'newbox@example.com'
    form.currentCode.value = '111111'
    form.newCode.value = '222222'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.rateLimited')
    expect(form.changeDone.value).toBe(false)
    expect(form.loading.value).toBe(false)
  })

  it('surfaces the backend detail message for other confirm failures', async () => {
    submit.mockRejectedValue({ response: { status: 409, data: { detail: '换绑失败，请更换邮箱后重试' } } })
    const form = makeForm()
    form.newEmail.value = 'newbox@example.com'
    form.currentCode.value = '111111'
    form.newCode.value = '222222'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('换绑失败，请更换邮箱后重试')
    expect(form.changeDone.value).toBe(false)
  })

  it('falls back to the generic failure message without details', async () => {
    submit.mockRejectedValue({})
    const form = makeForm()
    form.newEmail.value = 'newbox@example.com'
    form.currentCode.value = '111111'
    form.newCode.value = '222222'

    await form.handleSubmit()

    expect(form.errorMsg.value).toBe('auth.emailChangeFailed')
  })

  it('reset clears all form state including both countdowns', async () => {
    const form = makeForm()
    form.newEmail.value = 'newbox@example.com'
    form.currentCode.value = '111111'
    form.newCode.value = '222222'
    await form.handleSendCurrentOtp()
    await form.handleSendNewOtp()
    await form.handleSubmit()
    expect(form.changeDone.value).toBe(true)

    form.reset()

    expect(form.newEmail.value).toBe('')
    expect(form.currentCode.value).toBe('')
    expect(form.newCode.value).toBe('')
    expect(form.errorMsg.value).toBe('')
    expect(form.successMsg.value).toBe('')
    expect(form.changeDone.value).toBe(false)
    expect(form.loading.value).toBe(false)
    expect(form.currentOtpLoading.value).toBe(false)
    expect(form.newOtpLoading.value).toBe(false)
    expect(form.currentOtpCountdown.value).toBe(0)
    expect(form.newOtpCountdown.value).toBe(0)
  })
})
