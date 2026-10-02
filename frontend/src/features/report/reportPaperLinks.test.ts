import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '@/composables/useLatexRenderer'
import { parseBroadsheet, type BroadsheetItem } from './reportBroadsheet'
import { itemPaperLinks, paperArxivId, paperLinkLabel, paperLinksIn } from './reportPaperLinks'

const itemsOf = (markdown: string): BroadsheetItem[] => {
  const block = parseBroadsheet(renderMarkdown(markdown)).sections[0]?.blocks[0]
  if (block?.kind !== 'items') throw new Error(`expected items, got ${block?.kind}`)
  return block.items
}

describe('paperArxivId', () => {
  it('reads the arXiv id off Hugging Face paper pages, their mirror, arXiv and alphaXiv, without the version', () => {
    expect(paperArxivId('https://hf-mirror.com/papers/2609.33439')).toBe('2609.33439')
    expect(paperArxivId('https://huggingface.co/papers/2609.33439/')).toBe('2609.33439')
    expect(paperArxivId('https://arxiv.org/abs/2609.33439v2')).toBe('2609.33439')
    expect(paperArxivId('https://arxiv.org/pdf/2609.33439v1.pdf')).toBe('2609.33439')
    expect(paperArxivId('http://www.arxiv.org/html/2609.3343v3')).toBe('2609.3343')
    expect(paperArxivId('https://www.alphaxiv.org/abs/2609.33439?x=1#top')).toBe('2609.33439')
  })

  it('leaves everything else alone', () => {
    for (const href of [
      'https://github.com/papers/2609.33439',
      'https://huggingface.co/2609.33439',
      'https://huggingface.co/datasets/2609.33439',
      'https://arxiv.org/papers/2609.33439',
      'https://arxiv.org/list/cs.AI/recent',
      'https://arxiv.org/abs/cs/0101001',
      'https://arxiv.org/abs/2609.123',
      'https://evil-arxiv.org/abs/2609.33439',
      'javascript:alert(1)',
      '/papers/2609.33439',
      '',
      null,
    ]) expect(paperArxivId(href), String(href)).toBeNull()
  })
})

describe('paperLinkLabel', () => {
  it('drops the 来源 / Source tail and keeps nothing for a generic label', () => {
    expect(paperLinkLabel('Raven来源')).toBe('Raven')
    expect(paperLinkLabel(' Omni-IO  Skills 来源 ')).toBe('Omni-IO Skills')
    expect(paperLinkLabel('MALA')).toBe('MALA')
    expect(paperLinkLabel('VoxMem paper')).toBe('VoxMem')
    expect(paperLinkLabel('论文来源')).toBe('')
    expect(paperLinkLabel('论文原文')).toBe('')
    expect(paperLinkLabel('Source')).toBe('')
    expect(paperLinkLabel('Paper')).toBe('')
  })
})

describe('paperLinksIn / itemPaperLinks', () => {
  it('finds every paper an item cites, its source first, each paper once', () => {
    const [topic, single, plain] = itemsOf([
      '## 本期研究热点 `#arxiv`',
      '',
      '1. **智能体支撑层**：Raven 与 Omni-IO Skills 均通过任务分解扩展智能体，另见 [Raven 论文](https://arxiv.org/abs/2609.33439v2)。[Raven来源](https://hf-mirror.com/papers/2609.33439) [Omni-IO Skills来源](https://hf-mirror.com/papers/2609.31847)',
      '2. **MaLiang-Harness**：它针对可执行程序违背用户意图的缺口。[论文来源](https://hf-mirror.com/papers/2609.34309)',
      '3. **综述**：没有论文链接，只有[项目主页](https://github.com/acme/agent)。',
    ].join('\n'))

    expect(itemPaperLinks(topic!)).toEqual([
      { arxivId: '2609.33439', href: 'https://hf-mirror.com/papers/2609.33439', label: 'Raven' },
      { arxivId: '2609.31847', href: 'https://hf-mirror.com/papers/2609.31847', label: 'Omni-IO Skills' },
    ])
    expect(itemPaperLinks(single!)).toEqual([{ arxivId: '2609.34309', href: 'https://hf-mirror.com/papers/2609.34309', label: '' }])
    expect(itemPaperLinks(plain!)).toEqual([])
  })

  it('reads plain HTML fragments and ignores ones without links', () => {
    expect(paperLinksIn('')).toEqual([])
    expect(paperLinksIn('<p>没有链接</p>')).toEqual([])
    expect(paperLinksIn('<a href="https://arxiv.org/abs/2609.00001">A</a>、<a href="https://arxiv.org/pdf/2609.00001v3">A again</a>')).toEqual([
      { arxivId: '2609.00001', href: 'https://arxiv.org/abs/2609.00001', label: 'A' },
    ])
  })
})
