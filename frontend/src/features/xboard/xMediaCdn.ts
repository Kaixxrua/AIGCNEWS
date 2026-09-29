import { isPrimaryEntryHost } from '@/services/http/fallbackEntry'

export const X_MEDIA_IMG_PATH = '/api/media/x/img'

/**
 * X 图片媒体域名（腾讯云 CDN）：GeoDNS 境内 CNAME 到 CDN、境外落日本边缘，
 * 回源两边缘的同一 nginx 媒体缓存。空串表示关闭，全部同源。
 * - 只收 pbs.twimg.com（推文照片、视频封面、头像）；video.twimg.com 播放流
 *   体积大且走 Range，留在同源。
 * - 只在主入口启用：备用入口 aigcradar.online 是主域不可达时的逃生口，媒体
 *   跟主域一起挂就失去意义；本地开发与预览同理保持同源。
 * - CDN 加载失败由 installXMediaCdnFallback 退回同源重试一次。
 */
export const X_MEDIA_CDN_ORIGIN = ''
const X_MEDIA_CDN_HOSTS = new Set(['pbs.twimg.com'])

export const pageHostname = (): string => (typeof window === 'undefined' ? '' : window.location.hostname)

/** 媒体 URL 的源前缀：命中 CDN 条件返回 CDN 源，否则 ''（同源相对路径）。 */
export const xMediaOrigin = (twimgHost: string, hostname: string, cdnOrigin: string = X_MEDIA_CDN_ORIGIN): string => (
  cdnOrigin && X_MEDIA_CDN_HOSTS.has(twimgHost) && isPrimaryEntryHost(hostname) ? cdnOrigin : ''
)

/** CDN 形态的媒体 URL 还原为同源路径；非 CDN 媒体 URL 返回 null。 */
export const sameOriginMediaFallback = (url: string, cdnOrigin: string = X_MEDIA_CDN_ORIGIN): string | null => {
  if (!cdnOrigin || !url.startsWith(`${cdnOrigin}${X_MEDIA_IMG_PATH}/`)) return null
  return url.slice(cdnOrigin.length)
}

/**
 * CDN 图片加载失败时退回同源重试一次。捕获阶段在 document 上拦截，
 * 先于组件自身的 @error（隐藏图片、换占位）执行并截断本次事件；
 * 同源重试再失败时 URL 已不是 CDN 形态，事件照常交给组件处理。
 */
export const installXMediaCdnFallback = (root: Document = document, cdnOrigin: string = X_MEDIA_CDN_ORIGIN): void => {
  if (!cdnOrigin) return
  root.addEventListener('error', (event) => {
    const target = event.target
    if (!(target instanceof HTMLImageElement)) return
    const fallback = sameOriginMediaFallback(target.currentSrc || target.src, cdnOrigin)
    if (!fallback) return
    event.stopImmediatePropagation()
    target.src = fallback
  }, true)
}
