<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { Camera } from 'lucide-vue-next'
import PdfCanvasViewer from '../PdfCanvasViewer.vue'
import type { PaperReaderPaper } from '../../composables/usePaperReaderController'
import type { PdfProgress } from '../../features/papers/pdfViewerModel'
import type { VisionPopup, VisionRegionCapture } from '../../features/papers/paperReaderModel'

defineProps<{
  paper: PaperReaderPaper | null
  paperLoading: boolean
  paperError: string
  pdfProgress: PdfProgress
  visionPopup: VisionPopup | null
  isSending: boolean
}>()

const emit = defineEmits<{
  downloadPdf: []
  rightclickRegion: [payload: VisionRegionCapture]
  progress: [payload: PdfProgress]
  'update:visionPopup': [popup: VisionPopup]
  popupKeydown: [event: KeyboardEvent]
  sendVision: []
  closePopup: []
  popupInputRef: [element: Element | null]
}>()
</script>

<template>
  <div class="flex-1 min-w-0 min-h-0 h-1/2 md:h-auto flex flex-col overflow-hidden bg-gray-50/50">
    <header class="flex shrink-0 items-start justify-between gap-3 px-5 py-3" style="border-bottom: 1px solid rgba(168,162,158,0.12)">
      <div class="min-w-0 flex-1">
        <div v-if="paperLoading" class="h-4 w-48 animate-pulse rounded bg-stone-200"/>
        <h1 v-else-if="paper" class="text-sm font-semibold text-stone-800 leading-snug line-clamp-2 font-serif">{{ paper.title }}</h1>
        <p v-else class="text-sm text-red-400">{{ paperError || t('paper.loadFailed') }}</p>
        <div v-if="paper" class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-400">
          <span v-if="paper.published_date">{{ paper.published_date?.slice(0, 10) }}</span>
          <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener noreferrer" class="hover:text-stone-600 underline transition">{{ t('paper.originalLink') }}</a>
          <span v-if="pdfProgress.phase === 'rendering' && pdfProgress.totalPages > 0" class="text-cyan-600 font-medium">{{ t('paper.renderingPages', { loaded: pdfProgress.loadedPages, total: pdfProgress.totalPages }) }}</span>
        </div>
      </div>
      <button v-if="paper?.pdf_media_url" class="shrink-0 flex items-center gap-1.5 rounded-xl border border-stone-200 bg-white px-3 py-1.5 text-xs text-stone-600 transition hover:bg-stone-50 hover:border-stone-300" @click="emit('downloadPdf')">
        <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
        {{ t('paper.downloadPdf') }}
      </button>
    </header>

    <div class="flex-1 min-h-0 flex flex-col relative overflow-hidden">
      <PdfCanvasViewer :pdf-url="paper?.pdf_media_url ?? null" @rightclick-region="emit('rightclickRegion', $event)" @progress="emit('progress', $event)" />
      <Transition name="popup-fade">
        <div v-if="visionPopup?.visible" class="absolute bottom-4 md:bottom-24 left-1/2 -translate-x-1/2 w-[340px] max-w-[calc(100%_-_24px)] max-h-[calc(100%_-_24px)] overflow-y-auto rounded-2xl p-4 shadow-2xl" style="background: rgba(255,255,255,0.97); border: 1px solid rgba(168,162,158,0.25); backdrop-filter: blur(16px); z-index: 50">
          <p class="mb-2 text-xs font-semibold text-stone-600 flex items-center gap-1"><Camera class="h-3.5 w-3.5" /> {{ t('paper.captured') }}</p>
          <div class="mb-2 max-h-[160px] overflow-hidden rounded-lg border border-stone-200 bg-stone-100"><img :src="visionPopup.base64" :alt="t('paper.previewAlt')" class="w-full h-auto object-contain max-h-[160px]" /></div>
          <input :ref="(element) => emit('popupInputRef', element as Element | null)" :value="visionPopup.question" type="text" :placeholder="t('paper.visionPlaceholder')" class="w-full rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-700 placeholder:text-stone-400 focus:outline-none focus:ring-1 focus:ring-cyan-400/40" @input="emit('update:visionPopup', { ...visionPopup, question: ($event.target as HTMLInputElement).value })" @keydown="emit('popupKeydown', $event)" />
          <div class="mt-2.5 flex gap-2">
            <button class="flex-1 rounded-xl bg-stone-700 px-3 py-1.5 text-xs text-white transition hover:bg-stone-800 disabled:opacity-40" :disabled="!visionPopup.question.trim() || isSending" @click="emit('sendVision')">{{ t('paper.send') }}</button>
            <button class="rounded-xl border border-stone-200 px-3 py-1.5 text-xs text-stone-500 transition hover:bg-stone-50" @click="emit('closePopup')">{{ t('paper.cancel') }}</button>
          </div>
        </div>
      </Transition>
      <div v-if="!paperLoading && paper && !paper.pdf_media_url" class="absolute inset-0 flex items-center justify-center px-8">
        <div class="max-w-xl rounded-2xl p-6 text-center" style="background: rgba(255,255,255,0.85); border: 1px solid rgba(168,162,158,0.18)">
          <p class="mb-3 text-sm font-semibold text-stone-700 font-serif">{{ t('paper.pdfUnavailable') }}</p>
          <p class="text-xs text-stone-500 leading-6">{{ paper.summary?.slice(0, 400) }}…</p>
          <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener noreferrer" class="mt-4 inline-block text-xs text-stone-500 underline hover:text-stone-700">{{ t('paper.viewOriginal') }}</a>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.popup-fade-enter-active, .popup-fade-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.popup-fade-enter-from, .popup-fade-leave-to { opacity: 0; transform: translateX(-50%) translateY(8px) scale(0.97); }
.popup-fade-enter-to, .popup-fade-leave-from { transform: translateX(-50%) translateY(0) scale(1); }
</style>
