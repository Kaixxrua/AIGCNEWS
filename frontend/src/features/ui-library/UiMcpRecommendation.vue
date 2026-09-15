<script setup lang="ts">
import { computed } from 'vue'
import { ArrowUpRight, PlugZap } from 'lucide-vue-next'
import type { UiLanguage } from './catalog'
import { uiLibraryMessages } from './messages'

const props = defineProps<{ lang: UiLanguage }>()
const text = computed(() => uiLibraryMessages[props.lang])
</script>

<template>
  <aside class="ui-mcp-tip" :aria-label="text.mcpRecommended">
    <PlugZap :size="20" aria-hidden="true" />
    <div><strong>{{ text.mcpRecommended }}</strong><p>{{ text.mcpRecommendation }}</p></div>
    <RouterLink to="/mcp">{{ text.mcpConnect }}<ArrowUpRight :size="15" aria-hidden="true" /></RouterLink>
  </aside>
</template>
