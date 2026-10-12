import { api } from '@/services/http/apiClient'

export type UiLanguage = 'zh' | 'en'
export interface UiTemplate {
  id: string
  deprecated?: boolean
  added_at?: string
  preview_kind?: 'html'
  preview_width?: number
  preview_package?: string
  preview_files?: Record<string, string>
  kind?: 'component' | 'block' | 'template' | 'theme'
  subcategory?: string
  styles?: string[]
  theme?: { light: Record<string, string>; dark: Record<string, string> }
  editorial?: { status: 'approved' | 'verified'; revision: string; source_sha256: string; reviewed_at: string; evidence: string; reason: string; position?: number }
  rights_evidence_url?: string
  name: Record<UiLanguage, string>
  description: Record<UiLanguage, string>
  notes: Record<UiLanguage, string>
  provider: string
  provider_id: string
  author: string
  license: string
  license_url: string
  revision: string
  source_url: string
  demo_url: string
  category: string
  frameworks: string[]
  aliases: string[]
  files: { name: string; path: string; sha256: string }[]
  notices: { name: string; path: string; sha256: string }[]
  dependencies: Record<string, string>
  export_name: string
  props: Record<string, unknown>
  assets: { name: string; path: string; sha256: string; license: string; license_url: string }[]
  preview_url: string
  clip_url: string
  poster_url: string
}
export interface UiSourceFile { name: string; content: string }
/** Card metadata; its first source entry is for taxonomy, never for copying. */
export type UiTemplateSummary = Pick<UiTemplate,
  'id' | 'deprecated' | 'added_at' | 'kind' | 'subcategory' | 'styles' | 'editorial'
  | 'name' | 'description' | 'provider' | 'provider_id' | 'author' | 'revision'
  | 'source_url' | 'demo_url' | 'category' | 'frameworks' | 'aliases'
  | 'preview_url' | 'clip_url' | 'poster_url' | 'files'>
const normalize = (text: string) => text.normalize('NFKC').toLowerCase().trim()
const stopWords = new Set(['a', 'an', 'the', 'for', 'with', 'and', 'in', 'make', 'build', 'please', 'show', 'me'])
export function queryTerms(query: string, items: readonly Pick<UiTemplate, 'aliases'>[]): string[] {
  const vocabulary = [...new Set(items.flatMap(item => item.aliases))]
  return normalize(query).match(/[a-z0-9]+|[\p{Script=Han}]+/gu)?.flatMap(term => {
    if (stopWords.has(term)) return []
    if (/\p{Script=Han}/u.test(term)) {
      const known = vocabulary.filter(alias => /\p{Script=Han}/u.test(alias) && term.includes(alias))
      return known.length ? known : [term]
    }
    return [term]
  }) ?? []
}
/** 搜索只看名称、简介、出处、别名、框架与分类；站内速查只留这几样字段，不必握着整份目录。 */
export type SearchableTemplate = Pick<UiTemplate, 'id' | 'name' | 'description' | 'provider' | 'aliases' | 'frameworks' | 'category'>
export function searchTemplates<T extends SearchableTemplate>(items: readonly T[], query = '', category = '', framework = ''): T[] {
  const terms = query.trim() ? queryTerms(query, items) : []
  if (!terms.length) return items.filter(item => (!category || item.category === category) && (!framework || item.frameworks.includes(framework)))
  return items.map((item, index) => {
    const title = normalize(`${item.name.zh} ${item.name.en} ${item.id}`)
    const core = normalize(`${title} ${item.provider} ${item.aliases.join(' ')} ${item.frameworks.join(' ')} ${item.category}`)
    const all = `${core} ${normalize(item.description.zh + ' ' + item.description.en)}`
    const score = terms.reduce((total, term) => total + (title.includes(term) ? 20 : core.includes(term) ? 10 : 1), 0)
    return { item, index, score, matches: terms.every(term => all.includes(term)) }
  }).filter(({ item, matches }) => matches && (!category || item.category === category) && (!framework || item.frameworks.includes(framework)))
    .sort((a, b) => b.score - a.score || a.index - b.index).map(({ item }) => item)
}
export function recentlyAdded<T extends Pick<UiTemplate, 'added_at'>>(items: T[], now = Date.now()): T[] {
  return items.filter(item => {
    const added = Date.parse(item.added_at ?? '')
    return Number.isFinite(added) && added <= now && added > now - 24 * 60 * 60 * 1000
  }).sort((a, b) => Date.parse(b.added_at!) - Date.parse(a.added_at!))
}
export function addedOnCalendarDay(items: UiTemplate[], now = Date.now(), timeZone = 'Asia/Shanghai'): UiTemplate[] {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  const targetDay = formatter.format(now)
  return items.filter(item => {
    const added = Date.parse(item.added_at ?? '')
    return Number.isFinite(added) && added <= now && formatter.format(added) === targetDay
  }).sort((a, b) => Date.parse(b.added_at!) - Date.parse(a.added_at!))
}
export interface UiIcon {
  id: string
  deprecated?: boolean
  name: string
  display: Record<UiLanguage, string>
  style: string
  category: string
  aliases: string[]
  file: string
  sha256: string
}
export interface UiIconSet {
  provider: string
  provider_id: string
  author: string
  license: string
  license_url: string
  license_note: string
  scope_note: string
  repository: string
  revision: string
  source_url: string
  format: string
  dependencies: Record<string, string>
  added_at: string
  rights_evidence_url: string
  icons: UiIcon[]
}
async function loadVisibleCatalog(path: string, signal?: AbortSignal, includeDeprecated = false, params: Record<string, string> = {}) {
  if (includeDeprecated) return (await api.get(path, { signal, params: { ...params, include_deprecated: true } })).data
  const query = new URLSearchParams(params).toString()
  const response = await fetch(`/api${path}${query ? '?' + query : ''}`, { signal, cache: 'no-store' })
  if (!response.ok) throw new Error('Catalog unavailable')
  return response.json()
}

export async function loadIconSets(signal?: AbortSignal, includeDeprecated = false): Promise<UiIconSet[]> {
  const data = await loadVisibleCatalog('/ui-library/icons', signal, includeDeprecated)
  if (data.version !== 1 || !Array.isArray(data.sets)) throw new Error('Invalid icon catalog')
  return data.sets
}
export function searchIcons(sets: UiIconSet[], query = '', provider = '', style = '', category = ''): UiIcon[] {
  const terms = normalize(query).match(/[a-z0-9]+|[\p{Script=Han}]+/gu)?.filter(term => !iconStopWords.has(term)) ?? []
  const results: { icon: UiIcon; index: number; score: number }[] = []
  sets.forEach((set, setIndex) => {
    if (provider && set.provider_id !== provider) return
    set.icons.forEach((icon, iconIndex) => {
      if (style && icon.style !== style) return
      if (category && icon.category !== category) return
      const title = normalize(`${icon.display.zh} ${icon.display.en} ${icon.id}`)
      const core = normalize(`${title} ${set.provider} ${icon.aliases.join(' ')} ${icon.style} ${icon.category}`)
      if (!terms.every(term => core.includes(term))) return
      const score = terms.reduce((total, term) => total + (title.includes(term) ? 20 : 10), 0)
      results.push({ icon, index: setIndex * 1000000 + iconIndex, score })
    })
  })
  return results.sort((a, b) => b.score - a.score || a.index - b.index).map(({ icon }) => icon)
}
const iconStopWords = new Set(['a', 'an', 'the', 'icon', 'icons', 'for', 'with', 'and', 'in', 'of'])
export function iconUrl(icon: UiIcon): string {
  return `/ui-library/${icon.file}`
}
export async function loadIconSource(icon: UiIcon, signal?: AbortSignal): Promise<string> {
  const response = await fetch(iconUrl(icon), { signal })
  if (!response.ok) throw new Error('Icon source unavailable')
  return response.text()
}
export function iconIntegrationPrompt(icon: UiIcon, set: UiIconSet, svg: string, lang: UiLanguage): string {
  const instruction = lang === 'zh'
    ? '请在当前项目中使用这个原版 SVG 图标。保留 viewBox、路径和无障碍属性，只调整尺寸与 currentColor 配色。按图标集许可证要求，随复制的图标保留许可文本。'
    : 'Use this original SVG icon in the current project. Keep the viewBox, paths and accessibility attributes unchanged, adapting only size and currentColor styling. Keep the license notice with the copied icon as the set license requires.'
  return `${instruction}\n\nicon: ${icon.id} (${icon.style} · ${icon.category})\nset: ${set.provider} by ${set.author} · ${set.license} · ${set.license_url}\nsource: ${set.source_url}\nrevision: ${set.revision}\nsha256: ${icon.sha256}\n\n--- ${icon.name}.svg ---\n\`\`\`svg\n${svg}\n\`\`\``
}

export async function loadIconLicense(set: UiIconSet, signal?: AbortSignal): Promise<string> {
  const response = await fetch(set.license_url, { signal })
  if (!response.ok) throw new Error('Icon license unavailable')
  return response.text()
}

export async function loadCatalogWithMeta(signal?: AbortSignal, includeDeprecated = false): Promise<{ items: UiTemplate[]; iconCount: number }> {
  const data = await loadVisibleCatalog('/ui-library/catalog', signal, includeDeprecated)
  if (data.version !== 1 || !Array.isArray(data.items)) throw new Error('Invalid catalog')
  return { items: data.items, iconCount: Number(data.icon_count) || 0 }
}
export async function loadCatalog(signal?: AbortSignal): Promise<UiTemplate[]> {
  const { items } = await loadCatalogWithMeta(signal)
  return items
}
export async function loadCatalogSummaries(signal?: AbortSignal, includeDeprecated = false): Promise<{ items: UiTemplateSummary[]; iconCount: number }> {
  const data = await loadVisibleCatalog('/ui-library/catalog', signal, includeDeprecated, { summary: 'true' })
  if (data.version !== 1 || !Array.isArray(data.items)) throw new Error('Invalid catalog')
  return { items: data.items, iconCount: Number(data.icon_count) || 0 }
}
export async function loadTemplate(id: string, signal?: AbortSignal, includeDeprecated = false): Promise<UiTemplate> {
  const data = await loadVisibleCatalog('/ui-library/catalog', signal, includeDeprecated, { template_id: id })
  if (data.version !== 1 || !Array.isArray(data.items) || data.items.length !== 1 || data.items[0]?.id !== id) {
    throw new Error('Source unavailable')
  }
  return data.items[0]
}
export async function loadSources(item: UiTemplate, signal?: AbortSignal): Promise<UiSourceFile[]> {
  return Promise.all([...item.files, ...(item.notices ?? [])].map(async file => {
    const response = await fetch(`/ui-library/${file.path}`, { signal })
    if (!response.ok) throw new Error('Source unavailable')
    return { name: file.name, content: await response.text() }
  }))
}
export function sourceBundle(files: UiSourceFile[]): string {
  return files.map(file => `--- ${file.name} ---\n\`\`\`\n${file.content}\n\`\`\``).join('\n\n')
}
export function integrationPrompt(item: UiTemplate, files: UiSourceFile[], lang: UiLanguage): string {
  const dependencies = Object.entries(item.dependencies).map(([name, version]) => `${name}@${version}`).join(' ')
  const assets = (item.assets ?? []).map(asset => `${asset.name}: ${new URL(`/ui-library/${asset.path}`, window.location.origin)} (${asset.license}; ${asset.license_url})`).join('\n')
  const instructions = lang === 'zh'
    ? `请把 ${item.provider} 的「${item.name.zh} / ${item.name.en}」集成到当前项目。\n先检查项目框架与已有依赖，保留原作品的视觉效果、配色和交互，只修改接入所需的导入、路径与容器尺寸。不要用重新生成的近似效果替代。保持响应式布局、键盘可用性和减少动态效果偏好。\n${item.notes.zh}\n依赖：${dependencies}\n源码按下面的文件路径组织；CSS 和相对导入文件也需要保留。保留作者和许可证。`
    : `Integrate "${item.name.en}" by ${item.provider} into the current project.\nInspect the existing framework and dependencies first. Preserve the original visuals, colors and interactions; only adapt imports, paths and container sizing. Do not replace it with a newly generated approximation. Preserve responsive behavior, keyboard access and reduced-motion preferences.\n${item.notes.en}\nDependencies: ${dependencies}\nKeep the source file structure below, including CSS and relative imports. Preserve authorship and license notices.`
  return `${instructions}\nExport: ${item.export_name}\nPreview props: ${JSON.stringify(item.props)}\nAssets (save at the original paths):\n${assets || 'None'}\n\n${item.source_url}\nRevision: ${item.revision}\nAuthor: ${item.author}\nLicense: ${item.license}\n\n${sourceBundle(files)}`
}
