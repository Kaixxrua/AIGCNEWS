import { beforeEach, describe, expect, it } from 'vitest'
import { useLoginPrompt } from './useLoginPrompt'

beforeEach(() => {
  const prompt = useLoginPrompt()
  prompt.closeLoginPrompt()
  prompt.consumeLoginRedirect()
})

describe('useLoginPrompt', () => {
  it('shares open state and safe redirect across consumers', () => {
    const first = useLoginPrompt()
    const second = useLoginPrompt()
    first.requestLogin('/dsh?step=identity')
    expect(second.isOpen.value).toBe(true)
    expect(second.redirectTarget.value).toBe('/dsh?step=identity')
    second.closeLoginPrompt()
    expect(first.isOpen.value).toBe(false)
  })

  it('rejects external redirects and consumes a redirect once', () => {
    const prompt = useLoginPrompt()
    prompt.requestLogin('//evil.example/path')
    expect(prompt.redirectTarget.value).toBe('/')
    expect(prompt.consumeLoginRedirect()).toBe('/')
    prompt.requestLogin('/mcp')
    expect(prompt.consumeLoginRedirect()).toBe('/mcp')
    expect(prompt.redirectTarget.value).toBe('/')
  })

  it('supports writable v-model state', () => {
    const prompt = useLoginPrompt()
    prompt.requestLogin('/chat')
    prompt.isOpen.value = false
    expect(prompt.isOpen.value).toBe(false)
    expect(prompt.redirectTarget.value).toBe('/chat')
  })
})
