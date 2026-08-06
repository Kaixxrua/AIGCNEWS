import { describe, expect, it } from 'vitest'
import {
  proxiedWechatImageUrl,
  sanitizeWechatArticleHtml,
} from '@/features/wechat/wechatArticleHtml'

describe('proxiedWechatImageUrl', () => {
  it('rewrites mmbiz image urls through the server proxy', () => {
    const url = 'https://mmbiz.qpic.cn/mmbiz_png/abc/640?wx_fmt=png'
    expect(proxiedWechatImageUrl(url)).toBe(
      `/api/media/wechat/proxy?url=${encodeURIComponent(url)}`,
    )
  })

  it('rewrites qlogo avatar urls as well', () => {
    const url = 'https://mmbiz.qlogo.cn/mmbiz/abc/0'
    expect(proxiedWechatImageUrl(url)).toBe(
      `/api/media/wechat/proxy?url=${encodeURIComponent(url)}`,
    )
  })

  it('passes through non-wechat hosts untouched', () => {
    const url = 'https://example.com/a.png'
    expect(proxiedWechatImageUrl(url)).toBe(url)
  })

  it('passes through invalid urls untouched', () => {
    expect(proxiedWechatImageUrl('not a url ::::')).toBe('not a url ::::')
  })
})

describe('sanitizeWechatArticleHtml', () => {
  it('strips script tags but keeps layout markup', () => {
    const html = '<section><p>正文</p><script>alert(1)</script></section>'
    const clean = sanitizeWechatArticleHtml(html)
    expect(clean).toContain('<p>正文</p>')
    expect(clean).not.toContain('script')
    expect(clean).not.toContain('alert')
  })

  it('rewrites mmbiz img src through the proxy and marks lazy loading', () => {
    const url = 'https://mmbiz.qpic.cn/mmbiz_png/abc/640?wx_fmt=png'
    const clean = sanitizeWechatArticleHtml(`<p><img src="${url}" alt="图"></p>`)
    expect(clean).toContain(
      `src="/api/media/wechat/proxy?url=${encodeURIComponent(url)}"`,
    )
    expect(clean).toContain('loading="lazy"')
    expect(clean).toContain('referrerpolicy="no-referrer"')
    expect(clean).toContain('alt="图"')
  })

  it('keeps non-mmbiz image src untouched but still lazy-marks it', () => {
    const clean = sanitizeWechatArticleHtml('<img src="https://cdn.example.com/a.png">')
    expect(clean).toContain('src="https://cdn.example.com/a.png"')
    expect(clean).toContain('loading="lazy"')
  })

  it('drops javascript: hrefs while keeping https links', () => {
    const clean = sanitizeWechatArticleHtml(
      '<p><a href="javascript:alert(1)">坏</a><a href="https://example.com">好</a></p>',
    )
    expect(clean).not.toContain('javascript:')
    expect(clean).toContain('href="https://example.com"')
  })

  it('forbids active content tags', () => {
    const clean = sanitizeWechatArticleHtml(
      '<div><iframe src="https://evil.example"></iframe><svg><circle></circle></svg><p>留存</p></div>',
    )
    expect(clean).toContain('<p>留存</p>')
    expect(clean).not.toContain('iframe')
    expect(clean).not.toContain('<svg')
  })

  it('keeps inline style for typography', () => {
    const clean = sanitizeWechatArticleHtml(
      '<span style="color: rgb(255, 0, 0); font-size: 16px;">红字</span>',
    )
    expect(clean).toContain('style=')
    expect(clean).toContain('红字')
  })

  it('removes event handler attributes', () => {
    const clean = sanitizeWechatArticleHtml('<p onclick="alert(1)">点我</p>')
    expect(clean).not.toContain('onclick')
    expect(clean).toContain('点我')
  })
})
