/// <reference types="node" />
import { readFileSync, statSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// vitest 从 frontend 根目录运行（与 cspHashContract.test.ts 相同）。
const frontendRoot = process.cwd()

/**
 * 与发布脚本 deploy.py 的产物校验同一条规则：index.html 里 a/link 的 href、
 * img/script/source/video/audio 的 src，凡是站内地址（/api/ 除外）都必须是产物里的文件。
 * /report 这类路由不是文件，写进去会让边缘发布失败（2026-10-05 noscript 栏目链接）。
 */
const REFERENCE_ATTRIBUTE: Record<string, string> = {
  a: 'href', link: 'href', img: 'src', script: 'src', source: 'src', video: 'src', audio: 'src',
}

function siteReferences(html: string): string[] {
  const references: string[] = []
  for (const [, tag, attributes] of html.replace(/<!--[\s\S]*?-->/g, '').matchAll(/<([a-z]+)\b([^>]*)>/gi)) {
    const attribute = REFERENCE_ATTRIBUTE[tag!.toLowerCase()]
    const value = attribute && new RegExp(`\\s${attribute}="([^"]+)"`, 'i').exec(attributes!)?.[1]
    if (!value || /^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith('//') || value.startsWith('#')) continue
    references.push(value)
  }
  return references
}

describe('index.html', () => {
  it('references only files the build ships, so the edge publish accepts it', () => {
    const references = siteReferences(readFileSync(`${frontendRoot}/index.html`, 'utf-8'))
    expect(references).toContain('/favicon.ico')

    const unshipped = references.filter((reference) => {
      const path = decodeURIComponent(reference.split(/[?#]/)[0]!)
      // 构建会把入口脚本换成 /assets/ 下的产物。
      if (path.startsWith('/api/') || path === '/src/main.ts') return false
      return !statSync(`${frontendRoot}/public${path}`, { throwIfNoEntry: false })?.isFile()
    })
    expect(unshipped).toEqual([])
  })
})
