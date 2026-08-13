import { beforeAll, describe, expect, it } from 'vitest'
import { renderMarkdown, renderPlainMarkdown } from './useLatexRenderer'

beforeAll(() => {
  document.write('<!doctype html><html><body></body></html>')
  document.close()
})

describe('renderMarkdown', () => {
  it('preserves the published Markdown formatting behavior', () => {
    const html = renderMarkdown('第一行\n第二行\n\n[链接](https://example.com)')

    expect(html).toContain('第一行<br>\n第二行')
    expect(html).toContain('<a href="https://example.com">链接</a>')
  })

  it('preserves fenced code blocks', () => {
    const html = renderMarkdown('```ts\nconst value = 1\n```')

    expect(html).toContain('<code class="language-ts">')
    expect(html).toContain('const value = 1')
  })

  it('renders inline and display formulas with KaTeX', () => {
    const html = renderMarkdown('行内 $x^2$\n\n$$\\frac{1}{2}$$')

    expect(html).toContain('class="katex"')
    expect(html).toContain('class="formula-wrap"')
    expect(html).toContain('class="formula-copy-btn"')
    expect(html).toContain('data-latex="\\frac{1}{2}"')
  })

  it('escapes formula source embedded in copy-button attributes', () => {
    const html = renderMarkdown('$$x & < y$$')

    expect(html).toContain('data-latex="x &amp; < y"')
    expect(html).not.toContain('data-latex="x & < y"')
  })

  it.each([
    '<script>alert(1)</script>',
    '<img src="x" onerror="alert(1)">',
    '<iframe src="https://example.com"></iframe>',
    '<svg onload="alert(1)"><circle /></svg>',
  ])('removes active HTML from untrusted Markdown: %s', payload => {
    const html = renderMarkdown(payload)

    expect(html).not.toMatch(/<(?:script|iframe)\b/i)
    expect(html).not.toMatch(/\son\w+=/i)
  })

  it('removes dangerous link schemes while preserving safe links', () => {
    const html = renderMarkdown('[危险](javascript:alert(1)) [安全](https://example.com)')

    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('href="https://example.com"')
  })

  it('keeps KaTeX and formula-copy markup after sanitization', () => {
    const html = renderMarkdown('$$\\frac{1}{2}$$\n\n<img src="x" onerror="alert(1)">')

    expect(html).toContain('class="katex"')
    expect(html).toContain('class="formula-copy-btn"')
    expect(html).toContain('data-latex="\\frac{1}{2}"')
    expect(html).not.toContain('onerror')
  })
})

describe('renderPlainMarkdown', () => {
  it('renders links and emphasis without a KaTeX pass', () => {
    const html = renderPlainMarkdown('**加粗** [链接](https://example.com)\n\n$x^2$')

    expect(html).toContain('<strong>加粗</strong>')
    expect(html).toContain('<a href="https://example.com">链接</a>')
    // 纯 Markdown 通道不做 KaTeX 渲染，公式语法按普通文本保留
    expect(html).not.toContain('class="katex"')
    expect(html).toContain('$x^2$')
  })

  it.each([
    '<script>alert(1)</script>',
    '<img src="x" onerror="alert(1)">',
    '<iframe src="https://example.com"></iframe>',
    '<svg onload="alert(1)"><circle /></svg>',
  ])('removes active HTML from untrusted Markdown: %s', payload => {
    const html = renderPlainMarkdown(payload)

    expect(html).not.toMatch(/<(?:script|iframe)\b/i)
    expect(html).not.toMatch(/\son\w+=/i)
  })

  it('removes dangerous link schemes while preserving safe links', () => {
    const html = renderPlainMarkdown('[危险](javascript:alert(1)) [安全](https://example.com)')

    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('href="https://example.com"')
  })

  it('renders empty input to an empty string', () => {
    expect(renderPlainMarkdown('')).toBe('')
  })
})
