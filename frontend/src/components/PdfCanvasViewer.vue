<script setup lang="ts">
/**
 * PdfCanvasViewer.vue — PDF.js 纯 Canvas 渲染器（禁 iframe）
 *
 * 新增功能：
 *  - 真实逐页渲染进度条（emit progress 事件）
 *  - 进度 UI：顶部细线型进度条 + 页数标注
 */
import { ref, watch, onMounted, onUnmounted, nextTick, computed } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

// Vite ?url 语法确保 Worker 被正确打包
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

export interface PdfProgress {
  phase: 'idle' | 'fetching' | 'parsing' | 'rendering' | 'done' | 'error'
  loadedPages: number
  totalPages: number
  percent: number
}

const props = defineProps<{ pdfUrl: string | null | undefined }>()

const emit = defineEmits<{
  'rightclick-region': [payload: {
    pageIndex: number
    base64: string
    x: number; y: number; w: number; h: number
  }]
  'progress': [payload: PdfProgress]
}>()

// ── 状态 ──────────────────────────────────────────────────────────────────
const containerRef = ref<HTMLDivElement | null>(null)
const isLoading = ref(false)
const errorMessage = ref('')
const totalPages = ref(0)
const loadedPages = ref(0)
const scale = ref(1.5)
const isMounted = ref(false)

/** 渲染进度百分比（0-100） */
const progressPercent = computed(() => {
  if (totalPages.value === 0) return 0
  return Math.round(10 + (loadedPages.value / totalPages.value) * 90)
})

/** 当前进度阶段 */
const progressPhase = ref<PdfProgress['phase']>('idle')

const emitProgress = () => {
  const payload: PdfProgress = {
    phase: progressPhase.value,
    loadedPages: loadedPages.value,
    totalPages: totalPages.value,
    percent: progressPercent.value,
  }
  emit('progress', payload)
}

interface PageEntry {
  canvas: HTMLCanvasElement
  viewport: { width: number; height: number; scale: number }
}
const pageEntries = ref<PageEntry[]>([])

let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null
let renderTask: pdfjsLib.RenderTask | null = null

// ── 右键选区状态 ──────────────────────────────────────────────────────────
const selectionBox = ref<{
  startX: number; startY: number; endX: number; endY: number; active: boolean
} | null>(null)
const selectionStyle = ref({ left: '0px', top: '0px', width: '0px', height: '0px' })

// ── 核心渲染函数 ──────────────────────────────────────────────────────────
const clearContainer = () => {
  if (!containerRef.value) return
  const canvases = containerRef.value.querySelectorAll('canvas')
  canvases.forEach(c => c.remove())
}

const loadPdf = async (url: string) => {
  renderTask?.cancel()
  renderTask = null

  await nextTick()
  if (!isMounted.value || !containerRef.value) {
    console.error('[PdfCanvasViewer] containerRef is null or unmounted after nextTick')
    return
  }

  // 重置状态
  isLoading.value = true
  errorMessage.value = ''
  pageEntries.value = []
  totalPages.value = 0
  loadedPages.value = 0
  progressPhase.value = 'parsing'
  emitProgress()
  clearContainer()

  try {
    console.log('[PdfCanvasViewer] Loading PDF:', url)

    const loadingTask = pdfjsLib.getDocument({
      url,
      cMapUrl: new URL('pdfjs-dist/cmaps/', import.meta.url).toString(),
      cMapPacked: true,
    })

    pdfDoc = await loadingTask.promise.catch((err) => {
      throw new Error(`PDF 解析失败: ${err?.message || err}`)
    })

    if (!isMounted.value) return

    totalPages.value = pdfDoc.numPages
    progressPhase.value = 'rendering'
    emitProgress()
    console.log('[PdfCanvasViewer] numPages:', pdfDoc.numPages)

    // 逐页渲染循环
    for (let pageNum = 1; pageNum <= pdfDoc.numPages; pageNum++) {
      if (!isMounted.value || !containerRef.value) break

      const page = await pdfDoc.getPage(pageNum).catch((err) => {
        throw new Error(`第 ${pageNum} 页获取失败: ${err?.message || err}`)
      })

      const viewport = page.getViewport({ scale: scale.value })

      const canvas = document.createElement('canvas')
      canvas.width = Math.floor(viewport.width)
      canvas.height = Math.floor(viewport.height)
      canvas.style.cssText = [
        'display: block',
        'max-width: 100%',
        'height: auto',
        'margin: 0 auto 16px auto',
        'border-radius: 6px',
        'box-shadow: 0 2px 12px rgba(0,0,0,0.10)',
      ].join(';')
      canvas.dataset.pageIndex = String(pageNum - 1)

      if (!isMounted.value || !containerRef.value) break
      containerRef.value.appendChild(canvas)

      const ctx = canvas.getContext('2d')
      if (!ctx) continue

      renderTask = page.render({ canvasContext: ctx, viewport, canvas })
      await renderTask.promise.catch((err) => {
        if (err?.name !== 'RenderingCancelledException') {
          console.warn(`[PdfCanvasViewer] page ${pageNum} render error:`, err)
        }
      })

      if (!isMounted.value) break

      pageEntries.value.push({
        canvas,
        viewport: { width: canvas.width, height: canvas.height, scale: scale.value },
      })

      // 更新进度
      loadedPages.value = pageNum
      emitProgress()
    }

    if (isMounted.value) {
      isLoading.value = false
      progressPhase.value = 'done'
      emitProgress()
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    console.error('[PdfCanvasViewer] Fatal error:', err)
    if (isMounted.value) {
      errorMessage.value = msg
      isLoading.value = false
      progressPhase.value = 'error'
      emitProgress()
    }
  }
}

// 等待祖先容器有实际高度再渲染
let resizeObserver: ResizeObserver | null = null

const startRenderWhenReady = (url: string) => {
  if (!containerRef.value) return

  const findAncestorWithHeight = (): Element | null => {
    let el: Element | null = containerRef.value
    for (let i = 0; i < 6; i++) {
      if (!el) break
      if ((el as HTMLElement).offsetHeight > 10) return el
      el = el.parentElement
    }
    return null
  }

  const ancestor = findAncestorWithHeight()
  if (ancestor && (ancestor as HTMLElement).offsetHeight > 10) {
    loadPdf(url)
    return
  }

  const targetEl = containerRef.value.parentElement?.parentElement ?? containerRef.value
  resizeObserver?.disconnect()
  resizeObserver = new ResizeObserver(() => {
    const h = findAncestorWithHeight()
    if (h && (h as HTMLElement).offsetHeight > 10) {
      resizeObserver?.disconnect()
      resizeObserver = null
      if (isMounted.value) loadPdf(url)
    }
  })
  resizeObserver.observe(targetEl)
  if (targetEl.parentElement) resizeObserver.observe(targetEl.parentElement)
}

onMounted(() => {
  isMounted.value = true
  if (props.pdfUrl) startRenderWhenReady(props.pdfUrl)
})

watch(() => props.pdfUrl, (url) => {
  if (!isMounted.value) return
  if (url) {
    loadPdf(url)
  } else {
    isLoading.value = false
    errorMessage.value = ''
    pageEntries.value = []
    totalPages.value = 0
    loadedPages.value = 0
    progressPhase.value = 'idle'
    emitProgress()
    if (containerRef.value) clearContainer()
  }
})

onUnmounted(() => {
  isMounted.value = false
  resizeObserver?.disconnect()
  resizeObserver = null
  renderTask?.cancel()
  pdfDoc?.destroy()
})

// ── 右键选区（mousedown/mousemove/mouseup）────────────────────────────────
const getContainerOffset = () => {
  const rect = containerRef.value?.getBoundingClientRect()
  return rect ? { left: rect.left, top: rect.top } : { left: 0, top: 0 }
}

const onMouseDown = (e: MouseEvent) => {
  if (e.button !== 0) return
  const offset = getContainerOffset()
  const scrollTop = containerRef.value?.scrollTop ?? 0
  const scrollLeft = containerRef.value?.scrollLeft ?? 0
  const x = e.clientX - offset.left + scrollLeft
  const y = e.clientY - offset.top + scrollTop
  selectionBox.value = { startX: x, startY: y, endX: x, endY: y, active: true }
  updateSelectionStyle()
}

const onMouseMove = (e: MouseEvent) => {
  if (!selectionBox.value?.active) return
  const offset = getContainerOffset()
  const scrollTop = containerRef.value?.scrollTop ?? 0
  const scrollLeft = containerRef.value?.scrollLeft ?? 0
  selectionBox.value.endX = e.clientX - offset.left + scrollLeft
  selectionBox.value.endY = e.clientY - offset.top + scrollTop
  updateSelectionStyle()
}

const onMouseUp = (e: MouseEvent) => {
  if (e.button !== 0 || !selectionBox.value?.active) return
  selectionBox.value.active = false
  captureRegion()
}

const onContextMenu = (e: MouseEvent) => e.preventDefault()

const updateSelectionStyle = () => {
  if (!selectionBox.value) return
  const { startX, startY, endX, endY } = selectionBox.value
  const left = Math.min(startX, endX)
  const top = Math.min(startY, endY)
  const w = Math.abs(endX - startX)
  const h = Math.abs(endY - startY)
  selectionStyle.value = {
    left: `${left}px`, top: `${top}px`,
    width: `${w}px`, height: `${h}px`,
  }
}

// ── 内存截图 ────────────────────────────────────────────────────
const captureRegion = () => {
  if (!selectionBox.value) return
  const { startX, startY, endX, endY } = selectionBox.value
  const left = Math.min(startX, endX)
  const top = Math.min(startY, endY)
  const w = Math.abs(endX - startX)
  const h = Math.abs(endY - startY)

  if (w < 8 || h < 8) { selectionBox.value = null; return }

  interface Slice {
    canvas: HTMLCanvasElement
    pageIndex: number
    sx: number; sy: number; sw: number; sh: number
  }
  const slices: Slice[] = []

  for (const entry of pageEntries.value) {
    const canvasEl = entry.canvas
    const pageIndex = Number(canvasEl.dataset.pageIndex ?? 0)
    const canvasTop = canvasEl.offsetTop
    const canvasLeft = canvasEl.offsetLeft

    const cx = left - canvasLeft
    const cy = top - canvasTop

    if (cx + w <= 0 || cy + h <= 0) continue
    if (cx >= canvasEl.width || cy >= canvasEl.height) continue

    const sx = Math.max(0, cx)
    const sy = Math.max(0, cy)
    const sw = Math.min(w, canvasEl.width - sx)
    const sh = Math.min(h, canvasEl.height - sy)

    if (sw <= 0 || sh <= 0) continue
    slices.push({ canvas: canvasEl, pageIndex, sx, sy, sw, sh })
  }

  if (slices.length === 0) { selectionBox.value = null; return }

  const totalW = Math.max(...slices.map(s => s.sw))
  const totalH = slices.reduce((sum, s) => sum + s.sh, 0)

  const offscreen = document.createElement('canvas')
  offscreen.width = totalW
  offscreen.height = totalH
  const ctx = offscreen.getContext('2d')!

  let drawY = 0
  for (const s of slices) {
    ctx.drawImage(s.canvas, s.sx, s.sy, s.sw, s.sh, 0, drawY, s.sw, s.sh)
    drawY += s.sh
  }

  let dataUrl = offscreen.toDataURL('image/jpeg', 0.85)
  if (dataUrl.length > 500_000) {
    dataUrl = offscreen.toDataURL('image/jpeg', 0.6)
  }

  const first = slices[0]!
  emit('rightclick-region', {
    pageIndex: first.pageIndex,
    base64: dataUrl,
    x: Math.round(first.sx),
    y: Math.round(first.sy),
    w: Math.round(totalW),
    h: Math.round(totalH),
  })

  selectionBox.value = null
}
</script>

<template>
  <div class="pdf-viewer-wrapper">
    <!-- ═══ 顶部进度条 ═══ -->
    <div v-if="isLoading || progressPhase === 'rendering'" class="pdf-progress-header">
      <div class="pdf-progress-bar">
        <div
          class="pdf-progress-fill"
          :style="{ width: `${progressPercent}%` }"
        />
      </div>
      <div class="pdf-progress-label">
        <span v-if="progressPhase === 'parsing'">解析 PDF…</span>
        <span v-else-if="progressPhase === 'rendering' && totalPages > 0">
          渲染中 {{ loadedPages }}/{{ totalPages }} 页
        </span>
        <span v-else>加载中…</span>
        <span class="pdf-progress-pct">{{ progressPercent }}%</span>
      </div>
    </div>

    <!-- ═══ PDF Canvas 容器 ═══ -->
    <div
      ref="containerRef"
      class="pdf-canvas-container"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @contextmenu="onContextMenu"
    >
      <!-- 加载状态（仅在进度条前显示 spinner） -->
      <div v-if="isLoading && loadedPages === 0" class="pdf-status">
        <div class="pdf-spinner" />
        <span class="pdf-status-text">PDF 加载中…</span>
      </div>

      <!-- 错误状态 -->
      <div v-else-if="errorMessage" class="pdf-error">
        <div class="pdf-error-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-8 h-8 text-rose-400"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        </div>
        <div class="pdf-error-msg">{{ errorMessage }}</div>
      </div>

      <!-- 无 URL 提示 -->
      <div v-else-if="!props.pdfUrl" class="pdf-status">
        <span class="pdf-status-text">暂无 PDF 文件</span>
      </div>

      <!-- 右键选区蓝框 -->
      <div
        v-if="selectionBox && (selectionBox.active || selectionBox.startX !== selectionBox.endX)"
        class="selection-rect"
        :style="selectionStyle"
      />
    </div>
  </div>
</template>

<style scoped>
.pdf-viewer-wrapper {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  flex: 1 1 0;
  overflow: hidden;
}

/* ═══ 进度条头部 ═══ */
.pdf-progress-header {
  flex-shrink: 0;
  padding: 6px 12px 4px;
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(168, 162, 158, 0.08);
}

.pdf-progress-bar {
  width: 100%;
  height: 3px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(168, 162, 158, 0.12);
}

.pdf-progress-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease-out;
  background: linear-gradient(90deg, #06b6d4, #8b5cf6);
}

.pdf-progress-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 3px;
  font-size: 11px;
  color: #78716c;
}

.pdf-progress-pct {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: #06b6d4;
}

/* ═══ PDF Canvas 容器 ═══ */
.pdf-canvas-container {
  position: relative;
  width: 100%;
  flex: 1 1 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px 12px;
  box-sizing: border-box;
  user-select: none;
  background: #f8f8f8;
  cursor: crosshair;
}

.pdf-canvas-container :deep(canvas) {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 0 auto 16px auto;
}

.pdf-status {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: #9ca3af;
}

.pdf-status-text {
  font-size: 14px;
}

.pdf-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e5e7eb;
  border-top-color: #06b6d4;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.pdf-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 8px;
  padding: 24px;
}

.pdf-error-icon {
  font-size: 32px;
}

.pdf-error-msg {
  font-size: 13px;
  color: #ef4444;
  text-align: center;
  max-width: 320px;
  line-height: 1.5;
  word-break: break-all;
}

.selection-rect {
  position: absolute;
  border: 2px solid #06b6d4;
  background: rgba(6, 182, 212, 0.10);
  pointer-events: none;
  z-index: 10;
  border-radius: 2px;
}
</style>
