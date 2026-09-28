import { describe, expect, it } from 'vitest'
import {
  displayHotScore,
  estimateProjectCardHeight,
  favoriteButtonLabelKey,
  formatProjectLastPush,
  localizedCategoryName,
  localizedPersonalTagLabel,
  projectCategoryName,
  projectDescription,
  projectDisplayTags,
  projectLastPushTitle,
  recommendButtonLabelKey,
} from './projectPresentation'

const project = {
  id: 'website:1', source: 'website' as const, website_id: 1, full_name: 'Example Website',
  category_slug: 'coding_tools', category_name: '开发工具',
  category_name_zh: '开发工具', category_name_en: 'Developer Tools',
  subcategory_slug: 'code_review', subcategory_name: '代码审查',
  subcategory_name_zh: '代码审查', subcategory_name_en: 'Code Review',
  description: 'raw metadata', description_zh: '中文说明', description_en: 'Natural English description.',
}

describe('projectPresentation localization', () => {
  it('selects localized taxonomy names without changing slugs', () => {
    expect(localizedCategoryName({ name: '中文', name_zh: '中文', name_en: 'English' }, 'en-US')).toBe('English')
    expect(projectCategoryName(project, 'zh-CN')).toBe('开发工具')
    expect(projectDisplayTags(project, false, 'en-US').slice(0, 2)).toEqual([
      { type: 'subcategory', label: 'Code Review', categorySlug: 'coding_tools', value: 'code_review' },
      { type: 'category', label: 'Developer Tools', value: 'coding_tools' },
    ])
  })

  it('prefers authored English and falls back compatibly', () => {
    expect(projectDescription(project, 'en-US', 'fallback')).toBe('Natural English description.')
    expect(projectDescription({ ...project, description_en: '' }, 'en-US', 'fallback')).toBe('raw metadata')
    expect(projectDescription(project, 'zh-CN', 'fallback')).toBe('中文说明')
  })

  it('returns locale keys for card actions', () => {
    expect(favoriteButtonLabelKey({ ...project, is_favorited: false }, false, false)).toBe('projects.loginFavorite')
    expect(favoriteButtonLabelKey({ ...project, is_favorited: false }, false, true)).toBe('projects.favorite')
    expect(favoriteButtonLabelKey({ ...project, is_favorited: true }, false, true)).toBe('projects.favorited')
    expect(favoriteButtonLabelKey({ ...project, is_favorited: false }, true, true)).toBe('common.processing')
    expect(recommendButtonLabelKey({ ...project, is_recommended: false }, false)).toBe('projects.recommend')
    expect(recommendButtonLabelKey({ ...project, is_recommended: true }, false)).toBe('projects.unrecommend')
  })

  it('uses localized fallback labels without changing their stable chip values', () => {
    const emptyProject = { repo_id: 1, full_name: 'owner/project' }
    expect(projectDisplayTags(emptyProject, false, 'en-US', {
      project: 'AI project',
      website: 'Website favorite',
    })).toEqual([{ type: 'tag', label: 'AI project', value: 'AI 项目' }])
  })

  it('localizes system tags while preserving stable filter values', () => {
    const bilingual = {
      ...project,
      tags: ['代码助手', 'IDE 插件'],
      tags_zh: ['代码助手', 'IDE 插件'],
      tags_en: ['Coding assistant', 'IDE plugin'],
      tags_origin: 'system' as const,
    }
    expect(projectDisplayTags(bilingual, false, 'en-US').slice(2)).toEqual([
      { type: 'tag', label: 'Coding assistant', value: '代码助手' },
      { type: 'tag', label: 'IDE plugin', value: 'IDE 插件' },
    ])
    expect(projectDisplayTags(bilingual, false, 'zh-CN').slice(2)).toEqual([
      { type: 'tag', label: '代码助手', value: '代码助手' },
      { type: 'tag', label: 'IDE 插件', value: 'IDE 插件' },
    ])
  })

  it('localizes personal system tags without changing their filter values', () => {
    const systemTag = {
      value: '着色器效果', label: '着色器效果', label_zh: '着色器效果', label_en: 'Shader effects',
      count: 1, tags_origin: 'system' as const,
    }
    const userTag = {
      value: '我的标签', label: '我的标签', label_zh: '不应显示', label_en: 'Must not display',
      count: 1, tags_origin: 'user' as const,
    }

    expect(localizedPersonalTagLabel(systemTag, 'en-US')).toBe('Shader effects')
    expect(localizedPersonalTagLabel(systemTag, 'zh-CN')).toBe('着色器效果')
    expect(localizedPersonalTagLabel(userTag, 'en-US')).toBe('我的标签')
    expect(systemTag.value).toBe('着色器效果')
  })

  it('keeps user-authored and legacy tags unchanged in every locale', () => {
    const personal = {
      repo_id: 1,
      full_name: 'owner/project',
      tags: ['个人标签'],
      tags_zh: ['不应显示'],
      tags_en: ['Must not display'],
      tags_origin: 'user' as const,
    }
    expect(projectDisplayTags(personal, true, 'en-US')).toEqual([
      { type: 'tag', label: '个人标签', value: '个人标签' },
    ])
    expect(projectDisplayTags({ repo_id: 2, full_name: 'legacy', tags: ['旧标签'] }, false, 'en-US')).toEqual([
      { type: 'tag', label: '旧标签', value: '旧标签' },
    ])
  })
})

describe('projectPresentation last push label', () => {
  const now = new Date('2026-08-11T08:00:00Z')

  it('returns an empty label when pushed_at is missing', () => {
    expect(formatProjectLastPush('', 'zh-CN', now)).toBe('')
    expect(formatProjectLastPush(undefined, 'en-US', now)).toBe('')
  })

  it('treats date-only and full timestamps of the same UTC day identically', () => {
    expect(formatProjectLastPush('2026-08-08', 'zh-CN', now)).toBe('3天前')
    expect(formatProjectLastPush('2026-08-08T03:00:00Z', 'zh-CN', now)).toBe('3天前')
    expect(formatProjectLastPush('2026-08-08', 'en-US', now)).toBe('3 days ago')
    expect(formatProjectLastPush('2026-08-08T23:59:59Z', 'en-US', now)).toBe('3 days ago')
  })

  it('buckets day, month, and year ranges in both locales', () => {
    expect(formatProjectLastPush('2026-08-11', 'zh-CN', now)).toBe('今天')
    expect(formatProjectLastPush('2026-08-10', 'en-US', now)).toBe('yesterday')
    expect(formatProjectLastPush('2026-06-27', 'zh-CN', now)).toBe('上个月')
    expect(formatProjectLastPush('2026-06-12', 'en-US', now)).toBe('2 months ago')
    expect(formatProjectLastPush('2025-07-13', 'zh-CN', now)).toBe('去年')
    expect(formatProjectLastPush('2024-05-18', 'en-US', now)).toBe('2 years ago')
  })

  it('clamps future dates to today and passes invalid values through', () => {
    expect(formatProjectLastPush('2026-08-12', 'zh-CN', now)).toBe('今天')
    expect(formatProjectLastPush('not-a-date', 'en-US', now)).toBe('not-a-date')
  })

  it('renders the full push date in the hover title', () => {
    const t = (key: string, params?: Record<string, unknown>) => `${key}|${String(params?.date ?? '')}`
    expect(projectLastPushTitle({ full_name: 'o/p', pushed_at: '2026-08-08' }, t, 'zh-CN'))
      .toBe('projects.lastPushTitle|2026/08/08')
    expect(projectLastPushTitle({ full_name: 'o/p', pushed_at: '' }, t, 'zh-CN')).toBe('')
  })
})

describe('estimateProjectCardHeight', () => {
  const bareRepo = { repo_id: 7, full_name: 'owner/project' }
  const longZh = '这是一段用来撑高卡片的中文描述，反复铺陈项目用途与亮点细节，足足数行'

  it('floors at the card min-height even for an empty project', () => {
    expect(estimateProjectCardHeight(bareRepo, 280)).toBe(292) // 280 min + 12 gap
  })

  it('grows with longer descriptions', () => {
    const short = estimateProjectCardHeight({ ...bareRepo, description_zh: '短描述' }, 280, 'zh-CN')
    const long = estimateProjectCardHeight({ ...bareRepo, description_zh: longZh }, 280, 'zh-CN')
    expect(long).toBeGreaterThan(short)
  })

  it('grows in narrower columns because text wraps more', () => {
    const repo = { ...bareRepo, description_zh: longZh }
    expect(estimateProjectCardHeight(repo, 260, 'zh-CN')).toBeGreaterThan(estimateProjectCardHeight(repo, 460, 'zh-CN'))
  })

  it('grows when tags wrap onto more rows', () => {
    const described = { ...bareRepo, description_zh: longZh }
    const tagged = { ...described, tags: ['代码助手', 'IDE 插件', '模型上下文协议', '自动化工作流', '向量数据库'] }
    expect(estimateProjectCardHeight(tagged, 280, 'zh-CN')).toBeGreaterThan(estimateProjectCardHeight(described, 280, 'zh-CN'))
  })

  it('adds a domain row for website projects', () => {
    const site = { source: 'website' as const, website_id: 3, full_name: 'Example Website', title: 'Example', description_zh: longZh.repeat(3) } // 长描述先顶过卡片最小高度，域名行才显形
    expect(estimateProjectCardHeight({ ...site, domain: 'example.com' }, 280, 'zh-CN'))
      .toBeGreaterThan(estimateProjectCardHeight(site, 280, 'zh-CN'))
  })

  it('follows the locale-preferred description', () => {
    const repo = { ...bareRepo, description_zh: longZh, description_en: 'short' }
    expect(estimateProjectCardHeight(repo, 280, 'zh-CN')).toBeGreaterThan(estimateProjectCardHeight(repo, 280, 'en-US'))
  })

  it('does not shrink when the hot-score stat joins the footer', () => {
    const repo = { ...bareRepo, pushed_at: '2026-08-20', hot_score: 42 }
    const plain = estimateProjectCardHeight(repo, 300, 'zh-CN', { sort: 'stars', scope: 'all' })
    const hot = estimateProjectCardHeight(repo, 300, 'zh-CN', { sort: 'hot', scope: 'all' })
    expect(hot).toBeGreaterThanOrEqual(plain)
  })
})

describe('displayHotScore', () => {
  it('keeps the ends fixed and lifts the v7 percentiles', () => {
    expect(displayHotScore(0)).toBe(0)
    expect(displayHotScore(100)).toBeCloseTo(100, 10)
    // 2026-09-24..27 生产涨星项目原始分：P50 4.89、P90 14.40、P99 33.34
    expect(displayHotScore(4.89)).toBeCloseTo(27.3, 1)
    expect(displayHotScore(14.4)).toBeCloseTo(49.7, 1)
    expect(displayHotScore(33.34)).toBeCloseTo(70.5, 1)
  })

  it('never reorders scores', () => {
    const raw = [0, 0.05, 1, 4.89, 14.4, 33.34, 56.71, 79.7, 99.99, 100]
    const shown = raw.map(displayHotScore)
    expect([...shown].sort((a, b) => a - b)).toEqual(shown)
    expect(new Set(shown).size).toBe(shown.length)
  })

  it('clamps out-of-range and non-finite input', () => {
    expect(displayHotScore(-5)).toBe(0)
    expect(displayHotScore(Number.NaN)).toBe(0)
    expect(displayHotScore(250)).toBeCloseTo(100, 10)
  })
})
