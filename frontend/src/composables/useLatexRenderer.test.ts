import { beforeAll, describe, expect, it } from 'vitest'
import { normalizeEmphasisFlanking, renderMarkdown, renderPlainMarkdown } from './useLatexRenderer'

beforeAll(() => {
  document.write('<!doctype html><html><body></body></html>')
  document.close()
})

describe('normalizeEmphasisFlanking', () => {
  it('inserts a space after a closing ** followed by a letter/CJK run', () => {
    expect(normalizeEmphasisFlanking('**要点：**正文')).toBe('**要点：** 正文')
    expect(normalizeEmphasisFlanking('**要点：**OpenART')).toBe('**要点：** OpenART')
  })

  it('is idempotent', () => {
    const once = normalizeEmphasisFlanking('**要点：**正文')

    expect(normalizeEmphasisFlanking(once)).toBe(once)
  })

  it('leaves already-valid pairs and punctuation-followed closings untouched', () => {
    expect(normalizeEmphasisFlanking('**标题**（注）')).toBe('**标题**（注）')
    expect(normalizeEmphasisFlanking('宣布 **Gemini 3.7 Flash**，并称')).toBe('宣布 **Gemini 3.7 Flash**，并称')
    expect(normalizeEmphasisFlanking('**a**b')).toBe('**a**b')
  })

  it('keeps ** inside code segments untouched', () => {
    expect(normalizeEmphasisFlanking('`a**b**c` 和 **要点：**正文')).toBe('`a**b**c` 和 **要点：** 正文')
  })
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

  it.each([
    '**Agent 安全与研究自动化成为学术热点。**OpenART 试图扩大红队测试规模。',
    '**核心要点：**这类系统需要同时建模环境状态与智能体动作。',
    '**AI 产品竞争集中到速度。**Google 推出新模型。',
  ])('renders bold lead-ins closed before a letter/CJK run: %s', src => {
    const html = renderMarkdown(src)

    expect(html).toContain('<strong>')
    expect(html).not.toContain('**')
  })

  it('does not insert a space when the closing ** is followed by punctuation', () => {
    const html = renderMarkdown('宣布 **Gemini 3.7 Flash**，称其速度翻倍。')

    expect(html).toContain('<strong>Gemini 3.7 Flash</strong>，')
  })

  it('keeps ** inside inline code and fenced code blocks literal', () => {
    const html = renderMarkdown('`a**b**c`\n\n```\nx**y**z\n```')

    expect(html).toContain('<code>a**b**c</code>')
    expect(html).toContain('x**y**z')
  })

  it('does not pair ** across paragraph boundaries', () => {
    const html = renderMarkdown('**未闭合的 opener\n\n**要点：**紧接正文')

    expect(html).toContain('**未闭合的 opener')
    expect(html).toContain('<strong>要点：</strong> 紧接正文')
  })

  it.each([
    ['# 今日热点摘要 `#news` `#LLM`', 'news'],
    ['## 今日热点摘要 `#news` `#LLM`', 'news'],
    ['### 1. 条目 `#arxiv` `#Agent` `#安全对齐`', 'arxiv'],
  ])(
    'hides the leading # of tag code chips inside headings: %s',
    (src, chip) => {
      const html = renderMarkdown(src)

      expect(html).toContain(`<code>${chip}</code>`)
      expect(html).not.toContain('<code>#')
    },
  )

  it('keeps the # of inline code outside headings', () => {
    const html = renderMarkdown('正文里的 `#define` 宏与 `#include` 保留')

    expect(html).toContain('<code>#define</code>')
    expect(html).toContain('<code>#include</code>')
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

  it('preserves site-relative image sources from the upload endpoint', () => {
    const html = renderPlainMarkdown('![群二维码](/api/media/site/abc123.png)')

    // 上传产物是站内相对路径：消毒必须放行（否则联系合作页正文插图全部裂图）
    expect(html).toContain('<img src="/api/media/site/abc123.png"')
    expect(html).toContain('alt="群二维码"')
  })

  it('applies the same CJK bold-closing fix as renderMarkdown', () => {
    const html = renderPlainMarkdown('**注意：**请先看文档')

    expect(html).toContain('<strong>注意：</strong> 请先看文档')
    expect(html).not.toContain('**')
  })
})
