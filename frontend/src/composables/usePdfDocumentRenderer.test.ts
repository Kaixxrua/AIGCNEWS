import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePdfDocumentRenderer } from './usePdfDocumentRenderer'

const getDocument = vi.hoisted(() => vi.fn())
vi.mock('pdfjs-dist', () => ({ getDocument }))

const mountRenderer = () => {
  const renderer = usePdfDocumentRenderer({ onProgress: vi.fn() })
  renderer.containerRef.value = document.createElement('div')
  renderer.mount()
  return renderer
}

describe('PDF worker lifecycle', () => {
  beforeEach(() => getDocument.mockReset())
  afterEach(() => vi.unstubAllGlobals())

  it('cancels deferred rendering when its URL is cleared', async () => {
    let notify!: () => void
    const disconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { notify = callback }
      observe() {}
      disconnect = disconnect
    })
    const renderer = mountRenderer()
    renderer.startRenderWhenReady('https://example.test/old.pdf')
    renderer.handlePdfUrlChange(null)
    expect(disconnect).toHaveBeenCalledOnce()

    Object.defineProperty(renderer.containerRef.value, 'offsetHeight', { value: 100 })
    notify()
    await flushPromises()
    expect(getDocument).not.toHaveBeenCalled()
    renderer.unmount()
  })

  it('destroys the loading task on unmount with the PDF.js 6 API', async () => {
    const destroy = vi.fn(async () => {})
    getDocument.mockReturnValue({ promise: Promise.resolve({ numPages: 0 }), destroy })
    const renderer = mountRenderer()
    await renderer.loadPdf('https://example.test/paper.pdf')
    renderer.unmount()
    expect(destroy).toHaveBeenCalledOnce()
  })

  it('releases an in-flight document when its URL is cleared and ignores its late result', async () => {
    let resolve!: (doc: { numPages: number }) => void
    const destroy = vi.fn(async () => {})
    getDocument.mockReturnValue({ promise: new Promise((done) => { resolve = done }), destroy })
    const renderer = mountRenderer()
    const loading = renderer.loadPdf('https://example.test/old.pdf')
    await flushPromises()
    renderer.handlePdfUrlChange(null)
    expect(destroy).toHaveBeenCalledOnce()
    resolve({ numPages: 9 })
    await loading
    expect(renderer.totalPages.value).toBe(0)
    expect(renderer.progressPhase.value).toBe('idle')
    renderer.unmount()
  })

  it('replaces the old worker and keeps the new document when requests finish out of order', async () => {
    let resolve!: (doc: { numPages: number }) => void
    const destroyOld = vi.fn(async () => {})
    getDocument.mockReturnValueOnce({ promise: new Promise((done) => { resolve = done }), destroy: destroyOld })
      .mockReturnValueOnce({ promise: Promise.resolve({ numPages: 0 }), destroy: vi.fn(async () => {}) })
    const renderer = mountRenderer()
    const old = renderer.loadPdf('https://example.test/old.pdf')
    await flushPromises()
    await renderer.loadPdf('https://example.test/new.pdf')
    resolve({ numPages: 9 })
    await old
    expect(destroyOld).toHaveBeenCalledOnce()
    expect(renderer.totalPages.value).toBe(0)
    expect(renderer.progressPhase.value).toBe('done')
    renderer.unmount()
  })
})
