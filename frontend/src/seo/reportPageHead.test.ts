import { describe, expect, it } from 'vitest'
import { reportPageHead, reportSearchText } from './reportPageHead'

describe('briefing issue search metadata', () => {
  it('excludes confirmed missing issues from search results', () => {
    expect(reportPageHead({ date: '2026-10-19' }, 'missing', '每日简报')).toMatchObject({ noindex: true })
  })

  it.each(['loading', 'ready', 'pending', 'failed'] as const)('keeps %s issues eligible and drops tracking query params', state => {
    expect(reportPageHead({ date: '2026-10-20', type: 'github', utm_source: 'google' }, state, '每日简报')).toEqual({
      title: '每日简报 2026-10-20', noindex: false,
      canonicalQuery: { date: '2026-10-20', type: 'github' },
    })
  })

  it('leaves the latest-issue landing page indexable and removes default issue filters', () => {
    expect(reportPageHead({}, 'missing', '每日简报')).toBeNull()
    expect(reportPageHead({ date: 'invalid' }, 'missing', '每日简报')).toBeNull()
    expect(reportPageHead({ date: '2026-10-20', type: 'all' }, 'ready', '每日简报')?.canonicalQuery)
      .toEqual({ date: '2026-10-20', type: null })
  })

  it('uses the published issue heading and introduction instead of identical search snippets', () => {
    const content = '# Open models and agent tools `#news`\n\nGenerated: 2026-10-19\n\n**Open models** and [agent tools](https://example.test) lead today’s releases, with practical deployment notes.'
    expect(reportPageHead({ date: '2026-10-19', type: 'news' }, 'ready', 'AI News', content)).toMatchObject({
      title: 'Open models and agent tools 2026-10-19',
      description: 'Open models and agent tools lead today’s releases, with practical deployment notes.',
      canonicalQuery: { date: '2026-10-19', type: 'news' },
    })
    expect(reportPageHead({ date: '2026-10-19' }, 'loading', 'AI News', content)?.description).toBeUndefined()
  })

  it('handles stored escaped newlines and excludes datelines and heading tags', () => {
    const content = '# AI 新闻 `#Agent`\\n\\n生成日期：2026 年 10 月 19 日。这一行是发布日期与来源说明，而不是本期内容的摘要。\\n\\n本期关注开源大模型、智能体工具与人工智能产品发布，介绍新能力、工程实践、使用限制与原始信息来源，帮助读者理解新闻。'
    const text = reportSearchText(content)
    expect(text.heading).toBe('AI 新闻')
    expect(text.description).toMatch(/^本期关注开源大模型/)
    expect(text.description).not.toContain('生成日期')
  })

  it('skips real Chinese datelines whose bold markers touch the date', () => {
    const content = '# AI 行业商业日报\n\n**生成日期：**2026年10月20日｜**榜单日期：**2026年10月19日\n\n本报梳理本期模型研发、算力适配、产品商业化，以及版权、政府采购与网络安全方面的关键动态。'
    expect(reportSearchText(content).description).toMatch(/^本报梳理本期模型研发/)
  })

  it('keeps LaTeX commands intact while interpreting escaped paragraph separators', () => {
    expect(reportSearchText('Research using \\nabla and \\nu explores efficient neural networks and their practical performance.').description)
      .toContain('\\nabla and \\nu')
  })
})
