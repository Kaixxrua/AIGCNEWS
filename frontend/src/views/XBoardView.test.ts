import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import XBoardView from './XBoardView.vue'
import { forgetSavedItems } from '@/composables/useSavedItems'
import { setAppDensity } from '@/composables/useAppDensity'
import { tweetReadId } from '@/features/xboard/xBoardViewModel'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'

// 桌面推文墙（≥1024px）的折叠、胶片、纯文字等按 useMediaQuery 判断；jsdom 没有 matchMedia，默认按手机与平板
const viewport = vi.hoisted(() => ({ desktop: false }))
vi.mock('@vueuse/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@vueuse/core')>()
  const { ref } = await import('vue')
  return {
    ...actual,
    useMediaQuery: (query: string) => (query === '(min-width: 1024px)' ? ref(viewport.desktop) : actual.useMediaQuery(query)),
  }
})

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
  // 桌面的快捷键表按需加载（components/keyboard/desktopParts.ts），挂上时就开始取；等包到了再开始操作。
  await vi.dynamicImportSettled()
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
  viewport.desktop = false
  localStorage.clear()
  forgetSavedItems()
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

describe('XBoardView 切换动效接线', () => {
  it('推文卡按链接带 data-reflow-key；换窗口加载期间墙变淡，首批推文一到即恢复', async () => {
    controller().docs.value = makeTweets(3)
    const wrapper = await mountView()
    expect(wrapper.findAll('article.tweet-card').map((card) => card.attributes('data-reflow-key'))).toEqual([
      'https://x.com/alice/status/1000', 'https://x.com/alice/status/1001', 'https://x.com/alice/status/1002',
    ])

    controller().loading.value = true
    await nextTick()
    expect(wrapper.get('.masonry-grid').classes()).toContain('masonry-grid--stale')
    controller().docs.value = makeTweets(2)
    await nextTick()
    expect(wrapper.get('.masonry-grid').classes()).not.toContain('masonry-grid--stale')
  })

  it('窗口开关：选中的一段带 xboard-window-active，切到历史日期时移到日期段', async () => {
    controller().docs.value = makeTweets(1)
    const wrapper = await mountView()
    const recent = wrapper.get('.xboard-window-switch .xboard-recent')
    const date = wrapper.get('.xboard-window-switch .xboard-date')
    expect(recent.classes()).toContain('xboard-window-active')
    expect(recent.attributes('aria-pressed')).toBe('true')
    expect(date.classes()).not.toContain('xboard-window-active')

    controller().selectedDate.value = '2026-08-01'
    await nextTick()
    expect(recent.classes()).not.toContain('xboard-window-active')
    expect(recent.attributes('aria-pressed')).toBe('false')
    expect(date.classes()).toContain('xboard-window-active')
  })
})

describe('XBoardView 桌面推文墙：同账号折叠、按卡位分页、纯文字与胶片', () => {
  beforeEach(() => {
    viewport.desktop = true
    setViewportWidth(1280)
    i18n.global.setLocaleMessage('zh-CN', {
      xboard: { foldMore: '＋{count} 条 {name} 的推文', foldShow: '展开', foldHide: '收起', readMore: '全文', seenLabel: '浏览过', seenRule: '上次看到这里', seenRuleCount: '此后新增 {count} 条' },
    })
  })

  afterEach(() => {
    i18n.global.setLocaleMessage('zh-CN', {})
    vi.restoreAllMocks()
    setAppDensity('compact')
  })

  // 按给定账号依次生成推文（越靠前越新）
  const byHandles = (handles: string[]): TopDoc[] => handles.map((handle, i) => ({
    id: `tw${i}`,
    title: `Tweet ${i}`,
    summary: `Tweet ${i} body`,
    url: `https://x.com/${handle}/status/${1000 + i}`,
    author_name: handle.charAt(0).toUpperCase() + handle.slice(1),
    raw_score: 1,
    published_at: new Date(Date.UTC(2026, 7, 4, 12, 0, 0) - i * 60_000).toISOString(),
  }))
  const wallCards = (wrapper: VueWrapper) => wrapper.findAll('.masonry-grid article.tweet-card')
  const wallBodies = (wrapper: VueWrapper) => wallCards(wrapper).map((card) => card.get('.tweet-text').text()).sort()

  it.each(['compact', 'comfortable'] as const)('%s 版面回看只显示浏览提示，打开详情和再次进入都保留完整卡片与进度线', async (density) => {
    setAppDensity(density)
    const tweets = byHandles(['alice', 'bob', 'carol'])
    controller().docs.value = tweets
    localStorage.setItem('read_marks_x', JSON.stringify({ [tweetReadId(tweets[1]!)]: Math.floor(Date.now() / 60_000) }))
    const wrapper = await mountView()
    const card = (index: number) => wallCards(wrapper).find((item) => item.get('.tweet-text').text() === `Tweet ${index} body`)!

    expect(wallCards(wrapper)).toHaveLength(3)
    expect(card(0).find('.tweet-seen-mark').exists()).toBe(false)
    expect(card(1).get('.tweet-time .tweet-seen-mark').text()).toBe('浏览过')
    expect(card(1).get('.tweet-text').text()).toBe('Tweet 1 body')
    expect(wrapper.find('.masonry-grid .is-read').exists()).toBe(false)
    expect(wrapper.get('.xboard-seen-rule__count').text()).toBe('此后新增 1 条')

    await card(0).get('.tweet-text').trigger('click')
    expect(wrapper.get('.detail-backdrop .tweet-text').text()).toContain('Tweet 0 body')
    expect(card(0).get('.tweet-seen-mark').text()).toBe('浏览过')
    expect(wrapper.find('.masonry-grid .is-read').exists()).toBe(false)
    // 本次打开不挪动进度线；再次进入时才按保留的浏览记录重新定位。
    expect(wrapper.get('.xboard-seen-rule__count').text()).toBe('此后新增 1 条')
    wrapper.unmount()
    mounted.splice(mounted.indexOf(wrapper), 1)
    const revisited = await mountView()
    expect(revisited.findAll('.tweet-seen-mark')).toHaveLength(2)
    expect(revisited.find('.masonry-grid .is-read').exists()).toBe(false)
    expect(wallCards(revisited)).toHaveLength(3)
    // 没有新增内容时不画空分隔线。
    expect(revisited.find('.xboard-seen-rule').exists()).toBe(false)
  })

  it('同一页里一个账号达到 3 条只留第一条，折叠行点开就地展开、再点收回', async () => {
    controller().docs.value = byHandles(['alice', 'bob', 'alice', 'carol', 'alice', 'alice'])
    const wrapper = await mountView()

    expect(wallBodies(wrapper)).toEqual(['Tweet 0 body', 'Tweet 1 body', 'Tweet 3 body'])
    const folds = wrapper.findAll('.tweet-fold')
    expect(folds).toHaveLength(1)
    const fold = folds[0]!
    // 折叠行挂在留下的第一条底下
    expect(fold.element.closest('article')?.textContent).toContain('Tweet 0 body')
    expect(fold.text()).toContain('＋3 条 Alice 的推文')
    expect(fold.text()).toContain('展开')
    expect(fold.attributes('aria-expanded')).toBe('false')

    await fold.trigger('click')
    await nextTick()
    expect(wallBodies(wrapper)).toEqual(['Tweet 0 body', 'Tweet 1 body', 'Tweet 2 body', 'Tweet 3 body', 'Tweet 4 body', 'Tweet 5 body'])
    expect(fold.attributes('aria-expanded')).toBe('true')
    expect(fold.text()).toContain('收起')

    await fold.trigger('click')
    await nextTick()
    expect(wallCards(wrapper)).toHaveLength(3)

    // 换一批推文时折叠全部收回
    await fold.trigger('click')
    controller().docs.value = byHandles(['alice', 'bob', 'alice', 'alice'])
    await nextTick()
    expect(wallCards(wrapper)).toHaveLength(2)
    expect(wrapper.get('.tweet-fold').attributes('aria-expanded')).toBe('false')
  })

  it('按卡位分页：折叠收起的不占卡位，一页收进的推文可以多于 20 条', async () => {
    // alice 10 条在前，其后 20 个账号各 1 条：第一页 alice 一张卡 + 19 张，共 29 条；第二页 1 条
    const handles = [...Array.from({ length: 10 }, () => 'alice'), ...Array.from({ length: 20 }, (_, i) => `user${i}`)]
    controller().docs.value = byHandles(handles)
    const wrapper = await mountView()

    expect(wallCards(wrapper)).toHaveLength(20)
    expect(wrapper.get('.tweet-fold').text()).toContain('＋9 条 Alice 的推文')
    expect(wrapper.find('.xboard-pagination').exists()).toBe(true)

    await nextPageButton(wrapper).trigger('click')
    await nextTick()
    expect(controller().goPage).toHaveBeenCalledWith(2)
    expect(wallBodies(wrapper)).toEqual(['Tweet 29 body'])
  })

  it('折叠后一页装得下就不出分页条', async () => {
    const handles = [...Array.from({ length: 10 }, () => 'alice'), ...Array.from({ length: 15 }, (_, i) => `user${i}`)]
    controller().docs.value = byHandles(handles)
    const wrapper = await mountView()

    expect(wallCards(wrapper)).toHaveLength(16)
    expect(wrapper.find('.xboard-pagination').exists()).toBe(false)
  })

  it('页级全选只选墙上看得见的，折叠收起的不算，展开后才算', async () => {
    controller().docs.value = byHandles(['alice', 'bob', 'alice', 'alice'])
    const wrapper = await mountView()

    await wrapper.get('.xboard-toolbar input[type="checkbox"]').trigger('change')
    expect(controller().toggleSelectAll).toHaveBeenLastCalledWith(['tw0', 'tw1'])

    await wrapper.get('.tweet-fold').trigger('click')
    await nextTick()
    await wrapper.get('.xboard-toolbar input[type="checkbox"]').trigger('change')
    expect(controller().toggleSelectAll).toHaveBeenLastCalledWith(['tw0', 'tw2', 'tw3', 'tw1'])
  })

  it('纯文字一键收起配图与链接卡，时间行留提示钮点开详情；选择记在本机', async () => {
    const [rich, plain] = byHandles(['alice', 'bob'])
    rich!.media = [{ type: 'photo', url: 'https://pbs.twimg.com/media/a.jpg', width: 1600, height: 900 }]
    rich!.link_card = { url: 'https://example.com', title: 'Example' }
    controller().docs.value = [rich!, plain!]
    const wrapper = await mountView()

    // 桌面链接卡横排
    expect(wrapper.findAll('.masonry-grid .tweet-media-list')).toHaveLength(1)
    expect(wrapper.get('.masonry-grid .tweet-linkcard').classes()).toContain('tweet-linkcard--row')
    expect(wrapper.find('.tweet-media-hint').exists()).toBe(false)

    const toggle = wrapper.get('.xboard-text-only')
    expect(toggle.attributes('aria-pressed')).toBe('false')
    await toggle.trigger('click')
    await nextTick()
    expect(toggle.attributes('aria-pressed')).toBe('true')
    expect(toggle.classes()).toContain('xboard-mode-active')
    expect(localStorage.getItem('xboard_text_only')).toBe('1')
    expect(wrapper.find('.masonry-grid .tweet-media-list').exists()).toBe(false)
    expect(wrapper.find('.masonry-grid .tweet-linkcard').exists()).toBe(false)

    const hints = wrapper.findAll('.tweet-media-hint')
    expect(hints).toHaveLength(1)
    expect(hints[0]!.element.closest('article')?.textContent).toContain('Tweet 0 body')
    await hints[0]!.trigger('click')
    await flushPromises()
    // 详情浮层照常带配图与链接卡，链接卡仍是竖排
    expect(wrapper.find('.detail-backdrop .tweet-media-list').exists()).toBe(true)
    expect(wrapper.get('.detail-backdrop .tweet-linkcard').classes()).not.toContain('tweet-linkcard--row')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    // 再开一次页面仍是纯文字
    wrapper.unmount()
    mounted.splice(mounted.indexOf(wrapper), 1)
    const again = await mountView()
    expect(again.get('.xboard-text-only').attributes('aria-pressed')).toBe('true')
    expect(again.find('.masonry-grid .tweet-media-list').exists()).toBe(false)

    await again.get('.xboard-text-only').trigger('click')
    await nextTick()
    expect(localStorage.getItem('xboard_text_only')).toBe('0')
    expect(again.findAll('.masonry-grid .tweet-media-list')).toHaveLength(1)
  })

  it('多图排成一行胶片：胶片里的视频帧点开详情，单个视频照常就地播放', async () => {
    const [strip, single] = byHandles(['alice', 'bob'])
    strip!.media = [
      { type: 'photo', url: 'https://pbs.twimg.com/media/a.jpg', width: 1600, height: 900 },
      { type: 'video', url: 'https://video.twimg.com/strip.mp4' },
    ]
    single!.media = [{ type: 'video', url: 'https://video.twimg.com/single.mp4' }]
    controller().docs.value = [strip!, single!]
    const wrapper = await mountView()

    const lists = wrapper.findAll('.masonry-grid .tweet-media-list')
    const stripList = lists.find((list) => list.classes('tweet-media-list--strip'))
    const singleList = lists.find((list) => !list.classes('tweet-media-list--strip'))
    expect(stripList?.element.closest('article')?.textContent).toContain('Tweet 0 body')
    expect(singleList?.element.closest('article')?.textContent).toContain('Tweet 1 body')

    await stripList!.get('.tweet-video-btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.detail-backdrop').exists()).toBe(true)
    expect(wrapper.find('.masonry-grid video').exists()).toBe(false)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    await singleList!.get('.tweet-video-btn').trigger('click')
    expect(wrapper.findAll('.masonry-grid video')).toHaveLength(1)
    expect(wrapper.find('.detail-backdrop').exists()).toBe(false)
  })

  it('正文被限行截住的推文，排好后时间行多一枚「全文」，点开看全文', async () => {
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('tweet-text') && this.textContent?.includes('LONG') ? 300 : 0
    })
    const [long, short] = byHandles(['alice', 'bob'])
    long!.summary = 'LONG body'
    controller().docs.value = [long!, short!]
    const wrapper = await mountView()

    // 列数一变就重新排、重新量
    setViewportWidth(1024)
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    const more = wrapper.findAll('.tweet-more')
    expect(more).toHaveLength(1)
    expect(more[0]!.text()).toBe('全文')
    expect(more[0]!.element.closest('article')?.textContent).toContain('LONG body')

    await more[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.get('.detail-backdrop .tweet-text').text()).toContain('LONG body')
  })

  it('键盘流：j 按时间线走、x 开合折叠，o 开详情后 j 换下一条，关掉详情光标落在最后看的那条', async () => {
    // jsdom 不排版：每张卡都算整张在视野里；详情浮层（aria-modal）算画出来了，列表键位让给它
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
      { top: 10, bottom: 90, left: 0, right: 300, width: 300, height: 80, x: 0, y: 10, toJSON: () => ({}) } as DOMRect,
    )
    vi.spyOn(Element.prototype, 'getClientRects').mockImplementation(function (this: Element) {
      return (this.getAttribute('aria-modal') === 'true' ? [{}] : []) as unknown as DOMRectList
    })
    controller().docs.value = byHandles(['alice', 'bob', 'alice', 'alice', 'carol'])
    const wrapper = await mountView()
    const press = async (key: string) => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
      await flushPromises()
    }
    const cursorCard = () => wrapper.get('.masonry-grid article.is-cursor')

    await press('j')
    expect(cursorCard().get('.tweet-text').text()).toBe('Tweet 0 body')
    expect(document.activeElement).toBe(cursorCard().element)

    // 在领头那条上按 x 展开，j 走进展开的组；组里按 x 收回，光标落回领头那条
    await press('x')
    expect(wrapper.get('.tweet-fold').attributes('aria-expanded')).toBe('true')
    await press('j')
    expect(cursorCard().get('.tweet-text').text()).toBe('Tweet 2 body')
    await press('x')
    expect(wrapper.get('.tweet-fold').attributes('aria-expanded')).toBe('false')
    expect(cursorCard().get('.tweet-text').text()).toBe('Tweet 0 body')

    await press('j')
    expect(cursorCard().get('.tweet-text').text()).toBe('Tweet 1 body')
    await press('o')
    expect(wrapper.get('.detail-backdrop .tweet-text').text()).toContain('Tweet 1 body')
    await press('j')
    expect(wrapper.get('.detail-backdrop .tweet-text').text()).toContain('Tweet 4 body')

    await press('Escape')
    expect(wrapper.find('.detail-backdrop').exists()).toBe(false)
    expect(cursorCard().get('.tweet-text').text()).toBe('Tweet 4 body')
    expect(document.activeElement).toBe(cursorCard().element)

    await press('?')
    expect(wrapper.find('.list-keys-sheet').exists()).toBe(true)
    await press('Escape')
    expect(wrapper.find('.list-keys-sheet').exists()).toBe(false)
    await press('Escape')
    expect(wrapper.find('.masonry-grid article.is-cursor').exists()).toBe(false)
  })

  it('收藏：书签或按 s 收下，「收藏」一段照收下的先后排、不折叠不显示浏览提示，在里面取消的留到离开再撤', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
      { top: 10, bottom: 90, left: 0, right: 300, width: 300, height: 80, x: 0, y: 10, toJSON: () => ({}) } as DOMRect,
    )
    vi.spyOn(Element.prototype, 'getClientRects').mockImplementation(function (this: Element) {
      return (this.getAttribute('aria-modal') === 'true' ? [{}] : []) as unknown as DOMRectList
    })
    controller().docs.value = byHandles(['alice', 'alice', 'alice', 'bob'])
    const wrapper = await mountView()
    const press = async (key: string) => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
      await flushPromises()
    }
    const card = (body: string) => wallCards(wrapper).find((item) => item.get('.tweet-text').text() === body)!
    const bodiesInOrder = () => wallCards(wrapper).map((item) => item.get('.tweet-text').text())
    // 窗口开关里一直有「收藏」一段，没收过时是 0
    expect(wrapper.get('.xboard-saved .xboard-saved-count').text()).toBe('0')

    // 卡片上的书签收下 bob 那条
    await card('Tweet 3 body').get('.save-toggle').trigger('click')
    expect(card('Tweet 3 body').get('.save-toggle').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('.xboard-saved .xboard-saved-count').text()).toBe('1')

    // s 收下光标停着的那条；折叠组展开后组里的也能收
    await press('j')
    await press('s')
    await press('x')
    await press('j')
    await press('s')
    // 详情里按 s 收下、取消正在看的这条，底栏的收藏钮跟着换
    await press('j')
    await press('o')
    const detailSave = () => wrapper.get('.detail-backdrop .detail-save')
    expect(detailSave().attributes('aria-pressed')).toBe('false')
    await press('s')
    expect(detailSave().attributes('aria-pressed')).toBe('true')
    await press('Escape')
    expect(wrapper.get('.xboard-saved .xboard-saved-count').text()).toBe('4')

    // 「收藏」一段：最近收的在前，不折叠；开过详情的那条只在窗口里显示浏览提示
    expect(card('Tweet 2 body').get('.tweet-seen-mark').text()).toBe('浏览过')
    await wrapper.get('.xboard-saved').trigger('click')
    expect(wrapper.get('.xboard-saved').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('.xboard-saved').classes()).toContain('xboard-window-active')
    expect(wrapper.get('.xboard-recent').classes()).not.toContain('xboard-window-active')
    expect(wrapper.find('.xboard-follow-toggle').exists()).toBe(false)
    expect(bodiesInOrder()).toEqual(['Tweet 2 body', 'Tweet 1 body', 'Tweet 0 body', 'Tweet 3 body'])
    expect(wrapper.find('.tweet-fold').exists()).toBe(false)
    expect(wrapper.find('.masonry-grid .tweet-seen-mark').exists()).toBe(false)
    expect(wrapper.find('.tweet-head input[type="checkbox"]').exists()).toBe(false)

    // 在收藏里取消的那条留在墙上，书签变空，计数先减；刷新按此刻重拍才撤下，不去重拉窗口
    await card('Tweet 1 body').get('.save-toggle').trigger('click')
    expect(card('Tweet 1 body').get('.save-toggle').attributes('aria-pressed')).toBe('false')
    expect(wallCards(wrapper)).toHaveLength(4)
    expect(wrapper.get('.xboard-saved .xboard-saved-count').text()).toBe('3')
    await wrapper.get('.xboard-refresh').trigger('click')
    expect(controller().refresh).not.toHaveBeenCalled()
    expect(bodiesInOrder()).toEqual(['Tweet 2 body', 'Tweet 0 body', 'Tweet 3 body'])

    // 点「最近 24 小时」回到窗口：窗口本来就是今天的，不重拉，折叠照旧
    await wrapper.get('.xboard-recent').trigger('click')
    expect(controller().showRecent).not.toHaveBeenCalled()
    expect(wrapper.get('.xboard-recent').classes()).toContain('xboard-window-active')
    expect(wrapper.get('.xboard-saved').attributes('aria-pressed')).toBe('false')
    expect(wrapper.find('.tweet-fold').exists()).toBe(true)

    // 收藏里改日期：回到窗口并换到那一天
    await wrapper.get('.xboard-saved').trigger('click')
    const date = wrapper.get('.xboard-date input')
    ;(date.element as HTMLInputElement).value = '2026-08-01'
    await date.trigger('change')
    expect(controller().onDateChange).toHaveBeenCalledWith('2026-08-01')
    expect(wrapper.get('.xboard-saved').attributes('aria-pressed')).toBe('false')
  })

  it('还没收过时「收藏」一段点进去说怎么收，点「最近 24 小时」回来', async () => {
    controller().docs.value = byHandles(['alice', 'bob'])
    const wrapper = await mountView()

    await wrapper.get('.xboard-saved').trigger('click')
    expect(wrapper.get('.xboard-saved').attributes('aria-pressed')).toBe('true')
    expect(wallCards(wrapper)).toHaveLength(0)
    expect(wrapper.text()).toContain('saved.emptyTitle')
    expect(wrapper.text()).toContain('saved.emptyXHint')

    await wrapper.get('.xboard-recent').trigger('click')
    expect(controller().showRecent).not.toHaveBeenCalled()
    expect(wallCards(wrapper)).toHaveLength(2)
  })

  it('报眉选了舒适：桌面照旧排墙（不折叠、不排胶片、不限行、最多 4 列、没有纯文字档），收藏照常；换回紧凑都回来', async () => {
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('tweet-text') && this.textContent?.includes('LONG') ? 300 : 0
    })
    setAppDensity('comfortable')
    localStorage.setItem('xboard_text_only', '1')
    setViewportWidth(1920)
    const docs = byHandles(['alice', 'alice', 'alice', 'bob', ...Array.from({ length: 20 }, (_, i) => `user${i}`)])
    docs[0]!.media = [
      { type: 'photo', url: 'https://pbs.twimg.com/media/a.jpg', width: 1600, height: 900 },
      { type: 'photo', url: 'https://pbs.twimg.com/media/b.jpg', width: 1600, height: 900 },
    ]
    docs[1]!.link_card = { url: 'https://example.com', title: 'Example' }
    docs[2]!.summary = 'LONG body'
    controller().docs.value = docs
    const wrapper = await mountView()

    // 1920 宽紧凑版排 5 列，舒适版最多 4 列；同账号不折叠，按条分页一页 20 条
    expect(wrapper.findAll('.masonry-col')).toHaveLength(4)
    expect(wrapper.find('.tweet-fold').exists()).toBe(false)
    expect(wallCards(wrapper)).toHaveLength(20)
    expect(wrapper.find('.xboard-pagination').exists()).toBe(true)
    // 记着的纯文字在舒适版不生效，开关也不出；多图照常竖排、链接卡竖排、长正文不截
    expect(wrapper.find('.xboard-text-only').exists()).toBe(false)
    expect(wrapper.find('.tweet-media-list--strip').exists()).toBe(false)
    expect(wrapper.findAll('.masonry-grid .tweet-media-list')).toHaveLength(1)
    expect(wrapper.get('.masonry-grid .tweet-linkcard').classes()).not.toContain('tweet-linkcard--row')
    expect(wrapper.find('.tweet-more').exists()).toBe(false)
    // 收藏不分版面
    expect(wrapper.find('.xboard-saved').exists()).toBe(true)
    expect(wrapper.findAll('.masonry-grid .save-toggle')).toHaveLength(20)

    setAppDensity('compact')
    await flushPromises()
    expect(wrapper.findAll('.masonry-col')).toHaveLength(5)
    expect(wrapper.get('.tweet-fold').text()).toContain('＋2 条 Alice 的推文')
    expect(wrapper.get('.xboard-text-only').attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('.masonry-grid .tweet-media-list').exists()).toBe(false)
    expect(localStorage.getItem('xboard_text_only')).toBe('1')
  })

  it('手机与平板照旧：不折叠、不排胶片，也没有纯文字档', async () => {
    viewport.desktop = false
    localStorage.setItem('xboard_text_only', '1')
    const docs = byHandles(['alice', 'alice', 'alice', 'bob'])
    docs[0]!.media = [
      { type: 'photo', url: 'https://pbs.twimg.com/media/a.jpg', width: 1600, height: 900 },
      { type: 'photo', url: 'https://pbs.twimg.com/media/b.jpg', width: 1600, height: 900 },
    ]
    docs[1]!.link_card = { url: 'https://example.com', title: 'Example' }
    controller().docs.value = docs
    const wrapper = await mountView()

    expect(wallCards(wrapper)).toHaveLength(4)
    expect(wrapper.find('.tweet-fold').exists()).toBe(false)
    expect(wrapper.find('.xboard-text-only').exists()).toBe(false)
    expect(wrapper.find('.tweet-media-list--strip').exists()).toBe(false)
    expect(wrapper.findAll('.masonry-grid .tweet-media-list')).toHaveLength(1)
    expect(wrapper.get('.masonry-grid .tweet-linkcard').classes()).not.toContain('tweet-linkcard--row')

    // 也没有键盘流
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true, cancelable: true }))
    await nextTick()
    expect(wrapper.find('.is-cursor').exists()).toBe(false)
    expect(wrapper.find('.list-keys-sheet').exists()).toBe(false)
    // 也没有收藏
    expect(wrapper.find('.save-toggle').exists()).toBe(false)
    expect(wrapper.find('.xboard-saved').exists()).toBe(false)
  })
})
