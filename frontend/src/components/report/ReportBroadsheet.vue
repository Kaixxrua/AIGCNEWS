<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useId, watch, type ComponentPublicInstance } from 'vue'
import { useI18n } from 'vue-i18n'
import ListKeysSheet from '@/components/keyboard/ListKeysSheet.vue'
import SaveButton from '@/components/saved/SaveButton.vue'
import { vIndicator } from '@/motion/indicator'
import { vMorph } from '@/motion/morph'
import { prefersReducedMotion } from '@/motion/motion'
import { useListKeys } from '@/composables/useListKeys'
import { useReadMarks } from '@/composables/useReadMarks'
import type { BroadsheetPeek, PeekEntry } from '@/composables/useReportPeek'
import { broadsheetItemReadId, type Broadsheet, type BroadsheetBlock, type BroadsheetItem } from '@/features/report/reportBroadsheet'
import { itemPaperLinks, paperArxivId } from '@/features/report/reportPaperLinks'

/**
 * 桌面版简报的大报排法：每节的正文段落分三栏，条目排成两到三栏的网格，条目的标题句加粗打头。
 * 全文模式下条目正文最多 5 行、导读模式下 2 行（节内段落收成 2 行的一栏），点开看全文；条目的出处链接排在标题句
 * 右侧（没有标题句的排在底行），正文收着也能直接点，「展开全文」在正文下方的底行。生成中全部展开，跟着流式文字长。
 * 收起与展开、两种模式之间切换时正文高度平滑过渡。
 * 看过的条目下次再打开这一期时变淡，点过其中链接的立刻变淡（记录只存在本机浏览器）。
 * 给了 saves 时每条多一枚书签（标题句一排的最右，没有标题句的在底行打头），按 s 也能收下光标停着的那条（生成中没有）。
 * 给了 peek（宽屏）时，点条目里的论文链接、讲到论文的条目的标题，在右侧看这篇的详情，不离开简报；详情开着时
 * j / k 只走讲到论文的条目，右侧跟着换，Esc 收起。
 */
export type ReportReadingMode = 'full' | 'lead'

/** 条目收藏：收没收下，收下或取消；收下时告诉它这条原在哪一节（刊头导语为空串）、在这一期里排第几。 */
export interface BroadsheetSaves {
  has(item: BroadsheetItem): boolean
  toggle(item: BroadsheetItem, place: { section: string; order: number }): void
}

const props = withDefaults(defineProps<{
  sheet: Broadsheet
  mode: ReportReadingMode
  generating: boolean
  saves?: BroadsheetSaves | null
  /** 看过的条目变淡；看收藏时不淡，也不记。 */
  dimRead?: boolean
  /** 宽屏右侧的论文详情栏；不给就照旧点链接离开、o 在新标签页打开。 */
  peek?: BroadsheetPeek | null
}>(), { saves: null, dimRead: true, peek: null })

const { t } = useI18n()
const uid = useId()

interface Group { heading: string | null; blocks: BroadsheetBlock[] }
const groups = computed<Group[]>(() => [
  ...(props.sheet.intro.length ? [{ heading: null, blocks: props.sheet.intro }] : []),
  ...props.sheet.sections,
])

const pieceId = (group: number, block: number, item?: number) => item == null ? `${group}-${block}` : `${group}-${block}-${item}`
const bodyId = (id: string) => `${uid}-rb-${id}`

// 版面上的每一条：条目本身、原在哪一节、按版面顺序排第几、已读记录用的标识。
interface Piece { item: BroadsheetItem; section: string; order: number; readId: string }
const pieces = computed(() => {
  const map = new Map<string, Piece>()
  groups.value.forEach((group, g) => group.blocks.forEach((block, b) => {
    if (block.kind !== 'items') return
    block.items.forEach((item, i) => map.set(pieceId(g, b, i), { item, section: group.heading ?? '', order: map.size, readId: broadsheetItemReadId(item) }))
  }))
  return map
})

// 已读淡化：条目露出一半停够一秒记为看过，下次打开这一期时变淡；生成中文字还在变，不记也不淡。
// 一期简报是写定的一份，后来不会再添条目，所以不画「上次看到这里」。
const readMarks = useReadMarks({ list: 'briefing', enabled: computed(() => !props.generating && props.dimRead) })
const vReadMark = readMarks.directive
const readId = (id: string) => pieces.value.get(id)?.readId ?? ''
const isRead = (id: string) => readMarks.isRead(readId(id))

const canSave = computed(() => !!props.saves && !props.generating)
const isSaved = (id: string) => {
  const piece = pieces.value.get(id)
  return !!piece && !!props.saves?.has(piece.item)
}
const toggleSave = (id: string) => {
  const piece = pieces.value.get(id)
  if (piece && canSave.value) props.saves?.toggle(piece.item, { section: piece.section, order: piece.order })
}

// 讲到论文的条目（按版面顺序）登记给详情栏；生成中文字还在变，不登记。
const peekEntries = computed<PeekEntry[]>(() => {
  if (!props.peek || props.generating) return []
  return [...pieces.value].flatMap(([key, piece]) => {
    const papers = itemPaperLinks(piece.item)
    return papers.length ? [{ key, papers }] : []
  })
})
const peekLinks = computed(() => new Map(peekEntries.value.map((entry) => [entry.key, entry.papers])))
const paperLinksOf = (id: string) => peekLinks.value.get(id) ?? []
watch(peekEntries, (entries) => props.peek?.setEntries(entries), { immediate: true })
onBeforeUnmount(() => props.peek?.releaseEntries(peekEntries.value))
const peekKey = computed(() => props.peek?.target?.key ?? null)
const isPeeked = (id: string) => peekKey.value === id

/** 在右侧打开这条讲的论文（默认第一篇）；看过详情的条目记为看过。 */
const peekAt = (id: string, arxivId = paperLinksOf(id)[0]?.arxivId): boolean => {
  if (!props.peek || !arxivId || !props.peek.open({ key: id, arxivId })) return false
  readMarks.markSeen(readId(id))
  return true
}

/** 宽屏：点条目里的论文链接、讲到论文的条目的标题，在右侧看详情；带修饰键的点击照常在新标签页打开链接。 */
const peekFromClick = (event: MouseEvent, target: Element): boolean => {
  if (!props.peek || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false
  const id = target.closest<HTMLElement>('[data-list-key]')?.dataset.listKey
  if (!id || !paperLinksOf(id).length) return false
  const link = target.closest('a[href]')
  const arxivId = link ? paperArxivId(link.getAttribute('href')) : target.closest('.report-broadsheet__lead') ? undefined : null
  if (arxivId === null || !peekAt(id, arxivId)) return false
  event.preventDefault()
  return true
}

const ITEM_LINES = { full: 5, lead: 2 } as const
const linesOf = (kind: 'prose' | 'item', intro: boolean) => {
  if (props.generating || intro) return 0
  if (kind === 'prose') return props.mode === 'lead' ? 2 : 0
  return ITEM_LINES[props.mode]
}

// 每段正文不截断时的高度与行高：截断与否、要不要给「展开全文」都按它算，切换模式时同一轮渲染就能定下来。
const heights = reactive(new Map<string, { full: number; line: number }>())
const opened = reactive(new Set<string>())
const bodies = new Map<string, HTMLElement>()

const overflows = (id: string, lines: number) => {
  const height = heights.get(id)
  return !!height && lines > 0 && height.full > lines * height.line + height.line / 2
}
const isOpen = (id: string) => opened.has(id)
const isClamped = (id: string, lines: number) => lines > 0 && !opened.has(id)
const morphKey = (id: string, lines: number) => `${lines}:${opened.has(id)}`

const setBody = (id: string) => (el: Element | ComponentPublicInstance | null) => {
  if (el instanceof HTMLElement) bodies.set(id, el)
  else bodies.delete(id)
}

/** 一次量完：全部先放开截断量自然高度，再一起恢复，只触发一次排版。 */
const measure = () => {
  if (props.generating) return
  const entries = [...bodies.entries()].filter(([, el]) => el.isConnected)
  entries.forEach(([, el]) => el.classList.add('is-measuring'))
  const results = entries.map(([id, el]) => ({ id, full: el.getBoundingClientRect().height, line: parseFloat(getComputedStyle(el).lineHeight) || 0 }))
  entries.forEach(([, el]) => el.classList.remove('is-measuring'))
  for (const { id, full, line } of results) {
    const previous = heights.get(id)
    if (!previous || Math.abs(previous.full - full) > 0.5 || previous.line !== line) heights.set(id, { full, line })
  }
}

const root = ref<HTMLElement | null>(null)
let resizeObserver: ResizeObserver | undefined
let observedWidth = 0
onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && root.value) {
    resizeObserver = new ResizeObserver(([entry]) => {
      const width = entry?.contentRect.width ?? 0
      if (Math.abs(width - observedWidth) < 0.5) return
      observedWidth = width
      measure()
    })
    resizeObserver.observe(root.value)
  }
  void document.fonts?.ready.then(() => measure())
})
onBeforeUnmount(() => resizeObserver?.disconnect())
watch(() => [props.sheet, props.generating], () => measure(), { flush: 'post' })
// 换模式时各条回到该模式的默认长度。
watch(() => props.mode, () => opened.clear())

// 读完长条目在底部收起时，条目开头可能已滚出视野：滚回到刚好露出开头（让开顶部控制条的距离由 scroll-margin-top 定），
// 开头仍在视野里就不动。
const revealStart = (id: string) => {
  void nextTick(() => {
    root.value?.querySelector<HTMLElement>(`[data-piece="${id}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
  })
}

// 展开读全文的条目记为看过（读着的时候不变淡）。
const toggle = (id: string) => {
  if (opened.has(id)) {
    opened.delete(id)
    revealStart(id)
  } else {
    opened.add(id)
    readMarks.markSeen(readId(id))
  }
}

// 点被截断的条目任意处（链接、按钮、正在选中文字除外）也能展开。点了条目里的链接，这条立刻变淡，像访问过的链接。
const expandFromClick = (event: MouseEvent) => {
  const target = event.target as Element | null
  if (target && peekFromClick(event, target)) return
  const link = target?.closest('a[href]')
  const linked = link?.closest<HTMLElement>('[data-piece]')?.dataset.piece
  if (linked) readMarks.markOpened(readId(linked))
  if (!target || target.closest('a, button, input, label, summary')) return
  const piece = target.closest<HTMLElement>('[data-piece]')
  const id = piece?.dataset.piece
  if (!piece || !id || opened.has(id) || !overflows(id, Number(piece.dataset.lines))) return
  const selection = window.getSelection()
  if (selection && !selection.isCollapsed && piece.contains(selection.anchorNode)) return
  opened.add(id)
  readMarks.markSeen(readId(id))
}

// 键盘流：j / k 按版面顺序在条目之间走，走过的记为看过；o 在新标签页打开条目的出处（简报留在这里接着往下读，
// 没有链接时展开全文；宽屏上讲到论文的条目先在右侧看详情，再按一次才打开），s 收藏，x 展开或收起全文。
// 详情开着时 j / k 只走讲到论文的条目，右侧跟着换。生成中文字还在长，不接键。
const pieceEl = (id: string) => root.value?.querySelector<HTMLElement>(`[data-piece="${id}"]`) ?? null
const canToggle = (id: string) => opened.has(id) || overflows(id, Number(pieceEl(id)?.dataset.lines))
const itemOrder = computed(() => [...pieces.value.keys()])
const peekOrder = computed(() => peekEntries.value.map((entry) => entry.key))
const listKeys = useListKeys({
  enabled: computed(() => !props.generating),
  root,
  keys: computed(() => (peekKey.value ? peekOrder.value : itemOrder.value)),
  open: (id) => {
    const shown = props.peek?.target
    if (shown?.key !== id && peekAt(id)) return
    // 右侧已经在看这条：打开正看的那篇
    const piece = pieceEl(id)
    const href = (shown?.key === id ? paperLinksOf(id).find((paper) => paper.arxivId === shown.arxivId)?.href : undefined)
      ?? (piece?.querySelector<HTMLAnchorElement>('.report-broadsheet__source a[href]') ?? piece?.querySelector<HTMLAnchorElement>('a[href]'))?.href
    if (href) {
      window.open(href, '_blank', 'noopener')
      readMarks.markOpened(readId(id))
    } else if (canToggle(id)) toggle(id)
  },
  // 没给收藏时不接 s
  get save() {
    return props.saves ? toggleSave : undefined
  },
  toggle: (id) => {
    if (canToggle(id)) toggle(id)
  },
  passed: (id) => readMarks.markSeen(readId(id)),
  // 详情开着时，右侧跟着光标换到这条
  reached: (id) => {
    if (peekKey.value && peekKey.value !== id) peekAt(id)
  },
  escape: () => {
    if (!peekKey.value) return false
    props.peek?.close()
    return true
  },
})
const { help: keysHelp, isCursor } = listKeys

// 在详情栏里换了一条：列表的光标跟过去、把那条滚进视野。收起时焦点若还在栏里（点了 ×），放回那一条，接着用键盘往下走。
watch(peekKey, (key, previous) => {
  if (key) {
    if (listKeys.cursor.value !== key) listKeys.setCursor(key, { reveal: true })
  } else if (previous && document.activeElement?.closest('.report-peek')) {
    listKeys.setCursor(previous, { focus: true })
  }
})

const proseLayout =(block: Extract<BroadsheetBlock, { kind: 'prose' }>, intro: boolean) => {
  if (intro) return 'is-standfirst'
  if (block.ems <= 180) return 'is-short'
  return block.ems > 1100 ? 'is-long' : 'is-columns'
}
</script>

<template>
  <div
    ref="root"
    v-indicator="{ active: '.is-cursor', mark: 'after' }"
    class="report-broadsheet prose-content prose-report"
    :data-mode="mode"
    @click="expandFromClick"
  >
    <component
      :is="group.heading == null ? 'div' : 'section'"
      v-for="(group, g) in groups"
      :key="g"
      :class="group.heading == null ? 'report-broadsheet__intro' : 'report-section'"
    >
      <h2 v-if="group.heading != null" v-html="group.heading" />
      <template v-for="(block, b) in group.blocks" :key="b">
        <p v-if="block.kind === 'meta'" class="report-broadsheet__meta" v-html="block.html" />

        <div
          v-else-if="block.kind === 'prose'"
          class="report-broadsheet__piece report-broadsheet__prose"
          :class="[proseLayout(block, group.heading == null), {
            'is-clamped': isClamped(pieceId(g, b), linesOf('prose', group.heading == null)),
            'is-open': isOpen(pieceId(g, b)),
            'is-overflowing': overflows(pieceId(g, b), linesOf('prose', group.heading == null)),
          }]"
          :data-piece="pieceId(g, b)"
          :data-lines="linesOf('prose', group.heading == null)"
        >
          <div
            :id="bodyId(pieceId(g, b))"
            :ref="setBody(pieceId(g, b))"
            v-morph="morphKey(pieceId(g, b), linesOf('prose', group.heading == null))"
            class="report-broadsheet__body"
            :style="{ '--lines': linesOf('prose', group.heading == null) }"
          >
            <p v-for="(paragraph, p) in block.paragraphs" :key="p" v-html="paragraph" />
          </div>
          <button
            v-if="overflows(pieceId(g, b), linesOf('prose', group.heading == null))"
            type="button"
            class="report-broadsheet__toggle"
            :aria-expanded="isOpen(pieceId(g, b))"
            :aria-controls="bodyId(pieceId(g, b))"
            @click="toggle(pieceId(g, b))"
          >
            {{ isOpen(pieceId(g, b)) ? t('report.collapse') : t('report.expand') }}
          </button>
        </div>

        <component
          :is="block.ordered ? 'ol' : 'ul'"
          v-else-if="block.kind === 'items'"
          class="report-broadsheet__items"
          role="list"
        >
          <li
            v-for="(item, i) in block.items"
            :key="i"
            v-read-mark="readId(pieceId(g, b, i))"
            class="report-broadsheet__piece report-broadsheet__item"
            :class="{
              'is-numbered': item.number != null,
              'is-peekable': peekLinks.has(pieceId(g, b, i)),
              'is-peeked': isPeeked(pieceId(g, b, i)),
              'is-read': isRead(pieceId(g, b, i)),
              'is-cursor': isCursor(pieceId(g, b, i)),
              'is-clamped': isClamped(pieceId(g, b, i), linesOf('item', group.heading == null)),
              'is-open': isOpen(pieceId(g, b, i)),
              'is-overflowing': overflows(pieceId(g, b, i), linesOf('item', group.heading == null)),
            }"
            :data-piece="pieceId(g, b, i)"
            :data-list-key="pieceId(g, b, i)"
            :data-lines="linesOf('item', group.heading == null)"
          >
            <span v-if="item.number != null" class="report-broadsheet__num" aria-hidden="true">{{ item.number }}</span>
            <div v-if="item.lead" class="report-broadsheet__head">
              <h3 class="report-broadsheet__lead">
                <span v-html="item.lead" />
                <small v-if="item.note" class="report-broadsheet__note" v-html="item.note" />
              </h3>
              <!-- 出处和书签排在标题句右侧，书签在最右：正文不长的条目就不用再占一行底栏 -->
              <span v-if="canSave || item.source" class="report-broadsheet__credit">
                <span v-if="item.source" class="report-broadsheet__source" v-html="item.source" />
                <SaveButton
                  v-if="canSave"
                  class="report-broadsheet__save"
                  :saved="isSaved(pieceId(g, b, i))"
                  @toggle="toggleSave(pieceId(g, b, i))"
                />
              </span>
            </div>
            <div
              v-if="item.body"
              :id="bodyId(pieceId(g, b, i))"
              :ref="setBody(pieceId(g, b, i))"
              v-morph="morphKey(pieceId(g, b, i), linesOf('item', group.heading == null))"
              class="report-broadsheet__body"
              :style="{ '--lines': linesOf('item', group.heading == null) }"
              v-html="item.body"
            />
            <!-- 底行：「展开全文」落在正文断开的地方；没有标题句的条目，书签打头、出处在右，也排在这里 -->
            <div
              v-if="overflows(pieceId(g, b, i), linesOf('item', group.heading == null)) || (!item.lead && (item.source || canSave))"
              class="report-broadsheet__foot"
            >
              <SaveButton
                v-if="!item.lead && canSave"
                class="report-broadsheet__save"
                :saved="isSaved(pieceId(g, b, i))"
                @toggle="toggleSave(pieceId(g, b, i))"
              />
              <button
                v-if="overflows(pieceId(g, b, i), linesOf('item', group.heading == null))"
                type="button"
                class="report-broadsheet__toggle"
                :aria-expanded="isOpen(pieceId(g, b, i))"
                :aria-controls="bodyId(pieceId(g, b, i))"
                @click="toggle(pieceId(g, b, i))"
              >
                {{ isOpen(pieceId(g, b, i)) ? t('report.collapse') : t('report.expand') }}
              </button>
              <span v-if="!item.lead && item.source" class="report-broadsheet__source" v-html="item.source" />
            </div>
          </li>
        </component>

        <div v-else class="report-broadsheet__raw" v-html="block.html" />
      </template>
    </component>
    <p v-if="sheet.dateline" class="report-dateline" v-html="sheet.dateline" />
    <ListKeysSheet
      v-model:open="keysHelp"
      :actions="{ open: peek ? t('listKeys.briefingPeek') : t('listKeys.briefingOpen'), save: saves ? t('listKeys.save') : undefined, toggle: t('listKeys.briefingToggle') }"
    />
  </div>
</template>
