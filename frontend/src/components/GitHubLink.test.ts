import { createApp, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import GitHubLink from './GitHubLink.vue'
import i18n, { setAppLocale } from '@/i18n'

let unmount: (() => void) | undefined

describe('GitHubLink', () => {
  beforeEach(() => {
    localStorage.clear()
    setAppLocale('zh-CN')
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  it('links to the GitHub repository in a new tab', () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(GitHubLink)
    app.use(i18n)
    app.mount(host)
    unmount = () => { app.unmount(); host.remove() }

    const link = host.querySelector('a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('https://github.com/Kaixxrua/AIGC_NEWS')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
    expect(link.getAttribute('aria-label')).toBe('GitHub 仓库')
    expect(link.querySelector('svg')).not.toBeNull()
  })

  it('localizes the label with the active catalog', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(GitHubLink)
    app.use(i18n)
    app.mount(host)
    unmount = () => { app.unmount(); host.remove() }

    const link = host.querySelector('a') as HTMLAnchorElement
    setAppLocale('en-US')
    await nextTick()
    expect(link.getAttribute('aria-label')).toBe('GitHub repository')
  })
})
