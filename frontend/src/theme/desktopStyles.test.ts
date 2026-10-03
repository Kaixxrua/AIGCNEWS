import { afterEach, describe, expect, it } from 'vitest'
import { DESKTOP_STYLES_MEDIA, installDesktopStyles } from './desktopStyles'

const HREF = '/assets/comic-pages-test.css'

/** 可以手动切换的媒体查询：jsdom 没有 matchMedia。 */
function fakeWindow(matches: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>()
  const query = {
    matches,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
  }
  const win = { document, matchMedia: (media: string) => (media === DESKTOP_STYLES_MEDIA ? query : null) } as unknown as Window
  const resize = (next: boolean) => {
    query.matches = next
    for (const listener of [...listeners]) listener({ matches: next } as MediaQueryListEvent)
  }
  return { win, resize, listeners }
}

const comicSheets = () => [...document.head.querySelectorAll<HTMLLinkElement>(`link[rel="stylesheet"][href="${HREF}"]`)]

/** 判断 Promise 此刻是否已经兑现。 */
async function isSettled(promise: Promise<void>): Promise<boolean> {
  let settled = false
  void promise.then(() => { settled = true })
  await Promise.resolve()
  await Promise.resolve()
  return settled
}

afterEach(() => {
  document.head.innerHTML = ''
})

describe('desktop styles', () => {
  it('puts the sheet right after the entry stylesheet on desktop and waits for it before mounting', async () => {
    document.head.innerHTML = '<meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/assets/index-a.css"><link rel="modulepreload" href="/assets/x.js">'
    const ready = installDesktopStyles(HREF, fakeWindow(true).win)

    const sheet = comicSheets()[0]!
    expect(sheet.previousElementSibling?.getAttribute('href')).toBe('/assets/index-a.css')
    expect(await isSettled(ready)).toBe(false)

    sheet.dispatchEvent(new Event('load'))
    expect(await isSettled(ready)).toBe(true)
  })

  it('still lets the app mount when the sheet fails to load', async () => {
    const ready = installDesktopStyles(HREF, fakeWindow(true).win)
    comicSheets()[0]!.dispatchEvent(new Event('error'))
    expect(await isSettled(ready)).toBe(true)
  })

  it('downloads nothing below desktop width until the window widens, then adds the sheet once', async () => {
    const { win, resize, listeners } = fakeWindow(false)
    const ready = installDesktopStyles(HREF, win)

    expect(await isSettled(ready)).toBe(true)
    expect(comicSheets()).toHaveLength(0)

    resize(false)
    expect(comicSheets()).toHaveLength(0)
    resize(true)
    resize(false)
    resize(true)
    expect(comicSheets()).toHaveLength(1)
    expect(listeners.size).toBe(0)
  })

  it('widened later, still goes right after the entry stylesheet, ahead of the page stylesheets loaded meanwhile', () => {
    document.head.innerHTML = '<link rel="stylesheet" href="/assets/index-a.css">'
    const { win, resize } = fakeWindow(false)
    void installDesktopStyles(HREF, win)
    document.head.insertAdjacentHTML('beforeend', '<link rel="stylesheet" href="/assets/GitHubProjectsView-b.css">')

    resize(true)
    const sheet = comicSheets()[0]!
    expect(sheet.previousElementSibling?.getAttribute('href')).toBe('/assets/index-a.css')
    expect(sheet.nextElementSibling?.getAttribute('href')).toBe('/assets/GitHubProjectsView-b.css')
  })

  it('in development, where the entry styles are <style> elements, goes after the last of them', () => {
    document.head.innerHTML = '<style id="style-css"></style><style id="motion-css"></style>'
    const { win, resize } = fakeWindow(false)
    void installDesktopStyles(HREF, win)
    document.head.insertAdjacentHTML('beforeend', '<style id="page-css"></style>')

    resize(true)
    expect(comicSheets()[0]!.previousElementSibling?.id).toBe('motion-css')
  })
})
