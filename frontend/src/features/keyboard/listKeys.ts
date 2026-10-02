/**
 * 列表键盘流的纯逻辑：哪个键做什么、什么时候不接、光标往哪走。DOM 与状态在 useListKeys 里。
 */
export type ListKeyAction = 'next' | 'prev' | 'open' | 'save' | 'toggle' | 'escape' | 'help'

const LETTERS: Readonly<Record<string, ListKeyAction>> = { j: 'next', k: 'prev', o: 'open', s: 'save', x: 'toggle' }

/**
 * 按下的键对应的动作；不是列表键位时为 null。只认不带 Ctrl、⌘、Alt 的单键，Shift 只给「?」；输入法组字中不接。
 * 字母先看产出的字符（大写锁定也认），非拉丁键盘布局退回看物理键位。回车与 o 同义，接不接由调用方看焦点在哪。
 */
export function listKeyAction(event: KeyboardEvent): ListKeyAction | null {
  if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return null
  if (event.ctrlKey || event.metaKey || event.altKey) return null
  if (event.key === '?' || event.key === '？') return 'help'
  if (event.key === 'Escape') return 'escape'
  if (event.shiftKey) return null
  if (event.key === 'Enter') return 'open'
  const letter = /^[a-z]$/i.test(event.key)
    ? event.key.toLowerCase()
    : /^Key[A-Z]$/.test(event.code ?? '') && !/^[\x20-\x7e]$/.test(event.key) ? event.code.slice(3).toLowerCase() : ''
  return LETTERS[letter] ?? null
}

// 字母键在这些地方有自己的用处：打字、下拉与菜单的首字母跳转、滑块与数值框。
const TYPING = 'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"], [role="listbox"], [role="menu"], [role="menubar"], [role="slider"], [role="spinbutton"]'
const NOT_TYPING_INPUTS = new Set(['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file', 'image'])

/** 焦点所在处是否要把字母键留给它自己。勾选框、按钮一类不打字的输入不算。 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  const field = target.closest(TYPING)
  if (!field) return false
  return !(field instanceof HTMLInputElement && NOT_TYPING_INPUTS.has(field.type))
}

/** 页面上是否开着模态浮层（推文详情、图片放大、登录框之类）：开着时列表键位让给浮层。 */
export function isModalOpen(doc: Document = document): boolean {
  for (const el of doc.querySelectorAll('[aria-modal="true"]')) if (el.getClientRects().length > 0) return true
  try {
    return doc.querySelector('dialog:modal') !== null
  } catch {
    return false
  }
}

/** 光标从 current 往 direction 走一步；走出头时为 null。current 不在列表里时也为 null，由调用方另找起点。 */
export function stepKey(keys: readonly string[], current: string, direction: 1 | -1): string | null {
  const index = keys.indexOf(current)
  if (index < 0) return null
  return keys[index + direction] ?? null
}

export interface Span { top: number; bottom: number }

/**
 * 按阅读顺序，第一条整个顶边落在视野里的条目；没有的话第一条露出了一截的；都没有为 null。
 * view 是视野上下沿（已扣掉顶部与底部被遮住的部分），box 给出条目此刻的上下沿，取不到（没渲染）为 null。
 */
export function firstInView(keys: readonly string[], box: (key: string) => Span | null, view: Span): string | null {
  let partial: string | null = null
  for (const key of keys) {
    const span = box(key)
    if (!span || span.bottom <= view.top || span.top >= view.bottom) continue
    if (span.top >= view.top - 1) return key
    partial ??= key
  }
  return partial
}
