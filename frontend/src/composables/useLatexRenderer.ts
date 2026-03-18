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
import MarkdownIt from 'markdown-it'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { copyToClipboard } from './useClipboard'

// ── 内部辅助 ──────────────────────────────────────────────────────────────

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
      return `<div class="formula-wrap"><button class="formula-copy-btn" data-latex="${escaped}" title="复制公式"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:12px;height:12px;display:inline-block;vertical-align:middle"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>${html}</div>`
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
 * renderMarkdown: 先走 LaTeX 渲染，再走 markdown-it，最后后处理 <code> 中残留 LaTeX。
 */
export function renderMarkdown(text: string): string {
  const withKatex = renderLatex(text || '')
  const mdInstance = new MarkdownIt({ html: true, linkify: true, breaks: true })
  let html = mdInstance.render(withKatex)

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
    alert('未检测到公式')
    return
  }
  await copyToClipboard(formulas.join('\n\n'))
  alert(`已复制 ${formulas.length} 条公式`)
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
