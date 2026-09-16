// @vitest-environment node
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { describe, expect, it, vi, afterEach } from 'vitest'
import { addedOnCalendarDay, recentlyAdded, searchTemplates, integrationPrompt, loadCatalog, loadSources, iconUrl, loadIconSets, searchIcons, type UiIconSet, type UiTemplate } from './catalog'

const dataRoot = pathToFileURL(resolve(process.cwd(), '../mcp-go/internal/uicatalog/data') + '/')
const items: UiTemplate[] = JSON.parse(readFileSync(new URL('catalog.json', dataRoot), 'utf8')).items
const iconSets: UiIconSet[] = JSON.parse(readFileSync(new URL('icons.json', dataRoot), 'utf8')).sets
const searchItems: UiTemplate[] = JSON.parse(readFileSync(new URL('../testdata/search_catalog.json', dataRoot), 'utf8')).items
const cases: { q: string; category?: string; framework?: string; ids: string[] }[] = JSON.parse(readFileSync(new URL('../testdata/search_cases.json', dataRoot), 'utf8'))
afterEach(() => vi.unstubAllGlobals())

describe('UI catalog shared Chinese/English contract', () => {
  it.each(cases)('finds $q / $framework / $category', ({ q, category, framework, ids }) => {
    expect(searchTemplates(searchItems, q, category, framework).map(item => item.id).sort()).toEqual([...ids].sort())
  })
  it('keeps all original bytes and licensed, pinned provenance', () => {
    expect(items.length).toBeGreaterThan(0)
    const licenses = new Set<string>()
    const hashes = new Map<string, string>()
    for (const item of items) {
      expect(item.revision).toMatch(/^[a-f0-9]{40}$/)
      if (!licenses.has(item.provider_id)) {
        expect(readFileSync(new URL(`licenses/${item.provider_id}/LICENSE`, dataRoot), 'utf8')).toBeTruthy()
        licenses.add(item.provider_id)
      }
      for (const file of item.files) {
        if (!hashes.has(file.path)) hashes.set(file.path, createHash('sha256').update(readFileSync(new URL(file.path, dataRoot))).digest('hex'))
        expect(hashes.get(file.path)).toBe(file.sha256)
      }
    }
  }, 120000)
  it('uses the first import timestamp and an exclusive rolling 24-hour boundary', () => {
    const now = Date.parse('2026-09-11T00:00:00Z')
    const rows = [undefined, 'invalid', '2026-09-11T00:00:01Z', '2026-09-10T00:00:00Z', '2026-09-10T00:00:01Z', '2026-09-11T08:00:00+08:00'].map((added_at, index) => ({ ...items[0]!, id: String(index), added_at }))
    expect(recentlyAdded(rows, now).map(item => item.id)).toEqual(['5', '4'])
    expect(rows.map(item => item.id)).toEqual(['0', '1', '2', '3', '4', '5'])
    expect(recentlyAdded(rows, now + 24 * 60 * 60 * 1000)).toEqual([rows[2]])
  })
  it('counts imports by the Beijing calendar day instead of a rolling window', () => {
    const now = Date.parse('2026-09-16T02:00:00Z')
    const rows = [
      '2026-09-15T15:59:59Z',
      '2026-09-15T16:00:00Z',
      '2026-09-16T01:30:00Z',
      '2026-09-16T03:00:00Z',
      'invalid',
    ].map((added_at, index) => ({ ...items[0]!, id: String(index), added_at }))

    expect(addedOnCalendarDay(rows, now).map(item => item.id)).toEqual(['2', '1'])
  })
  it('copies a useful bilingual prompt with all supplied files and provenance', () => {
    vi.stubGlobal('window', { location: { origin: 'https://catalog.test' } })
    const item = items[0]!
    const files = item.files.map(file => ({ name: file.name, content: readFileSync(new URL(file.path, dataRoot), 'utf8') }))
    for (const language of ['zh', 'en'] as const) {
      const prompt = integrationPrompt(item, files, language)
      expect(prompt).toContain(item.source_url)
      expect(prompt).toContain(item.revision)
      expect(prompt).toContain(item.author)
      expect(prompt).toContain(item.license)
      for (const file of files) { expect(prompt).toContain(file.name); expect(prompt).toContain(file.content) }
    }
  })
  it('keeps every icon pinned, hashed and license-covered like component sources', () => {
    expect(iconSets.length).toBeGreaterThan(0)
    for (const set of iconSets) {
      expect(set.revision).toMatch(/^[a-f0-9]{40}$/)
      expect(set.icons.length).toBeGreaterThan(0)
      expect(readFileSync(new URL(`licenses/${set.provider_id}/LICENSE`, dataRoot), 'utf8')).toBeTruthy()
      const manifest = JSON.parse(readFileSync(new URL(set.rights_evidence_url.replace('/ui-library/', ''), dataRoot), 'utf8'))
      expect(manifest.license_grants).toContain('commercial-use')
      expect(manifest.license_grants).toContain('redistribution')
      expect(manifest.screenshot_sha256).toBeTruthy()
      for (const icon of set.icons) {
        expect(icon.id).toBe(`${set.provider_id}:${icon.name}`)
        expect(icon.file.startsWith(`sources/${set.provider_id}/`)).toBe(true)
        expect(manifest.source_files[icon.file]).toBe(icon.sha256)
        const bytes = readFileSync(new URL(icon.file, dataRoot))
        expect(createHash('sha256').update(bytes).digest('hex')).toBe(icon.sha256)
        expect(bytes.byteLength).toBeLessThanOrEqual(64 * 1024)
        const text = bytes.toString('utf8')
        expect(text).not.toMatch(/<script|onload=|javascript:/i)
      }
    }
  }, 120000)
  it('searches icons with the same strict all-terms contract as components', () => {
    const set = iconSets[0]!
    const probe = set.icons[0]!
    const matches = searchIcons(iconSets, probe.name)
    expect(matches.map(icon => icon.id)).toContain(probe.id)
    expect(searchIcons(iconSets, '', set.provider_id).every(icon => icon.id.startsWith(set.provider_id + ':'))).toBe(true)
    expect(searchIcons(iconSets, probe.name, '', probe.style).every(icon => icon.style === probe.style)).toBe(true)
    expect(searchIcons(iconSets, 'definitely-not-an-icon-xyz')).toEqual([])
    expect(iconUrl(probe)).toBe(`/ui-library/${probe.file}`)
  })
  it('fails visibly on bad catalog or unavailable source instead of copying HTML', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    await expect(loadCatalog()).rejects.toThrow()
    await expect(loadSources(items[0]!)).rejects.toThrow()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ version: 2, items: [] }) }))
    await expect(loadCatalog()).rejects.toThrow('Invalid catalog')
    await expect(loadIconSets()).rejects.toThrow('Invalid icon catalog')
  })
})
