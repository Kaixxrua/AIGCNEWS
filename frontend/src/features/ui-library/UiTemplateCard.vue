<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowUpRight, Check, Code2, LoaderCircle, Play, Sparkles } from 'lucide-vue-next'
import { integrationPrompt, loadSources, sourceBundle, type UiLanguage, type UiTemplate } from './catalog'
import { uiLibraryMessages } from './messages'
import UiCardVideo from './UiCardVideo.vue'
import UiLikeButton from './UiLikeButton.vue'
import { categoryLabel } from './taxonomy'
import { useUiLibraryAccount } from './useUiLibraryAccount'
import { useViewportPreview } from './useViewportPreview'
const account = useUiLibraryAccount()

const props = defineProps<{ item: UiTemplate; lang: UiLanguage; previewEnabled: boolean }>()
const emit = defineEmits<{ open: [event: Event] }>()
const text = computed(() => uiLibraryMessages[props.lang])
const poster = ref<HTMLElement>()
const { attached, playing } = useViewportPreview(poster, () => props.previewEnabled && Boolean(props.item.clip_url))
const previewState = ref<'loading' | 'ready' | 'error'>('loading')
watch(attached, () => { previewState.value = 'loading' })
const busy = ref('')
const copied = ref('')
const feedback = ref('')
const controller = new AbortController()
let feedbackTimer: ReturnType<typeof setTimeout> | undefined
async function copy(kind: 'source' | 'prompt') {
  if (busy.value || !await account.requireAccount()) return
  clearTimeout(feedbackTimer)
  busy.value = kind
  copied.value = ''
  feedback.value = ''
  try {
    const files = await loadSources(props.item, controller.signal)
    if (controller.signal.aborted) return
    const value = kind === 'source' ? sourceBundle(files) : integrationPrompt(props.item, files, props.lang)
    if (await account.copyValue(props.item.id, kind, value)) {
      copied.value = kind
      feedback.value = kind === 'prompt' ? text.value.promptReady : text.value.sourceReady
    }
  } catch (error) {
    if (!controller.signal.aborted) feedback.value = error instanceof Error && error.message !== 'Source unavailable'
      ? error.message : text.value.sourceError
  }
  finally {
    busy.value = ''
    if (!controller.signal.aborted) feedbackTimer = setTimeout(() => { copied.value = ''; feedback.value = '' }, 4000)
  }
}
onBeforeUnmount(() => {
  controller.abort()
  clearTimeout(feedbackTimer)
})
</script>

<template>
  <article class="ui-library__card" :data-template-id="item.id" :data-preview-state="!item.clip_url ? 'static' : attached ? previewState : 'paused'">
    <div class="ui-library__card-open">
      <span ref="poster" class="ui-library__poster">
        <img :src="item.poster_url" :alt="item.name[lang]" loading="lazy" />
        <UiCardVideo v-if="attached && previewState !== 'error'" class="ui-library__card-preview" :class="{ 'is-ready': previewState === 'ready' }" :src="item.clip_url" :playing="playing" :title="`${text.preview}: ${item.name[lang]}`" @ready="previewState = 'ready'" @error="previewState = 'error'" />
        <button type="button" class="ui-library__preview-trigger" :aria-label="`${text.preview}: ${item.name[lang]}`" @click="emit('open', $event)"><span class="ui-library__play"><Play :size="16" />{{ attached && previewState === 'loading' ? text.loadingPreview : text.preview }}</span></button>
        <span class="ui-library__badge">{{ item.kind === 'theme' ? 'Theme · CSS' : item.frameworks[0] === 'vue' ? 'Vue' : item.frameworks[0] === 'html' ? 'HTML' : 'React' }}</span>
        <span v-if="previewState === 'error'" class="ui-library__hover-error">{{ text.hoverError }}</span>
      </span>
      <button type="button" class="ui-library__card-title" @click="emit('open', $event)">{{ item.name[lang] }}<ArrowUpRight :size="15" aria-hidden="true" /></button>
    </div>
    <div class="ui-library__card-meta"><span>{{ item.provider }} · {{ categoryLabel(item, lang) }}</span><UiLikeButton :id="item.id" :lang="lang" /></div>
    <div class="ui-library__card-actions">
      <button type="button" class="ui-library__copy-source" :title="text.sourceBundleHint" :disabled="Boolean(busy)" @click="copy('source')"><LoaderCircle v-if="busy === 'source'" :size="16" class="ui-library__spinner" /><Check v-else-if="copied === 'source'" :size="16" /><Code2 v-else :size="16" />{{ copied === 'source' ? text.copied : text.copySource }}</button>
      <button type="button" class="ui-library__copy-prompt" :title="text.promptHint" :disabled="Boolean(busy)" @click="copy('prompt')"><LoaderCircle v-if="busy === 'prompt'" :size="16" class="ui-library__spinner" /><Check v-else-if="copied === 'prompt'" :size="16" /><Sparkles v-else :size="16" />{{ copied === 'prompt' ? text.copied : text.copyPrompt }}</button>
    </div>
    <p v-if="feedback" class="ui-library__card-feedback" role="status">{{ feedback }}</p>
  </article>
</template>
