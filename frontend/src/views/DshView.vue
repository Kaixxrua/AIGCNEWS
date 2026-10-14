<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import { Box, CalendarDays, Clock3, Github, Wrench } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { useDshPluginCalls } from '@/composables/useDshPluginCalls'
import { useDshSetupController } from '@/composables/useDshSetupController'
import { DSH_PLUGIN_INSTALL_METHODS, DSH_PLUGIN_REPOSITORY_URL, MCP_MEMBER_QUOTA } from '@/features/mcp/dshPlugin'
import { installAgentSetupMessages } from '@/i18n/locales/agentSetup'
import RollingNumber from '@/components/dashboard/RollingNumber.vue'
import DshAgentSetup from '@/components/dsh/DshAgentSetup.vue'
import DshManualInstall from '@/components/dsh/DshManualInstall.vue'
import '@/components/mcp/agent-setup.css'

/**
 * /dsh：一颗「复制给 Agent 的配置提示词」打头，Agent 装好 dsh-aigc-radar 插件（npm 优先、GitHub 兜底）并写好专属 Token；
 * 侧栏是插件能力与折叠起来的「手动安装」。页面对游客开放，Token 只在登录后由服务端签发。
 * 页面持有一个控制器，主卡与手动安装共用同一枚 Token 和同一个连接检测：登录了才取 Token，
 * 认证一丢（登出、会话失效）立即清空，迟到的响应也回填不进来。
 */
installAgentSetupMessages()

const { t, locale } = useI18n()
const auth = useAuthStore()
const controller = useDshSetupController()
const count = (value: number) => value.toLocaleString(locale.value)

watch(
  () => auth.status,
  (status) => {
    if (status === 'authenticated') void controller.ensure()
    else controller.clearToken()
  },
  { immediate: true },
)

// 桌面漫画版报头的一行统计：调用数与首页「dsh 插件调用」同源实时计数，只在桌面上订阅。
const desktop = useMediaQuery('(min-width: 1024px)')
const dshCalls = useDshPluginCalls(desktop)

onBeforeUnmount(controller.dispose)
</script>

<template>
  <div class="dsh-page agent-page">
    <div class="agent-page-scroll">
      <header class="agent-page-head">
        <p class="dsh-page-title comic-title agent-page-brush" aria-hidden="true">{{ t('dsh.pageTitle') }}</p>
        <h1 class="agent-page-title">{{ t('dsh.title') }}</h1>
        <p class="agent-page-description">{{ t('dsh.description') }}</p>
        <section v-if="desktop" class="dsh-stats agent-page-stats" :aria-label="t('dsh.stats.label')">
          <div class="dsh-stat"><Box aria-hidden="true" /><span>{{ t('dsh.stats.calls') }}</span><strong><RollingNumber v-if="dshCalls !== null" :value="dshCalls" grouping /><template v-else>—</template></strong></div>
          <div class="dsh-stat"><Wrench aria-hidden="true" /><span>{{ t('dsh.stats.methods') }}</span><strong>{{ DSH_PLUGIN_INSTALL_METHODS.length }}</strong></div>
          <div class="dsh-stat"><Clock3 aria-hidden="true" /><span>{{ t('dsh.stats.vipDaily') }}</span><strong>{{ count(MCP_MEMBER_QUOTA.rolling24h) }}</strong></div>
          <div class="dsh-stat"><CalendarDays aria-hidden="true" /><span>{{ t('dsh.stats.vipMonthly') }}</span><strong>{{ count(MCP_MEMBER_QUOTA.rolling30d) }}</strong></div>
        </section>
      </header>

      <div class="agent-page-grid">
        <DshAgentSetup v-if="auth.status === 'authenticated' || auth.status === 'anonymous'" class="agent-page-hero" :controller="controller" />
        <section v-else-if="auth.status === 'initializing'" class="agent-card agent-page-hero agent-page-status">
          <p class="agent-card-text">{{ t('dsh.authRestoring') }}</p>
        </section>
        <section v-else class="agent-card agent-page-hero agent-page-status">
          <p class="agent-card-error">{{ t('dsh.authDegraded') }}</p>
          <div class="agent-card-actions">
            <button type="button" class="agent-btn" @click="auth.initFromStorage()">{{ t('dsh.authRetry') }}</button>
          </div>
        </section>
        <div class="agent-page-side">
          <section class="agent-card dsh-capabilities">
            <p class="agent-setup-kicker dsh-eyebrow"><span aria-hidden="true">✦ </span>{{ t('dsh.capabilitiesKicker') }}</p>
            <h2 class="agent-card-title">{{ t('dsh.capabilitiesTitle') }}</h2>
            <p class="agent-card-text">{{ t('dsh.capabilitiesDescription') }}</p>
            <div class="agent-card-actions">
              <a :href="DSH_PLUGIN_REPOSITORY_URL" target="_blank" rel="noopener" class="agent-btn agent-btn--ink"><Github class="agent-btn-icon" aria-hidden="true" />{{ t('dsh.repository') }}</a>
              <RouterLink to="/mcp" class="agent-btn">{{ t('dsh.mcpLink') }}</RouterLink>
            </div>
          </section>
          <DshManualInstall v-if="auth.status === 'authenticated' || auth.status === 'anonymous'" :controller="controller" />
        </div>
      </div>
    </div>
  </div>
</template>
