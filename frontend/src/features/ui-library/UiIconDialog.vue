<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, Code2, Download, ExternalLink, Sparkles, X } from 'lucide-vue-next'
import UiSourceViewer from './UiSourceViewer.vue'
import { iconIntegrationPrompt, iconUrl, loadIconLicense, loadIconSource, type UiIcon, type UiIconSet, type UiLanguage } from './catalog'
import { uiLibraryMessages } from './messages'
import { useUiLibraryAccount } from './useUiLibraryAccount'
const account = useUiLibraryAccount()

const props = defineProps<{ icon: UiIcon; set: UiIconSet; lang: UiLanguage }>()
const emit = defineEmits<{ close: [] }>()
const text = computed(() => uiLibraryMessages[props.lang])
const dialog = ref<HTMLDialogElement>()
const svg = ref('')
const license = ref('')
const loading = ref(true)
const loadError = ref(false)
const copying = ref(false)
const copied = ref('')
const feedback = ref('')
const promptLang = ref<UiLanguage>(props.lang)
const controller = new AbortController()
let feedbackTimer: ReturnType<typeof setTimeout> | undefined
async function load() {
  loading.value = true
  loadError.value = false
  try {
    const [source, notice] = await Promise.all([
      loadIconSource(props.icon, controller.signal),
      loadIconLicense(props.set, controller.signal),
    ])
    if (controller.signal.aborted) return
    svg.value = source
    license.value = notice
  } catch {
    if (!controller.signal.aborted) loadError.value = true
  } finally { loading.value = false }
}
async function copy(kind: 'source' | 'prompt') {
  if (copying.value || !await account.requireAccount()) return
  copying.value = true
  try {
    const value = kind === 'source' ? svg.value : iconIntegrationPrompt(props.icon, props.set, svg.value, promptLang.value)
    if (!await account.copyValue(props.icon.id, kind, value)) return
    feedback.value = text.value.copied
    copied.value = kind
  } catch (error) {
    feedback.value = error instanceof Error ? error.message : text.value.copyError
  } finally { copying.value = false }
  clearTimeout(feedbackTimer)
  feedbackTimer = setTimeout(() => { copied.value = ''; feedback.value = '' }, 3000)
}
onMounted(() => {
  dialog.value?.showModal()
  void load()
})
onBeforeUnmount(() => {
  controller.abort()
  clearTimeout(feedbackTimer)
  dialog.value?.close()
})
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="ui-detail ui-detail--icon" aria-labelledby="ui-icon-detail-title" @cancel.prevent="emit('close')" @click.self="emit('close')">
      <header class="ui-detail__header"><div><h2 id="ui-icon-detail-title">{{ icon.display[lang] }}</h2><p>{{ set.provider }} · {{ set.author }}</p></div><button type="button" class="ui-detail__icon" :aria-label="text.close" autofocus @click="emit('close')"><X :size="21" /></button></header>
      <div class="ui-detail__body">
        <section class="ui-detail__visual" :aria-label="text.preview">
          <div class="ui-library__icon-stage"><img :src="iconUrl(icon)" :alt="icon.display[lang]" /></div>
          <p class="ui-library__icon-facts"><span>{{ set.provider }}</span><span>{{ icon.style }}</span><span>{{ icon.category }}</span><span>{{ set.license }}</span></p>
          <div class="ui-detail__credits">
            <a :href="set.source_url" target="_blank" rel="noopener noreferrer">{{ text.github }}<ExternalLink :size="13" /></a>
            <a :href="iconUrl(icon)" :download="`${icon.name}.svg`">{{ text.downloadSvg }}<Download :size="13" /></a>
          </div>
          <p v-if="set.scope_note" class="ui-detail__description">{{ set.scope_note }}</p>
          <details v-if="license" class="ui-library__icon-license"><summary>{{ text.license }} · {{ set.license }}</summary><pre>{{ license }}</pre></details>
        </section>
        <section class="ui-detail__code" :aria-label="text.source">
          <div class="ui-detail__actions"><button type="button" class="ui-detail__copy-source" :disabled="copying || loading || loadError" @click="copy('source')"><Check v-if="copied === 'source'" :size="18" /><Code2 v-else :size="18" />{{ copied === 'source' ? text.copied : text.copySvg }}</button><button type="button" class="ui-detail__copy-prompt" :disabled="copying || loading || loadError" @click="copy('prompt')"><Check v-if="copied === 'prompt'" :size="18" /><Sparkles v-else :size="18" />{{ copied === 'prompt' ? text.copied : text.copyPrompt }}</button></div>
          <p class="ui-library__quota">{{ account.quotaText.value }}</p>
          <div class="ui-detail__prompt-options"><p>{{ text.iconPromptHint }}</p><label><span class="sr-only">{{ text.promptLanguage }}</span><select v-model="promptLang"><option value="zh">中文</option><option value="en">English</option></select></label></div>
          <p v-if="feedback" class="ui-detail__feedback" role="status">{{ feedback }}</p>
          <div v-if="loading" class="ui-detail__code-message" role="status">{{ text.loading }}</div>
          <div v-else-if="loadError" class="ui-detail__code-message" role="alert">{{ text.sourceError }}<button type="button" @click="load">{{ text.retry }}</button></div>
          <UiSourceViewer v-else :code="svg" :filename="`${icon.name}.svg`" :lang="lang" />
        </section>
      </div>
    </dialog>
  </Teleport>
</template>
