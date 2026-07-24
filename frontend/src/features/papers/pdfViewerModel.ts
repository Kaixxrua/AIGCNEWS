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

export function getPdfProgressPercent(loadedPages: number, totalPages: number): number {
  if (totalPages === 0) return 0
  return Math.round(10 + (loadedPages / totalPages) * 90)
}
