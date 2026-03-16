<script lang="ts">
/**
 * 模块级对话记录：切换论文时左侧对话不清空。
 * 放在普通 <script> 块中，整个模块生命周期内只初始化一次，
 * 组件销毁/重建不影响。
 */
import { ref as moduleRef } from 'vue'

interface PaperMsg {
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
  visionExtract?: string
  imageBase64?: string
  showRaw?: boolean
}

// 模块级持久化：对话记录 + 输入框文本
const persistedMessages = moduleRef<PaperMsg[]>([])
const persistedInputText = moduleRef('')
</script>

<script setup lang="ts">
/**
 * PaperReadView.vue — 沉浸式左右分屏阅读页
 *
 * 布局：
 *   左 35% → 对话流（RAG Chat + Vision 问答）
 *   右 65% → PDF.js Canvas 渲染器（禁 iframe）
 *
 * 核心能力：
 *   - PDF.js Canvas 多页渲染，支持跨页长截图
 *   - 左键拖选 → 内存截图 → 悬浮弹窗含截图预览
 *   - vision-relay SSE：先上传截图拿 image_id，再流式问答（请求体轻量）
 *   - 截图 Base64 全程内存中，不落盘
 */
import {
  ref, computed, nextTick, onMounted, onUnmounted,
  watch,
} from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarkdownIt from 'markdown-it'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { useEventSource } from '../composables/useEventSource'
import { api, fetchPaperDetail, type PaperItem } from '../services/api'
import PdfCanvasViewer from '../components/PdfCanvasViewer.vue'

const route = useRoute()
const router = useRouter()
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

// ── 论文元数据 ──────────────────────────────────────────────────────────────
const paper = ref<PaperItem | null>(null)
const paperLoading = ref(true)
const paperError = ref('')

const paperId = computed(() => String(route.params.id ?? ''))

const loadPaper = async (id: string) => {
  if (!id) { paperError.value = '无效的论文 ID'; paperLoading.value = false; return }
  paperLoading.value = true
  paperError.value = ''
  try {
    paper.value = await fetchPaperDetail(id)
    if (!paper.value) paperError.value = '论文不存在'
  } catch (e) {
    paperError.value = String(e)
  } finally {
    paperLoading.value = false
  }
}

onMounted(() => loadPaper(paperId.value))

// 切换论文时：只重新加载右侧 PDF 数据，左侧对话保持不变
watch(paperId, (newId) => {
  visionPopup.value = null
  loadPaper(newId)
})

// ── 对话消息（使用模块级持久化 ref，组件重建不丢失）────────────────────────────
type Msg = PaperMsg

const messages = persistedMessages
const inputText = persistedInputText
const chatListRef = ref<HTMLElement | null>(null)
const isSending = ref(false)

/** 清空对话（模块级 ref 也同步清空） */
const clearChat = () => { messages.value = [] }

const scrollBottom = async () => {
  await nextTick()
  if (chatListRef.value) chatListRef.value.scrollTop = chatListRef.value.scrollHeight
}

watch(() => messages.value.length, scrollBottom)

// ── 右键选区弹窗（vision intent popup）──────────────────────────────────────
const visionPopup = ref<{
  visible: boolean
  base64: string
  question: string
  pageIndex: number
} | null>(null)
const popupInputRef = ref<HTMLInputElement | null>(null)

const onRightclickRegion = async (payload: {
  pageIndex: number; base64: string; x: number; y: number; w: number; h: number
}) => {
  visionPopup.value = {
    visible: true,
    base64: payload.base64,
    question: '',
    pageIndex: payload.pageIndex,
  }
  await nextTick()
  popupInputRef.value?.focus()
}

const closePopup = () => { visionPopup.value = null }

// ── 消息精准更新辅助（避免展开运算符导致 role: undefined）─────────────────────
const patchMsg = (idx: number, patch: Partial<Msg>) => {
  const cur = messages.value[idx]
  if (!cur) return
  messages.value[idx] = {
    role: cur.role,
    content: patch.content !== undefined ? patch.content : cur.content,
    isStreaming: patch.isStreaming !== undefined ? patch.isStreaming : cur.isStreaming,
    visionExtract: patch.visionExtract !== undefined ? patch.visionExtract : cur.visionExtract,
    imageBase64: cur.imageBase64,  // 保留截图预览
    showRaw: patch.showRaw !== undefined ? patch.showRaw : cur.showRaw,
  }
}

// ── 发送 Vision 追问 ─────────────────────────────────────────────────────────
const sendVision = async () => {
  if (!visionPopup.value?.question.trim() || isSending.value) return
  const question = visionPopup.value.question.trim()
  const base64 = visionPopup.value.base64
  closePopup()

  messages.value.push({ role: 'user', content: `📸 截图追问：${question}`, imageBase64: base64 })
  messages.value.push({ role: 'assistant', content: '', isStreaming: true })
  const assistantIdx = messages.value.length - 1
  isSending.value = true

  const baseURL = (api.defaults.baseURL ?? '').replace(/\/+$/, '')
  const { connect } = useEventSource()

  // ── Step 1：先上传截图到服务器，拿到 image_id（避免在 SSE body 里塞大 base64）
  let imageId: string
  try {
    const uploadRes = await api.post<{ image_id: string }>('/chat/upload-screenshot', {
      image_base64: base64,
      mime_type: 'image/jpeg',
    })
    imageId = uploadRes.data.image_id
  } catch (e) {
    patchMsg(assistantIdx, { isStreaming: false, content: `❌ 截图上传失败：${e}` })
    isSending.value = false
    return
  }

  // ── Step 2：用 image_id 发起视觉问答 SSE（请求体轻量）
  await connect({
    url: `${baseURL}/chat/vision-relay`,
    body: {
      paper_id: paperId.value || null,
      question,
      image_id: imageId,
      history: messages.value
        .slice(0, assistantIdx)
        .filter(m => m.role !== 'assistant' || m.content)
        .slice(-12)
        .map(m => ({ role: m.role, content: m.content })),
    },
    onMessage: (payload: unknown) => {
      const ev = payload as { type: string; data?: string }
      if (ev.type === 'status') return
      if (ev.type === 'vision_extract') {
        patchMsg(assistantIdx, { visionExtract: ev.data ?? '' })
        return
      }
      if (ev.type === 'content') {
        const cur = messages.value[assistantIdx]
        if (cur) patchMsg(assistantIdx, { content: cur.content + (ev.data ?? '') })
        scrollBottom()
      }
      if (ev.type === 'error') {
        patchMsg(assistantIdx, { isStreaming: false, content: `❌ ${ev.data ?? '未知错误'}` })
      }
    },
    onDone: () => {
      const cur = messages.value[assistantIdx]
      patchMsg(assistantIdx, { isStreaming: false, content: cur?.content || '（模型未返回内容）' })
      isSending.value = false
    },
    onError: (e: unknown) => {
      patchMsg(assistantIdx, { isStreaming: false, content: `❌ 请求失败：${e}` })
      isSending.value = false
    },
  })
}

// ── 普通文本追问（不含图片）──────────────────────────────────────────────────
const sendText = async () => {
  const text = inputText.value.trim()
  if (!text || isSending.value) return
  inputText.value = ''

  messages.value.push({ role: 'user', content: text })
  messages.value.push({ role: 'assistant', content: '', isStreaming: true })
  const assistantIdx = messages.value.length - 1
  isSending.value = true

  const baseURL = (api.defaults.baseURL ?? '').replace(/\/+$/, '')
  const { connect } = useEventSource()

  await connect({
    url: `${baseURL}/chat/stream`,
    body: {
      message: text,
      history: messages.value.slice(0, assistantIdx).slice(-10).map(m => ({ role: m.role, content: m.content })),
      temperature: 0.7,
    },
    onMessage: (payload: unknown) => {
      const ev = payload as { type: string; data?: unknown }
      if (ev.type === 'content') {
        const cur = messages.value[assistantIdx]
        if (cur) patchMsg(assistantIdx, { content: cur.content + String(ev.data ?? '') })
        scrollBottom()
      }
      if (ev.type === 'error') {
        patchMsg(assistantIdx, { isStreaming: false, content: `❌ ${ev.data ?? '未知错误'}` })
      }
    },
    onDone: () => {
      const cur = messages.value[assistantIdx]
      patchMsg(assistantIdx, { isStreaming: false, content: cur?.content || '（模型未返回内容）' })
      isSending.value = false
    },
    onError: (e: unknown) => {
      patchMsg(assistantIdx, { isStreaming: false, content: `❌ 流式请求失败：${e}` })
      isSending.value = false
    },
  })
}

const handleKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText() }
}

const handlePopupKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter') { e.preventDefault(); sendVision() }
  if (e.key === 'Escape') closePopup()
}

// ── 渲染 markdown + LaTeX 公式 ───────────────────────────────────────────────
/** HTML 转义（用于 data-latex 属性） */
const escapeAttr = (s: string) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** 尝试用 KaTeX 渲染，外包复制按钮容器 */
const tryKatex = (expr: string, displayMode: boolean): string | null => {
  try {
    const html = katex.renderToString(expr.trim(), { displayMode, throwOnError: false })
    const escaped = escapeAttr(expr.trim())
    if (displayMode) {
      return `<div class="formula-wrap"><button class="formula-copy-btn" data-latex="${escaped}" title="复制公式">📋</button>${html}</div>`
    }
    // 行内公式：不加按钮，避免干扰排版
    return html
  } catch { return null }
}

/** 解码 HTML 实体 */
const decodeHtml = (s: string) =>
  s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'")

/** 复制文本到剪贴板（兼容非 HTTPS） */
const copyToClipboard = (text: string): Promise<void> => {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text)
  }
  // fallback：textarea + execCommand
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
  return Promise.resolve()
}

/** 全局事件委托：处理公式复制按钮点击 */
const handleFormulaCopy = (e: Event) => {
  const btn = (e.target as HTMLElement).closest('.formula-copy-btn') as HTMLElement | null
  if (!btn) return
  const latex = btn.getAttribute('data-latex')
    ?.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  if (!latex) return
  copyToClipboard(latex).then(() => {
    btn.textContent = '✅'
    setTimeout(() => { btn.textContent = '📋' }, 1200)
  })
}
onMounted(() => document.addEventListener('click', handleFormulaCopy))
onUnmounted(() => document.removeEventListener('click', handleFormulaCopy))

/**
 * renderLatex: 将文本中的 LaTeX 公式替换为 KaTeX HTML。
 * 支持的分隔符：
 *   块级：$$...$$ / \[...\] / 独立 \begin{env}...\end{env}
 *   行内：$...$ / \(...\)
 */
const renderLatex = (text: string): string => {
  if (!text) return ''

  // 1) 保护代码块（```...```），但**不保护**行内反引号（里面可能是 LaTeX）
  const codeBlocks: string[] = []
  let s = text.replace(/```[\s\S]*?```/g, (m) => { codeBlocks.push(m); return `%%CODEBLOCK_${codeBlocks.length - 1}%%` })

  // 2) 块级 $$...$$
  s = s.replace(/\$\$([\s\S]+?)\$\$/g, (_m, expr: string) => tryKatex(expr, true) ?? _m)
  // 3) 块级 \[...\]
  s = s.replace(/\\\[([\s\S]+?)\\\]/g, (_m, expr: string) => tryKatex(expr, true) ?? _m)
  // 4) 独立 \begin{env}...\end{env}（不在 $ 内的 LaTeX 环境）
  s = s.replace(/\\begin\{([a-zA-Z*]+)\}([\s\S]+?)\\end\{\1\}/g, (_m, env: string, body: string) => {
    const full = `\\begin{${env}}${body}\\end{${env}}`
    return tryKatex(full, true) ?? _m
  })
  // 5) 行内 \(...\)
  s = s.replace(/\\\(([\s\S]+?)\\\)/g, (_m, expr: string) => tryKatex(expr, false) ?? _m)
  // 6) 行内 $...$（不跨行，排除 $$）
  s = s.replace(/(?<!\$)\$(?!\$)([^\n$]+?)\$(?!\$)/g, (_m, expr: string) => tryKatex(expr, false) ?? _m)

  // 7) 恢复代码块
  s = s.replace(/%%CODEBLOCK_(\d+)%%/g, (_m, idx: string) => codeBlocks[Number(idx)] || _m)
  return s
}

/**
 * renderMd: markdown + LaTeX → HTML
 * 先替换 LaTeX 为 KaTeX HTML，再 markdown-it 渲染，最后后处理 <code> 中的残留 LaTeX。
 */
const renderMd = (t: string) => {
  const withKatex = renderLatex(t || '')
  const mdHtml = new MarkdownIt({ html: true, linkify: true, breaks: true })
  let html = mdHtml.render(withKatex)

  // 后处理：先处理 <pre><code>（块级），再处理行内 <code>，避免顺序冲突
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

/** 提取消息中所有 LaTeX 公式源码（用于复制） */
const extractLatexSources = (content: string): string[] => {
  const sources: string[] = []
  // $$...$$
  content.replace(/\$\$([\s\S]+?)\$\$/g, (_m, expr: string) => { sources.push(`$$${expr.trim()}$$`); return '' })
  // \[...\]
  content.replace(/\\\[([\s\S]+?)\\\]/g, (_m, expr: string) => { sources.push(`\\[${expr.trim()}\\]`); return '' })
  // \begin{env}...\end{env}
  content.replace(/\\begin\{([a-zA-Z*]+)\}([\s\S]+?)\\end\{\1\}/g, (_m, env: string, body: string) => {
    sources.push(`\\begin{${env}}${body}\\end{${env}}`); return ''
  })
  // \(...\)
  content.replace(/\\\(([\s\S]+?)\\\)/g, (_m, expr: string) => { sources.push(`\\(${expr.trim()}\\)`); return '' })
  // $...$
  content.replace(/(?<!\$)\$(?!\$)([^\n$]+?)\$(?!\$)/g, (_m, expr: string) => { sources.push(`$${expr.trim()}$`); return '' })
  // 反引号中的 LaTeX
  content.replace(/`([^`\n]+)`/g, (_m, inner: string) => {
    if (/\\[a-zA-Z]/.test(inner)) sources.push(inner.trim())
    return ''
  })
  return sources
}

/** 复制所有公式到剪贴板 */
const copyFormulas = async (content: string) => {
  const formulas = extractLatexSources(content)
  if (!formulas.length) { alert('未检测到公式'); return }
  await copyToClipboard(formulas.join('\n\n'))
  alert(`已复制 ${formulas.length} 条公式`)
}

// ── 下载原始 PDF ─────────────────────────────────────────────────────────────
const downloadPdf = () => {
  const url = paper.value?.pdf_media_url
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <!-- ══ 绝对根节点：水平排布基座，撑满卡片内部剩余空间 ══ -->
  <div class="w-full flex-1 min-h-0 flex flex-row overflow-hidden">

    <!-- ════ 左柱 Left Pillar - 专属聊天区 (35%) ════ -->
    <div class="w-[35%] flex-shrink-0 flex flex-col h-full bg-white border-r border-gray-100/80 hover:border-gray-200 transition-colors">

      <!-- 左柱头部 -->
      <header class="flex shrink-0 items-center justify-between px-4 py-3" style="border-bottom: 1px solid rgba(168,162,158,0.12)">
        <button class="flex items-center gap-1.5 text-xs text-stone-400 hover:text-stone-600 transition" @click="router.push('/chat')">
          <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
          </svg>
          返回
        </button>
        <span class="text-xs font-semibold text-stone-600 font-serif">AI 对话</span>
        <button class="text-xs text-stone-400 hover:text-stone-600 transition" @click="clearChat">清空</button>
      </header>

      <!-- 聊天记录区（flex-1 撑满，overflow-y-auto 滚动） -->
      <div ref="chatListRef" class="flex-1 overflow-y-auto space-y-4 px-4 py-4">
        <!-- 空状态 -->
        <div v-if="!messages.length" class="flex h-full flex-col items-center justify-center gap-2 text-stone-400">
          <svg class="h-12 w-12 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
          </svg>
          <p class="text-sm font-medium">在右侧左键选取区域询问 AI</p>
          <p class="text-xs text-center max-w-[200px]">或直接在下方输入问题</p>
        </div>

        <!-- 消息列表 -->
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          class="flex"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <!-- AI 头像 -->
          <div v-if="msg.role === 'assistant'" class="mr-2 mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-stone-700 text-white text-2xs font-bold">AI</div>

          <div class="max-w-[85%]" :class="msg.role === 'user' ? '' : 'flex-1'">
            <!-- 用户气泡 -->
            <div v-if="msg.role === 'user'" class="rounded-[18px] rounded-br-sm bg-stone-700 px-3.5 py-2.5 text-xs leading-6 text-white">
              <!-- 截图预览（如有） -->
              <div v-if="msg.imageBase64" class="mb-2 rounded-lg overflow-hidden border border-white/20">
                <img :src="msg.imageBase64" alt="截图" class="w-full max-h-[200px] object-contain bg-white/10" />
              </div>
              {{ msg.content }}
            </div>

            <!-- AI 气泡 -->
            <div v-else class="space-y-1.5">
              <!-- Vision 提取结果（可折叠） -->
              <details v-if="msg.visionExtract" class="rounded-xl overflow-hidden" style="border: 1px solid rgba(168,162,158,0.18)">
                <summary class="cursor-pointer px-3 py-2 text-2xs font-medium text-stone-400 select-none hover:bg-stone-50">
                  👁 视觉提取内容（点击展开）
                </summary>
                <pre class="px-3 pb-3 pt-1 text-2xs leading-5 text-stone-500 whitespace-pre-wrap break-all">{{ msg.visionExtract }}</pre>
              </details>

              <!-- 等待动画 -->
              <div v-if="!msg.content && msg.isStreaming" class="flex items-center gap-1.5 rounded-[18px] px-3.5 py-2.5 bg-stone-50">
                <span v-for="i in 3" :key="i" class="h-1.5 w-1.5 animate-bounce rounded-full bg-stone-300" :style="`animation-delay:${(i-1)*150}ms`"/>
              </div>

              <!-- 正文 -->
              <div v-if="msg.content" class="rounded-[18px] rounded-bl-sm px-3.5 py-2.5" style="background: rgba(255,255,255,0.9); border: 1px solid rgba(168,162,158,0.18)">
                <!-- 渲染/源码/复制按钮 -->
                <div class="flex justify-end gap-1 mb-1">
                  <button
                    class="text-2xs px-2 py-0.5 rounded-md bg-stone-100 text-stone-400 hover:text-stone-600 transition"
                    @click="copyFormulas(msg.content)"
                    title="复制公式 LaTeX 源码"
                  >
                    📋 复制公式
                  </button>
                  <button
                    class="text-2xs px-2 py-0.5 rounded-md transition"
                    :class="msg.showRaw ? 'bg-stone-200 text-stone-600' : 'bg-stone-100 text-stone-400 hover:text-stone-600'"
                    @click="msg.showRaw = !msg.showRaw"
                  >
                    {{ msg.showRaw ? '📐 渲染公式' : '{ } 源码' }}
                  </button>
                </div>
                <!-- 渲染后内容 -->
                <div v-if="!msg.showRaw" class="prose-content text-xs leading-6 text-stone-700" v-html="renderMd(msg.content)"/>
                <!-- LaTeX 源码 -->
                <pre v-else class="text-xs leading-5 text-stone-600 whitespace-pre-wrap break-all font-mono bg-stone-50 rounded-lg p-2">{{ msg.content }}</pre>
                <span v-if="msg.isStreaming" class="inline-block h-3 w-0.5 animate-pulse bg-stone-500 ml-0.5 align-middle"/>
              </div>
            </div>
          </div>

          <!-- 用户头像 -->
          <div v-if="msg.role === 'user'" class="ml-2 mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-stone-200 text-stone-600 text-2xs font-bold">U</div>
        </div>
      </div>

      <!-- 底部输入框（shrink-0 固定在左柱底部，不脱离文档流） -->
      <footer class="shrink-0 px-3 py-3" style="border-top: 1px solid rgba(168,162,158,0.12)">
        <div class="flex items-end gap-2">
          <textarea
            v-model="inputText"
            rows="1"
            class="flex-1 resize-none rounded-2xl border border-stone-200 bg-white px-3 py-2 text-xs text-stone-700 placeholder:text-stone-400 focus:outline-none focus:ring-1 focus:ring-stone-400 max-h-28 min-h-[38px]"
            placeholder="输入问题…（Enter 发送）"
            :disabled="isSending"
            @keydown="handleKeydown"
          />
          <button
            class="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-full bg-stone-700 text-white transition hover:bg-stone-800 disabled:opacity-40"
            :disabled="!inputText.trim() || isSending"
            @click="sendText"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      </footer>
    </div>

    <!-- ════ 右柱 Right Pillar - 专属阅读区 (flex-1 = 65%) ════ -->
    <div class="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden bg-gray-50/50">

      <!-- 右柱头部：论文标题 + 下载按钮 -->
      <header class="flex shrink-0 items-start justify-between gap-3 px-5 py-3" style="border-bottom: 1px solid rgba(168,162,158,0.12)">
        <div class="min-w-0 flex-1">
          <div v-if="paperLoading" class="h-4 w-48 animate-pulse rounded bg-stone-200"/>
          <h1 v-else-if="paper" class="text-sm font-semibold text-stone-800 leading-snug line-clamp-2 font-serif">{{ paper.title }}</h1>
          <p v-else class="text-sm text-red-400">{{ paperError || '论文加载失败' }}</p>

          <div v-if="paper" class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-400">
            <span v-if="paper.published_date">{{ paper.published_date?.slice(0, 10) }}</span>
            <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener noreferrer" class="hover:text-stone-600 underline transition">原始链接 ↗</a>
          </div>
        </div>

        <!-- 下载 PDF 按钮 -->
        <button
          v-if="paper?.pdf_media_url"
          class="shrink-0 flex items-center gap-1.5 rounded-xl border border-stone-200 bg-white px-3 py-1.5 text-xs text-stone-600 transition hover:bg-stone-50 hover:border-stone-300"
          @click="downloadPdf"
        >
          <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
          </svg>
          下载 PDF
        </button>
      </header>

      <!-- PDF.js Canvas 渲染区（flex-1 撑满，禁止 iframe！） -->
      <div class="flex-1 min-h-0 flex flex-col relative overflow-hidden">
        <PdfCanvasViewer
          :pdf-url="paper?.pdf_media_url ?? null"
          @rightclick-region="onRightclickRegion"
        />

        <!-- 视觉追问悬浮弹窗 -->
        <Transition name="popup-fade">
          <div
            v-if="visionPopup?.visible"
            class="absolute bottom-24 left-1/2 -translate-x-1/2 w-[340px] rounded-2xl p-4 shadow-2xl"
            style="background: rgba(255,255,255,0.97); border: 1px solid rgba(168,162,158,0.25); backdrop-filter: blur(16px); z-index: 50"
          >
            <p class="mb-2 text-xs font-semibold text-stone-600">📸 已截取区域，向 AI 提问</p>
            <!-- 截图预览 -->
            <div class="mb-2 max-h-[160px] overflow-hidden rounded-lg border border-stone-200 bg-stone-100">
              <img :src="visionPopup.base64" alt="截图预览" class="w-full h-auto object-contain max-h-[160px]" />
            </div>
            <input
              ref="popupInputRef"
              v-model="visionPopup.question"
              type="text"
              placeholder="例如：请解释这个图表的含义…"
              class="w-full rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-700 placeholder:text-stone-400 focus:outline-none focus:ring-1 focus:ring-stone-400"
              @keydown="handlePopupKeydown"
            />
            <div class="mt-2.5 flex gap-2">
              <button
                class="flex-1 rounded-xl bg-stone-700 px-3 py-1.5 text-xs text-white transition hover:bg-stone-800 disabled:opacity-40"
                :disabled="!visionPopup.question.trim() || isSending"
                @click="sendVision"
              >
                发送
              </button>
              <button class="rounded-xl border border-stone-200 px-3 py-1.5 text-xs text-stone-500 transition hover:bg-stone-50" @click="closePopup">
                取消
              </button>
            </div>
          </div>
        </Transition>

        <!-- 无 PDF 时显示摘要 -->
        <div
          v-if="!paperLoading && paper && !paper.pdf_media_url"
          class="absolute inset-0 flex items-center justify-center px-8"
        >
          <div class="max-w-xl rounded-2xl p-6 text-center" style="background: rgba(255,255,255,0.85); border: 1px solid rgba(168,162,158,0.18)">
            <p class="mb-3 text-sm font-semibold text-stone-700 font-serif">PDF 暂未就绪</p>
            <p class="text-xs text-stone-500 leading-6">{{ paper.summary?.slice(0, 400) }}…</p>
            <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener noreferrer" class="mt-4 inline-block text-xs text-stone-500 underline hover:text-stone-700">在 arXiv/HuggingFace 上查看 ↗</a>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.popup-fade-enter-active,
.popup-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.popup-fade-enter-from,
.popup-fade-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(8px) scale(0.97);
}
.popup-fade-enter-to,
.popup-fade-leave-from {
  transform: translateX(-50%) translateY(0) scale(1);
}

/* KaTeX 公式溢出处理 —— 长公式可横向滚动，不撑破气泡 */
:deep(.katex-display) {
  overflow-x: auto;
  overflow-y: hidden;
  max-width: 100%;
  padding: 4px 0;
}
:deep(.katex-display > .katex) {
  white-space: nowrap;
}
:deep(.prose-content) {
  overflow: hidden;
  max-width: 100%;
}

/* 公式容器 + 独立复制按钮 */
:deep(.formula-wrap) {
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 6px 0;
}
:deep(.formula-copy-btn) {
  position: absolute;
  top: 2px;
  right: 2px;
  z-index: 5;
  cursor: pointer;
  background: rgba(245,245,244,0.85);
  border: 1px solid rgba(168,162,158,0.2);
  border-radius: 6px;
  padding: 1px 5px;
  font-size: 11px;
  line-height: 1.4;
  opacity: 0;
  transition: opacity 0.15s;
}
:deep(.formula-wrap:hover .formula-copy-btn) {
  opacity: 1;
}
:deep(.katex-block-wrapper) {
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 6px 0;
}
</style>
