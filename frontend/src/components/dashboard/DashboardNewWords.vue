<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { ArrowUpRight, X } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { fetchNewWords, type NewWord, type NewWordsSnapshot } from '@/services/dashboard/newWordsApi'

const props = defineProps<{ date: string; historical: boolean }>()
const { t, locale } = useI18n()
const snapshot = ref<NewWordsSnapshot | null>(null)
const loading = ref(true)
const failed = ref(false)
const selected = ref<NewWord | null>(null)
const dialog = ref<HTMLDialogElement>()
const words = computed(() => snapshot.value?.items.slice(0, 2) ?? [])
const chinese = computed(() => locale.value.startsWith('zh'))
const stateLabel = computed(() => loading.value ? 'loading' : failed.value ? 'failed' : snapshot.value?.status === 'pending' ? 'pending' : 'empty')
let controller: AbortController | undefined
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

function close() {
  dialog.value?.close()
  selected.value = null
}

async function open(word: NewWord) {
  selected.value = word
  await nextTick()
  dialog.value?.showModal()
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
      <button v-for="word in words" :key="word.id" type="button" class="new-word" aria-haspopup="dialog" @click="open(word)">
        <span>{{ word.term }}</span><ArrowUpRight :size="18" aria-hidden="true" />
      </button>
    </div>
    <p v-else class="new-words-state" role="status">{{ t('dashboard.newWords.' + stateLabel) }}</p>
    <button v-if="failed" type="button" class="new-words-retry" @click="refresh">{{ t('common.retry') }}</button>
  </section>
  <Teleport to="body">
    <dialog ref="dialog" class="new-word-dialog" aria-labelledby="new-word-detail-title" @close="selected = null" @click="(event) => { if (event.target === dialog) close() }">
      <template v-if="selected">
        <button type="button" class="new-word-close" :aria-label="t('dashboard.newWords.close')" @click="close"><X :size="22" /></button>
        <h2 id="new-word-detail-title">{{ selected.term }}</h2>
        <p>{{ chinese ? selected.definition_zh : selected.definition_en }}</p>
        <h3>{{ t('dashboard.newWords.why') }}</h3>
        <p>{{ chinese ? selected.reason_zh : selected.reason_en }}</p>
        <h3>{{ t('dashboard.newWords.sources') }}</h3>
        <ul>
          <li v-for="source in selected.evidence" :key="source.id">
            <a v-if="sourceUrl(source.url)" :href="sourceUrl(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }} ↗</a>
          </li>
        </ul>
        <p class="new-word-first-seen">{{ t('dashboard.newWords.firstSeen') }} · {{ selected.first_seen }}</p>
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
.new-word:only-child { grid-column:1 / -1;justify-self:start; }
.new-word svg { flex-shrink:0; }
.new-word:hover { transform:translateY(-2px) rotate(-2deg); }
.new-word:nth-child(2):hover { transform:translateY(-2px) rotate(2deg); }
.new-word:focus-visible,.new-words-retry:focus-visible { outline:2px solid var(--ink);outline-offset:5px; }
.new-words-state { margin-top:13px;min-height:32px;color:var(--ink-secondary);font-size:12px;line-height:1.6; }
.new-words-retry { min-height:32px;font-size:12px;text-decoration:underline; }
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
:root[data-theme='dark'] .new-words-card { background:var(--paper-raised); }
:root[data-theme='dark'] .new-words-card::before { opacity:.1; }
:root[data-theme='dark'] .new-words-card h2::before { opacity:.25; }
@media (max-width:1023px) { .new-word,.new-words-retry { min-height:44px; } }
</style>
