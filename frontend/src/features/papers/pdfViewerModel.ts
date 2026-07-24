export type PdfProgressPhase = 'idle' | 'fetching' | 'parsing' | 'rendering' | 'done' | 'error'

export interface PdfProgress {
  phase: PdfProgressPhase
  loadedPages: number
  totalPages: number
  percent: number
}

export interface PdfPageEntry {
  canvas: HTMLCanvasElement
  viewport: {
    width: number
    height: number
    scale: number
  }
}

export interface PdfDocumentRendererOptions {
  onProgress: (progress: PdfProgress) => void
}

export interface PdfRegionSelection {
  startX: number
  startY: number
  endX: number
  endY: number
  active: boolean
}

export interface PdfRegionCapture {
  pageIndex: number
  base64: string
  x: number
  y: number
  w: number
  h: number
}

export interface PdfRegionCaptureOptions {
  containerRef: { value: HTMLDivElement | null }
  pageEntries: { value: PdfPageEntry[] }
  onCapture: (capture: PdfRegionCapture) => void
}

export function getPdfProgressPercent(loadedPages: number, totalPages: number): number {
  if (totalPages === 0) return 0
  return Math.round(10 + (loadedPages / totalPages) * 90)
}
