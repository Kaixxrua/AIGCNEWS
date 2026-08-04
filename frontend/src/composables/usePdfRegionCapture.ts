import { ref } from 'vue'
import type {
  PdfRegionCaptureOptions,
  PdfRegionSelection,
} from '@/features/papers/pdfViewerModel'

export function usePdfRegionCapture(options: PdfRegionCaptureOptions) {
  const selectionBox = ref<PdfRegionSelection | null>(null)
  const selectionStyle = ref({ left: '0px', top: '0px', width: '0px', height: '0px' })

  const getContainerOffset = () => {
    const rect = options.containerRef.value?.getBoundingClientRect()
    return rect ? { left: rect.left, top: rect.top } : { left: 0, top: 0 }
  }

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

    for (const entry of options.pageEntries.value) {
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
    options.onCapture({
      pageIndex: first.pageIndex,
      base64: dataUrl,
      x: Math.round(first.sx),
      y: Math.round(first.sy),
      w: Math.round(totalW),
      h: Math.round(totalH),
    })

    selectionBox.value = null
  }

  const onMouseDown = (e: MouseEvent) => {
    if (e.button !== 0) return
    const offset = getContainerOffset()
    const scrollTop = options.containerRef.value?.scrollTop ?? 0
    const scrollLeft = options.containerRef.value?.scrollLeft ?? 0
    const x = e.clientX - offset.left + scrollLeft
    const y = e.clientY - offset.top + scrollTop
    selectionBox.value = { startX: x, startY: y, endX: x, endY: y, active: true }
    updateSelectionStyle()
  }

  const onMouseMove = (e: MouseEvent) => {
    if (!selectionBox.value?.active) return
    const offset = getContainerOffset()
    const scrollTop = options.containerRef.value?.scrollTop ?? 0
    const scrollLeft = options.containerRef.value?.scrollLeft ?? 0
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

  return {
    selectionBox,
    selectionStyle,
    onMouseDown,
    onMouseMove,
    onMouseUp,
    onContextMenu,
  }
}
