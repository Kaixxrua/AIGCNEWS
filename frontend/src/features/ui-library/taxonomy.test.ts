// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { UiTemplate } from './catalog'
import { browseMaterials, isFeatured, libraryKinds, materialKind, resolveLibraryKind, subcategory } from './taxonomy'
const items: UiTemplate[] = JSON.parse(readFileSync(resolve('../mcp-go/internal/uicatalog/data/catalog.json'), 'utf8')).items
describe('Material browsing and review boundaries', () => {
  it('defaults to all materials and keeps legacy featured links usable', () => {
    expect(libraryKinds.map(([key]) => key)).toEqual(['component', 'template', 'theme'])
    for (const value of ['', 'featured', 'unknown']) {
      expect(browseMaterials(items, resolveLibraryKind(value))).toEqual(items)
    }
    expect(resolveLibraryKind('theme')).toBe('theme')
    const block = { ...items[0]!, kind: 'block' as const }
    expect(browseMaterials([block], 'component')).toEqual([block])
    expect(browseMaterials([block], 'block')).toEqual([block])
  })
  it('keeps basic controls in a specific category and separates full pages and themes', () => {
    const legacyInput = { ...items[0]!, provider_id: 'hyperui', subcategory: undefined, category: 'component', files: [{ name: 'input.html', path: 'sources/hyperui/public/examples/application/inputs/1.html', sha256: '0'.repeat(64) }] }
    expect(subcategory(legacyInput)).toBe('inputs')
    expect(materialKind(items.find(i => i.id === 'shadcn-dashboard-01')!)).toBe('template')
    const themes = browseMaterials(items, 'theme')
    expect(themes).toHaveLength(42)
    expect(themes.every(i => i.theme?.light.primary && i.theme.dark.primary)).toBe(true)
    expect(browseMaterials(items, 'template', 'dashboard').map(i => i.id)).toContain('shadcn-dashboard-01')
  })
  it('requires a review for the exact imported source revision before featuring', () => {
    const item = { ...items[0]! }
    delete item.editorial
    expect(isFeatured(item)).toBe(false)
    item.editorial = { status: 'approved', revision: item.revision, source_sha256: item.files[0]!.sha256, reviewed_at: '2026-09-11', evidence: '/review.png', reason: 'Reviewed original' }
    expect(isFeatured(item)).toBe(true)
    expect(isFeatured({ ...item, revision: '0'.repeat(40) })).toBe(false)
    expect(isFeatured({ ...item, files: [{ ...item.files[0]!, sha256: '0'.repeat(64) }] })).toBe(false)
  })
  it('combines type, purpose and style without hiding legacy all-category URLs', () => {
    const before = items.map(i => i.id)
    expect(browseMaterials(items, 'theme', '', 'nature').every(i => i.kind === 'theme' && i.styles?.includes('nature'))).toBe(true)
    const rows = [
      { ...items[0]!, id: 'legacy-shader', kind: 'component' as const, category: 'shader', subcategory: 'shader' },
      { ...items[0]!, id: 'form', kind: 'component' as const, category: 'component', subcategory: 'inputs' },
    ]
    expect(browseMaterials(rows, 'all', 'shader').map(i => i.id)).toEqual(['legacy-shader'])
    expect(browseMaterials(rows, 'all', 'component').map(i => i.id)).toEqual(['form'])
    expect(items.map(i => i.id)).toEqual(before)
  })
})
