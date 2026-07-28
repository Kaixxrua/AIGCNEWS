<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
/**
 * PdfCanvasViewer.vue — PDF.js 纯 Canvas 渲染器（禁 iframe）
 *
 * 新增功能：
 *  - 真实逐页渲染进度条（emit progress 事件）
 *  - 进度 UI：顶部细线型进度条 + 页数标注
 */
import { watch, onMounted, onUnmounted } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { PdfProgress } from '../features/papers/pdfViewerModel'
import { usePdfDocumentRenderer } from '../composables/usePdfDocumentRenderer'
import { usePdfRegionCapture } from '../composables/usePdfRegionCapture'

export type { PdfProgress } from '../features/papers/pdfViewerModel'

// Vite ?url 语法确保 Worker 被正确打包
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

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
const {
  containerRef,
  isLoading,
  errorMessage,
  totalPages,
  loadedPages,
  progressPercent,
  progressPhase,
  pageEntries,
  startRenderWhenReady,
  mount,
  handlePdfUrlChange,
  unmount,
} = usePdfDocumentRenderer({
  onProgress: (payload) => emit('progress', payload),
})

// ── 右键选区状态 ──────────────────────────────────────────────────────────
const {
  selectionBox,
  selectionStyle,
  onMouseDown,
  onMouseMove,
  onMouseUp,
  onContextMenu,
} = usePdfRegionCapture({
  containerRef,
  pageEntries,
  onCapture: (payload) => emit('rightclick-region', payload),
})

onMounted(() => {
  mount()
  if (props.pdfUrl) startRenderWhenReady(props.pdfUrl)
})

watch(() => props.pdfUrl, handlePdfUrlChange)

onUnmounted(unmount)

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
        <span v-if="progressPhase === 'parsing'">{{ t('paper.pdfParsing') }}</span>
        <span v-else-if="progressPhase === 'rendering' && totalPages > 0">
          {{ t('paper.pdfRendering', { loaded: loadedPages, total: totalPages }) }}
        </span>
        <span v-else>{{ t('paper.pdfLoading') }}</span>
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
        <span class="pdf-status-text">PDF {{ t('paper.pdfLoading') }}</span>
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
        <span class="pdf-status-text">{{ t('paper.pdfMissing') }}</span>
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
