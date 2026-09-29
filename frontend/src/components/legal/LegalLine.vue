<script setup lang="ts">
import { computed } from 'vue'
import { splitLead } from '@/features/legal/legalText'

const props = defineProps<{ text: string }>()
const parts = computed(() => splitLead(props.text))
</script>

<template>
  <template v-if="parts"><strong class="legal-lead">{{ parts[0] }}</strong>{{ parts[1] }}</template>
  <template v-else>{{ text }}</template>
</template>

<style scoped>
/* 窄屏保持原排版：标签与正文同字重，仅桌面漫画版（comic-pages.css）加粗。 */
.legal-lead{font-weight:inherit;color:inherit}
</style>
