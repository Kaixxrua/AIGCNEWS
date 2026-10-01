<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useId, watch, type ComponentPublicInstance } from 'vue'
import { useI18n } from 'vue-i18n'
import { vMorph } from '@/motion/morph'
import { prefersReducedMotion } from '@/motion/motion'
import type { Broadsheet, BroadsheetBlock } from '@/features/report/reportBroadsheet'

/**
 * 桌面版简报的大报排法：每节的正文段落分三栏，条目排成两到三栏的网格，条目的标题句加粗打头。
 * 全文模式下条目正文最多 5 行、导读模式下 2 行（节内段落收成 2 行的一栏），点开看全文；条目的出处链接与「展开全文」
 * 同排在底行，正文收着也能直接点。生成中全部展开，跟着流式文字长。收起与展开、两种模式之间切换时正文高度平滑过渡。
 */
export type ReportReadingMode = 'full' | 'lead'

const props = defineProps<{
  sheet: Broadsheet
  mode: ReportReadingMode
  generating: boolean
}>()

const { t } = useI18n()
const uid = useId()

interface Group { heading: string | null; blocks: BroadsheetBlock[] }
const groups = computed<Group[]>(() => [
  ...(props.sheet.intro.length ? [{ heading: null, blocks: props.sheet.intro }] : []),
  ...props.sheet.sections,
])

const pieceId = (group: number, block: number, item?: number) => item == null ? `${group}-${block}` : `${group}-${block}-${item}`
const bodyId = (id: string) => `${uid}-rb-${id}`

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

const toggle = (id: string) => {
  if (opened.has(id)) {
    opened.delete(id)
    revealStart(id)
  } else {
    opened.add(id)
  }
}

// 点被截断的条目任意处（链接、按钮、正在选中文字除外）也能展开。
const expandFromClick = (event: MouseEvent) => {
  const target = event.target as Element | null
  if (!target || target.closest('a, button, input, label, summary')) return
  const piece = target.closest<HTMLElement>('[data-piece]')
  const id = piece?.dataset.piece
  if (!piece || !id || opened.has(id) || !overflows(id, Number(piece.dataset.lines))) return
  const selection = window.getSelection()
  if (selection && !selection.isCollapsed && piece.contains(selection.anchorNode)) return
  opened.add(id)
}

const proseLayout = (block: Extract<BroadsheetBlock, { kind: 'prose' }>, intro: boolean) => {
  if (intro) return 'is-standfirst'
  if (block.ems <= 180) return 'is-short'
  return block.ems > 1100 ? 'is-long' : 'is-columns'
}
</script>

<template>
  <div ref="root" class="report-broadsheet prose-content prose-report" :data-mode="mode" @click="expandFromClick">
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
            class="report-broadsheet__piece report-broadsheet__item"
            :class="{
              'is-numbered': item.number != null,
              'is-clamped': isClamped(pieceId(g, b, i), linesOf('item', group.heading == null)),
              'is-open': isOpen(pieceId(g, b, i)),
              'is-overflowing': overflows(pieceId(g, b, i), linesOf('item', group.heading == null)),
            }"
            :data-piece="pieceId(g, b, i)"
            :data-lines="linesOf('item', group.heading == null)"
          >
            <span v-if="item.number != null" class="report-broadsheet__num" aria-hidden="true">{{ item.number }}</span>
            <h3 v-if="item.lead" class="report-broadsheet__lead">
              <span v-html="item.lead" />
              <small v-if="item.note" class="report-broadsheet__note" v-html="item.note" />
            </h3>
            <div
              v-if="item.body"
              :id="bodyId(pieceId(g, b, i))"
              :ref="setBody(pieceId(g, b, i))"
              v-morph="morphKey(pieceId(g, b, i), linesOf('item', group.heading == null))"
              class="report-broadsheet__body"
              :style="{ '--lines': linesOf('item', group.heading == null) }"
              v-html="item.body"
            />
            <div
              v-if="item.source || overflows(pieceId(g, b, i), linesOf('item', group.heading == null))"
              class="report-broadsheet__foot"
            >
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
              <span v-if="item.source" class="report-broadsheet__source" v-html="item.source" />
            </div>
          </li>
        </component>

        <div v-else class="report-broadsheet__raw" v-html="block.html" />
      </template>
    </component>
    <p v-if="sheet.dateline" class="report-dateline" v-html="sheet.dateline" />
  </div>
</template>
