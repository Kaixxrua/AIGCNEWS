<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { useChatStore } from '../stores/chatStore'

const store = useChatStore()
const inputText = ref('')
const listRef = ref<HTMLElement | null>(null)
const showSettings = ref(false)
const isSending = ref(false)

const localSettings = ref({ ...store.settings })

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

const messages = computed(() => store.messages)

const renderMarkdown = (text: string) => md.render(text || '')

interface SourceFlat {
  id?: string
  score?: number
  source?: string
  title?: string
  url?: string
  published_date?: string
  metadata?: {
    title?: string
    url?: string
    source?: string
    source_type?: string
    node?: { id?: string }
  }
}

const getSourceTitle = (src: unknown): string => {
  const s = src as SourceFlat
  return s?.title || s?.metadata?.title || s?.metadata?.node?.id || s?.id || 'Unknown Source'
}

const getSourceType = (src: unknown): string => {
  const s = src as SourceFlat
  const channel = s?.source || s?.metadata?.source_type || s?.metadata?.source || ''
  if (channel === 'arxiv') return 'Arxiv'
  if (channel === 'github') return 'GitHub'
  if (channel === 'news') return 'News'
  if (channel.toLowerCase().includes('neo4j') || channel.toLowerCase().includes('graph')) return 'Neo4j'
  if (channel.toLowerCase().includes('milvus') || channel.toLowerCase().includes('vector')) return 'Milvus'
  return channel || 'Unknown'
}

const getSourceUrl = (src: unknown): string | null => {
  const s = src as SourceFlat
  return s?.url || s?.metadata?.url || null
}

const sourceTypeBadgeClass = (type: string) => {
  return 'bg-white text-stone-600 border border-stone-200'
}

const thinkingExpanded = ref<Record<number, boolean>>({})
const toggleThinking = (idx: number) => {
  thinkingExpanded.value = { ...thinkingExpanded.value, [idx]: !thinkingExpanded.value[idx] }
}
const isThinkingExpanded = (idx: number) => !!thinkingExpanded.value[idx]

const autoScroll = ref(true)

const onWheelHandler = (e: WheelEvent) => { if (e.deltaY < 0) autoScroll.value = false }

let lastTouchY = 0
const onTouchStart = (e: TouchEvent) => { lastTouchY = e.touches[0]?.clientY ?? 0 }
const onTouchMoveHandler = (e: TouchEvent) => {
  const currentY = e.touches[0]?.clientY ?? 0
  if (currentY > lastTouchY) autoScroll.value = false
  lastTouchY = currentY
}

onMounted(() => {
  const el = listRef.value
  if (el) {
    el.addEventListener('wheel', onWheelHandler, { passive: true })
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMoveHandler, { passive: true })
  }
})

onUnmounted(() => {
  const el = listRef.value
  if (el) {
    el.removeEventListener('wheel', onWheelHandler)
    el.removeEventListener('touchstart', onTouchStart)
    el.removeEventListener('touchmove', onTouchMoveHandler)
  }
})

const scrollToBottom = async () => {
  if (!autoScroll.value) return
  await nextTick()
  const el = listRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

let scrollRafId: number | null = null
const scheduleScroll = () => {
  if (!autoScroll.value) return
  if (scrollRafId !== null) return
  scrollRafId = requestAnimationFrame(async () => {
    scrollRafId = null
    await scrollToBottom()
  })
}

watch(
  () => store.messages.map((m) => `${m.role}:${m.content.length}:${m.thinking.length}`).join('|'),
  scheduleScroll,
)

const handleSend = async () => {
  const text = inputText.value.trim()
  if (!text || isSending.value) return
  inputText.value = ''
  autoScroll.value = true
  isSending.value = true
  try { await store.sendMessage(text) }
  finally { isSending.value = false }
  await scrollToBottom()
}

const handleKeydown = async (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); await handleSend() }
}

const openSettings = () => { localSettings.value = { ...store.settings }; showSettings.value = true }
const saveSettings = () => { store.updateSettings({ ...localSettings.value }); showSettings.value = false }
const cancelSettings = () => { showSettings.value = false }
</script>

<template>
  <div class="flex h-full overflow-hidden">
    <section class="flex flex-1 flex-col overflow-hidden">

      <!-- 标题栏 -->
      <header class="stagger-enter flex items-center justify-between px-5 py-3.5 shrink-0"
        style="border-bottom: 1px solid rgba(168,162,158,0.15)"
      >
        <div class="flex items-center gap-3">
          <div class="flex h-9 w-9 items-center justify-center rounded-2xl bg-stone-100">
            <svg class="h-5 w-5 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/>
              <path d="M9.5 9.5a2.5 2.5 0 015 0c0 2-2 3-2.5 4"/>
              <circle cx="12" cy="17" r=".5" fill="currentColor"/>
            </svg>
          </div>
          <div>
            <h2 class="text-sm font-semibold text-stone-800 font-serif">RAG 智能助手</h2>
            <p class="text-2xs text-stone-400">
              记忆 {{ store.settings.maxHistoryTurns }} 轮 · T={{ store.settings.temperature.toFixed(1) }}
            </p>
          </div>
        </div>

        <div class="flex items-center gap-1.5">
          <button class="btn-ghost text-xs" @click="store.clearMessages()">
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/>
            </svg>
            清空
          </button>
          <button class="rounded-full p-2 text-stone-400 transition hover:bg-stone-100 hover:text-stone-600" @click="openSettings">
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="12" r="3"/><path d="M19.07 4.93l-1.41 1.41M16.24 7.76A6 6 0 1 0 7.76 16.24M4.93 19.07l1.41-1.41"/>
            </svg>
          </button>
        </div>
      </header>

      <!-- 设置浮层 -->
      <Transition name="settings-panel">
        <div
          v-if="showSettings"
          class="absolute left-1/2 top-[60px] z-30 w-80 -translate-x-1/2 glass-card p-5"
          style="box-shadow: 0 4px 20px rgba(0,0,0,0.06)"
        >
          <h3 class="mb-4 text-sm font-semibold text-stone-800 font-serif">对话设置</h3>
          <div class="mb-4 space-y-1.5">
            <label class="flex items-center justify-between text-sm text-stone-500">
              <span>历史记忆轮次</span>
              <span class="font-bold text-stone-800">{{ localSettings.maxHistoryTurns }}</span>
            </label>
            <input v-model.number="localSettings.maxHistoryTurns" type="range" min="0" max="20" step="1" class="w-full accent-stone-600 h-1.5 rounded-full" />
            <div class="flex justify-between text-2xs text-stone-400"><span>0 无记忆</span><span>20</span></div>
          </div>
          <div class="mb-5 space-y-1.5">
            <label class="flex items-center justify-between text-sm text-stone-500">
              <span>Temperature</span>
              <span class="font-bold text-stone-800">{{ localSettings.temperature.toFixed(1) }}</span>
            </label>
            <input v-model.number="localSettings.temperature" type="range" min="0" max="2" step="0.1" class="w-full accent-stone-600 h-1.5 rounded-full" />
            <div class="flex justify-between text-2xs text-stone-400"><span>0.0 精确</span><span>2.0 创意</span></div>
          </div>
          <div class="flex gap-2">
            <button class="btn-secondary flex-1 justify-center" @click="cancelSettings">取消</button>
            <button class="btn-primary flex-1 justify-center" @click="saveSettings">保存</button>
          </div>
        </div>
      </Transition>

      <div v-if="showSettings" class="fixed inset-0 z-20" @click="cancelSettings" />

      <!-- 消息列表 -->
      <div ref="listRef" class="stagger-enter flex-1 space-y-5 overflow-y-auto px-5 py-5" style="animation-delay: 0.1s">
        <div v-if="!messages.length" class="flex h-full flex-col items-center justify-center gap-3 text-stone-400">
          <div class="flex h-16 w-16 items-center justify-center rounded-3xl bg-stone-100">
            <svg class="h-8 w-8 opacity-40 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
            </svg>
          </div>
          <p class="text-sm font-medium text-stone-500 font-serif">开始一段对话</p>
          <p class="text-xs text-center max-w-xs text-stone-400">输入问题，RAG 助手将基于知识库给出准确答案并提供参考来源</p>
        </div>

        <div
          v-for="(msg, idx) in messages"
          :key="`${idx}-${msg.role}`"
          class="flex animate-slide-up"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <div
            v-if="msg.role !== 'user'"
            class="mr-2.5 mt-1 h-7 w-7 shrink-0 flex items-center justify-center rounded-full bg-stone-700 text-white text-xs font-bold shadow-sm"
          >AI</div>

          <div class="max-w-[80%]" :class="msg.role === 'user' ? 'max-w-[70%]' : 'flex-1'">
            <!-- 用户气泡 -->
            <div
              v-if="msg.role === 'user'"
              class="inline-block rounded-[20px] rounded-br-md bg-stone-700 px-4 py-3 text-sm leading-6 text-white shadow-sm"
            >{{ msg.content }}</div>

            <!-- AI 消息 -->
            <div v-else class="space-y-2">
              <!-- 思维链 -->
              <div
                v-if="msg.thinking || msg.isThinking"
                class="rounded-[20px] overflow-hidden"
                style="background: rgba(255,255,255,0.85); border: 1px solid rgba(168,162,158,0.20)"
              >
                <button
                  class="flex w-full items-center gap-2 px-3.5 py-2.5 text-left transition hover:bg-stone-50"
                  :class="msg.isThinking ? 'cursor-default' : 'cursor-pointer'"
                  @click="!msg.isThinking && toggleThinking(idx)"
                >
                  <svg v-if="msg.isThinking" class="h-3.5 w-3.5 animate-spin text-stone-500" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
                  </svg>
                  <svg v-else class="h-3.5 w-3.5 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.346A3 3 0 0115 18H9a3 3 0 01-2.12-.879l-.347-.346a5 5 0 010-7.072z"/>
                  </svg>
                  <span class="flex-1 text-xs font-medium" :class="msg.isThinking ? 'text-stone-500' : 'text-stone-400'">
                    {{ msg.isThinking ? '思考中…' : '查看思维链' }}
                  </span>
                  <svg v-if="!msg.isThinking" class="h-3.5 w-3.5 text-stone-400 transition-transform duration-200" :class="isThinkingExpanded(idx) ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                  </svg>
                </button>
                <div v-show="msg.isThinking || isThinkingExpanded(idx)" class="px-3.5 py-2.5" style="border-top: 1px solid rgba(168,162,158,0.15)">
                  <p class="font-mono text-[11px] leading-5 text-stone-500 whitespace-pre-wrap break-words">{{ msg.thinking }}</p>
                  <span v-if="msg.isThinking" class="inline-block h-3 w-0.5 animate-pulse bg-stone-500 align-middle ml-0.5"/>
                </div>
              </div>

              <!-- 等待点动画 -->
              <div v-if="!msg.content && !msg.thinking && !msg.isThinking" class="flex items-center gap-1.5 rounded-[20px] px-4 py-3 bg-stone-50">
                <span class="h-2 w-2 animate-bounce rounded-full bg-stone-300" style="animation-delay: 0ms"/>
                <span class="h-2 w-2 animate-bounce rounded-full bg-stone-300" style="animation-delay: 150ms"/>
                <span class="h-2 w-2 animate-bounce rounded-full bg-stone-300" style="animation-delay: 300ms"/>
              </div>

              <!-- 正文 -->
              <div v-if="msg.content" class="rounded-[20px] rounded-bl-md px-4 py-3" style="background: rgba(255,255,255,0.85); border: 1px solid rgba(168,162,158,0.20)">
                <div class="prose-content text-sm leading-7 text-stone-700" v-html="renderMarkdown(msg.content)" />
              </div>

              <!-- 来源卡片 -->
              <div v-if="msg.sources?.length" class="space-y-1.5 pt-1">
                <p class="text-2xs font-semibold uppercase tracking-widest text-stone-400 px-1">参考来源 · {{ msg.sources.length }} 条</p>
                <div class="flex flex-col gap-1.5">
                  <div
                    v-for="(source, sidx) in msg.sources"
                    :key="sidx"
                    class="flex items-center gap-2 rounded-2xl px-3 py-2 text-xs"
                    style="background: rgba(255,255,255,0.85); border: 1px solid rgba(168,162,158,0.20)"
                  >
                    <span class="shrink-0 text-2xs font-bold text-stone-400 w-4 text-center">{{ sidx + 1 }}</span>
                    <span class="shrink-0 badge border" :class="sourceTypeBadgeClass(getSourceType(source))">{{ getSourceType(source) }}</span>
                    <span class="min-w-0 flex-1 truncate font-medium text-stone-600" :title="getSourceTitle(source)">{{ getSourceTitle(source) }}</span>
                    <a v-if="getSourceUrl(source)" :href="getSourceUrl(source)!" target="_blank" rel="noopener noreferrer" class="shrink-0 text-stone-400 hover:text-stone-600 transition-colors">
                      <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="msg.role === 'user'" class="ml-2.5 mt-1 h-7 w-7 shrink-0 flex items-center justify-center rounded-full bg-stone-200 text-stone-600 text-xs font-bold">U</div>
        </div>
      </div>

      <!-- 回到底部 -->
      <div v-if="!autoScroll" class="pointer-events-none absolute bottom-20 right-5 z-10">
        <button class="pointer-events-auto btn-primary text-xs" @click="() => { autoScroll = true; scrollToBottom() }">
          <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          回到底部
        </button>
      </div>

      <!-- 输入区 -->
      <footer class="stagger-enter shrink-0 p-4" style="border-top: 1px solid rgba(168,162,158,0.15); animation-delay: 0.2s">
        <div class="flex items-end gap-3">
          <div class="relative flex-1">
            <textarea v-model="inputText" rows="1" class="input max-h-36 min-h-[48px] resize-y" placeholder="输入问题…（Enter 发送，Shift+Enter 换行）" @keydown="handleKeydown" />
          </div>
          <button class="btn-primary h-[48px] w-[48px] shrink-0 justify-center !rounded-full p-0" :disabled="!inputText.trim() || isSending" @click="handleSend">
            <svg v-if="!isSending" class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            <svg v-if="isSending" class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/></svg>
          </button>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.settings-panel-enter-active,
.settings-panel-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.settings-panel-enter-from,
.settings-panel-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-6px);
}
.settings-panel-enter-to,
.settings-panel-leave-from {
  transform: translateX(-50%) translateY(0);
}
</style>
