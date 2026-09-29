import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import XBoardView from './XBoardView.vue'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'

const controllerSpy = vi.hoisted(() => vi.fn())
const ctlBox = vi.hoisted(() => ({ current: null as null | Record<string, any> }))
const authBox = vi.hoisted(() => ({ current: null as null | { isAdmin: boolean } }))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  if (!authBox.current) authBox.current = reactive({ isAdmin: true })
  return { useAuthStore: () => authBox.current }
})

vi.mock('@/composables/useXBoardController', async () => {
  const { computed, ref } = await import('vue')
  const { clampPage, pageCount } = await import('@/features/xboard/xBoardViewModel')
  const pageSize = 20
  const page = ref(1)
  const unfollowedAccounts = ref<Set<string>>(new Set())
  const box: Record<string, any> = {
    availableAccounts: computed(() => Array.from(new Set(
      box.docs.value.map((tweet: TopDoc) => {
        const retweetedBy = typeof tweet.retweeted_by === 'string' ? tweet.retweeted_by.toLowerCase() : ''
        return retweetedBy || tweet.url?.match(/x\.com\/([^/]+)\/status/)?.[1]?.toLowerCase() || ''
      }))).filter(Boolean).sort()),
    availableAccountOptions: computed(() => box.availableAccounts.value.map((handle: string) => {
      const doc = box.docs.value.find((tweet: TopDoc) => {
        const owner = typeof tweet.retweeted_by === 'string'
          ? tweet.retweeted_by.toLowerCase()
          : tweet.url?.match(/x\.com\/([^/]+)\/status/)?.[1]?.toLowerCase()
        return owner === handle
      })
      return { handle, displayName: doc?.followed_account_name || doc?.author_name || `@${handle}` }
    })),
    availableDates: ref<string[]>([]),
    clearSelection: vi.fn(() => { box.selectedIds.value = new Set() }),
    currentPage: computed(() => clampPage(page.value, box.totalPages.value)),
    daysBack: ref(0),
    deleteSelected: vi.fn(async () => ({ deleted: 0, notFound: 0 })),
    deleting: ref(false),
    dispose: vi.fn(),
    docs: ref<TopDoc[]>([]),
    errorMsg: ref(''),
    followAllAccounts: vi.fn(() => { unfollowedAccounts.value = new Set(); page.value = 1 }),
    followedAccounts: computed(() => box.availableAccounts.value.filter((handle: string) => !unfollowedAccounts.value.has(handle))),
    goPage: vi.fn((next: number) => { page.value = clampPage(next, box.totalPages.value) }),
    hasNext: computed(() => box.currentPage.value < box.totalPages.value),
    hasPrev: computed(() => box.currentPage.value > 1),
    load: vi.fn(),
    loading: ref(false),
    onDateChange: vi.fn(),
    pageSize,
    refresh: vi.fn(),
    selectedDate: ref('2026-08-04'),
    selectedIds: ref<Set<string>>(new Set()),
    showRecent: vi.fn(),
    today: '2026-08-04',
    toggleSelectAll: vi.fn((ids: string[]) => {
      if (!ids.length) return
      const next = new Set<string>(box.selectedIds.value)
      if (ids.every((id) => next.has(id))) ids.forEach((id) => next.delete(id))
      else ids.forEach((id) => next.add(id))
      box.selectedIds.value = next
    }),
    toggleFollowAccount: vi.fn((handle: string) => {
      const next = new Set(unfollowedAccounts.value)
      if (next.has(handle)) next.delete(handle)
      else next.add(handle)
      unfollowedAccounts.value = next
      page.value = 1
    }),
    toggleSelection: vi.fn((docId: string) => {
      const next = new Set<string>(box.selectedIds.value)
      if (next.has(docId)) next.delete(docId)
      else next.add(docId)
      box.selectedIds.value = next
    }),
    totalPages: computed(() => pageCount(box.visibleDocs.value.length, pageSize)),
    unfollowAllAccounts: vi.fn(() => { unfollowedAccounts.value = new Set(box.availableAccounts.value); page.value = 1 }),
    unfollowedAccounts,
    visibleDocs: computed(() => box.docs.value.filter((tweet: TopDoc) => {
      const retweetedBy = typeof tweet.retweeted_by === 'string' ? tweet.retweeted_by.toLowerCase() : ''
      const handle = retweetedBy || tweet.url?.match(/x\.com\/([^/]+)\/status/)?.[1]?.toLowerCase() || ''
      return !handle || !unfollowedAccounts.value.has(handle)
    })),
    // 测试专用：视图不消费，供 beforeEach 复位页码
    __page: page,
  }
  ctlBox.current = box
  return { useXBoardController: controllerSpy.mockReturnValue(box) }
})

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {},
  missingWarn: false,
  fallbackWarn: false,
})

// jsdom 未实现 Element.scrollTo；视图分页回顶依赖它
const scrollToSpy = vi.fn()
Element.prototype.scrollTo = scrollToSpy as unknown as Element['scrollTo']

const controller = () => ctlBox.current as Record<string, any>

const makeTweets = (count: number): TopDoc[] => (
  Array.from({ length: count }, (_, i) => ({
    id: `tw${i}`,
    title: `Tweet ${i}`,
    summary: `Tweet ${i} body`,
    url: `https://x.com/alice/status/${1000 + i}`,
    raw_score: count - i,
    // i 越小越新：timelineTweets 排序后应保持 0,1,2,… 顺序
    published_at: new Date(Date.UTC(2026, 7, 4, 12, 0, 0) - i * 60_000).toISOString(),
  }))
)

const mounted: VueWrapper[] = []
const mountView = async () => {
  const wrapper = mount(XBoardView, {
    attachTo: document.body,
    global: {
      plugins: [i18n],
      stubs: { Teleport: true },
    },
  })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

const setViewportWidth = (width: number) => {
  Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: width })
}

beforeEach(() => {
  const ctl = controller()
  for (const [key, value] of Object.entries(ctl)) {
    if (typeof value === 'function' && 'mockClear' in value) value.mockClear()
    void key
  }
  ctl.docs.value = []
  ctl.selectedIds.value = new Set()
  ctl.errorMsg.value = ''
  ctl.loading.value = false
  ctl.deleting.value = false
  ctl.availableDates.value = []
  ctl.unfollowedAccounts.value = new Set()
  ctl.selectedDate.value = '2026-08-04'
  ctl.__page.value = 1
  authBox.current!.isAdmin = true
  controllerSpy.mockClear()
  scrollToSpy.mockClear()
  setViewportWidth(1024)
})

afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
  document.body.innerHTML = ''
})

const nextPageButton = (wrapper: VueWrapper) => {
  const buttons = wrapper.find('.xboard-pagination').findAll('button')
  return buttons[buttons.length - 1]!
}

describe('XBoardView video playback', () => {
  it.each([true, false])('loads the advertised variant when available=%s', async (hasVariant) => {
    const [doc] = makeTweets(1)
    doc!.media = [{ type: 'video', url: 'https://video.twimg.com/original.mp4',
      ...(hasVariant ? { playback_url: 'https://video.twimg.com/small.mp4' } : {}),
    }]
    controller().docs.value = [doc]
    const wrapper = await mountView()
    expect(wrapper.find('video').exists()).toBe(false)
    await wrapper.get('.tweet-video-btn').trigger('click')
    expect(wrapper.get('video').attributes('src')).toBe(
      `/api/media/x/img/video.twimg.com/${hasVariant ? 'small' : 'original'}.mp4`,
    )
  })
})

describe('XBoardView 分页 × 分列 × 页级全选接线', () => {
  it('默认关注全部账号，并可按账号即时筛选推文', async () => {
    const tweets = makeTweets(3)
    tweets[0]!.author_name = 'Alice Zhang'
    tweets[1]!.url = 'https://x.com/openai/status/1001'
    tweets[1]!.followed_account_name = 'OpenAI'
    tweets[2]!.url = 'https://x.com/anthropic/status/1002'
    tweets[2]!.author_name = 'Anthropic'
    controller().docs.value = tweets
    const wrapper = await mountView()

    // 关注账号侧栏默认收起：开关按钮显示已关注数，推文墙照常展示
    const toggle = wrapper.get('.xboard-follow-toggle')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.text()).toContain('3/3')
    expect(wrapper.find('.xboard-follow-panel').exists()).toBe(false)
    expect(wrapper.findAll('article.tweet-card')).toHaveLength(3)

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('.xboard-follow-panel').attributes('id')).toBe(toggle.attributes('aria-controls'))
    const chips = wrapper.findAll('.xboard-account-chip')
    expect(chips.map((chip) => chip.text())).toEqual(['Alice Zhang', 'Anthropic', 'OpenAI'])
    expect(chips.every((chip) => (chip.find('input').element as HTMLInputElement).checked)).toBe(true)

    await chips[0]!.find('input').trigger('change')
    await nextTick()
    expect(controller().toggleFollowAccount).toHaveBeenCalledWith('alice')
    expect(wrapper.findAll('article.tweet-card')).toHaveLength(2)
    expect(toggle.text()).toContain('2/3')

    // 侧栏内收起：筛选结果保留
    await wrapper.get('.xboard-follow-close').trigger('click')
    expect(wrapper.find('.xboard-follow-panel').exists()).toBe(false)
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.findAll('article.tweet-card')).toHaveLength(2)
  })

  it('桌面端展开关注账号侧栏时推文墙少排一列', async () => {
    setViewportWidth(1280)
    controller().docs.value = makeTweets(12)
    const wrapper = await mountView()
    expect(wrapper.findAll('.masonry-col')).toHaveLength(4)

    await wrapper.get('.xboard-follow-toggle').trigger('click')
    expect(wrapper.findAll('.masonry-col')).toHaveLength(3)
    expect(wrapper.findAll('article.tweet-card')).toHaveLength(12)

    setViewportWidth(1024)
    window.dispatchEvent(new Event('resize'))
    await nextTick()
    expect(wrapper.findAll('.masonry-col')).toHaveLength(2)

    // 窄屏侧栏叠在推文墙上方，列数不受影响
    setViewportWidth(800)
    window.dispatchEvent(new Event('resize'))
    await nextTick()
    expect(wrapper.findAll('.masonry-col')).toHaveLength(2)
  })

  it('挂载即调用 load，并把当前页推文按估高贪心分进 JS 列', async () => {
    controller().docs.value = makeTweets(25)
    const wrapper = await mountView()

    expect(controllerSpy).toHaveBeenCalledOnce()
    expect(controller().load).toHaveBeenCalledTimes(1)

    // 25 条 > 单页 20：首屏只渲染第一页 20 张卡
    expect(wrapper.findAll('article.tweet-card')).toHaveLength(20)

    // jsdom 视口 1024 → 3 列；测试卡等高，估高贪心在同高时取最左列，
    // 分布退化为轮询：第 i 条进第 i % 3 列（7/7/6）
    const columns = wrapper.findAll('.masonry-col')
    expect(columns).toHaveLength(3)
    expect(columns[0]!.findAll('.tweet-card')).toHaveLength(7)
    expect(columns[1]!.findAll('.tweet-card')).toHaveLength(7)
    expect(columns[2]!.findAll('.tweet-card')).toHaveLength(6)

    // 每列自上而下是索引步进列数的子序列（列内保持时间降序）
    const colTexts = columns.map((col) => col.findAll('.tweet-card').map((card) => card.text()))
    expect(colTexts[0]!.every((text, i) => text.includes(`Tweet ${i * 3} body`))).toBe(true)
    expect(colTexts[1]!.every((text, i) => text.includes(`Tweet ${i * 3 + 1} body`))).toBe(true)
    expect(colTexts[2]!.every((text, i) => text.includes(`Tweet ${i * 3 + 2} body`))).toBe(true)
  })

  it('视口跨过断点后按新列数重新分列', async () => {
    controller().docs.value = makeTweets(25)
    const wrapper = await mountView()
    expect(wrapper.findAll('.masonry-col')).toHaveLength(3)

    setViewportWidth(1280)
    window.dispatchEvent(new Event('resize'))
    await nextTick()

    const columns = wrapper.findAll('.masonry-col')
    expect(columns).toHaveLength(4)
    expect(columns.every((col) => col.findAll('.tweet-card').length === 5)).toBe(true)
    expect(columns[1]!.text()).toContain('Tweet 1 body')
  })

  it('翻页走控制器 goPage：渲染第二页切片并滚动回顶', async () => {
    controller().docs.value = makeTweets(25)
    const wrapper = await mountView()

    const pagination = wrapper.find('.xboard-pagination')
    expect(pagination.exists()).toBe(true)
    const buttons = pagination.findAll('button')
    expect((buttons[0]!.element as HTMLButtonElement).disabled).toBe(true)
    expect((buttons[1]!.element as HTMLButtonElement).disabled).toBe(false)

    await buttons[1]!.trigger('click')
    await nextTick()

    expect(controller().goPage).toHaveBeenCalledWith(2)
    expect(scrollToSpy).toHaveBeenCalledWith({ top: 0 })
    const cards = wrapper.findAll('article.tweet-card')
    expect(cards).toHaveLength(5)
    expect(cards[0]!.text()).toContain('Tweet 20 body')
  })

  it('页级全选只切换当前页 id，不波及不可见条目', async () => {
    controller().docs.value = makeTweets(25)
    const wrapper = await mountView()

    const selectAll = wrapper.find('.xboard-toolbar input[type="checkbox"]')
    expect(selectAll.exists()).toBe(true)
    await selectAll.trigger('change')
    await nextTick()

    const pageOneIds = Array.from({ length: 20 }, (_, i) => `tw${i}`)
    expect(controller().toggleSelectAll).toHaveBeenNthCalledWith(1, pageOneIds)
    expect(controller().selectedIds.value.size).toBe(20)
    expect((selectAll.element as HTMLInputElement).checked).toBe(true)

    // 翻到第二页后再次全选：只并入第二页 5 个 id
    await nextPageButton(wrapper).trigger('click')
    await nextTick()
    await wrapper.find('.xboard-toolbar input[type="checkbox"]').trigger('change')
    await nextTick()

    expect(controller().toggleSelectAll).toHaveBeenNthCalledWith(2, ['tw20', 'tw21', 'tw22', 'tw23', 'tw24'])
    expect(controller().selectedIds.value.size).toBe(25)
  })

  it('非管理员不渲染多选工具栏与卡头复选框', async () => {
    authBox.current!.isAdmin = false
    controller().docs.value = makeTweets(3)
    const wrapper = await mountView()

    expect(wrapper.find('.xboard-toolbar').exists()).toBe(false)
    expect(wrapper.findAll('.tweet-head input[type="checkbox"]')).toHaveLength(0)
  })

  it('纯转贴卡片在作者行之上标注转贴者，普通推文不渲染该行', async () => {
    const [rt, plain] = makeTweets(2)
    rt!.retweeted_by = 'watcher'
    controller().docs.value = [rt!, plain!]
    const wrapper = await mountView()

    const cards = wrapper.findAll('article.tweet-card')
    const rtCard = cards.find((card) => card.text().includes('Tweet 0 body'))!
    const plainCard = cards.find((card) => card.text().includes('Tweet 1 body'))!

    const line = rtCard.find('.tweet-retweet-line')
    expect(line.exists()).toBe(true)
    const link = line.find('a.tweet-retweet-link')
    expect(link.attributes('href')).toBe('https://x.com/watcher')
    expect(link.text()).toBe('@watcher')
    // 转贴行在作者头行之前（先标转贴者，再显原作者）
    expect(rtCard.html().indexOf('tweet-retweet-line')).toBeLessThan(rtCard.html().indexOf('tweet-head'))
    expect(plainCard.find('.tweet-retweet-line').exists()).toBe(false)
  })
})

describe('XBoardView 详情浮层焦点管理', () => {
  it('打开聚焦关闭钮，ESC 关闭后焦点还原触发元素', async () => {
    controller().docs.value = makeTweets(1)
    const wrapper = await mountView()

    const textEl = wrapper.find('.tweet-text')
    expect(textEl.attributes('role')).toBe('button')
    expect(textEl.attributes('tabindex')).toBe('0')
    ;(textEl.element as HTMLElement).focus()
    await textEl.trigger('click')
    await flushPromises()

    const dialog = wrapper.find('.detail-backdrop')
    expect(dialog.exists()).toBe(true)
    expect(document.activeElement).toBe(wrapper.find('.detail-close').element)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(wrapper.find('.detail-backdrop').exists()).toBe(false)
    expect(document.activeElement).toBe(textEl.element)
  })
})

describe('XBoardView 浮层期间 dock 抑制', () => {
  it('详情浮层打开期间 dockSuppressed 为 true，关闭后恢复', async () => {
    const { dockSuppressed } = await import('@/composables/useDockSuppression')
    controller().docs.value = makeTweets(1)
    const wrapper = await mountView()
    expect(dockSuppressed.value).toBe(false)

    await wrapper.find('.tweet-text').trigger('click')
    await flushPromises()
    expect(wrapper.find('.detail-backdrop').exists()).toBe(true)
    expect(dockSuppressed.value).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.find('.detail-backdrop').exists()).toBe(false)
    expect(dockSuppressed.value).toBe(false)
  })

  it('视图带浮层卸载时自动归还抑制计数', async () => {
    const { dockSuppressed } = await import('@/composables/useDockSuppression')
    controller().docs.value = makeTweets(1)
    const wrapper = await mountView()

    await wrapper.find('.tweet-text').trigger('click')
    await flushPromises()
    expect(dockSuppressed.value).toBe(true)

    wrapper.unmount()
    expect(dockSuppressed.value).toBe(false)
    // afterEach 的重复 unmount 不会把计数压成负数
    expect(dockSuppressed.value).toBe(false)
  })
})
