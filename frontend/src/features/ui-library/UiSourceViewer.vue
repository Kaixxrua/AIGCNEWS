<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { highlightSource } from './highlight'
import type { UiLanguage } from './catalog'
import { uiLibraryMessages } from './messages'

const props = defineProps<{ code: string; filename: string; lang: UiLanguage }>()
const highlighted = computed(() => highlightSource(props.code, props.filename))
const lines = computed(() => props.code.split('\n').length)
const numbers = computed(() => Array.from({ length: lines.value }, (_, index) => index + 1).join('\n'))
const pre = ref<HTMLPreElement>()
watch(() => props.filename, () => { pre.value?.scrollTo?.(0, 0) })
</script>

<template>
  <div class="ui-source-viewer">
    <div class="ui-source-viewer__bar"><span class="ui-source-viewer__language">{{ highlighted.label }}</span><span class="ui-source-viewer__filename" :title="filename">{{ filename }}</span><span class="ui-source-viewer__count">{{ lines }} {{ uiLibraryMessages[lang].lines }}</span></div>
    <pre ref="pre" tabindex="0" :aria-label="filename"><span class="ui-source-viewer__gutter" aria-hidden="true">{{ numbers }}</span><code class="hljs" v-html="highlighted.html"></code></pre>
  </div>
</template>
