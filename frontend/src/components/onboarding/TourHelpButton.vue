<script setup lang="ts">
import { CircleHelp } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { requestTour } from '@/features/onboarding/signals'
const { t } = useI18n()
</script>

<template>
  <button type="button" class="tour-help" data-tour="help" :title="t('onboarding.help')" :aria-label="t('onboarding.help')" aria-haspopup="dialog" @click="requestTour">
    <CircleHelp :size="19" :stroke-width="1.8" aria-hidden="true" />
  </button>
</template>

<style scoped>
.tour-help { display: inline-grid; place-items: center; width: 32px; height: 32px; flex: 0 0 32px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: var(--ink-muted); cursor: pointer; }
.tour-help:hover { background: var(--acid-soft); color: var(--ink); }
.tour-help:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
</style>
