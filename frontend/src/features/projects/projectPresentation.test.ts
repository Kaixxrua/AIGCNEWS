import { describe, expect, it } from 'vitest'
import {
  favoriteButtonLabelKey,
  localizedCategoryName,
  projectCategoryName,
  projectDescription,
  projectDisplayTags,
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
    })).toEqual([{ type: 'tag', label: 'AI project', value: 'AI project' }])
  })
})
