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
  const box: Record<string, any> = {
    availableDates: ref<string[]>([]),
    clearSelection: vi.fn(() => { box.selectedIds.value = new Set() }),
    currentPage: computed(() => clampPage(page.value, box.totalPages.value)),
    daysBack: ref(0),
    deleteSelected: vi.fn(async () => ({ deleted: 0, notFound: 0 })),
    deleting: ref(false),
    dispose: vi.fn(),
    docs: ref<TopDoc[]>([]),
    errorMsg: ref(''),
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
    toggleSelection: vi.fn((docId: string) => {
      const next = new Set<string>(box.selectedIds.value)
      if (next.has(docId)) next.delete(docId)
      else next.add(docId)
      box.selectedIds.value = next
    }),
    totalPages: computed(() => pageCount(box.docs.value.length, pageSize)),
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

describe('XBoardView 分页 × 分列 × 页级全选接线', () => {
  it('挂载即调用 load，并按行主序把当前页推文分进 JS 列', async () => {
    controller().docs.value = makeTweets(25)
    const wrapper = await mountView()

    expect(controllerSpy).toHaveBeenCalledOnce()
    expect(controller().load).toHaveBeenCalledTimes(1)

    // 25 条 > 单页 20：首屏只渲染第一页 20 张卡
    expect(wrapper.findAll('article.tweet-card')).toHaveLength(20)

    // jsdom 视口 1024 → 3 列；行主序：第 i 条进第 i % 3 列（7/7/6）
    const columns = wrapper.findAll('.masonry-col')
    expect(columns).toHaveLength(3)
    expect(columns[0]!.findAll('.tweet-card')).toHaveLength(7)
    expect(columns[1]!.findAll('.tweet-card')).toHaveLength(7)
    expect(columns[2]!.findAll('.tweet-card')).toHaveLength(6)

    // 每列自上而下是索引步进列数的子序列（左上 = 最新，横读连续）
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
