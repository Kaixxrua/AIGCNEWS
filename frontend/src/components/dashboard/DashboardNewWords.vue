<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { ArrowUpRight, History, Info, X } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { fetchNewWords, fetchNewWordsHistory, type NewWord, type NewWordsSnapshot } from '@/services/dashboard/newWordsApi'

const props = defineProps<{ date: string; historical: boolean }>()
const { t, locale } = useI18n()
const snapshot = ref<NewWordsSnapshot | null>(null)
const loading = ref(true)
const failed = ref(false)
const selected = ref<NewWord | null>(null)
const dialog = ref<HTMLDialogElement>()
const panel = ref<'word' | 'history' | 'method' | null>(null)
const fromHistory = ref(false)
const history = ref<NewWordsSnapshot[]>([])
const historyNext = ref<string | null>(null)
const historyLoading = ref(false)
const historyFailed = ref(false)
const methodSteps = ['candidateStep', 'verifyStep', 'filterStep', 'rankStep', 'repeatStep'] as const
const words = computed(() => snapshot.value?.items.slice(0, 2) ?? [])
const sampling = computed(() => snapshot.value?.items[0]?.sampling)
const chinese = computed(() => locale.value.startsWith('zh'))
const stateLabel = computed(() => loading.value ? 'loading' : failed.value ? 'failed' : snapshot.value?.status === 'pending' ? 'pending' : 'empty')
let controller: AbortController | undefined
let historyController: AbortController | undefined
let timer: ReturnType<typeof setInterval> | undefined
let active = true

async function refresh() {
  if (!active) return
  controller?.abort()
  const request = new AbortController()
  controller = request
  const date = props.date
  loading.value = !snapshot.value
  try {
    const result = await fetchNewWords(date, request.signal)
    if (request.signal.aborted || date !== props.date) return
    if (result.date !== date) throw new Error('Mismatched new-word date')
    snapshot.value = result
    failed.value = false
  } catch {
    if (!request.signal.aborted) failed.value = true
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}

function resetPanel() {
  historyController?.abort()
  historyLoading.value = false
  panel.value = null
  selected.value = null
}

function close() {
  dialog.value?.close()
  resetPanel()
}

async function showDialog() {
  await nextTick()
  if (!active || !panel.value) return
  if (!dialog.value?.open) dialog.value?.showModal()
  dialog.value?.querySelector<HTMLElement>('#new-word-detail-title')?.focus()
}

async function open(word: NewWord, historical = false) {
  selected.value = word
  fromHistory.value = historical
  panel.value = 'word'
  await showDialog()
}

async function openMethod() {
  panel.value = 'method'
  await showDialog()
}

async function openHistory() {
  panel.value = 'history'
  await showDialog()
  if (panel.value !== 'history') return
  await loadHistory(true)
}

async function backToHistory() {
  panel.value = 'history'
  await showDialog()
}

async function loadHistory(reset = false) {
  historyController?.abort()
  const request = new AbortController()
  historyController = request
  const date = props.date
  const before = reset
    ? new Date(Date.parse(`${date}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10)
    : historyNext.value
  if (!before) return
  if (reset) { history.value = []; historyNext.value = null }
  historyLoading.value = true
  historyFailed.value = false
  try {
    const result = await fetchNewWordsHistory(before, request.signal)
    if (request.signal.aborted || date !== props.date) return
    history.value = [...new Map([...history.value, ...result.items].map(day => [day.date, day])).values()]
    historyNext.value = result.next_before
  } catch {
    if (!request.signal.aborted) historyFailed.value = true
  } finally {
    if (!request.signal.aborted) historyLoading.value = false
  }
}

function sourceHost(url: string) {
  const safe = sourceUrl(url)
  return safe ? new URL(safe).hostname.replace(/^www\./, '') : ''
}

function sourceUrl(url: string) {
  try {
    const parsed = new URL(url)
    return ['https:', 'http:'].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : undefined
  } catch { return undefined }
}

function refreshVisible() {
  if (active && document.visibilityState === 'visible' && !props.historical) void refresh()
}

watch(() => props.date, () => {
  snapshot.value = null
  failed.value = false
  close()
  history.value = []
  historyNext.value = null
  void refresh()
}, { immediate: true })
onMounted(() => {
  timer = setInterval(refreshVisible, 60_000)
  document.addEventListener('visibilitychange', refreshVisible)
})
onActivated(() => {
  if (!active) { active = true; void refresh() }
})
onDeactivated(() => { active = false; controller?.abort(); close() })
onBeforeUnmount(() => {
  controller?.abort()
  clearInterval(timer)
  document.removeEventListener('visibilitychange', refreshVisible)
  close()
})
</script>

<template>
  <section class="new-words-card" aria-labelledby="new-words-title">
    <h2 id="new-words-title">{{ t(historical ? 'dashboard.newWords.historyTitle' : 'dashboard.newWords.title') }}</h2>
    <p class="new-words-subtitle">{{ t('dashboard.newWords.subtitle') }}</p>
    <div v-if="words.length" class="new-words-list">
      <button v-for="word in words" :key="word.id" type="button" class="new-word" :title="word.term" aria-haspopup="dialog" @click="open(word)">
        <span><strong>{{ word.term }}</strong><small>{{ t('dashboard.newWords.sourceCount', { count: word.evidence.filter(e => sourceUrl(e.url)).length }) }}</small></span><ArrowUpRight :size="18" aria-hidden="true" />
      </button>
    </div>
    <p v-else class="new-words-state" role="status">{{ t('dashboard.newWords.' + stateLabel) }}</p>
    <button v-if="failed" type="button" class="new-words-retry" @click="refresh">{{ t('common.retry') }}</button>
    <div class="new-words-tools">
      <button class="new-words-history" type="button" aria-haspopup="dialog" @click="openHistory"><History :size="13" aria-hidden="true" />{{ t('dashboard.newWords.archive') }}</button>
      <button class="new-words-method" type="button" aria-haspopup="dialog" @click="openMethod"><Info :size="13" aria-hidden="true" />{{ t('dashboard.newWords.method') }}</button>
    </div>
  </section>
  <Teleport to="body">
    <dialog ref="dialog" class="new-word-dialog" aria-labelledby="new-word-detail-title" @close="resetPanel" @click="(event) => { if (event.target === dialog) close() }">
      <button type="button" class="new-word-close" :aria-label="t('dashboard.newWords.close')" @click="close"><X :size="22" /></button>
      <template v-if="panel === 'word' && selected">
        <button v-if="fromHistory" type="button" class="new-word-back" @click="backToHistory">← {{ t('dashboard.newWords.backToHistory') }}</button>
        <h2 id="new-word-detail-title" tabindex="-1">{{ selected.term }}</h2>
        <h3>{{ t('dashboard.newWords.aiExplanation') }}</h3>
        <p class="new-word-definition" lang="zh-CN"><span class="new-word-language">中文</span>{{ selected.definition_zh }}</p>
        <p class="new-word-definition" lang="en"><span class="new-word-language">English</span>{{ selected.definition_en }}</p>
        <h3>{{ t('dashboard.newWords.why') }}</h3>
        <p>{{ chinese ? selected.reason_zh : selected.reason_en }}</p>
        <h3>{{ t('dashboard.newWords.sources') }}</h3>
        <p v-if="selected.support">{{ t('dashboard.newWords.support', selected.support) }}</p>
        <ul>
          <li v-for="source in selected.evidence.filter(e => sourceUrl(e.url))" :key="source.id">
            <span class="new-word-source-meta">{{ sourceHost(source.url) }} · {{ source.published_at.slice(0, 10) }}</span>
            <a :href="sourceUrl(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }} ↗</a>
          </li>
        </ul>
        <p class="new-word-first-seen">{{ t('dashboard.newWords.firstSeen') }} · {{ selected.first_seen }}</p>
      </template>
      <template v-else-if="panel === 'method'">
        <h2 id="new-word-detail-title" tabindex="-1">{{ t('dashboard.newWords.method') }}</h2>
        <p>{{ t('dashboard.newWords.methodIntro') }}</p>
        <p v-if="sampling">{{ t('dashboard.newWords.sampling', sampling) }}</p>
        <ol class="new-word-method-steps">
          <li v-for="step in methodSteps" :key="step">{{ t('dashboard.newWords.' + step) }}</li>
        </ol>
        <p class="new-word-method-note">{{ t('dashboard.newWords.methodLimit') }}</p>
      </template>
      <template v-else-if="panel === 'history'">
        <h2 id="new-word-detail-title" tabindex="-1">{{ t('dashboard.newWords.archive') }}</h2>
        <p>{{ t('dashboard.newWords.historyIntro') }}</p>
        <section v-for="day in history" :key="day.date" class="new-word-history-day">
          <h3><time :datetime="day.date">{{ day.date }}</time></h3>
          <button v-for="word in day.items" :key="word.id" type="button" class="new-word-history-item" @click="open(word, true)">
            <strong>{{ word.term }} ↗</strong>
            <span>{{ chinese ? word.definition_zh : word.definition_en }}</span>
            <small>{{ t('dashboard.newWords.sourceCount', { count: word.evidence.filter(e => sourceUrl(e.url)).length }) }}</small>
          </button>
        </section>
        <p v-if="historyLoading" role="status">{{ t('dashboard.newWords.historyLoading') }}</p>
        <p v-else-if="historyFailed" role="status">{{ t('dashboard.newWords.historyFailed') }}</p>
        <p v-else-if="!history.length" role="status">{{ t('dashboard.newWords.historyEmpty') }}</p>
        <button v-if="historyFailed" type="button" class="new-word-history-more" @click="loadHistory(!historyNext)">{{ t('common.retry') }}</button>
        <button v-else-if="historyNext" type="button" class="new-word-history-more" :disabled="historyLoading" @click="loadHistory()">{{ t('dashboard.newWords.historyMore') }}</button>
      </template>
    </dialog>
  </Teleport>
</template>

<style scoped>
.new-words-card { position:relative;isolation:isolate;container-type:inline-size;padding:12px 14px 14px;overflow:hidden;border:solid var(--rule-strong);border-width:2px 3px 3px 2px;border-radius:8px 5px 9px 4px;background:var(--paper);color:var(--ink); }
.new-words-card::before { content:'';position:absolute;inset:0;z-index:-1;background:radial-gradient(var(--comic-cyan-dot) .7px,transparent .9px);background-size:4px 4px;mask-image:linear-gradient(125deg,transparent 35%,#000);opacity:.2; }
.new-words-card h2 { position:relative;isolation:isolate;display:inline-block;font-size:24px;font-style:italic;font-weight:950;line-height:1.3; }
.new-words-card h2::before { content:'';position:absolute;inset:65% -3px 2px;z-index:-1;background:var(--acid);transform:rotate(-3deg) skewX(-15deg); }
.new-words-subtitle { margin-top:4px;color:var(--ink-secondary);font-size:11px;font-weight:650;line-height:1.4; }
.new-words-list { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:center;gap:9px;margin:13px 2px 2px; }
.new-word { display:flex;align-items:center;justify-content:space-between;gap:7px;min-width:0;max-width:100%;min-height:40px;padding:6px 10px;border:2px solid var(--rule-strong);border-radius:4px 6px 3px 5px;background:var(--acid);color:var(--acid-ink);box-shadow:3px 3px 0 var(--rule-strong);transform:rotate(-2deg);font-size:clamp(14px,5cqw,18px);font-weight:900;line-height:1.25;text-align:left; }
.new-word:nth-child(2) { background:var(--comic-cyan);color:var(--ink);transform:rotate(2deg); }
.new-word span { overflow-wrap:anywhere; }
.new-word strong { font-weight:900; }
.new-word small { display:block;margin-top:3px;font-size:10px;font-weight:650;opacity:.75; }
.new-word:only-child { grid-column:1 / -1;justify-self:start; }
.new-word svg { flex-shrink:0; }
.new-word:hover { transform:translateY(-2px) rotate(-2deg); }
.new-word:nth-child(2):hover { transform:translateY(-2px) rotate(2deg); }
.new-word:focus-visible,.new-words-retry:focus-visible { outline:2px solid var(--ink);outline-offset:5px; }
.new-words-state { margin-top:13px;min-height:32px;color:var(--ink-secondary);font-size:12px;line-height:1.6; }
.new-words-retry { min-height:32px;font-size:12px;text-decoration:underline; }
.new-words-tools { display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:12px;padding-top:6px;border-top:1px dashed var(--rule); }
.new-words-tools button { display:inline-flex;align-items:center;gap:4px;min-height:32px;font-size:11px;font-weight:750;color:var(--ink-secondary); }
.new-words-tools button:hover { color:var(--ink);text-decoration:underline;text-underline-offset:3px; }
.new-words-tools button:focus-visible,.new-word-history-item:focus-visible,.new-word-history-more:focus-visible,.new-word-back:focus-visible { outline:2px solid var(--ink);outline-offset:3px; }
.new-word-dialog { width:min(560px,calc(100vw - 32px));max-height:80dvh;margin:auto;padding:26px;background:var(--paper);color:var(--ink);border:3px solid var(--rule-strong);border-radius:10px 6px 12px 5px;box-shadow:7px 7px 0 var(--rule-strong);overflow:auto; }
.new-word-dialog::backdrop { background:rgb(7 23 53 / .6); }
.new-word-close { position:absolute;top:6px;right:6px;display:grid;place-items:center;width:44px;height:44px; }
.new-word-dialog h2 { padding-right:26px;overflow-wrap:anywhere;font-size:28px;font-weight:950;font-style:italic; }
.new-word-dialog h3 { margin:20px 0 6px;font-weight:850; }
.new-word-dialog p,.new-word-dialog li { font-size:14px;line-height:1.8;overflow-wrap:anywhere; }
.new-word-dialog h2 + p { margin-top:12px; }
.new-word-dialog ul { padding-left:18px;list-style:disc; }
.new-word-dialog li { margin-top:8px; }
.new-word-dialog a { text-decoration:underline;text-underline-offset:3px; }
.new-word-first-seen { margin-top:20px;color:var(--ink-secondary);font-size:12px !important; }
.new-word-source-meta { display:block;margin-top:10px;color:var(--ink-secondary);font-size:12px; }
.new-word-definition + .new-word-definition { margin-top:10px; }
.new-word-language { display:block;color:var(--ink-secondary);font-size:11px;font-weight:750; }
.new-word-method-steps { margin:18px 0;padding-left:23px;list-style:decimal; }
.new-word-method-steps li { margin-top:12px;padding-left:3px; }
.new-word-method-note { margin-top:18px;padding:12px;border:2px dashed var(--rule-strong);border-radius:4px;font-size:12px !important; }
.new-word-history-day { margin-top:20px; }
.new-word-history-day h3 { display:inline-block;margin:0 0 9px;padding:1px 7px;background:var(--acid);color:var(--acid-ink);font-size:13px;transform:rotate(-1deg); }
.new-word-history-item { display:grid;gap:4px;width:100%;margin:0 0 10px;padding:12px;border:2px solid var(--rule-strong);border-radius:4px 7px 5px 3px;text-align:left;box-shadow:2px 2px 0 var(--rule-strong); }
.new-word-history-item strong { font-size:16px;font-weight:850;overflow-wrap:anywhere; }
.new-word-history-item span { font-size:13px;line-height:1.6; }
.new-word-history-item small { font-size:11px;color:var(--ink-secondary); }
.new-word-history-item:hover { background:var(--paper-raised); }
.new-word-history-more,.new-word-back { min-height:44px;font-size:13px;font-weight:750;text-decoration:underline;text-underline-offset:4px; }
.new-word-history-more:disabled { opacity:.5; }
:root[data-theme='dark'] .new-words-card { background:var(--paper-raised); }
:root[data-theme='dark'] .new-words-card::before { opacity:.1; }
:root[data-theme='dark'] .new-words-card h2::before { opacity:.25; }
@media (max-width:1023px) { .new-word,.new-words-retry,.new-words-tools button { min-height:44px; } }
</style>
