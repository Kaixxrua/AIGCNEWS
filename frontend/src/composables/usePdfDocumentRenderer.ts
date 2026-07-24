import { computed, nextTick, ref } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import {
  getPdfProgressPercent,
  type PdfDocumentRendererOptions,
  type PdfPageEntry,
  type PdfProgress,
} from '../features/papers/pdfViewerModel'

export function usePdfDocumentRenderer(options: PdfDocumentRendererOptions) {
  const containerRef = ref<HTMLDivElement | null>(null)
  const isLoading = ref(false)
  const errorMessage = ref('')
  const totalPages = ref(0)
  const loadedPages = ref(0)
  const scale = ref(1.5)
  const isMounted = ref(false)
  const progressPercent = computed(() => getPdfProgressPercent(loadedPages.value, totalPages.value))
  const progressPhase = ref<PdfProgress['phase']>('idle')
  const pageEntries = ref<PdfPageEntry[]>([])

  let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null
  let renderTask: pdfjsLib.RenderTask | null = null
  let resizeObserver: ResizeObserver | null = null

  const emitProgress = () => {
    options.onProgress({
      phase: progressPhase.value,
      loadedPages: loadedPages.value,
      totalPages: totalPages.value,
      percent: progressPercent.value,
    })
  }

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

    const safeUrl = url.replace(/^http:\/\//i, 'https://')

    isLoading.value = true
    errorMessage.value = ''
    pageEntries.value = []
    totalPages.value = 0
    loadedPages.value = 0
    progressPhase.value = 'parsing'
    emitProgress()
    clearContainer()

    try {
      console.log('[PdfCanvasViewer] Loading PDF:', safeUrl)

      const loadingTask = pdfjsLib.getDocument({
        url: safeUrl,
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

  const mount = () => {
    isMounted.value = true
  }

  const handlePdfUrlChange = (url: string | null | undefined) => {
    if (!isMounted.value) return
    if (url) {
      loadPdf(url)
    } else {
      reset()
    }
  }

  const reset = () => {
    isLoading.value = false
    errorMessage.value = ''
    pageEntries.value = []
    totalPages.value = 0
    loadedPages.value = 0
    progressPhase.value = 'idle'
    emitProgress()
    if (containerRef.value) clearContainer()
  }

  const unmount = () => {
    isMounted.value = false
    resizeObserver?.disconnect()
    resizeObserver = null
    renderTask?.cancel()
    pdfDoc?.destroy()
  }

  return {
    containerRef,
    isLoading,
    errorMessage,
    totalPages,
    loadedPages,
    progressPercent,
    progressPhase,
    pageEntries,
    loadPdf,
    startRenderWhenReady,
    mount,
    handlePdfUrlChange,
    unmount,
  }
}
