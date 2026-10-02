import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProjectChartRow from './ProjectChartRow.vue'
import i18n, { DEFAULT_LOCALE } from '@/i18n'
import type { GitHubProjectItem } from '@/services/projects/projectApi'

const repo = (overrides: Partial<GitHubProjectItem> = {}): GitHubProjectItem => ({
  full_name: 'acme/rocket',
  description_en: 'A rocket for agents, written out in full instead of cut short after one line.',
  stars: 12345,
  forks: 321,
  tags: ['agents', 'cli', 'rust', 'mcp'],
  hot_score: 14,
  rolling_24h_star_growth: 420,
  ...overrides,
})

const mountRow = (props: Record<string, unknown> = {}) => mount(ProjectChartRow, {
  props: {
    repo: repo(),
    position: 3,
    movement: { kind: 'up', steps: 4 },
    metricDate: '2026-10-02',
    days: 14,
    canFavorite: true,
    canRecommend: false,
    isLoggedIn: true,
    favoriteBusy: false,
    favoriteActionsBusy: false,
    recommendBusy: false,
    recommendActionsBusy: false,
    ...props,
  },
  global: { plugins: [i18n] },
})

describe('ProjectChartRow', () => {
  beforeEach(() => { i18n.global.locale.value = 'en-US' })
  afterEach(() => { i18n.global.locale.value = DEFAULT_LOCALE })

  it('reads across one row: place and move, the whole description, then the numbers', () => {
    const row = mountRow()

    expect(row.classes()).toContain('project-row--podium')
    expect(row.get('.project-row__position').text()).toContain('3')
    expect(row.get('.project-row__move--up').text()).toContain('▲4')
    expect(row.get('.project-row__move--up').attributes('title')).toBe('Up 4 since yesterday')
    expect(row.get('.project-row__name a').attributes('href')).toBe('https://github.com/acme/rocket')
    expect(row.get('.project-row__desc').text()).toContain('A rocket for agents, written out in full instead of cut short after one line.')
    expect(row.get('.project-row__desc').text()).toContain('321 forks')
    expect(row.get('.project-row__stars').attributes('title')).toBe('12,345 GitHub stars')
    expect(row.get('.project-row__gain').text()).toContain('+420')
    expect(row.get('.project-row__gain').classes()).not.toContain('project-row__gain--flat')
    expect(row.get('.project-row__heat').classes()).not.toContain('project-row__heat--flat')
  })

  it('marks newcomers and unmoved rows, and drops the rank column for unranked sorts', async () => {
    const row = mountRow({ movement: { kind: 'new' } })
    expect(row.get('.project-row__move--new').text()).toContain('NEW')

    await row.setProps({ movement: { kind: 'same' } })
    expect(row.get('.project-row__move--same').attributes('title')).toBe('Same place as yesterday')

    await row.setProps({ position: null, movement: null })
    expect(row.find('.project-row__rank').exists()).toBe(false)
    expect(row.classes()).not.toContain('project-row--podium')
  })

  it('shows three tags and keeps the rest behind a toggle that wraps together with the last tag', async () => {
    const row = mountRow()
    const labels = () => row.findAll('.project-row__chip:not(.project-row__chip--more)').map((chip) => chip.text())
    expect(labels()).toEqual(['agents', 'cli', 'rust'])

    const more = row.get('.project-row__chip-tail .project-row__chip--more')
    expect(more.text()).toBe('+1')
    expect(more.attributes('aria-expanded')).toBe('false')
    await more.trigger('click')
    expect(labels()).toEqual(['agents', 'cli', 'rust', 'mcp'])
    expect(row.get('.project-row__chip--more').attributes('aria-expanded')).toBe('true')

    const [, cli] = row.findAll('.project-row__chip')
    await cli?.trigger('click')
    expect(row.emitted('chipClick')?.[0]?.[0]).toMatchObject({ type: 'tag', value: 'cli' })

    await row.setProps({ repo: repo({ tags: ['agents', 'cli'] }) })
    expect(row.find('.project-row__chip--more').exists()).toBe(false)
  })

  it('lets the list hold the tag toggle, so the keyboard can open and close a row\'s tags', async () => {
    const onUpdate = vi.fn()
    const row = mountRow({ tagsOpen: true, 'onUpdate:tagsOpen': onUpdate })
    const labels = () => row.findAll('.project-row__chip:not(.project-row__chip--more)').map((chip) => chip.text())
    expect(labels()).toEqual(['agents', 'cli', 'rust', 'mcp'])

    await row.get('.project-row__chip--more').trigger('click')
    expect(onUpdate).toHaveBeenCalledWith(false)
    // 列表说了算：它收起之前还是全部标签
    expect(labels()).toEqual(['agents', 'cli', 'rust', 'mcp'])
    await row.setProps({ tagsOpen: false })
    expect(labels()).toEqual(['agents', 'cli', 'rust'])
  })

  it('reports opening the repository from the name or the link icon, middle click included', async () => {
    const row = mountRow()
    // jsdom 不跟外链
    row.element.addEventListener('click', (event: Event) => event.preventDefault())
    await row.get('.project-row__name a').trigger('click')
    await row.get('.project-row__link').trigger('click')
    await row.get('.project-row__link').trigger('auxclick', { button: 1 })
    await row.get('.project-row__link').trigger('auxclick', { button: 2 })
    await row.get('.project-row__favorite').trigger('click')
    expect(row.emitted('visit')).toHaveLength(3)
    expect(row.emitted('visit')?.[0]?.[0]).toMatchObject({ full_name: 'acme/rocket' })
  })

  it('mutes rows without growth or heat, and shows a dash while heat is not counted yet', async () => {
    const row = mountRow({ repo: repo({ rolling_24h_star_growth: 0, hot_score: 0 }) })
    expect(row.get('.project-row__gain').classes()).toContain('project-row__gain--flat')
    expect(row.get('.project-row__heat').text()).toContain('0.0')
    expect(row.get('.project-row__heat').classes()).toContain('project-row__heat--flat')
    expect(row.get('.project-row__meta-heat').classes()).toContain('project-row__heat--flat')

    await row.setProps({ repo: repo({ rolling_24h_star_growth: null, daily_growth_available: false, hot_score: 0 }) })
    expect(row.get('.project-row__heat').text()).toContain('—')
    expect(row.get('.project-row__heat').classes()).toContain('project-row__heat--flat')
  })

  it('favourites from the row, offers picks only to curators and locks the star when favouriting is off', async () => {
    const row = mountRow()
    expect(row.find('.project-row__recommend').exists()).toBe(false)
    await row.get('.project-row__favorite').trigger('click')
    expect(row.emitted('favorite')?.[0]?.[0]).toMatchObject({ full_name: 'acme/rocket' })

    await row.setProps({ canRecommend: true, repo: repo({ is_recommended: true }) })
    expect(row.find('.project-row__pick').exists()).toBe(true)
    expect(row.get('.project-row__recommend').attributes('aria-pressed')).toBe('true')
    await row.get('.project-row__recommend').trigger('click')
    expect(row.emitted('recommend')).toHaveLength(1)

    await row.setProps({ canFavorite: false })
    expect(row.get('.project-row__favorite').attributes('disabled')).toBeDefined()
  })

  it('keeps a repository that went missing in place, dimmed and labelled', () => {
    const row = mountRow({ repo: repo({ availability_status: 'not_found' }) })
    expect(row.classes()).toContain('project-row--not-found')
    expect(row.find('.project-row__gone').exists()).toBe(true)
  })
})
