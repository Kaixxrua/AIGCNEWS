<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import DshSetupWizard from '@/components/dsh/DshSetupWizard.vue'
import { DSH_PLUGIN_REPOSITORY_URL } from '@/features/mcp/dshPlugin'

const { t } = useI18n()
</script>

<template>
  <div class="dsh-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-8">
      <div class="mx-auto flex max-w-5xl flex-col gap-5 pb-24">
        <section class="glass-card relative overflow-hidden p-5 md:p-7">
          <div class="dsh-grid-overlay" />
          <div class="relative z-10">
            <p class="text-2xs font-semibold uppercase tracking-[0.28em] text-stone-400">{{ t('dsh.eyebrow') }}</p>
            <h1 class="mt-2 max-w-3xl text-2xl font-extrabold leading-tight md:text-4xl">{{ t('dsh.title') }}</h1>
            <p class="mt-3 max-w-3xl text-sm leading-6 text-stone-500">{{ t('dsh.description') }}</p>
            <div class="mt-5 flex flex-wrap gap-2">
              <RouterLink to="/mcp" class="btn-secondary text-xs">{{ t('dsh.mcpLink') }}</RouterLink>
              <a :href="DSH_PLUGIN_REPOSITORY_URL" target="_blank" rel="noopener" class="btn-primary text-xs">{{ t('dsh.repository') }}</a>
            </div>
          </div>
        </section>

        <DshSetupWizard />

        <section class="glass-card grid gap-3 p-5 md:grid-cols-[auto_minmax(0,1fr)] md:items-start md:p-6">
          <div class="flex h-10 w-10 items-center justify-center border border-ink bg-[var(--acid)] text-lg font-black">✦</div>
          <div>
            <p class="text-2xs font-semibold uppercase tracking-[0.22em] text-stone-400">{{ t('dsh.capabilitiesKicker') }}</p>
            <h2 class="mt-1 text-lg font-extrabold">{{ t('dsh.capabilitiesTitle') }}</h2>
            <p class="mt-2 text-sm leading-6 text-stone-500">{{ t('dsh.capabilitiesDescription') }}</p>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dsh-page {
  --paper: var(--projects-paper);
  --paper-light: var(--projects-paper-light);
  --ink: var(--projects-accent);
  --muted: var(--dash-muted);
  --acid: var(--projects-acid);
  color: var(--ink);
  background: var(--paper);
  background-image: linear-gradient(rgb(var(--ink-grid-rgb) / .035) 1px, transparent 1px);
  background-size: 100% 32px;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}
.dsh-grid-overlay { position: absolute; inset: 0; pointer-events: none; opacity: .32; background-image: linear-gradient(rgb(var(--ink-grid-rgb) / .08) 1px, transparent 1px), linear-gradient(90deg, rgb(var(--ink-grid-rgb) / .08) 1px, transparent 1px); background-size: 34px 34px; }
.dsh-page :deep(.glass-card) { border: 1px solid var(--ink); border-radius: 6px; background: rgb(var(--projects-paper-light-rgb) / .94); box-shadow: 4px 4px 0 var(--shadow-hard); }
.dsh-page :deep(.btn-primary), .dsh-page :deep(.btn-secondary) { border-radius: 4px; font-weight: 800; box-shadow: none; }
.dsh-page :deep(.btn-primary) { border: 1px solid var(--ink); color: var(--mcp-btn-label); background: var(--ink); }
.dsh-page :deep(.btn-secondary) { border: 1px solid var(--ink); color: var(--ink); background: var(--paper-light); }
.dsh-install-method { border-radius: 4px; }
.dsh-install-method--recommended { border-color: var(--ink); box-shadow: 3px 3px 0 var(--shadow-hard); }
.text-2xs { font-size: .68rem; }
@media (prefers-reduced-motion: reduce) { .dsh-page *, .dsh-page *::before, .dsh-page *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; } }
</style>
