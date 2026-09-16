export type UiLanguage = 'zh' | 'en'
export interface UiTemplate {
  id: string
  added_at?: string
  preview_kind?: 'html'
  preview_width?: number
  preview_package?: string
  preview_files?: Record<string, string>
  kind?: 'component' | 'block' | 'template' | 'theme'
  subcategory?: string
  styles?: string[]
  theme?: { light: Record<string, string>; dark: Record<string, string> }
  editorial?: { status: 'approved'; revision: string; source_sha256: string; reviewed_at: string; evidence: string; reason: string; position?: number }
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
const normalize = (text: string) => text.normalize('NFKC').toLowerCase().trim()
const stopWords = new Set(['a', 'an', 'the', 'for', 'with', 'and', 'in', 'make', 'build', 'please', 'show', 'me'])
export function queryTerms(query: string, items: UiTemplate[]): string[] {
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
export function searchTemplates(items: UiTemplate[], query = '', category = '', framework = ''): UiTemplate[] {
  const terms = queryTerms(query, items)
  return items.map((item, index) => {
    const title = normalize(`${item.name.zh} ${item.name.en} ${item.id}`)
    const core = normalize(`${title} ${item.provider} ${item.aliases.join(' ')} ${item.frameworks.join(' ')} ${item.category}`)
    const all = `${core} ${normalize(item.description.zh + ' ' + item.description.en)}`
    const score = terms.reduce((total, term) => total + (title.includes(term) ? 20 : core.includes(term) ? 10 : 1), 0)
    return { item, index, score, matches: terms.every(term => all.includes(term)) }
  }).filter(({ item, matches }) => matches && (!category || item.category === category) && (!framework || item.frameworks.includes(framework)))
    .sort((a, b) => b.score - a.score || a.index - b.index).map(({ item }) => item)
}
export function recentlyAdded(items: UiTemplate[], now = Date.now()): UiTemplate[] {
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
export async function loadCatalog(signal?: AbortSignal): Promise<UiTemplate[]> {
  const response = await fetch('/ui-library/catalog.json', { signal })
  if (!response.ok) throw new Error('Catalog unavailable')
  const data = await response.json()
  if (data.version !== 1 || !Array.isArray(data.items)) throw new Error('Invalid catalog')
  return data.items
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
