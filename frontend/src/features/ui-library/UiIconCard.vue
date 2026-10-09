<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { Check, Code2, LoaderCircle } from 'lucide-vue-next'
import { iconUrl, loadIconSource, type UiIcon, type UiIconSet, type UiLanguage } from './catalog'
import { uiLibraryMessages } from './messages'
import { useUiLibraryAccount } from './useUiLibraryAccount'
import UiDeprecationButton from './UiDeprecationButton.vue'
const account = useUiLibraryAccount()

const props = defineProps<{ icon: UiIcon; set: UiIconSet; lang: UiLanguage }>()
const emit = defineEmits<{ open: [event: Event]; visibility: [deprecated: boolean] }>()
const text = computed(() => uiLibraryMessages[props.lang])
const busy = ref(false)
const copied = ref(false)
const feedback = ref('')
const controller = new AbortController()
let feedbackTimer: ReturnType<typeof setTimeout> | undefined
async function copy() {
  if (busy.value || !await account.requireAccount()) return
  clearTimeout(feedbackTimer)
  busy.value = true
  copied.value = false
  feedback.value = ''
  try {
    const svg = await loadIconSource(props.icon, controller.signal)
    if (controller.signal.aborted) return
    if (await account.copyValue(props.icon.id, 'source', svg)) {
      copied.value = true
      feedback.value = text.value.copied
    }
  } catch (error) {
    if (!controller.signal.aborted) feedback.value = error instanceof Error ? error.message : text.value.copyError
  } finally {
    busy.value = false
    if (!controller.signal.aborted) feedbackTimer = setTimeout(() => { copied.value = false; feedback.value = '' }, 4000)
  }
}
onBeforeUnmount(() => {
  controller.abort()
  clearTimeout(feedbackTimer)
})
</script>

<template>
  <article class="ui-library__icon-card" :data-icon-id="icon.id">
    <UiDeprecationButton :id="icon.id" :deprecated="icon.deprecated" :lang="lang" @changed="emit('visibility', $event)" />
    <button type="button" class="ui-library__icon-open" :aria-label="`${text.preview}: ${icon.display[lang]}`" @click="emit('open', $event)">
      <img class="ui-library__icon-glyph" :src="iconUrl(icon)" :alt="icon.display[lang]" loading="lazy" />
      <span class="ui-library__icon-name">{{ icon.display[lang] }}</span>
    </button>
    <button type="button" class="ui-library__icon-copy" :title="text.copySvgHint" :disabled="busy" @click="copy">
      <LoaderCircle v-if="busy" :size="13" class="ui-library__spinner" /><Check v-else-if="copied" :size="13" /><Code2 v-else :size="13" />{{ copied ? text.copied : text.copySvg }}
    </button>
    <p v-if="feedback" class="ui-library__card-feedback" role="status">{{ feedback }}</p>
  </article>
</template>
