<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import '@/components/mcp/connection-layout.css'
import { useClipboard } from '@/composables/useClipboard'
import { useMcpConnectController } from '@/composables/useMcpConnectController'
import McpSetupWizard from '@/components/mcp/McpSetupWizard.vue'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'

const { t } = useI18n()
const authStore = useAuthStore()
const { copy } = useClipboard()
const { requestLogin } = useLoginPrompt()

const controller = useMcpConnectController({
  copy,
  isLoggedIn: () => authStore.isLoggedIn,
  navigateToLogin: async () => { requestLogin('/mcp') },
  translate: t,
})

const {
  clearAuthenticatedState,
  dispose,
  loadTokens,
} = controller

const heroPillKeys = ['noAuth', 'publicTools', 'streamableHttp'] as const

// /mcp 对游客开放为获客入口：页面与客户端选择免登录可见，登录在向导
// 「下一步」处按需弹窗。Token 属账号数据：仅已认证时加载；认证丢失
// （含登出、异步恢复为 anonymous）立即清空内存中的 Token 元数据与一次性命令。
watch(
  () => authStore.status,
  (status) => {
    if (status === 'authenticated') {
      void loadTokens()
      return
    }
    clearAuthenticatedState()
  },
  { immediate: true },
)

onBeforeUnmount(dispose)
</script>

<template>
  <div class="mcp-connect-page connection-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="connection-scroll">
      <div class="connection-layout">
        <template v-if="authStore.status === 'authenticated' || authStore.status === 'anonymous'">
          <section class="connection-intro glass-card relative overflow-hidden p-4 md:p-5">
            <div class="mcp-grid-overlay" />
            <div class="connection-intro-content relative z-10">
              <div class="connection-heading">
              <div class="mb-3 flex flex-wrap gap-2">
                <span v-for="pillKey in heroPillKeys" :key="pillKey" class="rounded-full border border-cyan-200/60 bg-cyan-50/75 px-2.5 py-1 text-2xs font-semibold uppercase tracking-[0.12em] text-cyan-700">{{ t(`mcp.${pillKey}`) }}</span>
              </div>
              <p class="text-2xs font-semibold uppercase tracking-[0.28em] text-stone-400">{{ t('mcp.serverEyebrow') }}</p>
              <h1 class="mt-2 font-serif text-2xl font-semibold leading-tight text-stone-900 md:text-3xl">{{ t('mcp.title') }}</h1>
              </div>
              <div class="connection-summary">
              <p class="mt-2 text-sm leading-6 text-stone-500">{{ t('mcp.description') }}</p>
              <!-- 额度卡仅对已登录非会员展示。网站不向游客推介匿名额度：
                   按 IP 匿名桶只作为 GitHub/NPM 发布渠道（插件开箱即用）的默认体验，
                   游客在接入向导前进到下一步时按需登录。 -->
              <div v-if="authStore.status === 'authenticated' && !authStore.isMember" class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[20px] border border-amber-200 bg-amber-50/70 px-3 py-2">
                <p class="min-w-0 flex-1 basis-64 text-xs leading-5 text-amber-900">{{ t('mcp.quota.free') }}</p>
                <RouterLink to="/membership" class="btn-secondary shrink-0 text-xs">{{ t('mcp.quota.vipCta') }}</RouterLink>
              </div>
              </div>
            </div>
          </section>

          <McpSetupWizard :controller="controller" />

        </template>

        <section v-if="authStore.status === 'initializing'" class="glass-card p-5 md:p-6">
          <p class="text-xs text-stone-500">{{ t('mcp.authRestoring') }}</p>
        </section>
        <section v-else-if="authStore.status === 'degraded'" class="glass-card p-5 md:p-6">
          <p class="rounded bg-rose-50 p-3 text-xs text-rose-700">{{ t('mcp.authDegraded') }} <button type="button" class="underline" @click="authStore.initFromStorage()">{{ t('mcp.authRetry') }}</button></p>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mcp-connect-page {
  --paper: var(--projects-paper);
  --paper-light: var(--projects-paper-light);
  --ink: var(--projects-accent);
  --muted: var(--dash-muted);
  --acid: var(--projects-acid);
  --acid-soft: var(--projects-acid-soft);
  position: relative;
  color: var(--ink);
  background: var(--paper);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.mcp-connect-page::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgb(var(--ink-grid-rgb) / .035) 1px, transparent 1px);
  background-size: 100% 32px;
}

.mcp-grid-overlay {
  position: absolute;
  inset: 0;
  opacity: .32;
  background-image: linear-gradient(rgb(var(--ink-grid-rgb) / .08) 1px, transparent 1px), linear-gradient(90deg, rgb(var(--ink-grid-rgb) / .08) 1px, transparent 1px);
  background-size: 34px 34px;
  pointer-events: none;
}


.mcp-connect-page :deep(.glass-card) {
  border: 1px solid var(--rule);
  border-radius: var(--module-radius);
  background: rgb(var(--projects-paper-light-rgb) / .94);
  box-shadow: none;
  backdrop-filter: none;
}

.mcp-connect-page :deep(.font-serif) { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
.mcp-connect-page :deep(h1),
.mcp-connect-page :deep(h2) { color: var(--ink); font-weight: 700; letter-spacing: -.02em; }
.mcp-connect-page :deep(.text-stone-400),
.mcp-connect-page :deep(.text-stone-500) { color: var(--muted); }

.mcp-connect-page :deep(.rounded-full),
.mcp-connect-page :deep(.rounded-2xl),
.mcp-connect-page :deep(.rounded-xl),
.mcp-connect-page :deep([class*="rounded-["]) { border-radius: var(--control-radius); }

.mcp-connect-page :deep(.border-cyan-200\/60),
.mcp-connect-page :deep(.border-cyan-300),
.mcp-connect-page :deep(.border-cyan-100) { border-color: var(--rule); }
.mcp-connect-page :deep(.bg-cyan-50),
.mcp-connect-page :deep(.bg-cyan-50\/70),
.mcp-connect-page :deep(.bg-cyan-50\/75) { background: var(--paper-muted); }
.mcp-connect-page :deep(.text-cyan-700),
.mcp-connect-page :deep(.text-cyan-800\/80),
.mcp-connect-page :deep(.text-cyan-900) { color: var(--ink); }

.mcp-connect-page :deep(button),
.mcp-connect-page :deep(.btn-primary),
.mcp-connect-page :deep(.btn-secondary) {
  border-radius: var(--control-radius);
  font-weight: 600;
  box-shadow: none;
}
.mcp-connect-page :deep(.btn-primary) { border: 1px solid var(--ink); color: var(--mcp-btn-label); background: var(--ink); }
.mcp-connect-page :deep(.btn-primary:not(:disabled):hover) { border-color: var(--ink); color: var(--projects-on-acid); background: var(--acid); transform: none; }
.mcp-connect-page :deep(.btn-secondary) { border: 1px solid var(--ink); color: var(--ink); background: var(--paper-light); }
.mcp-connect-page :deep(.btn-secondary:not(:disabled):hover),
.mcp-connect-page :deep(.mcp-choice:hover) { border-color: var(--ink); color: var(--ink); background: var(--acid-soft); transform: none; }
.mcp-connect-page :deep(.mcp-choice--active),
.mcp-connect-page :deep(.mcp-choice--active:hover) { border-color: var(--ink); color: var(--projects-on-acid); background: var(--acid); }
.mcp-connect-page :deep(input),
.mcp-connect-page :deep(.input) { border-color: var(--rule-strong); border-radius: var(--control-radius); background: var(--paper-light); box-shadow: none; }
.mcp-connect-page :deep(input:focus),
.mcp-connect-page :deep(.input:focus) { border-color: var(--ink); box-shadow: 0 0 0 3px var(--acid-soft); }

.mcp-connect-page :deep(h1) { font-size: var(--text-page); }
.mcp-connect-page :deep(.mcp-choice--active .text-stone-800),
.mcp-connect-page :deep(.mcp-choice--active .text-stone-400),
.mcp-connect-page :deep(.mcp-choice--active .text-stone-500) { color: var(--projects-on-acid); }
.mcp-connect-page :deep(.mcp-choice--active .bg-stone-100) { background: rgb(0 0 0 / .08); }

@media (prefers-reduced-motion: reduce) {
  .mcp-connect-page *, .mcp-connect-page *::before, .mcp-connect-page *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
}


</style>
