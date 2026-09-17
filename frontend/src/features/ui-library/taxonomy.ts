import type { UiTemplate, UiLanguage } from './catalog'
import { detailedCategories, detailedStyles } from './taxonomyData'
export const libraryKinds = [
  ['component', '组件', 'Components'], ['template', '模板', 'Templates'], ['theme', '主题', 'Themes'], ['icon', '图标', 'Icons'],
] as const
export type LibraryKind = typeof libraryKinds[number][0] | 'all' | 'block'
export function resolveLibraryKind(value: string): LibraryKind {
  // Old featured links remain usable after removing that navigation category.
  if (value === 'block') return 'block'
  return libraryKinds.some(([key]) => key === value) ? value as LibraryKind : 'all'
}
export const categories = detailedCategories
export const styleTags = detailedStyles
const aliases: Record<string, string> = { button:'buttons', card:'cards', input:'inputs', forms:'inputs', textareas:'inputs', select:'inputs', selects:'inputs', checkbox:'checkboxes', 'radio-groups':'checkboxes', radio:'checkboxes', toggle:'toggles', loader:'loaders', 'progress-bars':'loaders', 'radio-buttons':'checkboxes', 'radio buttons':'checkboxes', 'toggle-switches':'toggles', 'toggle switches':'toggles', breadcrumb:'navigation', breadcrumbs:'navigation', pagination:'navigation', menus:'navigation', headers:'navigation', dropdowns:'navigation', 'side-menu':'navigation', 'vertical-menu':'navigation', announcements:'badges', alerts:'badges', toasts:'badges', tooltips:'badges', tooltip:'badges', faqs:'faq', footers:'footer', ctas:'hero', sections:'features', stats:'tables', patterns:'background' }
export function subcategory(item: UiTemplate): string {
  if (item.subcategory) return item.subcategory
  if (['shader', 'background', 'text'].includes(item.category)) return item.category
  const path = item.files[0]?.path ?? ''
  const sourceCategory = item.provider_id === 'galaxy' ? path.split('/')[2]?.toLowerCase() : item.provider_id === 'hyperui' ? path.split('/')[5] : ''
  const candidate = aliases[sourceCategory ?? ''] ?? sourceCategory
  return categories.some(([key]) => key === candidate) ? candidate! : 'other'
}
export function materialKind(item: UiTemplate): Exclude<LibraryKind, 'all'> {
  if (item.kind) return item.kind
  if (item.provider_id === 'hyperui' && ['hero', 'pricing', 'features', 'testimonials', 'faq', 'footer'].includes(subcategory(item))) return 'block'
  return 'component'
}
export function isFeatured(item: UiTemplate): boolean {
  const review = item.editorial
  return review?.status === 'approved' && review.revision === item.revision && review.source_sha256 === item.files[0]?.sha256
}
export function browseMaterials(items: UiTemplate[], kind: LibraryKind, category = '', style = '') {
  return items.filter(item => (kind === 'all' || materialKind(item) === kind || (kind === 'component' && materialKind(item) === 'block')) && (!category || subcategory(item) === category || item.category === category) && (!style || item.styles?.includes(style)))
}
export function categoryLabel(item: UiTemplate, lang: UiLanguage) {
  const row = categories.find(([key]) => key === subcategory(item))
  return row?.[lang === 'zh' ? 1 : 2] ?? ''
}
