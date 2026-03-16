<script setup lang="ts">
/**
 * PdfCanvasViewer.vue — PDF.js 纯 Canvas 渲染器（禁 iframe）
 *
 * 修复四大维度：
 *  1. Vite ?url 语法导入 Worker，生产构建正确打包
 *  2. 完整 try/catch + isLoading/errorMessage，死得明明白白
 *  3. onMounted + nextTick 保障 DOM 就绪再渲染
 *  4. Canvas display:block; max-width:100%; 防空间塌陷
 */
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

// Vite ?url 语法确保 Worker 被正确打包
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

const props = defineProps<{ pdfUrl: string | null | undefined }>()

const emit = defineEmits<{
  'rightclick-region': [payload: {
    pageIndex: number
    base64: string
    x: number; y: number; w: number; h: number
  }]
}>()

// ── 状态 ──────────────────────────────────────────────────────────────────
const containerRef = ref<HTMLDivElement | null>(null)
const isLoading = ref(false)
const errorMessage = ref('')
const totalPages = ref(0)
const scale = ref(1.5)
const isMounted = ref(false)

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
// 安全清空 canvas 容器（不用 innerHTML='' 避免破坏 Vue vDOM 引用）
const clearContainer = () => {
  if (!containerRef.value) return
  // 只移除 canvas 元素，保留 Vue 托管的其他节点
  const canvases = containerRef.value.querySelectorAll('canvas')
  canvases.forEach(c => c.remove())
}

const loadPdf = async (url: string) => {
  // 取消上一个渲染任务
  renderTask?.cancel()
  renderTask = null

  // 维度3：DOM 就绪检查
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
  clearContainer()

  try {
    console.log('[PdfCanvasViewer] Loading PDF:', url)

    const loadingTask = pdfjsLib.getDocument({
      url,
      cMapUrl: new URL('pdfjs-dist/cmaps/', import.meta.url).toString(),
      cMapPacked: true,
    })

    // 维度2：精准捕获 getDocument 错误
    pdfDoc = await loadingTask.promise.catch((err) => {
      throw new Error(`PDF 解析失败: ${err?.message || err}`)
    })

    if (!isMounted.value) return  // 组件已卸载

    totalPages.value = pdfDoc.numPages
    console.log('[PdfCanvasViewer] numPages:', pdfDoc.numPages)

    // 逐页渲染循环
    for (let pageNum = 1; pageNum <= pdfDoc.numPages; pageNum++) {
      if (!isMounted.value || !containerRef.value) break  // 组件已卸载

      const page = await pdfDoc.getPage(pageNum).catch((err) => {
        throw new Error(`第 ${pageNum} 页获取失败: ${err?.message || err}`)
      })

      const viewport = page.getViewport({ scale: scale.value })

      // 维度4：Canvas 样式防空间塌陷
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

      if (!isMounted.value || !containerRef.value) break  // 再次检查
      containerRef.value.appendChild(canvas)

      const ctx = canvas.getContext('2d')
      if (!ctx) continue

      renderTask = page.render({ canvasContext: ctx, viewport, canvas })
      await renderTask.promise.catch((err) => {
        // RenderingCancelledException 是正常的，其他错误上报
        if (err?.name !== 'RenderingCancelledException') {
          console.warn(`[PdfCanvasViewer] page ${pageNum} render error:`, err)
        }
      })

      if (!isMounted.value) break  // 渲染后再检查一次

      pageEntries.value.push({
        canvas,
        viewport: { width: canvas.width, height: canvas.height, scale: scale.value },
      })
    }

    if (isMounted.value) {
      isLoading.value = false
      const el = containerRef.value
      const parent = el?.parentElement
      const grandParent = parent?.parentElement
      console.log('[PdfCanvasViewer] All pages rendered.',
        el ? `container: ${el.offsetWidth}x${el.offsetHeight}` : 'container null',
        el ? `scrollHeight: ${el.scrollHeight}` : '',
        parent ? `parent: ${parent.offsetWidth}x${parent.offsetHeight} flex:${getComputedStyle(parent).display}` : '',
        grandParent ? `grandParent: ${grandParent.offsetWidth}x${grandParent.offsetHeight} flex:${getComputedStyle(grandParent).display}` : '')
    }
  } catch (err: unknown) {
    // 维度2：所有错误都打印 + 显示给用户
    const msg = err instanceof Error ? err.message : String(err)
    console.error('[PdfCanvasViewer] Fatal error:', err)
    if (isMounted.value) {
      errorMessage.value = msg
      isLoading.value = false
    }
  }
}

// 维度3：等待祖先容器有实际高度再渲染（解决 Transition 动画期间祖先高度为 0 的问题）
let resizeObserver: ResizeObserver | null = null

const startRenderWhenReady = (url: string) => {
  if (!containerRef.value) return

  // 找到第一个有正高度的祖先元素（最多向上找 5 层）
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
    // 祖先有高度，直接渲染
    loadPdf(url)
    return
  }

  // 祖先高度为 0，用 ResizeObserver 等待任意祖先出现高度
  // 监听容器的父元素（直接父容器）
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
  // 同时也监听更上一层
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

// ── 内存截图：支持跨页长截图，Canvas toDataURL，不落盘 ────────────────────
const captureRegion = () => {
  if (!selectionBox.value) return
  const { startX, startY, endX, endY } = selectionBox.value
  const left = Math.min(startX, endX)
  const top = Math.min(startY, endY)
  const w = Math.abs(endX - startX)
  const h = Math.abs(endY - startY)

  if (w < 8 || h < 8) { selectionBox.value = null; return }

  // 收集所有与选区相交的页面片段
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

  // 合并所有片段到一个 offscreen canvas
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
  // 若 base64 超过 500KB，降质重试
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
  <div
    ref="containerRef"
    class="pdf-canvas-container"
    @mousedown="onMouseDown"
    @mousemove="onMouseMove"
    @mouseup="onMouseUp"
    @contextmenu="onContextMenu"
  >
    <!-- 加载状态 -->
    <div v-if="isLoading" class="pdf-status">
      <div class="pdf-spinner" />
      <span class="pdf-status-text">PDF 加载中…</span>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="errorMessage" class="pdf-error">
      <div class="pdf-error-icon">⚠️</div>
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
</template>

<style scoped>
.pdf-canvas-container {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  flex: 1 1 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px 12px;
  box-sizing: border-box;
  user-select: none;
  background: #f8f8f8;
  cursor: crosshair;
}

/* 维度4：防空间塌陷 —— 所有 canvas 子元素继承 */
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
  border-top-color: #6366f1;
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
  border: 2px solid #6366f1;
  background: rgba(99, 102, 241, 0.12);
  pointer-events: none;
  z-index: 10;
  border-radius: 2px;
}
</style>
