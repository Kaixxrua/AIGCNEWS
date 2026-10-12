<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Code2, Sparkles, Check, X, ExternalLink, Monitor, Smartphone, Play, Pause, RotateCcw, Film, MousePointer2 } from 'lucide-vue-next'
import UiCardVideo from './UiCardVideo.vue'
import UiSourceViewer from './UiSourceViewer.vue'
import UiMcpRecommendation from './UiMcpRecommendation.vue'
import UiLikeButton from './UiLikeButton.vue'
import { useUiLibraryAccount } from './useUiLibraryAccount'
const account = useUiLibraryAccount()
const copying = ref(false)
import { integrationPrompt, loadSources, loadTemplate, type UiLanguage, type UiSourceFile, type UiTemplate, type UiTemplateSummary } from './catalog'
import { uiLibraryMessages } from './messages'

const props = defineProps<{ item: UiTemplateSummary; lang: UiLanguage }>()
const emit = defineEmits<{ close: [] }>()
const text = computed(() => uiLibraryMessages[props.lang])
const dialog = ref<HTMLDialogElement>()
const frame = ref<HTMLIFrameElement>()
const detail = ref<UiTemplate | null>(null)
const sources = ref<UiSourceFile[]>([])
const fileIndex = ref(0)
const codeLoading = ref(true)
const codeError = ref(false)
const feedback = ref('')
const copied = ref('')
const promptLang = ref<UiLanguage>(props.lang)
const mobile = ref(false)
const hasVideo = computed(() => Boolean(props.item.clip_url) && props.item.kind !== 'theme')
const interactive = ref(false)
const videoMode = computed(() => hasVideo.value && !interactive.value)
function setInteractive(value: boolean) {
  interactive.value = value
  replay()
}
const themeMode = ref('light')
const previewUrl = computed(() => props.item.preview_url + (props.item.kind === 'theme' ? '?mode=' + themeMode.value : ''))
const playing = ref(true)
const revision = ref(0)
const previewState = ref('loading')
const controller = new AbortController()
const code = computed(() => sources.value[fileIndex.value]?.content ?? '')
let timer: ReturnType<typeof setTimeout> | undefined
let feedbackTimer: ReturnType<typeof setTimeout> | undefined
async function getSources() {
  codeLoading.value = true
  codeError.value = false
  try {
    detail.value = await loadTemplate(props.item.id, controller.signal, account.isAdmin.value)
    if (controller.signal.aborted) return
    sources.value = await loadSources(detail.value, controller.signal)
  }
  catch { if (!controller.signal.aborted) codeError.value = true }
  finally { codeLoading.value = false }
}
async function copy(kind: 'source' | 'prompt') {
  if (copying.value || !detail.value || !await account.requireAccount()) return
  copying.value = true
  try {
    const value = kind === 'source' ? code.value : integrationPrompt(detail.value, sources.value, promptLang.value)
    if (!await account.copyValue(props.item.id, kind, value)) return
    feedback.value = text.value.copied
    copied.value = kind
  } catch (error) { feedback.value = error instanceof Error ? error.message : text.value.copyError }
  finally { copying.value = false }
  clearTimeout(feedbackTimer)
  feedbackTimer = setTimeout(() => { copied.value = ''; feedback.value = '' }, 3000)
}
function replay() {
  previewState.value = 'loading'
  playing.value = true
  revision.value++
  clearTimeout(timer)
  if (!videoMode.value) timer = setTimeout(() => { if (previewState.value === 'loading') previewState.value = 'error' }, 15000)
}
function receive(event: MessageEvent) {
  if (event.source !== frame.value?.contentWindow || event.data?.type !== 'ui-library-preview' || event.data?.id !== props.item.id) return
  if (!['ready', 'error', 'unsupported'].includes(event.data.state)) return
  previewState.value = event.data.state
  clearTimeout(timer)
}
onMounted(() => {
  dialog.value?.showModal()
  playing.value = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (playing.value) replay()
  window.addEventListener('message', receive)
  void getSources()
})
onBeforeUnmount(() => {
  controller.abort()
  clearTimeout(timer)
  clearTimeout(feedbackTimer)
  window.removeEventListener('message', receive)
  dialog.value?.close()
})
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="ui-detail" aria-labelledby="ui-detail-title" @cancel.prevent="emit('close')" @click.self="emit('close')">
      <header class="ui-detail__header"><div><h2 id="ui-detail-title">{{ item.name[lang] }}</h2><p>{{ item.provider }} · {{ item.author }}</p><UiLikeButton :id="item.id" :lang="lang" /></div><button type="button" class="ui-detail__icon" :aria-label="text.close" autofocus @click="emit('close')"><X :size="21" /></button></header>
      <div class="ui-detail__body">
        <section class="ui-detail__visual" :aria-label="text.preview">
          <div class="ui-detail__preview-toolbar">
            <select v-if="item.kind === 'theme'" v-model="themeMode" :aria-label="lang === 'zh' ? '主题明暗模式' : 'Theme appearance'" @change="replay"><option value="light">{{ lang === 'zh' ? '浅色' : 'Light' }}</option><option value="dark">{{ lang === 'zh' ? '深色' : 'Dark' }}</option></select>
            <div v-if="hasVideo"><button type="button" :title="text.videoPreview" :aria-label="text.videoPreview" :aria-pressed="videoMode" @click="setInteractive(false)"><Film :size="17" /></button><button type="button" :title="text.interactivePreview" :aria-label="text.interactivePreview" :aria-pressed="!videoMode" @click="setInteractive(true)"><MousePointer2 :size="17" /></button></div>
            <div v-if="!videoMode"><button type="button" :aria-label="text.desktop" :aria-pressed="!mobile" @click="mobile = false"><Monitor :size="17" /></button><button type="button" :aria-label="text.mobile" :aria-pressed="mobile" @click="mobile = true"><Smartphone :size="17" /></button></div>
            <div><button type="button" :aria-label="playing ? text.pause : text.play" @click="playing ? (playing = false) : replay()"><Pause v-if="playing" :size="16" /><Play v-else :size="16" /></button><button type="button" :aria-label="text.replay" @click="replay"><RotateCcw :size="16" /></button></div>
          </div>
          <div class="ui-detail__stage" :class="{ 'is-mobile': mobile && !videoMode }">
            <UiCardVideo v-if="playing && videoMode" :key="revision" :src="item.clip_url" :poster="item.poster_url" :title="`${text.preview}: ${item.name[lang]}`" :playing="playing" @ready="previewState = 'ready'" @error="previewState = 'error'" />
            <iframe v-else-if="playing" :key="revision" ref="frame" :src="previewUrl" :title="`${text.preview}: ${item.name[lang]}`" sandbox="allow-scripts" referrerpolicy="no-referrer" />
            <button v-else type="button" class="ui-detail__paused" @click="replay"><img :src="item.poster_url" :alt="item.name[lang]" /><span><Play :size="24" />{{ text.play }}</span></button>
            <span v-if="playing && previewState === 'loading'" class="ui-detail__preview-status" role="status">{{ text.loadingPreview }}</span>
            <div v-if="playing && ['error', 'unsupported'].includes(previewState)" class="ui-detail__preview-error" role="alert"><p>{{ previewState === 'unsupported' ? text.unsupported : text.previewError }}</p><button type="button" @click="replay">{{ text.retry }}</button><a :href="item.demo_url" target="_blank" rel="noopener noreferrer">{{ text.original }}</a></div>
          </div>
          <div class="ui-detail__credits"><a :href="item.source_url" target="_blank" rel="noopener noreferrer">{{ text.github }}<ExternalLink :size="13" /></a></div>
          <p class="ui-detail__description">{{ item.description[lang] }}</p>
          <UiMcpRecommendation :lang="lang" />
        </section>
        <section class="ui-detail__code" :aria-label="text.source">
          <div class="ui-detail__actions"><button type="button" class="ui-detail__copy-source" :disabled="copying || codeLoading || codeError" @click="copy('source')"><Check v-if="copied === 'source'" :size="18" /><Code2 v-else :size="18" />{{ copied === 'source' ? text.copied : text.copySource }}</button><button type="button" class="ui-detail__copy-prompt" :disabled="copying || codeLoading || codeError" @click="copy('prompt')"><Check v-if="copied === 'prompt'" :size="18" /><Sparkles v-else :size="18" />{{ copied === 'prompt' ? text.copied : text.copyPrompt }}</button></div>
          <p class="ui-library__quota">{{ account.quotaText.value }} · <RouterLink to="/membership" @click="emit('close')">VIP</RouterLink></p>
          <div class="ui-detail__prompt-options"><p>{{ text.promptHint }}</p><label><span class="sr-only">{{ text.promptLanguage }}</span><select v-model="promptLang"><option value="zh">中文</option><option value="en">English</option></select></label></div>
          <p v-if="feedback" class="ui-detail__feedback" role="status">{{ feedback }}</p>
          <div class="ui-detail__filebar"><span>{{ text.source }}</span><select v-model="fileIndex" :aria-label="text.sourceFile" :disabled="codeLoading || codeError"><option v-for="(file, index) in sources" :key="file.name" :value="index">{{ file.name.split('/').pop() }}</option></select></div>
          <div v-if="codeLoading" class="ui-detail__code-message" role="status">{{ text.loading }}</div>
          <div v-else-if="codeError" class="ui-detail__code-message" role="alert">{{ text.sourceError }}<button type="button" @click="getSources">{{ text.retry }}</button></div>
          <UiSourceViewer v-else :code="code" :filename="sources[fileIndex]?.name ?? ''" :lang="lang" />
          <div class="ui-detail__dependencies"><strong>{{ text.dependencies }}</strong><code v-for="(version, name) in detail?.dependencies" :key="name">{{ name }}{{ '@' }}{{ version }}</code></div>
        </section>
      </div>
    </dialog>
  </Teleport>
</template>
