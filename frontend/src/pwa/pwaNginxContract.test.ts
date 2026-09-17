/// <reference types="node" />
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

/**
 * PWA 与 nginx 缓存头的契约：
 * - sw.js 必须 no-cache——SW 更新检查依赖字节级比对，被缓存会导致新版本
 *   永远不被发现；
 * - manifest.webmanifest 必须 no-cache——安装元数据随版本更新；
 * - index.html 必须 no-cache——SPA fallback 经 try_files 内部重定向命中
 *   location = /index.html，入口文档被缓存会让预缓存外壳永远发旧版；
 * - /assets/ 仍保持 immutable（防回归）；
 * - vite.config.ts 中 /api 与 /camp-scene 走 navigateFallbackDenylist，
 *   场景目录不进预缓存，且不配 runtimeCaching。
 */

// vitest 从 frontend 根目录运行（npm scripts 与 CI 一致）。
const frontendRoot = process.cwd()

const nginxConf = readFileSync(`${frontendRoot}/nginx.conf`, 'utf-8')
const viteConfig = readFileSync(`${frontendRoot}/vite.config.ts`, 'utf-8')
// 剥离注释后的代码视图：配置项断言只看真实代码，注释中提及不算命中。
const viteConfigCode = viteConfig
  .split(/\r?\n/)
  .filter(line => !line.trimStart().startsWith('//'))
  .join('\n')

// 提取精确匹配 location 块（location = /path { ... }）的花括号体。
function extractExactLocationBody(conf: string, path: string): string {
  const escaped = path.replace(/[/.]/g, '\\$&')
  const match = conf.match(new RegExp(`location = ${escaped}\\s*\\{([^}]*)\\}`))
  if (!match) throw new Error(`nginx.conf 缺少 location = ${path} 块`)
  return match[1] ?? ''
}

describe('PWA 缓存头契约', () => {
  it('location = /sw.js 存在且 Cache-Control 为 no-cache', () => {
    const body = extractExactLocationBody(nginxConf, '/sw.js')
    expect(body).toMatch(/add_header\s+Cache-Control\s+"no-cache"/)
  })

  it('location = /manifest.webmanifest 存在且 Cache-Control 为 no-cache', () => {
    const body = extractExactLocationBody(nginxConf, '/manifest.webmanifest')
    expect(body).toMatch(/add_header\s+Cache-Control\s+"no-cache"/)
  })

  it('location = /index.html 存在且 Cache-Control 为 no-cache', () => {
    const body = extractExactLocationBody(nginxConf, '/index.html')
    expect(body).toMatch(/add_header\s+Cache-Control\s+"no-cache"/)
  })

  it('PWA 三个 location 块均重复声明安全头（add_header 块不继承 server 级）', () => {
    for (const path of ['/sw.js', '/manifest.webmanifest', '/index.html']) {
      const body = extractExactLocationBody(nginxConf, path)
      expect(body).toContain('X-Content-Type-Options')
      expect(body).toContain('X-Frame-Options')
      expect(body).toContain('Referrer-Policy')
    }
  })

  it('location = /index.html 重复声明 CSP 与 HSTS，且与 server 级逐字一致', () => {
    // 本块自带 add_header 后 nginx 不再继承 server 级响应头；index.html 是
    // 文档本体，CSP 只挂在文档响应上才生效。改 server 级 CSP（如轮换内联
    // 脚本 sha256）必须同步本块，否则入口文档失去 CSP 保护。
    const body = extractExactLocationBody(nginxConf, '/index.html')
    const extract = (conf: string, name: string) => {
      const match = conf.match(new RegExp(`add_header\\s+${name}\\s+"([^"]+)"`))
      if (!match) throw new Error(`缺少 ${name} 响应头`)
      return match[1] ?? ''
    }
    expect(body).toContain('Strict-Transport-Security')
    expect(extract(body, 'Content-Security-Policy')).toBe(
      extract(nginxConf, 'Content-Security-Policy'),
    )
  })

  it('/assets/ 仍为 immutable 长缓存（防回归）', () => {
    expect(nginxConf).toMatch(/location \/assets\/\s*\{[^}]*Cache-Control\s+"public, immutable"/)
  })

  it('vite.config.ts：导航回退 denylist 排除 /api，API 一律不经 SW', () => {
    expect(viteConfigCode).toMatch(/navigateFallbackDenylist:\s*\[[^\]]*\/api/)
  })

  it('vite.config.ts：Godot 场景不走 SPA 导航回退，也不进入 PWA 预缓存', () => {
    expect(viteConfigCode).toMatch(/navigateFallbackDenylist:\s*\[[^\]]*\/camp-scene/)
    expect(viteConfigCode).toMatch(/globIgnores:\s*\[[^\]]*camp-scene/)
  })

  it('vite.config.ts：不配 runtimeCaching（SSE/JWT 不被 SW 拦截缓存）', () => {
    expect(viteConfigCode).not.toContain('runtimeCaching')
  })

  it('vite.config.ts：手动注册（injectRegister: false），不注入 index.html', () => {
    // CSP 对内联脚本有 sha256 白名单契约，任何注入都会破坏它。
    expect(viteConfigCode).toMatch(/injectRegister:\s*false/)
  })
})
