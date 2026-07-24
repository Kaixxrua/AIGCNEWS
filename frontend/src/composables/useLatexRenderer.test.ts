import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './useLatexRenderer'

describe('renderMarkdown', () => {
  it('preserves the published Markdown formatting behavior', () => {
    const html = renderMarkdown('第一行\n第二行\n\n[链接](https://example.com)')

    expect(html).toContain('第一行<br>\n第二行')
    expect(html).toContain('<a href="https://example.com">链接</a>')
  })

  it('preserves fenced code blocks', () => {
    const html = renderMarkdown('```ts\nconst value = 1\n```')

    expect(html).toContain('<pre><code class="language-ts">')
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

    expect(html).toContain('data-latex="x &amp; &lt; y"')
    expect(html).not.toContain('data-latex="x & < y"')
  })
})
