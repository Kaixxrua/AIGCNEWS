import { INLINE_DOLLAR_MATH } from '@/utils/latexDelimiters'

/*
 * 论文摘要多是作者照 LaTeX 写的：\emph{…}、\textbf{…}、2\%、---、``…''、GLM~5.1……原样显示很难读
 * （2026-10-04 抽查 120 篇有 29 篇）。这里把公式外的写法换成排版：
 *   - paperAbstractMarkup：交给 renderMarkdown 的摘要，加粗、斜体、等宽、下划线、上下标和链接写成 HTML 标签；
 *   - paperPlainText：只放文字的地方（论文标题，首页论文榜、⌘K 搜索里的摘要），命令只留文字。
 * 公式（$…$、$$…$$、\(…\)、\[…\]、\begin{…}…\end{…}）一字不动留给 KaTeX，认法与 renderLatex 相同。
 * 不认识的命令（多是作者自己定义的 \ours、\method）去掉反斜杠、留下名字。
 */

type Style = 'bold' | 'italic' | 'code' | 'underline' | 'sup' | 'sub'

interface Scan {
  readonly src: string
  i: number
  /** true：产出给 renderMarkdown 的文本；false：纯文字。 */
  readonly markup: boolean
  /** 在等宽（\texttt）里：引号、破折号不换。 */
  code: boolean
}

const TAGS: Record<Style, string> = { bold: 'strong', italic: 'em', code: 'code', underline: 'u', sup: 'sup', sub: 'sub' }

// 带一个参数的排版命令；null 表示只留文字。
const STYLE_COMMANDS = new Map<string, Style | null>([
  ['textbf', 'bold'], ['emph', 'italic'], ['textit', 'italic'], ['textsl', 'italic'], ['texttt', 'code'],
  ['underline', 'underline'], ['uline', 'underline'], ['textsuperscript', 'sup'], ['textsubscript', 'sub'],
  ['textrm', null], ['textsf', null], ['textsc', null], ['textup', null], ['textmd', null], ['textnormal', null],
  ['text', null], ['mbox', null], ['hbox', null], ['fbox', null], ['ensuremath', null],
])
// {\it …}、{\bf …} 这类开关，管到所在花括号结束。
const STYLE_SWITCHES = new Map<string, Style | null>([
  ['bf', 'bold'], ['bfseries', 'bold'], ['it', 'italic'], ['itshape', 'italic'], ['em', 'italic'], ['sl', 'italic'],
  ['slshape', 'italic'], ['tt', 'code'], ['ttfamily', 'code'], ['rm', null], ['rmfamily', null], ['sf', null],
  ['sffamily', null], ['sc', null], ['scshape', null], ['upshape', null], ['mdseries', null], ['normalfont', null],
])
// 引用、交叉引用、竖向间距和颜色：连同参数一起去掉，前面的空格也去掉（「framework~\cite{x},」→「framework,」）。
const DROPPED_WITH_ARGUMENT = new Set([
  'cite', 'citep', 'citet', 'citealp', 'citealt', 'citeauthor', 'citeyear', 'nocite',
  'ref', 'eqref', 'autoref', 'cref', 'Cref', 'pageref', 'label', 'vspace', 'color',
])
const DROPPED = new Set([
  'xspace', 'relax', 'protect', 'noindent', 'centering', 'footnotemark',
  'smallskip', 'medskip', 'bigskip', 'hfill', 'vfill', 'nobreak', 'allowbreak', 'unskip',
])
const SYMBOLS = new Map<string, string>([
  // 写在公式外的数学符号
  ['times', '×'], ['approx', '≈'], ['sim', '∼'], ['simeq', '≃'], ['pm', '±'], ['mp', '∓'], ['le', '≤'], ['leq', '≤'],
  ['ge', '≥'], ['geq', '≥'], ['ne', '≠'], ['neq', '≠'], ['ll', '≪'], ['gg', '≫'], ['propto', '∝'], ['infty', '∞'],
  ['to', '→'], ['rightarrow', '→'], ['leftarrow', '←'], ['Rightarrow', '⇒'], ['Leftarrow', '⇐'], ['leftrightarrow', '↔'],
  ['uparrow', '↑'], ['downarrow', '↓'], ['cdot', '·'], ['cdots', '⋯'], ['ldots', '…'], ['dots', '…'], ['degree', '°'],
  ['circ', '∘'], ['checkmark', '✓'], ['bullet', '•'],
  ['alpha', 'α'], ['beta', 'β'], ['gamma', 'γ'], ['delta', 'δ'], ['epsilon', 'ϵ'], ['varepsilon', 'ε'], ['zeta', 'ζ'],
  ['eta', 'η'], ['theta', 'θ'], ['iota', 'ι'], ['kappa', 'κ'], ['lambda', 'λ'], ['mu', 'μ'], ['nu', 'ν'], ['xi', 'ξ'],
  ['pi', 'π'], ['rho', 'ρ'], ['sigma', 'σ'], ['tau', 'τ'], ['upsilon', 'υ'], ['phi', 'ϕ'], ['varphi', 'φ'], ['chi', 'χ'],
  ['psi', 'ψ'], ['omega', 'ω'], ['Gamma', 'Γ'], ['Delta', 'Δ'], ['Theta', 'Θ'], ['Lambda', 'Λ'], ['Xi', 'Ξ'], ['Pi', 'Π'],
  ['Sigma', 'Σ'], ['Phi', 'Φ'], ['Psi', 'Ψ'], ['Omega', 'Ω'],
  // 文本符号
  ['textendash', '–'], ['textemdash', '—'], ['textellipsis', '…'], ['textquoteleft', '‘'], ['textquoteright', '’'],
  ['textquotedblleft', '“'], ['textquotedblright', '”'], ['textasciitilde', '~'], ['textasciicircum', '^'],
  ['textbackslash', '\\'], ['textbar', '|'], ['textless', '<'], ['textgreater', '>'], ['textunderscore', '_'],
  ['textdegree', '°'], ['textbullet', '•'], ['textperiodcentered', '·'], ['textregistered', '®'], ['texttrademark', '™'],
  ['textcopyright', '©'], ['copyright', '©'], ['S', '§'], ['dag', '†'], ['ddag', '‡'], ['pounds', '£'], ['euro', '€'],
  ['LaTeX', 'LaTeX'], ['TeX', 'TeX'], ['i', 'ı'], ['j', 'ȷ'], ['o', 'ø'], ['O', 'Ø'], ['ss', 'ß'], ['ae', 'æ'], ['AE', 'Æ'],
  ['oe', 'œ'], ['OE', 'Œ'], ['aa', 'å'], ['AA', 'Å'], ['l', 'ł'], ['L', 'Ł'],
  // 空白
  ['quad', ' '], ['qquad', ' '], ['enspace', ' '], ['space', ' '], ['thinspace', '\u202f'],
  ['newline', ' '], ['linebreak', ' '], ['par', ' '],
])
// CVPR 模板里常见的缩写宏；后面本来就跟着句点时不再补一个。
const ABBREVIATIONS = new Map([
  ['eg', 'e.g.'], ['ie', 'i.e.'], ['etal', 'et al.'], ['vs', 'vs.'], ['etc', 'etc.'], ['wrt', 'w.r.t.'], ['cf', 'cf.'],
])
// 重音：\'e → é、\"{o} → ö、\v{c} → č；字母命令（\c、\v……）只认带花括号的写法。
const SYMBOL_ACCENTS = new Map([["'", '\u0301'], ['`', '\u0300'], ['^', '\u0302'], ['"', '\u0308'], ['~', '\u0303'], ['=', '\u0304'], ['.', '\u0307']])
const LETTER_ACCENTS = new Map([['c', '\u0327'], ['v', '\u030c'], ['u', '\u0306'], ['H', '\u030b'], ['r', '\u030a'], ['k', '\u0328']])
// \u516c\u5f0f\u5916\u7684 ^{\u2026}\u3001_{\u2026}\uff08DR^{3}-Eval\u3001\u03c0_{0.5}\uff09\u3002
const SCRIPTS = new Map<string, 'sup' | 'sub'>([['^', 'sup'], ['_', 'sub']])
const SCRIPT_DIGITS = { sup: '\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079', sub: '\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089' }

// 与 renderLatex 同样的公式认法：$ 开头的先认 $$…$$；反斜杠开头的认 \[…\]、\(…\)、\begin{…}…\end{…}。
const DOLLAR_MATH = [/\$\$[\s\S]+?\$\$/y, new RegExp(INLINE_DOLLAR_MATH, 'y')]
const BACKSLASH_MATH = [/\\\[[\s\S]+?\\\]/y, /\\\([\s\S]+?\\\)/y, /\\begin\{([a-zA-Z*]+)\}[\s\S]+?\\end\{\1\}/y]
const COMMAND_NAME = /[a-zA-Z]+/y
// 摘要里直接写的网址：引号、破折号和 ~ 都不动。
const URL_AT = /https?:\/\/[^\s<>"'`{}\\$]+/y

// 给 renderMarkdown 的文本里，原样要显示的字符写成实体，Markdown、公式和 HTML 都不会认错。
const MARKUP_ESCAPES: Record<string, string> = {
  '\\': '&#92;', '`': '&#96;', '*': '&#42;', '_': '&#95;', '[': '&#91;', ']': '&#93;',
  '<': '&lt;', '>': '&gt;', '#': '&#35;', '$': '&#36;', '&': '&amp;', '~': '&#126;',
}
const literal = (scan: Scan, text: string) =>
  scan.markup ? text.replace(/[\\`*_[\]<>#$&~]/g, c => MARKUP_ESCAPES[c] ?? c) : text
const attribute = (text: string) => text.replace(/[&"<>$`*\\]/g, c => `&#${c.charCodeAt(0)};`)

const wrap = (scan: Scan, style: Style | null, inner: string) =>
  style && scan.markup && inner.trim() ? `<${TAGS[style]}>${inner}</${TAGS[style]}>` : inner

function mathAt(scan: Scan, patterns: readonly RegExp[]): string | null {
  for (const pattern of patterns) {
    pattern.lastIndex = scan.i
    const match = pattern.exec(scan.src)
    if (match) return match[0]
  }
  return null
}

/** 命令后紧跟（可隔空格）的 { 的位置；没有参数时为 -1。 */
function groupStart(scan: Scan): number {
  let at = scan.i
  while (scan.src[at] === ' ') at += 1
  return scan.src[at] === '{' ? at : -1
}

/** 读一个 {…} 参数并排版其中内容；没有参数时为 null。 */
function readGroup(scan: Scan, style: Style | null = null): string | null {
  const start = groupStart(scan)
  if (start < 0) return null
  scan.i = start + 1
  return style === 'sup' || style === 'sub' ? script(scan, style, '') : styledRest(scan, style)
}

/** 读一个 {…} 参数的原文（网址、引用键）；花括号可以嵌套，\{ \} 不算。 */
function readRawGroup(scan: Scan): string | null {
  const start = groupStart(scan)
  if (start < 0) return null
  let depth = 0
  for (let at = start; at < scan.src.length; at += 1) {
    const c = scan.src[at]
    if (c === '\\') at += 1
    else if (c === '{') depth += 1
    else if (c === '}' && --depth === 0) {
      scan.i = at + 1
      return scan.src.slice(start + 1, at)
    }
  }
  scan.i = scan.src.length
  return scan.src.slice(start + 1)
}

function skipOptionalArguments(scan: Scan) {
  for (;;) {
    let at = scan.i
    while (scan.src[at] === ' ') at += 1
    const end = scan.src[at] === '[' ? scan.src.indexOf(']', at) : -1
    if (end < 0) return
    scan.i = end + 1
  }
}

function skipEmptyGroup(scan: Scan) {
  if (scan.src.startsWith('{}', scan.i)) scan.i += 2
}

/** 排版到所在花括号结束（连同 } 一起读掉），按 style 包起来。 */
function styledRest(scan: Scan, style: Style | null): string {
  const wasCode = scan.code
  if (style === 'code') scan.code = true
  const inner = parse(scan, true)
  scan.code = wasCode
  return wrap(scan, style, inner)
}

/**
 * 上下标的花括号里（^{…}、_{…}、\textsuperscript{…}）：标成上下标；纯文字里数字换成 ³、₀ 这类字符，
 * 别的去掉花括号、留下 marker（^ 或 _；\textsuperscript 没有）。^{\circ} 是度数。
 */
function script(scan: Scan, style: 'sup' | 'sub', marker: string): string {
  const inner = parse(scan, true)
  const text = inner.trim()
  if (style === 'sup' && (text === '∘' || text === 'circ')) return '°'
  if (scan.markup || !text) return wrap(scan, style, inner)
  return /^\d+$/.test(text) ? [...text].map(d => SCRIPT_DIGITS[style][Number(d)] ?? d).join('') : marker + inner
}

function link(scan: Scan, raw: string | null, label: string | null): string {
  const url = (raw ?? '').replace(/\\([%#&_~$])/g, '$1').trim()
  const text = label?.trim() ? label : literal(scan, url)
  if (!scan.markup || !/^(?:https?:\/\/|mailto:)/i.test(url)) return text
  return `<a href="${attribute(url)}">${text}</a>`
}

function accent(scan: Scan, mark: string, bare: string): string {
  let base = ''
  if (scan.src[scan.i] === '{') {
    const inner: Scan = { src: scan.src, i: scan.i + 1, markup: false, code: false }
    base = parse(inner, true)
    scan.i = inner.i
  } else if (/\p{L}/u.test(scan.src[scan.i] ?? '')) {
    base = scan.src[scan.i] ?? ''
    scan.i += 1
  }
  // 拼不成一个带重音的字母（如被转义的撇号 don\'t），就把符号原样放回去。
  const composed = (base.slice(0, 1) + mark).normalize('NFC')
  return literal(scan, base && composed.length === 1 ? composed + base.slice(1) : bare + base)
}

/** 反斜杠后跟非字母：\% \& \_ 之类转义、\, 等间距、\'e 等重音。 */
function escaped(scan: Scan): string {
  const c = scan.src[scan.i + 1]
  scan.i += 2
  if (c === undefined) return literal(scan, '\\')
  const mark = SYMBOL_ACCENTS.get(c)
  if (mark) return accent(scan, mark, c)
  if (c === ',') return '\u202f'
  if ('!/@-'.includes(c)) return ''
  if (/[\s;:>\\]/.test(c)) return ' '
  return literal(scan, c)
}

function command(scan: Scan, name: string): string {
  if (STYLE_COMMANDS.has(name)) return readGroup(scan, STYLE_COMMANDS.get(name) ?? null) ?? ''
  switch (name) {
    case 'textcolor':
    case 'colorbox':
      skipOptionalArguments(scan)
      readRawGroup(scan)
      return readGroup(scan) ?? ''
    case 'href':
      return link(scan, readRawGroup(scan), readGroup(scan))
    case 'url':
      return link(scan, readRawGroup(scan), null)
    case 'footnote': {
      skipOptionalArguments(scan)
      const note = readGroup(scan)?.trim()
      return note ? ` (${note})` : ''
    }
    case 'hspace':
      readRawGroup(scan)
      return ' '
  }
  const accentMark = LETTER_ACCENTS.get(name)
  if (accentMark && scan.src[scan.i] === '{') return accent(scan, accentMark, '')
  skipEmptyGroup(scan)
  const symbol = SYMBOLS.get(name)
  if (symbol !== undefined) return literal(scan, symbol)
  const abbreviation = ABBREVIATIONS.get(name)
  if (abbreviation) return scan.src[scan.i] === '.' ? abbreviation.slice(0, -1) : abbreviation
  return DROPPED.has(name) ? '' : name
}

/** 公式外的一段普通文字：``…'' 换成弯引号，--- 和 -- 换成破折号，词间的 ~ 换成不断行空格。 */
function typeset(scan: Scan, end: number): string {
  const { src } = scan
  if (scan.code) {
    const text = literal(scan, src.slice(scan.i, end))
    scan.i = end
    return text
  }
  let out = ''
  while (scan.i < end) {
    const at = scan.i
    URL_AT.lastIndex = at
    const url = URL_AT.exec(src)?.[0]
    if (url) {
      scan.i += url.length
      // 网址后直接跟着 {文字}（\href 只剩了参数）：当链接文字。
      out += src[scan.i] === '{' ? link(scan, url, readGroup(scan)) : url
      continue
    }
    const c = src[at] ?? ''
    const prev = src[at - 1] ?? ''
    if (src.startsWith('``', at) || src.startsWith("''", at)) {
      // 两头都写 '' 的（''happy paths''），词前那个当左引号。
      const opening = c === '`' || (/^[\s([{]?$/.test(prev) && /\S/.test(src[at + 2] ?? ''))
      out += opening ? '“' : '”'
      scan.i += 2
    } else if (c === '-' && prev !== '-') {
      let dashes = 1
      while (src[at + dashes] === '-') dashes += 1
      const next = src[at + dashes] ?? ''
      // 行首或空格后紧跟字母的 --（命令行参数 --flag）不换。
      const option = /^\s?$/.test(prev) && /[a-z]/i.test(next)
      if (dashes === 3) out += '—'
      else if (dashes === 2 && !option && prev !== '!' && next !== '>') out += '–'
      else out += src.slice(at, at + dashes)
      scan.i += dashes
    } else if (c === '~') {
      // 夹在两个字之间的 ~ 是 LaTeX 的不断行空格（GLM~5.1、(i)~the）；空格或左括号后的 ~ 是「约」（~7M、(~1%）。
      const next = src[at + 1] ?? ''
      out += prev && next && !/[\s([{]/.test(prev) && !/\s/.test(next) ? '\u00a0' : '~'
      scan.i += 1
    } else {
      out += scan.markup && (c === '<' || c === '>') ? (MARKUP_ESCAPES[c] ?? c) : c
      scan.i += 1
    }
  }
  return out
}

function parse(scan: Scan, inGroup: boolean): string {
  const { src } = scan
  let out = ''
  while (scan.i < src.length) {
    const c = src[scan.i]
    if (c === '}') {
      scan.i += 1
      if (inGroup) return out
      out += '}'
      continue
    }
    if (c === '{') {
      const marker = src[scan.i - 1] ?? ''
      const style = scan.code ? undefined : SCRIPTS.get(marker)
      scan.i += 1
      if (style && out.endsWith(marker)) out = out.slice(0, -1) + script(scan, style, marker)
      else out += parse(scan, true)
      continue
    }
    if (c === '$') {
      const math = mathAt(scan, DOLLAR_MATH)
      out += math ?? literal(scan, '$')
      scan.i += math?.length ?? 1
      continue
    }
    if (c !== '\\') {
      let end = scan.i
      while (end < src.length && !'\\{}$'.includes(src[end] ?? '')) end += 1
      out += typeset(scan, end)
      continue
    }
    const math = mathAt(scan, BACKSLASH_MATH)
    if (math) {
      out += math
      scan.i += math.length
      continue
    }
    COMMAND_NAME.lastIndex = scan.i + 1
    const name = COMMAND_NAME.exec(src)?.[0]
    if (!name) {
      out += escaped(scan)
      continue
    }
    scan.i += 1 + name.length
    if (STYLE_SWITCHES.has(name)) {
      // 开关管不到花括号外：不在花括号里就不理它。
      if (!inGroup) continue
      while (src[scan.i] === ' ') scan.i += 1
      return out + styledRest(scan, STYLE_SWITCHES.get(name) ?? null)
    }
    if (DROPPED_WITH_ARGUMENT.has(name)) {
      skipOptionalArguments(scan)
      readRawGroup(scan)
      out = out.replace(/[\s\u00a0]+$/, '')
      continue
    }
    out += command(scan, name)
  }
  return out
}

/** 论文摘要交给 renderMarkdown 之前先过这一道。 */
export function paperAbstractMarkup(text: string | null | undefined): string {
  return text ? parse({ src: text, i: 0, markup: true, code: false }, false) : ''
}

/** 论文标题和只放文字的摘要：LaTeX 命令只留文字，公式原样。 */
export function paperPlainText(text: string | null | undefined): string {
  return text ? parse({ src: text, i: 0, markup: false, code: false }, false).replace(/[ \t]{2,}/g, ' ').trim() : ''
}
