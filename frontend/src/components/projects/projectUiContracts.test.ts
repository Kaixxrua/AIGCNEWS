import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'
import ProjectFiltersPanel from './ProjectFiltersPanel.vue'
import ProjectPagination from './ProjectPagination.vue'
import ProjectResultCard from './ProjectResultCard.vue'
import ToolWebsiteAddDialog from './ToolWebsiteAddDialog.vue'
import ToolWebsiteEditDialog from './ToolWebsiteEditDialog.vue'
import type {
  GitHubProjectCategory,
  GitHubProjectItem,
  GitHubProjectSort,
  GitHubProjectTag,
  ProjectScope,
  ProjectTaxonomyItem,
  ProjectViewSource,
} from '@/services/projects/projectApi'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {},
  missingWarn: false,
  fallbackWarn: false,
})

const mountOptions = {
  global: {
    plugins: [i18n],
    stubs: { Teleport: true },
  },
}

const githubRepo = (patch: Partial<GitHubProjectItem> = {}): GitHubProjectItem => ({
  full_name: 'acme/radar',
  url: 'https://github.com/acme/radar',
  description: 'A radar for AI projects',
  language: 'TypeScript',
  stars: 1234,
  forks: 56,
  topics: ['ai', 'radar'],
  tags: ['agent'],
  source: 'github',
  ...patch,
})

const cardProps = (patch: Record<string, unknown> = {}) => ({
  repo: githubRepo(),
  index: 0,
  isPersonalView: false,
  canFavorite: true,
  canRecommend: true,
  canEdit: false,
  showDelete: false,
  isLoggedIn: true,
  favoriteBusy: false,
  favoriteActionsBusy: false,
  recommendBusy: false,
  recommendActionsBusy: false,
  savingEdit: false,
  deleting: false,
  logoLoaded: false,
  logoBroken: false,
  sort: 'hot' as const,
  scope: 'all' as const,
  ...patch,
})

type SourceOption = { value: ProjectViewSource; label: string; hint: string; authOnly?: boolean }

interface FiltersProps {
  sourceOptions: SourceOption[]
  source: ProjectViewSource
  requiresPersonalLogin: boolean
  searchQuery: string
  selectedLanguage: string
  sort: GitHubProjectSort
  selectedScope: ProjectScope
  isWebsiteOnlyView: boolean
  isPersonalView: boolean
  categoriesLoading: boolean
  tagsLoading: boolean
  allScope?: GitHubProjectCategory
  recommendedScope?: GitHubProjectCategory
  todayScope?: GitHubProjectCategory
  semanticCategories: GitHubProjectCategory[]
  activeCategory?: GitHubProjectCategory
  visibleSubcategories: GitHubProjectCategory[]
  selectedCategory: string
  selectedSubcategory: string
  personalTags: GitHubProjectTag[]
  selectedTag: string
}

const filtersProps = (patch: Partial<FiltersProps> = {}): FiltersProps => ({
  sourceOptions: [
    { value: 'github', label: 'GitHub', hint: 'repos' },
    { value: 'website', label: 'Websites', hint: 'tools' },
  ],
  source: 'github',
  requiresPersonalLogin: false,
  searchQuery: '',
  selectedLanguage: '',
  sort: 'hot',
  selectedScope: 'all',
  isWebsiteOnlyView: false,
  isPersonalView: false,
  categoriesLoading: false,
  tagsLoading: false,
  semanticCategories: [],
  visibleSubcategories: [],
  selectedCategory: 'all',
  selectedSubcategory: 'all',
  personalTags: [],
  selectedTag: '',
  ...patch,
})

describe('project card rail behavior', () => {
  it('renders the action rail with tooltip wiring and favorite aria state', () => {
    const wrapper = mount(ProjectResultCard, {
      ...mountOptions,
      props: cardProps({ repo: githubRepo({ is_favorited: true } as Partial<GitHubProjectItem>) }),
    })

    const rail = wrapper.find('aside.project-card__rail')
    expect(rail.exists()).toBe(true)
    const link = wrapper.find('a.project-card__link')
    expect(link.attributes('href')).toBe('https://github.com/acme/radar')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('aria-describedby')).toBe('project-action-0-link-tooltip')
    expect(wrapper.find('#project-action-0-link-tooltip').attributes('role')).toBe('tooltip')

    const favorite = wrapper.find('button.project-card__favorite')
    expect(favorite.exists()).toBe(true)
    expect(favorite.attributes('aria-pressed')).toBe('true')
    expect(favorite.attributes('aria-describedby')).toBe('project-action-0-favorite-tooltip')
    expect(favorite.classes()).toContain('project-card__favorite--active')
  })

  it('emits favorite and recommend with the repo payload', async () => {
    const repo = githubRepo()
    const wrapper = mount(ProjectResultCard, {
      ...mountOptions,
      props: cardProps({ repo }),
    })

    await wrapper.find('button.project-card__favorite').trigger('click')
    await wrapper.find('button.project-card__recommend').trigger('click')

    expect(wrapper.emitted('favorite')).toEqual([[repo]])
    expect(wrapper.emitted('recommend')).toEqual([[repo]])
  })

  it('disables rail actions while their actions are busy', () => {
    const wrapper = mount(ProjectResultCard, {
      ...mountOptions,
      props: cardProps({ favoriteActionsBusy: true, recommendActionsBusy: true }),
    })

    expect(wrapper.find('button.project-card__favorite').attributes('disabled')).toBeDefined()
    expect(wrapper.find('button.project-card__recommend').attributes('disabled')).toBeDefined()
  })

  it('hides edit and delete actions unless granted and emits them when shown', async () => {
    const repo = githubRepo()
    const hidden = mount(ProjectResultCard, { ...mountOptions, props: cardProps({ repo }) })
    expect(hidden.find('button.project-card__edit').exists()).toBe(false)
    expect(hidden.find('button.project-card__delete').exists()).toBe(false)

    const shown = mount(ProjectResultCard, {
      ...mountOptions,
      props: cardProps({ repo, canEdit: true, showDelete: true }),
    })
    await shown.find('button.project-card__edit').trigger('click')
    await shown.find('button.project-card__delete').trigger('click')
    expect(shown.emitted('edit')).toEqual([[repo]])
    expect(shown.emitted('delete')).toEqual([[repo]])
  })

  it('emits chipClick with the clicked chip', async () => {
    const wrapper = mount(ProjectResultCard, { ...mountOptions, props: cardProps() })
    const chip = wrapper.find('.project-chip')
    expect(chip.exists()).toBe(true)

    await chip.trigger('click')

    const events = wrapper.emitted('chipClick')
    expect(events).toHaveLength(1)
    expect(events![0]![0]).toMatchObject({ value: expect.any(String), type: expect.any(String) })
  })
})

describe('filters panel behavior', () => {
  it('renders source tabs with the active state and emits changeSource', async () => {
    const wrapper = mount(ProjectFiltersPanel, { ...mountOptions, props: filtersProps() })
    const tabs = wrapper.findAll('button.projects-source-tab')
    expect(tabs).toHaveLength(2)
    expect(tabs[0]!.classes()).toContain('projects-source-tab--active')
    expect(tabs[1]!.classes()).not.toContain('projects-source-tab--active')

    await tabs[1]!.trigger('click')

    expect(wrapper.emitted('changeSource')).toEqual([['website']])
  })

  it('emits update:searchQuery on typing and clears via the clear button', async () => {
    const wrapper = mount(ProjectFiltersPanel, {
      ...mountOptions,
      props: filtersProps({ searchQuery: 'radar' }),
    })

    const input = wrapper.find('input[type="search"]')
    await input.setValue('llm')
    expect(wrapper.emitted('update:searchQuery')?.[0]).toEqual(['llm'])

    await wrapper.find('button.projects-search__clear').trigger('click')
    expect(wrapper.emitted('update:searchQuery')?.[1]).toEqual([''])
  })

  it('emits update:sort from the sort select and disables it for the today scope', async () => {
    const wrapper = mount(ProjectFiltersPanel, { ...mountOptions, props: filtersProps() })
    const select = wrapper.find('.projects-sort select')
    expect(select.attributes('disabled')).toBeUndefined()

    await select.setValue('stars')
    expect(wrapper.emitted('update:sort')).toEqual([['stars']])

    const today = mount(ProjectFiltersPanel, {
      ...mountOptions,
      props: filtersProps({ selectedScope: 'today' }),
    })
    expect(today.find('.projects-sort select').attributes('disabled')).toBeDefined()
  })

  it('hides public sorting controls in personal views without emitting changes', async () => {
    for (const source of ['website', 'favorites'] as const) {
      const wrapper = mount(ProjectFiltersPanel, {
        ...mountOptions,
        props: filtersProps({ source, isPersonalView: true, sort: 'updated' }),
      })

      expect(wrapper.find('.projects-sort').exists()).toBe(false)
      expect(wrapper.emitted('update:sort')).toBeUndefined()
      await wrapper.setProps({ sort: 'stars' })
      expect(wrapper.emitted('update:sort')).toBeUndefined()
    }
  })

  it('keeps the personal tag panel compact until it has useful choices', async () => {
    const empty = mount(ProjectFiltersPanel, {
      ...mountOptions,
      props: filtersProps({ source: 'website', isPersonalView: true }),
    })
    expect(empty.find('.projects-tag-panel').exists()).toBe(false)

    const one = mount(ProjectFiltersPanel, {
      ...mountOptions,
      props: filtersProps({
        source: 'website',
        isPersonalView: true,
        personalTags: [{ value: 'agent', label: 'Agent', count: 1 }],
      }),
    })
    expect(one.find('.projects-tag-panel').exists()).toBe(false)

    const many = mount(ProjectFiltersPanel, {
      ...mountOptions,
      props: filtersProps({
        source: 'website',
        isPersonalView: true,
        personalTags: [{ value: 'agent', label: 'Agent', count: 1 }, { value: 'rag', label: 'RAG', count: 2 }],
      }),
    })
    expect(many.find('.projects-tag-panel').exists()).toBe(true)

    const selected = mount(ProjectFiltersPanel, {
      ...mountOptions,
      props: filtersProps({
        source: 'website',
        isPersonalView: true,
        personalTags: [{ value: 'agent', label: 'Agent', count: 1 }],
        selectedTag: 'agent',
      }),
    })
    expect(selected.find('.projects-tag-panel').exists()).toBe(true)
    await selected.find('button.projects-category--sub').trigger('click')
    expect(selected.emitted('clearPersonalTag')).toHaveLength(1)
  })

  it('emits scope and category selections from the category rows', async () => {
    const wrapper = mount(ProjectFiltersPanel, {
      ...mountOptions,
      props: filtersProps({
        allScope: { slug: 'all', name: 'All', count: 12 },
        recommendedScope: { slug: 'recommended', name: 'Recommended', count: 3 },
        semanticCategories: [{ slug: 'agents', name: 'Agents', count: 5, children: [] }],
      }),
    })

    await wrapper.find('button.projects-category--scope').trigger('click')
    await wrapper.find('button.projects-category--recommend').trigger('click')
    await wrapper.find('button.projects-category:not(.projects-category--scope):not(.projects-category--recommend):not(.projects-category--today):not(.projects-category--sub):not(.projects-category--tag)').trigger('click')

    expect(wrapper.emitted('selectScope')).toEqual([['all'], ['recommended']])
    expect(wrapper.emitted('selectCategory')).toEqual([['agents']])
  })
})

describe('pagination behavior', () => {
  const paginationProps = (patch: Record<string, unknown> = {}) => ({
    page: 2,
    totalPages: 5,
    total: 100,
    hasPrev: true,
    hasNext: true,
    pageJump: '',
    ...patch,
  })

  it('emits goPage with adjacent page numbers and respects boundaries', async () => {
    const wrapper = mount(ProjectPagination, { ...mountOptions, props: paginationProps() })
    const buttons = wrapper.findAll('button.projects-pagination__button')
    expect(buttons[0]!.attributes('disabled')).toBeUndefined()
    expect(buttons[2]!.attributes('disabled')).toBeUndefined()

    await buttons[0]!.trigger('click')
    await buttons[2]!.trigger('click')
    expect(wrapper.emitted('goPage')).toEqual([[1], [3]])

    const first = mount(ProjectPagination, {
      ...mountOptions,
      props: paginationProps({ page: 1, hasPrev: false }),
    })
    const last = mount(ProjectPagination, {
      ...mountOptions,
      props: paginationProps({ page: 5, hasNext: false }),
    })
    expect(first.findAll('button.projects-pagination__button')[0]!.attributes('disabled')).toBeDefined()
    expect(last.findAll('button.projects-pagination__button')[2]!.attributes('disabled')).toBeDefined()
  })

  it('mirrors the jump input via update:pageJump and submits jumpToPage', async () => {
    const wrapper = mount(ProjectPagination, { ...mountOptions, props: paginationProps() })

    await wrapper.find('input[type="number"]').setValue('4')
    expect(wrapper.emitted('update:pageJump')).toEqual([['4']])

    await wrapper.find('form.projects-pagination__jump').trigger('submit')
    expect(wrapper.emitted('jumpToPage')).toHaveLength(1)
  })
})

describe('tool website dialogs behavior', () => {
  const taxonomy: ProjectTaxonomyItem[] = [
    {
      slug: 'other',
      name: 'Other',
      children: [{ slug: 'other_uncategorized', name: 'Uncategorized', name_zh: '未分类', name_en: 'Uncategorized' }],
    },
  ]

  interface AddDialogProps {
    open: boolean
    active: boolean
    isMyCollection: boolean
    taxonomy: ProjectTaxonomyItem[]
    taxonomyLoading: boolean
    busy: boolean
    error: string
  }

  const addProps = (patch: Partial<AddDialogProps> = {}): AddDialogProps => ({
    open: true,
    active: true,
    isMyCollection: false,
    taxonomy,
    taxonomyLoading: false,
    busy: false,
    error: '',
    ...patch,
  })

  it('add dialog renders footer actions and guards close while busy', async () => {
    const wrapper = mount(ToolWebsiteAddDialog, { ...mountOptions, props: addProps() })
    expect(wrapper.find('.tool-modal__actions').exists()).toBe(true)

    await wrapper.find('button.tool-modal__close').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)

    const busyDialog = mount(ToolWebsiteAddDialog, { ...mountOptions, props: addProps({ busy: true }) })
    expect(busyDialog.find('button.tool-modal__close').attributes('disabled')).toBeDefined()
    await busyDialog.find('button.tool-modal__close').trigger('click')
    expect(busyDialog.emitted('close')).toBeUndefined()
  })

  it('add dialog requires a URL before emitting submitAuto', async () => {
    const wrapper = mount(ToolWebsiteAddDialog, { ...mountOptions, props: addProps() })

    await wrapper.find('form.tool-modal__panel').trigger('submit')
    expect(wrapper.emitted('submitAuto')).toBeUndefined()

    await wrapper.find('input').setValue(' https://example.com/tool ')
    await wrapper.find('form.tool-modal__panel').trigger('submit')
    expect(wrapper.emitted('submitAuto')).toEqual([['https://example.com/tool']])
  })

  it('add dialog validates manual fields and emits submitManual with parsed tags', async () => {
    const wrapper = mount(ToolWebsiteAddDialog, { ...mountOptions, props: addProps() })
    const tabButtons = wrapper.findAll('.tool-modal__tabs button')
    await tabButtons[1]!.trigger('click')

    const inputs = wrapper.findAll('input')
    await inputs[0]!.setValue('https://example.com/tool')
    await wrapper.find('form.tool-modal__panel').trigger('submit')
    expect(wrapper.emitted('submitManual')).toBeUndefined()

    await inputs[1]!.setValue('Example Tool')
    const textarea = wrapper.find('textarea')
    await textarea.setValue('A useful tool')
    await wrapper.find('form.tool-modal__panel').trigger('submit')

    expect(wrapper.emitted('submitManual')).toEqual([
      [
        {
          url: 'https://example.com/tool',
          title: 'Example Tool',
          description_zh: 'A useful tool',
          category_slug: 'other',
          subcategory_slug: 'other_uncategorized',
          tags: [],
        },
      ],
    ])
  })

  it('edit dialog renders footer actions, pre-fills from target, and emits submit', async () => {
    const target = githubRepo({
      website_id: 42,
      title: 'Existing Tool',
      description: 'Existing description',
      tags: ['ai', 'tool'],
    })
    const wrapper = mount(ToolWebsiteEditDialog, {
      ...mountOptions,
      props: {
        open: false,
        active: true,
        target,
        taxonomy,
        taxonomyLoading: false,
        busy: false,
        error: '',
      },
    })
    await wrapper.setProps({ open: true })

    expect(wrapper.find('.tool-modal__actions').exists()).toBe(true)
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('Existing Tool')

    await wrapper.find('form').trigger('submit')
    const events = wrapper.emitted('submit')
    expect(events).toHaveLength(1)
    expect(events![0]![0]).toBe(42)
    expect(events![0]![1]).toMatchObject({ title: 'Existing Tool', tags: ['ai', 'tool'] })
  })
})
