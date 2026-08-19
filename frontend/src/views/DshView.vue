<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { useClipboard } from '@/composables/useClipboard'
import { useDshInstallController } from '@/composables/useDshInstallController'
import { DSH_PLUGIN_INSTALL_METHODS, DSH_PLUGIN_REPOSITORY_URL } from '@/features/mcp/dshPlugin'

const { t } = useI18n()
const { copy } = useClipboard()
const copyError = ref(false)
const controller = useDshInstallController({
  copy,
  onCopyError: () => { copyError.value = true },
})
const { copiedKey, copyDshInstallCommand, dispose } = controller

onBeforeUnmount(dispose)
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

        <section class="glass-card p-5 md:p-7" :aria-label="t('dsh.installTitle')">
          <p class="text-2xs font-semibold uppercase tracking-[0.22em] text-stone-400">{{ t('dsh.installKicker') }}</p>
          <h2 class="mt-1 text-xl font-extrabold">{{ t('dsh.installTitle') }}</h2>
          <p class="mt-2 max-w-3xl text-sm leading-6 text-stone-500">{{ t('dsh.installDescription') }}</p>
          <p v-if="copyError" class="mt-4 border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-700">{{ t('mcp.copyFailed') }}</p>
          <div class="mt-5 grid gap-3">
            <article
              v-for="method in DSH_PLUGIN_INSTALL_METHODS"
              :key="method.id"
              class="dsh-install-method grid min-w-0 gap-4 border border-stone-200 bg-card/70 p-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
              :class="method.recommended ? 'dsh-install-method--recommended' : ''"
              :data-install-method="method.id"
            >
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <h3 class="text-sm font-extrabold">{{ t(method.titleKey) }}</h3>
                  <span v-if="method.recommended" class="border border-stone-900 bg-[var(--acid)] px-2 py-0.5 text-2xs font-extrabold">{{ t('dsh.recommended') }}</span>
                </div>
                <p class="mt-1 text-xs leading-5 text-stone-500">{{ t(method.descriptionKey) }}</p>
                <code class="mt-3 block overflow-x-auto whitespace-nowrap border border-stone-700 bg-stone-900 px-3 py-2 font-mono text-xs leading-5 text-stone-100">{{ method.command }}</code>
                <p v-if="method.sourceInstall" class="mt-3 text-xs leading-5 text-amber-800">
                  <strong>{{ t('dsh.sourceWarningTitle') }}</strong>
                  {{ t('dsh.sourceWarning') }}
                  <code>github:Kaixxrua/dsh-aigc-radar#&lt;sha&gt;</code>
                </p>
              </div>
              <button type="button" class="btn-primary justify-center text-xs" @click="copyDshInstallCommand(method.id)">
                {{ t(copiedKey === `dsh-install-${method.id}` ? 'mcp.copied' : 'dsh.copy') }}
              </button>
            </article>
          </div>
        </section>

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
