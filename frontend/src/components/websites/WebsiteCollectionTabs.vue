<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{ active: 'recommended' | 'personal' }>()
const { t } = useI18n()
</script>

<template>
  <nav class="website-tabs" :aria-label="t('recommendedWebsites.collectionNav')">
    <RouterLink to="/websites" :aria-current="active === 'recommended' ? 'page' : undefined">{{ t('recommendedWebsites.title') }}</RouterLink>
    <RouterLink to="/projects?source=website" :aria-current="active === 'personal' ? 'page' : undefined">{{ t('projects.source.websiteLabel') }}</RouterLink>
  </nav>
</template>

<style scoped>
.website-tabs { display: flex; width: fit-content; max-width: 100%; gap: 4px; padding: 3px; border-radius: var(--control-radius); background: var(--paper-muted); }
.website-tabs a { display: flex; align-items: center; justify-content: center; min-height: 38px; padding: 4px 12px; border: 1px solid transparent; border-radius: 6px; color: var(--ink-secondary); font-size: 13px; font-weight: 600; white-space: nowrap; }
.website-tabs a[aria-current] { color: var(--projects-on-acid); background: var(--projects-acid); border-color: var(--projects-accent); box-shadow: 2px 2px 0 var(--shadow-hard); }
.website-tabs a:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
@media (max-width: 639px) { .website-tabs { width: 100%; } .website-tabs a { flex: 1; padding: 4px 8px; font-size: 12px; } }
</style>
