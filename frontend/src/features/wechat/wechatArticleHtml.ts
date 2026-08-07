/**
 * 公众号正文渲染辅助：DOMPurify 白名单清洗 + mmbiz 图片代理改写。
 *
 * 服务端在入库时已做一道清洗（wechat_sogou.parser.extract_article_content），
 * 这里是渲染前的第二道防线。正文图片经 /api/media/wechat/proxy 同源代理
 * （mmbiz 防盗链要求 mp 域 Referer，由服务端回源携带）。
 */
import DOMPurify from 'dompurify'

const WECHAT_MEDIA_PROXY_PATH = '/api/media/wechat/proxy'
const WECHAT_MEDIA_HOSTS = new Set(['mmbiz.qpic.cn', 'mmbiz.qlogo.cn'])

/**
 * mmbiz 图片 URL 改写为服务端代理地址；非 mmbiz 或非法 URL 原样透传
 * （后端代理另有主机白名单校验，此处只做渲染层改写）。
 *
 * 后端代理只接受 https 目标；mmbiz 同一资源 https 可用，故统一升级
 * scheme，顺带覆盖 http:// 头像（避免 https 页面混合内容）与 // 协议
 * 相对封面两种来源形态。
 */
export const proxiedWechatImageUrl = (url: string): string => {
  try {
    const parsed = new URL(url, window.location.origin)
    if (!WECHAT_MEDIA_HOSTS.has(parsed.hostname)) return url
    const secure = `https://${parsed.host}${parsed.pathname}${parsed.search}`
    return `${WECHAT_MEDIA_PROXY_PATH}?url=${encodeURIComponent(secure)}`
  } catch {
    return url
  }
}

// 与服务端入库清洗的标签白名单保持一致（公众号排版结构）。
const ALLOWED_TAGS = [
  'section', 'span', 'p', 'div', 'br', 'hr',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'strong', 'b', 'em', 'i', 'u', 's', 'blockquote',
  'ul', 'ol', 'li', 'a', 'img', 'figure', 'figcaption',
  'table', 'thead', 'tbody', 'tr', 'td', 'th', 'caption',
  'code', 'pre', 'sup', 'sub',
]

/** 清洗公众号正文 HTML：白名单标签、允许排版 style、图片走代理。 */
export const sanitizeWechatArticleHtml = (html: string): string => {
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'style', 'target', 'rel', 'colspan', 'rowspan'],
    FORBID_TAGS: ['form', 'iframe', 'object', 'embed', 'svg', 'audio', 'video'],
    ALLOW_DATA_ATTR: false,
    FORBID_ATTR: ['formaction'],
  })
  // 图片代理改写放在 DOMPurify 之后的游离节点上做，避免注册全局 hook
  // 影响 useLatexRenderer 等其他 sanitize 调用方。
  const template = document.createElement('template')
  template.innerHTML = clean
  template.content.querySelectorAll('img').forEach((img) => {
    const src = img.getAttribute('src') ?? ''
    if (src) img.setAttribute('src', proxiedWechatImageUrl(src))
    img.setAttribute('loading', 'lazy')
    img.setAttribute('referrerpolicy', 'no-referrer')
  })
  return template.innerHTML
}
