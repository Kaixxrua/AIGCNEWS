import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '@/composables/useLatexRenderer'
import { broadsheetItemReadId, parseBroadsheet, type BroadsheetBlock, type BroadsheetItem } from './reportBroadsheet'

const sheetOf = (markdown: string) => parseBroadsheet(renderMarkdown(markdown))

const itemsOf = (block: BroadsheetBlock | undefined): BroadsheetItem[] => {
  if (block?.kind !== 'items') throw new Error(`expected items, got ${block?.kind}`)
  return block.items
}

const text = (html: string) => {
  const el = document.createElement('div')
  el.innerHTML = html
  return el.textContent ?? ''
}

describe('parseBroadsheet', () => {
  it('splits the overview into sections, lifts bold names into headlines and keeps the closing dateline apart', () => {
    const sheet = sheetOf([
      '# AIGC 技术资讯综合日报 `#news`',
      '',
      '## 本期内容摘要 `#news` `#LLM`',
      '',
      '本报梳理的主线有三条：第一，多教师蒸馏。第二，可编辑音乐。',
      '',
      '## 技术亮点 `#arxiv`',
      '',
      '1. **DN-MOPD**：论文指出，多教师在线策略蒸馏的路由只决定哪位专家教学。[论文原文](https://hf-mirror.com/papers/2609.35347)',
      '',
      '2. **YuE2**：YuE2用单个AR–NAR Mixture-of-Transformers先生成可读乐谱。',
      '',
      '生成日期：2026-10-01；榜单日期：2026-09-29（太平洋时间）',
    ].join('\n'))

    expect(sheet.intro).toEqual([])
    expect(sheet.sections.map(section => text(section.heading))).toEqual(['本期内容摘要 news LLM', '技术亮点 arxiv'])
    const summary = sheet.sections[0]!.blocks[0]
    expect(summary?.kind).toBe('prose')
    expect(summary?.kind === 'prose' && summary.paragraphs).toEqual(['本报梳理的主线有三条：第一，多教师蒸馏。第二，可编辑音乐。'])

    const [first, second] = itemsOf(sheet.sections[1]!.blocks[0])
    expect(first).toMatchObject({ number: 1, lead: 'DN-MOPD', note: '' })
    expect(first!.body).toBe('论文指出，多教师在线策略蒸馏的路由只决定哪位专家教学。')
    expect(first!.source).toBe('<a href="https://hf-mirror.com/papers/2609.35347">论文原文</a>')
    expect(second).toMatchObject({ number: 2, lead: 'YuE2', source: '' })
    expect(text(second!.body)).toBe('YuE2用单个AR–NAR Mixture-of-Transformers先生成可读乐谱。')
    expect(sheet.dateline).toBe('生成日期：2026-10-01；榜单日期：2026-09-29（太平洋时间）')
  })

  it('keeps the edition lines and standfirst before the first section, and sets a repository note beside its name', () => {
    const sheet = sheetOf([
      '# AI 工程开源项目日报',
      '',
      '生成日期：2026-10-01｜榜单日期：2026-09-30',
      '',
      '本报梳理本期榜单中的 10 个开源项目。',
      '',
      '## 本期明星项目 `#github`',
      '',
      '1. **dots**（feder-cr/dots）：这是一个面向网页的开源 AI Agent。[来源](https://github.com/feder-cr/dots)',
      '',
      '2. **HowToLiveBetter**：这是按性价比排序的循证生活指南。',
    ].join('\n'))

    expect(sheet.intro.map(block => block.kind)).toEqual(['meta', 'prose'])
    expect(sheet.intro[0]).toEqual({ kind: 'meta', html: '生成日期：2026-10-01｜榜单日期：2026-09-30' })
    const [dots, guide] = itemsOf(sheet.sections[0]!.blocks[0])
    expect(dots).toMatchObject({ lead: 'dots', note: '（feder-cr/dots）' })
    expect(text(dots!.body)).toBe('这是一个面向网页的开源 AI Agent。')
    expect(dots!.source).toBe('<a href="https://github.com/feder-cr/dots">来源</a>')
    expect(guide).toMatchObject({ lead: 'HowToLiveBetter', note: '' })
    expect(sheet.dateline).toBe('')
  })

  it('reads English dashes, leaves a bold subject inside its sentence and keeps lead-less items whole', () => {
    const sheet = sheetOf([
      '# ArXiv Research Daily',
      '',
      '**Edition date:** October 1, 2026  ',
      '**Ranking date:** September 29, 2026',
      '',
      '## Hotspots `#arxiv`',
      '',
      '1. Long-context inference is moving toward adaptive compute [MALA](https://hf-mirror.com/papers/2609.32712)',
      '2. Evaluation is moving closer to deployment reality',
      '',
      '## Breakthroughs',
      '',
      '1. **CoWA** provides a strong study of causal access.',
      '',
      '2. **Gemini 4 Argon** — Google DeepMind announced a frontier model.',
    ].join('\n'))

    expect(sheet.intro).toHaveLength(1)
    expect(sheet.intro[0]?.kind).toBe('meta')
    const hotspots = itemsOf(sheet.sections[0]!.blocks[0])
    expect(hotspots.map(item => item.lead)).toEqual(['', ''])
    // 链接是句子的一部分（前面没有句末标点），不当出处挪走。
    expect(hotspots[0]!.body).toBe('Long-context inference is moving toward adaptive compute <a href="https://hf-mirror.com/papers/2609.32712">MALA</a>')
    expect(hotspots[0]!.source).toBe('')
    const [cowa, argon] = itemsOf(sheet.sections[1]!.blocks[0])
    expect(cowa).toMatchObject({ lead: '', note: '' })
    expect(cowa!.body).toBe('<strong>CoWA</strong> provides a strong study of causal access.')
    expect(argon).toMatchObject({ lead: 'Gemini 4 Argon' })
    expect(argon!.body).toBe('Google DeepMind announced a frontier model.')
  })

  it('handles double dashes, a colon written inside the bold name, a line break after it and a closing paragraph', () => {
    const sheet = sheetOf([
      '# 全网热榜',
      '',
      '## 产品动态',
      '',
      '- **掘金**——掘金把字节的 AI 编程工具推上热榜',
      '- **要点：**正文紧跟在粗体冒号之后',
      '- **换行标题**  ',
      '  换行后的正文',
      '- **只有名称**',
      '',
      '**趋势观察：**本报横看36氪、极客公园。',
    ].join('\n'))

    const [section] = sheet.sections
    const items = itemsOf(section!.blocks[0])
    expect(items.map(item => item.number)).toEqual([null, null, null, null])
    expect(items.map(item => [item.lead, text(item.body)])).toEqual([
      ['掘金', '掘金把字节的 AI 编程工具推上热榜'],
      ['要点', '正文紧跟在粗体冒号之后'],
      ['换行标题', '换行后的正文'],
      ['只有名称', ''],
    ])
    // 列表后的段落仍归本节，按正文段落排（粗体闭合后的空格是渲染器为 CJK 侧翼规则补的）。
    expect(section!.blocks[1]).toMatchObject({ kind: 'prose', paragraphs: ['<strong>趋势观察：</strong> 本报横看36氪、极客公园。'] })
  })

  it('sets the closing source links apart with their label and the marks between them, and leaves other links in place', () => {
    const sheet = sheetOf([
      '## X 动态',
      '',
      '1. **Google**：Argon 目前通过 Vertex AI 提供。来源：[Google AI第1条](https://x.com/a/1)、[Google AI第2条](https://x.com/a/2)',
      '2. **Semos**：[Semos.ai](https://semos.ai) Manager Agents 是为管理者打造的代理。[来源：36氪](https://36kr.com/p/1)',
      '3. **只有链接**：[arXiv](https://arxiv.org/abs/1)',
      '4. **句中链接**：详见 [GitHub](https://github.com/a/b)',
    ].join('\n'))

    const [google, semos, bare, inline] = itemsOf(sheet.sections[0]!.blocks[0])
    expect(google).toMatchObject({
      lead: 'Google',
      body: 'Argon 目前通过 Vertex AI 提供。',
      source: '来源：<a href="https://x.com/a/1">Google AI第1条</a>、<a href="https://x.com/a/2">Google AI第2条</a>',
    })
    expect(semos).toMatchObject({
      body: '<a href="https://semos.ai">Semos.ai</a> Manager Agents 是为管理者打造的代理。',
      source: '<a href="https://36kr.com/p/1">来源：36氪</a>',
    })
    // 取走就没有正文了，或链接嵌在句子里：都留在原处。
    expect(bare).toMatchObject({ body: '<a href="https://arxiv.org/abs/1">arXiv</a>', source: '' })
    expect(inline).toMatchObject({ body: '详见 <a href="https://github.com/a/b">GitHub</a>', source: '' })
  })

  it('takes the source from the last paragraph of a loose item and drops a paragraph it leaves empty', () => {
    const sheet = sheetOf([
      '## 判断',
      '',
      '1. **甲**：第一段。',
      '',
      '   第二段。[来源](https://example.com/1)',
      '',
      '2. **乙**：只有一段。',
      '',
      '   [来源](https://example.com/2)',
    ].join('\n'))

    const [first, second] = itemsOf(sheet.sections[0]!.blocks[0])
    expect(first!.source).toBe('<a href="https://example.com/1">来源</a>')
    expect(first!.body).toMatch(/^第一段。\s*<p>第二段。<\/p>$/)
    expect(second).toMatchObject({ lead: '乙', body: '只有一段。', source: '<a href="https://example.com/2">来源</a>' })
  })

  it('merges adjacent paragraphs, numbers from the list start and keeps other blocks as they are', () => {
    const sheet = sheetOf([
      '## 判断',
      '',
      '第一段。',
      '',
      '第二段。',
      '',
      '> 引用一句',
      '',
      '3. **三**：第三条',
      '4. **四**：第四条',
    ].join('\n'))

    const [prose, quote, list] = sheet.sections[0]!.blocks
    expect(prose).toEqual({ kind: 'prose', paragraphs: ['第一段。', '第二段。'], ems: 8 })
    expect(quote).toEqual({ kind: 'raw', html: '<blockquote>\n<p>引用一句</p>\n</blockquote>' })
    expect(itemsOf(list).map(item => item.number)).toEqual([3, 4])
  })

  it('puts everything in the intro when the report has no sections, and never drops a sentence-internal date', () => {
    const sheet = sheetOf('# 标题\n\n只有一段正文。\n\n生成日期：2026-10-01')
    expect(sheet.sections).toEqual([])
    expect(sheet.dateline).toBe('')
    expect(sheet.intro.map(block => block.kind)).toEqual(['prose', 'meta'])

    const inline = sheetOf('## 一\n\n正文提到生成日期在句中。\n\n结尾')
    expect(inline.dateline).toBe('')
    expect(inline.sections[0]!.blocks).toEqual([{ kind: 'prose', paragraphs: ['正文提到生成日期在句中。', '结尾'], ems: 14 }])
  })

  it('keeps an English closing dateline and a later h1', () => {
    const sheet = sheetOf('# Overview\n\n## Takeaways\n\nOur judgment.\n\n# Appendix\n\nGenerated: 2026-10-01')
    expect(sheet.dateline).toBe('Generated: 2026-10-01')
    expect(sheet.sections[0]!.blocks.map(block => block.kind)).toEqual(['prose', 'raw'])
  })
})

describe('broadsheetItemReadId', () => {
  it('fingerprints what an item says, not how it is marked up', () => {
    const dots = { lead: 'dots', note: '（feder-cr/dots）', body: '这是一个面向网页的开源 <a href="https://a.example">AI Agent</a>。' }
    const id = broadsheetItemReadId(dots)
    expect(id).toMatch(/^[0-9a-z]{6,11}$/)
    expect(broadsheetItemReadId({ ...dots, body: '这是一个面向网页的开源 <a href="https://b.example" target="_blank" rel="noopener">AI Agent</a>。' })).toBe(id)
    expect(broadsheetItemReadId({ ...dots, body: `\n${dots.body}  ` })).toBe(id)

    expect(broadsheetItemReadId({ ...dots, body: '这是一个面向桌面的开源 AI Agent。' })).not.toBe(id)
    expect(broadsheetItemReadId({ ...dots, lead: 'dots2' })).not.toBe(id)
    expect(broadsheetItemReadId({ lead: '', note: '', body: '<br>' })).toBe('')
  })

  it('tells the items of a real issue apart', () => {
    const sheet = sheetOf([
      '## 技术亮点',
      '',
      '1. **DN-MOPD**：论文指出，多教师在线策略蒸馏的路由只决定哪位专家教学。[论文原文](https://hf-mirror.com/papers/2609.35347)',
      '2. **YuE2**：YuE2用单个AR–NAR Mixture-of-Transformers先生成可读乐谱。',
      '3. **YuE2**：YuE2用单个AR–NAR Mixture-of-Transformers先生成可读乐谱',
    ].join('\n'))
    const ids = itemsOf(sheet.sections[0]!.blocks[0]).map(broadsheetItemReadId)
    expect(new Set(ids).size).toBe(3)
    expect(ids.every(Boolean)).toBe(true)
  })
})
