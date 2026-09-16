import type { UiTemplate } from '../src/features/ui-library/catalog'

// Nested preview resources are opt-in and confined to one reviewed package.
export function previewFiles(item: Pick<UiTemplate, 'id' | 'preview_package' | 'preview_files'>) {
  const entries = Object.entries(item.preview_files ?? {})
  if (!entries.length) return entries
  if (!/^[a-z0-9-]+$/.test(item.preview_package ?? '')) throw new Error('Invalid preview package')
  for (const [name, digest] of entries) {
    const parts = name.split('/')
    if (parts.some(p => !p || p === '.' || p === '..') || /[\\%?#]/.test(name) ||
      (!name.startsWith('previews/eui/runtime/' + item.preview_package + '/') && name !== 'previews/eui/' + item.id + '.html') ||
      !/^[a-f0-9]{64}$/.test(digest)) throw new Error('Invalid pinned preview resource: ' + name)
  }
  return entries
}
