import type { UiLanguage, UiTemplate } from '@/features/ui-library/catalog'

// Reviewed for a full-frame homepage preview. Keep ordinary controls out of this pool.
const selections: { id: string; name: Record<UiLanguage, string>; scale: number }[] = [
  { id: 'eui-shader-worlds', name: { zh: '黑洞视界', en: 'Shader worlds' }, scale: 1 },
  // ThreeUI recordings center the effect in a padded demo canvas; crop that canvas here only.
  { id: 'threeui-liquidformbackground', name: { zh: '液态金属', en: 'Liquid metal' }, scale: 3 },
  { id: 'eui-fluid-studio', name: { zh: '流动工作室', en: 'Fluid studio' }, scale: 1 },
  { id: 'eui-adventure-roadbook', name: { zh: '金色星球', en: 'Golden globe' }, scale: 1 },
  { id: 'eui-bigscreen-cockpit', name: { zh: '数据指挥中心', en: 'Global command center' }, scale: 1 },
  { id: 'kokonut-flow-field', name: { zh: '粒子流场', en: 'Particle flow field' }, scale: 1 },
  { id: 'eui-exploded-view', name: { zh: '3D 芯片拆解', en: '3D chip explorer' }, scale: 1 },
  { id: 'eui-rainy-notes', name: { zh: '雨窗霓虹', en: 'Rainy neon' }, scale: 1 },
]

export type UiShowcaseItem = Pick<UiTemplate, 'id' | 'poster_url' | 'clip_url'>
export interface UiShowcaseCatalog { version: 1; total: number; items: UiShowcaseItem[] }

export function selectUiShowcase(items: UiShowcaseItem[]) {
  const catalog = new Map(items.map(item => [item.id, item]))
  return selections.flatMap(selection => {
    const item = catalog.get(selection.id)
    return item?.clip_url && item.poster_url ? [{ ...selection, item }] : []
  })
}

// The homepage needs the count and eight previews, not source files and licenses.
// Derive both from the same release catalog so the count cannot drift.
export function buildUiShowcaseCatalog(items: UiTemplate[]): UiShowcaseCatalog {
  return {
    version: 1,
    total: items.length,
    items: selectUiShowcase(items).map(({ item: { id, poster_url, clip_url } }) => ({ id, poster_url, clip_url })),
  }
}

export async function loadUiShowcaseCatalog(signal?: AbortSignal): Promise<UiShowcaseCatalog> {
  const response = await fetch('/ui-library/dashboard.json', { signal })
  if (!response.ok) throw new Error('Dashboard catalog unavailable')
  const data = await response.json()
  if (data.version !== 1 || !Number.isSafeInteger(data.total) || data.total < 0 || !Array.isArray(data.items)
    || data.items.some((item: UiShowcaseItem | null) => !item || typeof item.id !== 'string'
      || typeof item.poster_url !== 'string' || typeof item.clip_url !== 'string')) {
    throw new Error('Invalid dashboard catalog')
  }
  return data
}
