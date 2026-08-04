/// <reference types="node" />
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

/**
 * nginx.conf 的 CSP 对 index.html 内联引导脚本使用 sha256 白名单。
 * 改动 index.html 的内联脚本而不同步哈希会让生产页面直接失去主题引导，
 * 本测试强制两者一致；同时锁定 CSP 处于 enforce 态、HSTS 已启用。
 */

// vitest 从 frontend 根目录运行（npm scripts 与 CI 一致）。
const frontendRoot = process.cwd()

const indexHtml = readFileSync(`${frontendRoot}/index.html`, 'utf-8')
const nginxConf = readFileSync(`${frontendRoot}/nginx.conf`, 'utf-8')

function extractInlineScriptBodies(html: string): string[] {
  // 仅匹配无属性的 <script>（CSP 只约束内联脚本；带 src 的模块脚本不受哈希约束）。
  return [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1] ?? '')
}

function extractCspHeaderValue(conf: string): string {
  const match = conf.match(/add_header\s+Content-Security-Policy\s+"([^"]+)"/)
  if (!match) throw new Error('nginx.conf 缺少 enforce 态 Content-Security-Policy 响应头')
  return match[1] ?? ''
}

function sha256Base64(text: string): string {
  return `sha256-${createHash('sha256').update(text, 'utf-8').digest('base64')}`
}

describe('CSP 安全响应头契约', () => {
  it('CSP 为 enforce 态且不再使用 Report-Only', () => {
    expect(nginxConf).not.toMatch(/add_header\s+Content-Security-Policy-Report-Only/)
    expect(extractCspHeaderValue(nginxConf)).toContain("default-src 'self'")
  })

  it('HSTS 已启用', () => {
    expect(nginxConf).toMatch(/^[^#]*add_header\s+Strict-Transport-Security\s+"max-age=/m)
  })

  it('index.html 每个内联脚本都在 script-src 哈希白名单中', () => {
    const bodies = extractInlineScriptBodies(indexHtml)
    expect(bodies.length).toBeGreaterThan(0)
    const csp = extractCspHeaderValue(nginxConf)
    for (const body of bodies) {
      expect(csp).toContain(`'${sha256Base64(body)}'`)
    }
  })

  it('字体已自托管，CSP 不再放行外部字体源', () => {
    const csp = extractCspHeaderValue(nginxConf)
    expect(csp).not.toContain('fonts.googleapis.com')
    expect(csp).not.toContain('fonts.gstatic.com')
  })
})
