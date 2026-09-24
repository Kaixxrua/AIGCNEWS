<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Flame } from 'lucide-vue-next'
const props = defineProps<{ score?: number | string | null; available?: boolean | number | string | null }>()
const { t } = useI18n()
const valid = computed(() => (props.available === undefined || props.available === true || props.available === 1 || props.available === '1' || props.available === 'true')
  && props.score !== null && props.score !== undefined && props.score !== '' && Number.isFinite(Number(props.score)))
const display = computed(() => valid.value ? Math.max(0, Math.min(100, Number(props.score))).toFixed(1) : '—')
</script>

<template>
  <span class="project-heat" :title="t(valid ? 'projects.hotScoreTitle' : 'projects.heatPending')">
    <Flame :size="13" aria-hidden="true" />{{ t('projects.hotScore', { score: display }) }}
  </span>
</template>

<style scoped>
.project-heat { display: inline-flex; align-items: center; gap: 3px; white-space: nowrap; font-size: 11px; color: var(--heat-ink); }
</style>
