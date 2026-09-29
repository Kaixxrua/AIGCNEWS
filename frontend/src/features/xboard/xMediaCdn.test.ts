import { afterEach, describe, expect, it, vi } from 'vitest'
import { proxiedMediaUrl } from './xBoardViewModel'
import { installXMediaCdnFallback, sameOriginMediaFallback, X_MEDIA_CDN_ORIGIN, xMediaOrigin } from './xMediaCdn'

const CDN = 'https://media.aigcnews.cn'

describe('X_MEDIA_CDN_ORIGIN', () => {
  it('is switched on to the media domain by default', () => {
    expect(X_MEDIA_CDN_ORIGIN).toBe(CDN)
    expect(xMediaOrigin('pbs.twimg.com', 'aigcnews.cn')).toBe(CDN)
    expect(xMediaOrigin('pbs.twimg.com', 'aigcradar.online')).toBe('')
    expect(sameOriginMediaFallback(`${CDN}/api/media/x/img/pbs.twimg.com/media/a.jpg?name=small`))
      .toBe('/api/media/x/img/pbs.twimg.com/media/a.jpg?name=small')
  })
})
const PHOTO = 'https://pbs.twimg.com/media/G1a2b3c.jpg?format=jpg&name=4096x4096'
const PHOTO_PATH = '/api/media/x/img/pbs.twimg.com/media/G1a2b3c.jpg?format=jpg&name=4096x4096'

describe('xMediaOrigin', () => {
  it('routes pbs images through the CDN only on the primary entry', () => {
    expect(xMediaOrigin('pbs.twimg.com', 'aigcnews.cn', CDN)).toBe(CDN)
    expect(xMediaOrigin('pbs.twimg.com', 'www.aigcnews.cn', CDN)).toBe(CDN)
    // 备用入口与本地开发保持同源
    expect(xMediaOrigin('pbs.twimg.com', 'aigcradar.online', CDN)).toBe('')
    expect(xMediaOrigin('pbs.twimg.com', 'localhost', CDN)).toBe('')
  })

  it('keeps video streams and other twimg hosts same-origin', () => {
    expect(xMediaOrigin('video.twimg.com', 'aigcnews.cn', CDN)).toBe('')
    expect(xMediaOrigin('abs.twimg.com', 'aigcnews.cn', CDN)).toBe('')
  })

  it('is off when no CDN origin is configured', () => {
    expect(xMediaOrigin('pbs.twimg.com', 'aigcnews.cn', '')).toBe('')
  })

  it('keeps the proxied path byte-identical so edge cache and prewarm keys match', () => {
    // jsdom 页面主机不是主入口：proxiedMediaUrl 仍产出同源路径，CDN 形态只加源前缀
    expect(proxiedMediaUrl(PHOTO)).toBe(PHOTO_PATH)
    expect(`${xMediaOrigin('pbs.twimg.com', 'aigcnews.cn', CDN)}${proxiedMediaUrl(PHOTO)}`).toBe(`${CDN}${PHOTO_PATH}`)
  })
})

describe('sameOriginMediaFallback', () => {
  it('strips the CDN origin from CDN media urls', () => {
    expect(sameOriginMediaFallback(`${CDN}${PHOTO_PATH}`, CDN)).toBe(PHOTO_PATH)
  })

  it('ignores anything that is not a CDN image url', () => {
    expect(sameOriginMediaFallback(PHOTO_PATH, CDN)).toBeNull()
    expect(sameOriginMediaFallback(`http://localhost${PHOTO_PATH}`, CDN)).toBeNull()
    expect(sameOriginMediaFallback(`${CDN}/api/media/x/poster?url=x`, CDN)).toBeNull()
    expect(sameOriginMediaFallback(`${CDN}.evil.example${PHOTO_PATH}`, CDN)).toBeNull()
    expect(sameOriginMediaFallback(`${CDN}${PHOTO_PATH}`, '')).toBeNull()
  })
})

describe('installXMediaCdnFallback', () => {
  const images: HTMLImageElement[] = []
  const mountImage = (src: string) => {
    const img = document.createElement('img')
    img.setAttribute('src', src)
    const componentOnError = vi.fn()
    img.addEventListener('error', componentOnError)
    document.body.appendChild(img)
    images.push(img)
    return { img, componentOnError }
  }

  afterEach(() => {
    images.splice(0).forEach((img) => img.remove())
  })

  it('retries a failed CDN image same-origin before the component sees the error', () => {
    installXMediaCdnFallback(document, CDN)
    const { img, componentOnError } = mountImage(`${CDN}${PHOTO_PATH}`)

    img.dispatchEvent(new Event('error'))
    expect(img.getAttribute('src')).toBe(PHOTO_PATH)
    expect(componentOnError).not.toHaveBeenCalled()

    // 同源重试也失败：不再改写，交给组件自己的 @error
    img.dispatchEvent(new Event('error'))
    expect(img.getAttribute('src')).toBe(PHOTO_PATH)
    expect(componentOnError).toHaveBeenCalledOnce()
  })

  it('leaves non-CDN image errors to the component', () => {
    installXMediaCdnFallback(document, CDN)
    const { img, componentOnError } = mountImage('/api/media/site/logo.png')

    img.dispatchEvent(new Event('error'))
    expect(img.getAttribute('src')).toBe('/api/media/site/logo.png')
    expect(componentOnError).toHaveBeenCalledOnce()
  })
})
