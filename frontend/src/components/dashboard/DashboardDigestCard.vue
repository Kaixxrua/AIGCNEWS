<script setup lang="ts">
import { ArrowRight, Mail } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <section class="digest-card">
    <div class="digest-heading">
      <h2><Mail :size="21" aria-hidden="true" />{{ t('dashboard.editorial.digestTitle') }}</h2>
      <span class="digest-time">{{ t('dashboard.digest.compactTime') }}</span>
    </div>
    <div class="digest-body">
      <p>{{ t('dashboard.digest.compactEmail') }}<br />Telegram · Discord · Webhook</p>
      <RouterLink :to="{ path: '/report', query: { subscribe: '1' } }" class="digest-cta">
        {{ t('dashboard.digest.compactCta') }}<ArrowRight :size="16" aria-hidden="true" />
      </RouterLink>
    </div>
  </section>
</template>

<style scoped>
.digest-card { padding:11px 13px;border:solid var(--rule-strong);border-width:2px 2.5px 3px 2px;border-radius:6px 9px 5px 8px;background:var(--paper);color:var(--ink); }
.digest-heading { display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:5px 8px; }
.digest-heading h2 { display:flex;align-items:center;gap:7px;font-size:19px;font-weight:900;line-height:1.25; }
.digest-heading h2 svg { flex-shrink:0;transform:rotate(-8deg);color:var(--ink-secondary); }
.digest-time { padding:2px 5px;background:var(--comic-cyan);font-size:10px;font-weight:800;transform:rotate(2deg);border:1px solid var(--rule-strong);border-radius:3px; }
.digest-body { display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:8px; }
.digest-body p { color:var(--ink-secondary);font-size:11px;font-weight:650;line-height:1.65; }
.digest-cta { display:flex;flex-shrink:0;align-items:center;justify-content:center;gap:4px;min-height:38px;padding:4px 9px;border:2px solid var(--rule-strong);border-radius:7px 5px 8px 4px;background:var(--acid);color:var(--acid-ink);font-size:14px;font-weight:850;box-shadow:2px 2px 0 var(--rule-strong); }
.digest-cta:focus-visible { outline:2px solid var(--ink);outline-offset:4px; }
:root[data-theme='dark'] .digest-card { background:var(--paper-raised); }
@media (max-width:1023px) { .digest-cta { min-height:44px; } }
</style>
