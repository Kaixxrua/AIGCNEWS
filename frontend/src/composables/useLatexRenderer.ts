/**
 * useLatexRenderer — 公共 LaTeX / Markdown 渲染 composable
 *
 * 将 ChatView 和 PaperReadView 中完全重复的 KaTeX 渲染管线抽离为统一实现。
 * 支持的 LaTeX 分隔符：
 *   块级：$$...$$ / \[...\] / 独立 \begin{env}...\end{env}
 *   行内：$...$ / \(...\)
 *
 * 同时提供公式提取、公式复制按钮委托等辅助功能。
 */
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { copyToClipboard } from './useClipboard'
import { showToast } from './useToast'
import { i18n } from '@/i18n'

const markdown = new MarkdownIt({ html: true, linkify: true, breaks: true })

const sanitizeRenderedMarkdown = (html: string): string =>
  DOMPurify.sanitize(html, {
    ADD_ATTR: ['data-latex'],
    FORBID_TAGS: ['form', 'iframe', 'object', 'embed', 'svg'],
    ALLOW_DATA_ATTR: false,
    FORBID_ATTR: ['formaction'],
  })

// ── 内部辅助 ──────────────────────────────────────────────────────────────

// ── CJK 粗体闭合修正 ────────────────────────────────────────────────────────
// 模型爱写 `**要点：**紧接正文`：闭合 ** 前是标点（。：）、后紧跟字母/汉字时，
// 按 CommonMark 分隔符侧翼规则不构成 right-flanking（前为标点则后须为空白或
// 标点），markdown-it 找不到闭合配对，粗体失效并残留字面 **
// （2026-08-14 综合简报实测 82 处）。此处按同一套侧翼规则做分隔符配对扫描，
// 唯一配对障碍是"闭合符后紧跟非空白非标点字符"时，在闭合 ** 后补一个空格
// 使其合法。围栏代码块与行内代码内的 ** 原样保留；单星号 * 与 __ 在简报
// 语料中未出现，暂不处理。
const _CODE_SEGMENT_RE = /(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g
const _WS_RE = /\p{White_Space}/u
const _PUNCT_RE = /\p{P}/u

export function normalizeEmphasisFlanking(text: string): string {
  if (!text.includes('**')) return text
  const segments = text.split(_CODE_SEGMENT_RE)
  for (let i = 0; i < segments.length; i += 2) {
    segments[i] = fixEmphasisSegment(segments[i] ?? '')
  }
  return segments.join('')
}

function fixEmphasisSegment(seg: string): string {
  let result = ''
  let cursor = 0
  let opener = -1 // 最近一个未配对 opener 的位置（seg 坐标；模型输出不嵌套粗体，单槽即可）
  let i = 0
  while (i < seg.length) {
    const idx = seg.indexOf('**', i)
    if (idx === -1) break
    if (opener >= 0 && seg.slice(i, idx).includes('\n\n')) opener = -1 // 跨段落不配对
    const prev = idx > 0 ? seg[idx - 1] : ''
    const next = seg[idx + 2] ?? ''
    const prevPunct = !!prev && _PUNCT_RE.test(prev)
    const nextWs = !next || _WS_RE.test(next)
    const nextPunct = !!next && _PUNCT_RE.test(next)
    const leftFlanking = !nextWs && (!nextPunct || !prev || _WS_RE.test(prev) || prevPunct)
    const rightFlanking = !!prev && !_WS_RE.test(prev) && (!prevPunct || nextWs || nextPunct)

    if (opener >= 0 && rightFlanking) {
      opener = -1 // 正常闭合，无需处理
    } else if (opener >= 0 && prevPunct && next && !nextWs && !nextPunct) {
      // 断裂闭合：前是标点、后紧跟字母/数字/汉字 → 闭合 ** 后补空格
      result += seg.slice(cursor, idx + 2) + ' '
      cursor = idx + 2
      opener = -1
    } else if (leftFlanking) {
      opener = idx
    }
    i = idx + 2
  }
  return result + seg.slice(cursor)
}

// ── 标题标签前导 # 隐藏 ─────────────────────────────────────────────────────
// 简报标题按约定携带 `#来源` `#领域` 标签（反引号行内代码）。展示层只保留
// 标签文字、不显示前导 #；仅作用于标题（h1-h6）内的行内代码，正文代码片段
// 如 `#define` 不受影响。
const _HEADING_BLOCK_RE = /(<h[1-6][^>]*>[\s\S]*?<\/h[1-6]>)/g

const stripHeadingTagHashes = (html: string): string =>
  html.replace(_HEADING_BLOCK_RE, (heading) =>
    heading.replace(/<code>#([^<]*)<\/code>/g, '<code>$1</code>'),
  )

/** HTML 属性转义 */
const escapeAttr = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** HTML 实体解码 */
const decodeHtml = (s: string): string =>
  s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'")

/** 尝试用 KaTeX 渲染单个表达式，块级公式外包复制按钮容器 */
const tryKatex = (expr: string, displayMode: boolean): string | null => {
  try {
    const html = katex.renderToString(expr.trim(), { displayMode, throwOnError: false })
    const escaped = escapeAttr(expr.trim())
    if (displayMode) {
      const copyTitle = escapeAttr(i18n.global.t('chat.copyFormulaTitle'))
      return `<div class="formula-wrap"><button class="formula-copy-btn" data-latex="${escaped}" title="${copyTitle}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:12px;height:12px;display:inline-block;vertical-align:middle"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>${html}</div>`
    }
    return html
  } catch {
    return null
  }
}

// ── 导出函数 ──────────────────────────────────────────────────────────────

/**
 * renderLatex: 将文本中的 LaTeX 公式替换为 KaTeX HTML。
 *
 * 处理顺序：
 *   1. 保护代码块（```...```）
 *   2. 块级 $$...$$
 *   3. 块级 \[...\]
 *   4. 独立 \begin{env}...\end{env}
 *   5. 行内 \(...\)
 *   6. 行内 $...$（不跨行，排除 $$）
 *   7. 恢复代码块
 */
export function renderLatex(text: string): string {
  if (!text) return ''

  const codeBlocks: string[] = []
  let s = text.replace(/```[\s\S]*?```/g, (m) => {
    codeBlocks.push(m)
    return `%%CODEBLOCK_${codeBlocks.length - 1}%%`
  })

  // 块级
  s = s.replace(/\$\$([\s\S]+?)\$\$/g, (_m, expr: string) => tryKatex(expr, true) ?? _m)
  s = s.replace(/\\\[([\s\S]+?)\\\]/g, (_m, expr: string) => tryKatex(expr, true) ?? _m)
  s = s.replace(/\\begin\{([a-zA-Z*]+)\}([\s\S]+?)\\end\{\1\}/g, (_m, env: string, body: string) => {
    const full = `\\begin{${env}}${body}\\end{${env}}`
    return tryKatex(full, true) ?? _m
  })

  // 行内
  s = s.replace(/\\\(([\s\S]+?)\\\)/g, (_m, expr: string) => tryKatex(expr, false) ?? _m)
  s = s.replace(/(?<!\$)\$(?!\$)([^\n$]+?)\$(?!\$)/g, (_m, expr: string) => tryKatex(expr, false) ?? _m)

  // 恢复代码块
  s = s.replace(/%%CODEBLOCK_(\d+)%%/g, (_m, idx: string) => codeBlocks[Number(idx)] || _m)
  return s
}

/**
 * renderMarkdown: 先修正 CJK 粗体闭合，再走 LaTeX 渲染，再走 markdown-it，
 * 最后后处理 <code> 中残留 LaTeX。
 */
export function renderMarkdown(text: string): string {
  const withKatex = renderLatex(normalizeEmphasisFlanking(text || ''))
  let html = stripHeadingTagHashes(sanitizeRenderedMarkdown(markdown.render(withKatex)))

  // 后处理：先处理 <pre><code>（块级），再处理行内 <code>
  html = html.replace(/<pre><code(?:\s[^>]*)?>([\s\S]*?)<\/code><\/pre>/g, (_m, inner: string) => {
    const decoded = decodeHtml(inner)
    if (/\\[a-zA-Z]/.test(decoded)) {
      const result = tryKatex(decoded.trim(), true)
      if (result) return `<div class="katex-block-wrapper">${result}</div>`
    }
    return _m
  })
  html = html.replace(/<code>([\s\S]*?)<\/code>/g, (_m, inner: string) => {
    const decoded = decodeHtml(inner)
    if (/\\[a-zA-Z]/.test(decoded)) {
      return tryKatex(decoded.trim(), false) ?? _m
    }
    return _m
  })

  return html
}

/**
 * renderPlainMarkdown: 纯 Markdown → 消毒 HTML（无 KaTeX 环节）。
 * 供站点自定义页面等管理员撰写内容使用；与 renderMarkdown 共享同一
 * markdown-it 实例与 DOMPurify 消毒管线，禁止绕开消毒直接绑定渲染结果。
 */
export function renderPlainMarkdown(text: string): string {
  const html = sanitizeRenderedMarkdown(markdown.render(normalizeEmphasisFlanking(text || '')))
  return stripHeadingTagHashes(html)
}

/**
 * extractLatexSources: 提取文本中所有 LaTeX 公式源码（用于复制）
 */
export function extractLatexSources(content: string): string[] {
  const sources: string[] = []
  content.replace(/\$\$([\s\S]+?)\$\$/g, (_m, expr: string) => { sources.push(`$$${expr.trim()}$$`); return '' })
  content.replace(/\\\[([\s\S]+?)\\\]/g, (_m, expr: string) => { sources.push(`\\[${expr.trim()}\\]`); return '' })
  content.replace(/\\begin\{([a-zA-Z*]+)\}([\s\S]+?)\\end\{\1\}/g, (_m, env: string, body: string) => {
    sources.push(`\\begin{${env}}${body}\\end{${env}}`); return ''
  })
  content.replace(/\\\(([\s\S]+?)\\\)/g, (_m, expr: string) => { sources.push(`\\(${expr.trim()}\\)`); return '' })
  content.replace(/(?<!\$)\$(?!\$)([^\n$]+?)\$(?!\$)/g, (_m, expr: string) => { sources.push(`$${expr.trim()}$`); return '' })
  content.replace(/`([^`\n]+)`/g, (_m, inner: string) => {
    if (/\\[a-zA-Z]/.test(inner)) sources.push(inner.trim())
    return ''
  })
  return sources
}

/**
 * copyFormulas: 提取并复制所有公式到剪贴板
 */
export async function copyFormulas(content: string): Promise<void> {
  const formulas = extractLatexSources(content)
  if (!formulas.length) {
    showToast(i18n.global.t('common.noFormulas'))
    return
  }
  await copyToClipboard(formulas.join('\n\n'))
  showToast(i18n.global.t('common.formulasCopied', { count: formulas.length }))
}

/**
 * handleFormulaCopy: 全局事件委托 — 处理 .formula-copy-btn 按钮点击。
 * 在 onMounted 中注册到 document.addEventListener('click', handleFormulaCopy)
 */
export function handleFormulaCopy(e: Event): void {
  const btn = (e.target as HTMLElement).closest('.formula-copy-btn') as HTMLElement | null
  if (!btn) return
  const latex = btn.getAttribute('data-latex')
    ?.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  if (!latex) return
  copyToClipboard(latex).then(() => {
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:12px;height:12px;display:inline-block;vertical-align:middle"><polyline points="20 6 9 17 4 12"/></svg>'
    setTimeout(() => {
      btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:12px;height:12px;display:inline-block;vertical-align:middle"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>'
    }, 1200)
  })
}

/**
 * useLatexRenderer composable — 返回所有渲染与复制相关函数
 */
export function useLatexRenderer() {
  return {
    renderLatex,
    renderMarkdown,
    extractLatexSources,
    copyFormulas,
    handleFormulaCopy,
  }
}
