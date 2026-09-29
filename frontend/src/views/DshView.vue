<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useMediaQuery } from '@vueuse/core'
import { Box, CalendarDays, Crown, Wrench } from 'lucide-vue-next'
import '@/components/mcp/connection-layout.css'
import { RouterLink } from 'vue-router'
import DshSetupWizard from '@/components/dsh/DshSetupWizard.vue'
import { DSH_PLUGIN_INSTALL_METHODS, DSH_PLUGIN_REPOSITORY_URL, MCP_MEMBER_QUOTA } from '@/features/mcp/dshPlugin'
import { useAuthStore } from '@/stores/authStore'
import RollingNumber from '@/components/dashboard/RollingNumber.vue'
import { useDshPluginCalls } from '@/composables/useDshPluginCalls'

// /dsh 对游客开放为获客入口：插件介绍与安装方式选择免登录可见；
// 登录在向导「下一步」处按需弹窗，Token 签发仍由登录后的服务端完成。
const { t, locale } = useI18n()
const auth = useAuthStore()
// 桌面漫画版的四格统计：调用数与首页「dsh 插件调用」同源实时计数，只在桌面上订阅。
const desktop = useMediaQuery('(min-width: 1024px)')
const dshCalls = useDshPluginCalls(desktop)
</script>

<template>
  <div class="dsh-page connection-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="connection-scroll">
      <p class="dsh-page-title comic-title">{{ t('dsh.pageTitle') }}</p>
      <div class="connection-layout connection-layout--dsh">
        <div class="connection-aside">
          <section class="connection-intro glass-card relative overflow-hidden p-4 md:p-5">
            <div class="dsh-grid-overlay" />
            <div class="connection-intro-content relative z-10">
              <div class="connection-heading">
              <p class="dsh-eyebrow text-2xs font-semibold uppercase tracking-[0.28em] text-stone-400">{{ t('dsh.eyebrow') }}</p>
              <h1 class="mt-2 max-w-3xl text-2xl font-extrabold leading-tight md:text-4xl">{{ t('dsh.title') }}</h1>
              </div>
              <div class="connection-summary">
              <p class="mt-3 max-w-3xl text-sm leading-6 text-stone-500">{{ t('dsh.description') }}</p>
              <div class="mt-3 flex flex-wrap gap-2">
                <RouterLink to="/mcp" class="btn-secondary text-xs">{{ t('dsh.mcpLink') }}</RouterLink>
                <a :href="DSH_PLUGIN_REPOSITORY_URL" target="_blank" rel="noopener" class="btn-primary text-xs">{{ t('dsh.repository') }}</a>
              </div>
              </div>
            </div>
          </section>
  
          <section class="connection-details glass-card grid gap-3 p-4 md:grid-cols-[auto_minmax(0,1fr)] md:items-start">
            <div class="flex h-10 w-10 items-center justify-center border border-ink bg-[var(--acid)] text-lg font-black">✦</div>
            <div>
              <p class="dsh-eyebrow text-2xs font-semibold uppercase tracking-[0.22em] text-stone-400">{{ t('dsh.capabilitiesKicker') }}</p>
              <h2 class="mt-1 text-lg font-extrabold">{{ t('dsh.capabilitiesTitle') }}</h2>
              <p class="mt-2 text-sm leading-6 text-stone-500">{{ t('dsh.capabilitiesDescription') }}</p>
            </div>
          </section>
          <section v-if="desktop" class="dsh-stats" :aria-label="t('dsh.stats.label')">
            <div class="dsh-stat"><Box aria-hidden="true" /><span>{{ t('dsh.stats.calls') }}</span><strong><RollingNumber v-if="dshCalls !== null" :value="dshCalls" grouping /><template v-else>—</template></strong></div>
            <div class="dsh-stat"><Wrench aria-hidden="true" /><span>{{ t('dsh.stats.methods') }}</span><strong>{{ DSH_PLUGIN_INSTALL_METHODS.length }}</strong></div>
            <div class="dsh-stat"><Crown aria-hidden="true" /><span>{{ t('dsh.stats.vipDaily') }}</span><strong>{{ MCP_MEMBER_QUOTA.rolling24h.toLocaleString(locale) }}</strong></div>
            <div class="dsh-stat"><CalendarDays aria-hidden="true" /><span>{{ t('dsh.stats.vipMonthly') }}</span><strong>{{ MCP_MEMBER_QUOTA.rolling30d.toLocaleString(locale) }}</strong></div>
          </section>
        </div>

        <section v-if="auth.status === 'initializing'" class="glass-card p-5 md:p-6">
          <p class="text-xs text-stone-500">{{ t('dsh.authRestoring') }}</p>
        </section>
        <section v-else-if="auth.status === 'degraded'" class="glass-card p-5 md:p-6">
          <p class="rounded bg-rose-50 p-3 text-xs text-rose-700">{{ t('dsh.authDegraded') }} <button type="button" class="underline" @click="auth.initFromStorage()">{{ t('dsh.authRetry') }}</button></p>
        </section>
        <DshSetupWizard v-else />


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
.dsh-page-title { display: none; }
.dsh-grid-overlay { position: absolute; inset: 0; pointer-events: none; opacity: .32; background-image: linear-gradient(rgb(var(--ink-grid-rgb) / .08) 1px, transparent 1px), linear-gradient(90deg, rgb(var(--ink-grid-rgb) / .08) 1px, transparent 1px); background-size: 34px 34px; }
.dsh-page :deep(.glass-card) { border: 1px solid var(--rule); border-radius: var(--module-radius); background: rgb(var(--projects-paper-light-rgb) / .94); box-shadow: none; }
.dsh-page :deep(.btn-primary), .dsh-page :deep(.btn-secondary) { border-radius: var(--control-radius); font-weight: 600; box-shadow: none; }
.dsh-page :deep(.btn-primary) { border: 1px solid var(--ink); color: var(--mcp-btn-label); background: var(--ink); }
.dsh-page :deep(.btn-secondary) { border: 1px solid var(--ink); color: var(--ink); background: var(--paper-light); }
.dsh-install-method { border-radius: var(--control-radius); }
.dsh-install-method--recommended { border-color: var(--ink); box-shadow: none; }
.dsh-page :deep(h1) { font-size: var(--text-page); font-weight: 700; letter-spacing: -.02em; }
@media (prefers-reduced-motion: reduce) { .dsh-page *, .dsh-page *::before, .dsh-page *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; } }
</style>
