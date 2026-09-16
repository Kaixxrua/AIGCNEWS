// @vitest-environment node
import { expect, it } from 'vitest'
import { previewFiles } from './uiPreviewManifest'
const item = { id: 'eui-studio', preview_package: 'studio-cn', preview_files: {} }
const digest = 'a'.repeat(64)
it('accepts only canonical resources inside the pinned preview package', () => {
  for (const path of ['previews/eui/eui-studio.html', 'previews/eui/runtime/studio-cn/assets/app.js']) {
    expect(previewFiles({ ...item, preview_files: { [path]: digest } })).toHaveLength(1)
  }
  for (const path of ['previews/eui/runtime/other/app.js', 'previews/eui/runtime/studio-cn/../other/app.js', 'previews/eui/runtime/studio-cn/%2e%2e/app.js', 'previews/eui/runtime/studio-cn//app.js', 'sources/app.js']) {
    expect(() => previewFiles({ ...item, preview_files: { [path]: digest } })).toThrow()
  }
  expect(() => previewFiles({ ...item, preview_files: { 'previews/eui/eui-studio.html': 'stale' } })).toThrow()
})
