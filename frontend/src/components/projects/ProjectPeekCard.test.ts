import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ProjectPeekCard from './ProjectPeekCard.vue'
import i18n, { DEFAULT_LOCALE } from '@/i18n'
import type { PeekContent, PeekCurveState } from '@/composables/useProjectPeek'
import type { GitHubProjectItem, GitHubProjectPeek } from '@/services/projects/projectApi'
import type { PeekPlacement } from '@/features/projects/projectPeek'

const repo = (overrides: Partial<GitHubProjectItem> = {}): GitHubProjectItem => ({
  full_name: 'acme/rocket',
  stars: 12345,
  pushed_at: '2026-09-30T10:00:00Z',
  ...overrides,
})

const COMMIT_URL = 'https://github.com/acme/rocket/commit/abcdef1234567890'

const peek = (overrides: Partial<GitHubProjectPeek> = {}): GitHubProjectPeek => ({
  repo_id: 'acme/rocket',
  status: 'ok',
  has_readme: true,
  readme: ['Rocket is a launcher for agents.', 'It runs anywhere a shell does.'],
  readme_more: true,
  commit: { sha: 'abcdef1234567890', message: 'Fix the parser', author: 'octo', committed_at: '2026-10-01T08:00:00Z', url: COMMIT_URL },
  ...overrides,
})

/** 截至 10 月 2 日的最后几天，每天一个累计星标数 */
const curveOf = (...stars: number[]): PeekCurveState => {
  const dates = ['2026-09-30', '2026-10-01', '2026-10-02'].slice(-stars.length)
  return {
    status: 'ready',
    metricDate: '2026-10-02',
    days: 30,
    points: stars.map((count, index) => ({ date: dates[index]!, stars: count, gain: null })),
  }
}

const RISING: PeekCurveState = {
  status: 'ready',
  metricDate: '2026-10-02',
  days: 30,
  points: [
    { date: '2026-09-30', stars: 12000, gain: null },
    { date: '2026-10-01', stars: 12200, gain: 200 },
    { date: '2026-10-02', stars: 12345, gain: 145 },
  ],
}

const BELOW: PeekPlacement = { top: 120, above: false, maxHeight: 400 }

const mountCard = (
  content: PeekContent,
  curve: PeekCurveState = RISING,
  { item = repo(), placement = BELOW }: { item?: GitHubProjectItem; placement?: PeekPlacement } = {},
) => {
  const card = mount(ProjectPeekCard, {
    props: { repo: item, repoId: 'acme/rocket', content, curve, placement },
    global: { plugins: [i18n] },
  })
  // jsdom 不导航：只看点没点到
  card.element.addEventListener('click', (event: Event) => event.preventDefault())
  return card
}

const sections = (card: ReturnType<typeof mountCard>) => card.findAll('.project-peek__part')

describe('ProjectPeekCard', () => {
  beforeEach(() => { i18n.global.locale.value = 'en-US' })
  afterEach(() => { i18n.global.locale.value = DEFAULT_LOCALE })

  it("reads the README's opening, the latest commit and thirty days of stars", () => {
    const card = mountCard({ status: 'ready', peek: peek() })

    expect(card.attributes('aria-label')).toBe('Quick look: acme/rocket')
    expect(card.attributes('style')).toContain('top: 120px')
    expect(card.attributes('style')).toContain('--peek-max: 400px')
    expect(card.classes()).not.toContain('project-peek--above')
    expect(card.get('.project-peek__owner').text()).toBe('acme/')
    expect(card.get('.project-peek__name').text()).toBe('acme/rocket')
    expect(card.get('.project-peek__stars').attributes('title')).toBe('12,345 GitHub stars')

    expect(card.findAll('.project-peek__readme').map((p) => p.text())).toEqual([
      'Rocket is a launcher for agents.',
      'It runs anywhere a shell does.',
    ])
    const more = card.get('.project-peek__link')
    expect(more.text()).toBe('Read the rest on GitHub')
    expect(more.attributes()).toMatchObject({ href: 'https://github.com/acme/rocket#readme', target: '_blank', rel: 'noopener noreferrer' })

    expect(card.get('.project-peek__commit').text()).toBe('Fix the parser')
    expect(card.get('.project-peek__commit').attributes('href')).toBe(COMMIT_URL)
    expect(card.get('.project-peek__sha').text()).toBe('abcdef1')
    expect(card.get('.project-peek__facts').text()).toContain('octo')
    expect(card.get('.project-peek__facts time').attributes('datetime')).toBe('2026-10-01T08:00:00Z')
    expect(card.get('.project-peek__facts time').attributes('title')).toBeTruthy()

    expect(card.get('.project-peek__curve').attributes('aria-label')).toBe('Stars over the last 30 days: 12,000 on Sep 30, 12,345 on Oct 2 (+345)')
    expect(card.get('.project-peek__delta').classes()).toContain('project-peek__delta--up')
    expect(card.get('.project-peek__delta').text()).toBe('+345')
    expect(card.findAll('.project-peek__line')).toHaveLength(1)
    expect(card.findAll('.project-peek__area')).toHaveLength(1)
    expect(card.findAll('.project-peek__bridge')).toHaveLength(0)
    expect(card.get('.project-peek__dot').attributes('style')).toContain('left: 98.67%')
    // 横轴是 30 天窗口的头尾，曲线只占右边有数的那几天
    expect(card.findAll('.project-peek__axis span').map((span) => span.text())).toEqual(['Sep 3', 'Oct 2'])
    expect(card.findAll('[aria-busy="true"]')).toHaveLength(0)

    // 宽的时候分两栏：README 一栏，提交压着曲线另一栏
    expect(sections(card)[0]!.classes()).toContain('project-peek__part--readme')
    expect(card.get('.project-peek__side').findAll('.project-peek__part').map((part) => part.get('.project-peek__label').text()))
      .toEqual(['Latest commit', expect.stringContaining('Stars, last 30 days')])
  })

  it('opens on GitHub without "the rest" when the README ends there, and names a bare commit by its hash', () => {
    const card = mountCard({ status: 'ready', peek: peek({ readme_more: false, commit: { ...peek().commit!, message: '', author: '' } }) })
    expect(card.get('.project-peek__link').text()).toBe('Open on GitHub')
    expect(card.get('.project-peek__commit').text()).toBe('abcdef1')
    expect(card.get('.project-peek__facts').findAll('span')).toHaveLength(0)
  })

  it('counts following any GitHub link in the card as opening the repository', async () => {
    const card = mountCard({ status: 'ready', peek: peek() })
    await card.get('.project-peek__link').trigger('click')
    await card.get('.project-peek__commit').trigger('auxclick', { button: 1 })
    await card.get('.project-peek__commit').trigger('auxclick', { button: 2 })
    expect(card.emitted('visit')).toEqual([[repo()], [repo()]])
  })

  it('stands in skeletons while GitHub and the star history are read, and rises from the row when placed above', () => {
    const card = mountCard({ status: 'loading' }, { status: 'loading' }, { placement: { top: 300, above: true, maxHeight: 280 } })
    expect(card.classes()).toContain('project-peek--above')
    expect(sections(card)).toHaveLength(3)
    expect(card.findAll('[aria-busy="true"]')).toHaveLength(3)
    expect(sections(card)[0]!.findAll('.project-peek__skeleton')).toHaveLength(4)
    expect(sections(card)[1]!.findAll('.project-peek__skeleton')).toHaveLength(2)
    expect(sections(card)[2]!.find('.project-peek__skeleton--plot').exists()).toBe(true)
    expect(card.find('.project-peek__readme').exists()).toBe(false)
    expect(card.find('.project-peek__delta').exists()).toBe(false)
  })

  it("says GitHub can't be read and falls back to the catalog's last push, or leaves the commit out", () => {
    const unavailable = peek({ status: 'unavailable', has_readme: false, readme: [], readme_more: false, commit: null })
    const card = mountCard({ status: 'ready', peek: unavailable })
    expect(sections(card)[0]!.get('.project-peek__note').text()).toBe("GitHub can't be reached right now. Try again in a moment.")
    expect(sections(card)[0]!.find('a').exists()).toBe(false)
    expect(sections(card)[1]!.get('.project-peek__note').text()).toMatch(/^Last push /)

    const unpushed = mountCard({ status: 'ready', peek: unavailable }, RISING, { item: repo({ pushed_at: null }) })
    expect(sections(unpushed)).toHaveLength(2)
    expect(unpushed.find('.project-peek__commit').exists()).toBe(false)
  })

  it("says when the quick look didn't load", () => {
    const card = mountCard({ status: 'error' })
    expect(sections(card)[0]!.get('.project-peek__note').text()).toBe("The quick look didn't load. Try again in a moment.")
    expect(sections(card)[1]!.get('.project-peek__note').text()).toMatch(/^Last push /)
  })

  it('tells a README without an introduction from no README, and an empty repository from an unread one', () => {
    const prose = mountCard({ status: 'ready', peek: peek({ readme: [], readme_more: false, commit: null }) })
    expect(sections(prose)[0]!.get('.project-peek__note').text()).toContain('The README opens without a written introduction.')
    expect(sections(prose)[0]!.get('.project-peek__note a').text()).toBe('Open on GitHub')
    expect(sections(prose)[1]!.get('.project-peek__note').text()).toBe('No commits on the default branch yet.')

    const none = mountCard({ status: 'ready', peek: peek({ has_readme: false, readme: [], readme_more: false }) })
    expect(sections(none)[0]!.get('.project-peek__note').text()).toBe('This repository has no README.')
    expect(sections(none)[0]!.find('.project-peek__note a').exists()).toBe(false)
  })

  it('explains a missing curve and marks a falling or level one', () => {
    const ready: PeekContent = { status: 'ready', peek: peek() }
    expect(mountCard(ready, { status: 'error' }).get('.project-peek__part:last-child .project-peek__note').text())
      .toBe("The star history didn't load.")
    expect(mountCard(ready, curveOf(7)).get('.project-peek__part:last-child .project-peek__note').text())
      .toBe('Not enough daily star counts for the last 30 days yet.')

    const falling = mountCard(ready, curveOf(400, 345))
    expect(falling.get('.project-peek__delta').classes()).toContain('project-peek__delta--down')
    expect(falling.get('.project-peek__delta').text()).toBe('−55')
    const level = mountCard(ready, curveOf(345, 345))
    expect(level.get('.project-peek__delta').classes()).toContain('project-peek__delta--flat')
    expect(level.get('.project-peek__delta').text()).toBe('0')
  })

  it('speaks Chinese on the Chinese site', () => {
    i18n.global.locale.value = 'zh-CN'
    const card = mountCard({ status: 'ready', peek: peek() })
    expect(card.attributes('aria-label')).toBe('acme/rocket 速览')
    expect(card.get('.project-peek__link').text()).toBe('去 GitHub 读完')
    expect(card.findAll('.project-peek__label').map((label) => label.text())).toEqual(['README 开头', '最近一次提交', expect.stringContaining('近 30 天星标')])
  })
})
