import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ProjectPane from './ProjectPane.vue'
import i18n, { DEFAULT_LOCALE } from '@/i18n'
import type { PeekContent, PeekCurveState } from '@/composables/useProjectPeek'
import type { GitHubProjectItem, GitHubProjectPeek } from '@/services/projects/projectApi'

const repo = (overrides: Partial<GitHubProjectItem> = {}): GitHubProjectItem => ({
  full_name: 'acme/rocket',
  description_en: 'A rocket for agents, written out in full.',
  stars: 12345,
  forks: 321,
  open_issues: 17,
  language: 'Rust',
  created_at: '2025-03-04T00:00:00Z',
  pushed_at: '2026-09-30T10:00:00Z',
  tags: ['agents', 'cli', 'rust', 'mcp'],
  hot_score: 14,
  rolling_24h_star_growth: 420,
  ...overrides,
})

const peek = (overrides: Partial<GitHubProjectPeek> = {}): GitHubProjectPeek => ({
  repo_id: 'acme/rocket',
  status: 'ok',
  has_readme: true,
  readme: ['Rocket is a launcher for agents.'],
  readme_more: false,
  commit: null,
  ...overrides,
})

const RISING: PeekCurveState = {
  status: 'ready',
  metricDate: '2026-10-02',
  days: 30,
  points: [
    { date: '2026-10-01', stars: 12000, gain: null },
    { date: '2026-10-02', stars: 12345, gain: 345 },
  ],
}

const mountPane = (props: Record<string, unknown> = {}) => {
  const pane = mount(ProjectPane, {
    props: {
      repo: repo(),
      target: { key: 'github:acme/rocket', repoId: 'acme/rocket' },
      content: { status: 'ready', peek: peek() } as PeekContent,
      curve: RISING,
      position: 21,
      total: 340,
      direction: 0,
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
  // jsdom 不跟外链
  pane.element.addEventListener('click', (event: Event) => {
    if ((event.target as Element).closest('a')) event.preventDefault()
  })
  return pane
}

const facts = (pane: ReturnType<typeof mountPane>) => pane.findAll('.project-pane__fact').map((fact) => [fact.get('dt').text(), fact.get('dd').text()])

describe('ProjectPane', () => {
  beforeEach(() => { i18n.global.locale.value = 'en-US' })
  afterEach(() => { i18n.global.locale.value = DEFAULT_LOCALE })

  it('lays out the whole project: name, full description, figures, every tag, actions and the quick look', () => {
    const pane = mountPane()
    expect(pane.attributes('aria-label')).toBe('Details: acme/rocket')
    expect(pane.get('.project-pane__count').attributes('aria-label')).toBe('Project 21 of 340')
    expect(pane.get('.project-pane__count').text()).toBe('21/340')
    expect(pane.get('.project-pane__name a').attributes()).toMatchObject({ href: 'https://github.com/acme/rocket', target: '_blank', rel: 'noopener noreferrer' })
    expect(pane.get('.project-pane__owner').text()).toBe('acme/')
    expect(pane.get('.project-pane__desc').text()).toBe('A rocket for agents, written out in full.')
    expect(facts(pane)).toEqual([
      ['Stars', '12.3K'],
      ['24h', '+420'],
      ['Heat', expect.stringMatching(/^\d+\.\d$/)],
      ['Forks', '321'],
      ['Open issues', '17'],
      ['Language', 'Rust'],
      ['Created', new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: 'numeric' }).format(new Date(repo().created_at!))],
      ['Last push', expect.any(String)],
    ])
    expect(pane.get('.project-pane__fact--stars dd').attributes('title')).toBe('12,345 GitHub stars')
    // 标签全摆出来（最多五个，语言也算一个）
    expect(pane.findAll('.project-pane__chip').map((chip) => chip.text())).toEqual(['agents', 'cli', 'rust', 'mcp', 'Rust'])
    expect(pane.get('.project-pane__action.is-primary').text()).toBe('Open on GitHub')
    expect(pane.get('.project-pane__favorite').text()).toBe('Favorite')
    expect(pane.find('.project-pane__recommend').exists()).toBe(false)
    expect(pane.findAll('.project-peek__readme').map((p) => p.text())).toEqual(['Rocket is a launcher for agents.'])
    // 曲线紧跟一组数字，README 和最近一次提交在动作下面
    expect(pane.get('.project-pane__facts').element.nextElementSibling?.classList.contains('project-pane__curve')).toBe(true)
    expect(pane.get('.project-pane__curve').find('.project-peek__curve').exists()).toBe(true)
    expect(pane.find('.project-pane__peek .project-peek__curve').exists()).toBe(false)
    expect(pane.find('.project-peek__retry').exists()).toBe(false)
    expect(pane.get('.project-pane__keys').text()).toContain('Esc')
  })

  it('leaves out the figures a repository does not have, and mutes a quiet one', () => {
    const pane = mountPane({ repo: repo({ forks: null, open_issues: null, language: null, created_at: null, pushed_at: null, hot_score: null, rolling_24h_star_growth: 0, daily_star_growth: 0 }) })
    expect(facts(pane).map(([label]) => label)).toEqual(['Stars', '24h', 'Heat'])
    expect(pane.get('.project-pane__fact--gain').classes()).toContain('is-flat')
  })

  it('shows pending instead of zero when growth has not been counted', () => {
    const pane = mountPane({ repo: repo({ rolling_24h_star_growth: null, daily_growth_available: false, daily_star_growth: 0 }) })
    expect(pane.get('.project-pane__fact--gain dd').text()).toBe('Pending')
    expect(pane.get('.project-pane__fact--gain').classes()).toContain('is-flat')
  })

  it('steps, closes, favourites, recommends, filters by a tag and counts GitHub links as a visit', async () => {
    const pane = mountPane({ canRecommend: true })
    const [prev, next, close] = pane.findAll('.project-pane__btn')
    await prev!.trigger('click')
    await next!.trigger('click')
    await close!.trigger('click')
    expect(pane.emitted('step')).toEqual([[-1], [1]])
    expect(pane.emitted('close')).toHaveLength(1)

    await pane.get('.project-pane__favorite').trigger('click')
    await pane.get('.project-pane__recommend').trigger('click')
    await pane.findAll('.project-pane__chip')[1]!.trigger('click')
    expect(pane.emitted('favorite')?.[0]?.[0]).toMatchObject({ full_name: 'acme/rocket' })
    expect(pane.emitted('recommend')).toHaveLength(1)
    expect(pane.emitted('chipClick')?.[0]?.[0]).toMatchObject({ label: 'cli' })

    await pane.get('.project-pane__name a').trigger('click')
    await pane.get('.project-pane__action.is-primary').trigger('auxclick', { button: 1 })
    await pane.get('.project-peek__link').trigger('click')
    expect(pane.emitted('visit')).toHaveLength(3)
  })

  it('disables stepping past either end of the whole list', async () => {
    const pane = mountPane({ position: 1, total: 2 })
    const buttons = () => pane.findAll('.project-pane__btn')
    expect(buttons()[0]!.attributes('disabled')).toBeDefined()
    expect(buttons()[1]!.attributes('disabled')).toBeUndefined()
    await pane.setProps({ position: 2 })
    expect(buttons()[0]!.attributes('disabled')).toBeUndefined()
    expect(buttons()[1]!.attributes('disabled')).toBeDefined()
    await pane.setProps({ position: null })
    expect(pane.find('.project-pane__count').exists()).toBe(false)
    expect(buttons()[0]!.attributes('disabled')).toBeDefined()
    expect(buttons()[1]!.attributes('disabled')).toBeDefined()
    expect(buttons()[2]!.attributes('disabled')).toBeUndefined()
  })

  it('offers a retry where GitHub or the star history did not load', async () => {
    const pane = mountPane({ content: { status: 'error' }, curve: { status: 'error' } })
    const retries = pane.findAll('.project-peek__retry')
    expect(retries.map((button) => button.text())).toEqual(['Retry', 'Retry'])
    await retries[0]!.trigger('click')
    await retries[1]!.trigger('click')
    expect(pane.emitted('retry')).toHaveLength(2)

    await pane.setProps({ content: { status: 'ready', peek: peek({ status: 'unavailable', has_readme: false, readme: [] }) }, curve: RISING })
    expect(pane.findAll('.project-peek__retry')).toHaveLength(1)
    await pane.setProps({ content: { status: 'ready', peek: peek({ has_readme: false, readme: [] }) } })
    expect(pane.find('.project-peek__retry').exists()).toBe(false)
  })

  it('goes back to the top when it moves on to another project', async () => {
    const pane = mountPane()
    const scroller = pane.get('.project-pane__scroll').element as HTMLElement
    scroller.scrollTop = 240
    await pane.setProps({ target: { key: 'github:acme/other', repoId: 'acme/other' }, repo: repo({ full_name: 'acme/other' }), direction: 1 })
    expect(scroller.scrollTop).toBe(0)
    expect(pane.get('.project-pane__name').text()).toBe('acme/other')
  })

  it('speaks Chinese on the Chinese site', () => {
    i18n.global.locale.value = 'zh-CN'
    const pane = mountPane({ repo: repo({ description_zh: '给智能体用的火箭。' }) })
    expect(pane.attributes('aria-label')).toBe('acme/rocket 详情')
    expect(pane.get('.project-pane__kicker').text()).toBe('项目详情')
    expect(pane.get('.project-pane__count').attributes('aria-label')).toBe('第 21 个，共 340 个')
    expect(pane.get('.project-pane__desc').text()).toBe('给智能体用的火箭。')
    expect(facts(pane).map(([label]) => label)).toEqual(['星标', '24 小时', '热度', 'Fork 数', '未关 issue', '语言', '创建于', '最近推送'])
    expect(pane.get('.project-pane__action.is-primary').text()).toBe('去 GitHub 打开')
  })
})
