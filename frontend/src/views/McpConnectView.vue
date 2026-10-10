<script setup lang="ts">
import { useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import { CalendarDays, Crown, Library, MessageSquareText } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { useLiveCallCount } from '@/composables/useLiveCallCount'
import { MCP_MEMBER_QUOTA } from '@/features/mcp/dshPlugin'
import { MCP_PAGE_EXAMPLE_IDS, mcpExamplesByIds } from '@/features/mcp/mcpExamplePrompts'
import { installAgentSetupMessages } from '@/i18n/locales/agentSetup'
import RollingNumber from '@/components/dashboard/RollingNumber.vue'
import McpAgentSetup from '@/components/mcp/McpAgentSetup.vue'
import McpEndpointCard from '@/components/mcp/McpEndpointCard.vue'
import McpManualSetup from '@/components/mcp/McpManualSetup.vue'
import McpPromptExampleList from '@/components/mcp/McpPromptExampleList.vue'
import '@/components/mcp/agent-setup.css'

/**
 * /mcp：一颗「复制给 Agent 的配置提示词」打头，选客户端、跑命令都交给用户自己的 Agent。
 * 侧栏是两条备用路径：只能填网址的客户端复制一行远程地址；不支持浏览器授权或要排障时，展开「手动配置」。
 * 页面对游客开放：提示词和地址都不带 Token，游客也能复制；Token、接入回显与额度提示只在登录后出现。
 */
installAgentSetupMessages()

const { t, locale } = useI18n()
const auth = useAuthStore()

const pillKeys = ['agentSetup.mcp.oauth', 'agentSetup.mcp.noToken', 'mcp.streamableHttp'] as const
const examples = mcpExamplesByIds(MCP_PAGE_EXAMPLE_IDS)
const examplesTitleId = `mcp-examples-${useId()}`
const count = (value: number) => value.toLocaleString(locale.value)

// 桌面漫画版报头的一行统计：总调用数与首页「MCP 总调用次数」同源实时计数，只在桌面上订阅。
const desktop = useMediaQuery('(min-width: 1024px)')
const mcpCalls = useLiveCallCount('mcp_total_calls', desktop)
</script>

<template>
  <div class="mcp-connect-page agent-page">
    <div class="agent-page-scroll">
      <header class="agent-page-head">
        <p class="mcp-page-title comic-title agent-page-brush" aria-hidden="true">{{ t('mcp.pageTitle') }}</p>
        <ul class="agent-page-pills">
          <li v-for="key in pillKeys" :key="key">{{ t(key) }}</li>
        </ul>
        <h1 class="agent-page-title">{{ t('mcp.title') }}</h1>
        <p class="agent-page-description">{{ t('agentSetup.mcp.description') }}</p>
        <section v-if="desktop" class="mcp-stats agent-page-stats" :aria-label="t('mcp.stats.label')">
          <div class="mcp-stat"><Library aria-hidden="true" /><span>{{ t('mcp.stats.calls') }}</span><strong><RollingNumber v-if="mcpCalls !== null" :value="mcpCalls" grouping /><template v-else>—</template></strong></div>
          <div class="mcp-stat"><Crown aria-hidden="true" /><span>{{ t('dsh.stats.vipDaily') }}</span><strong>{{ count(MCP_MEMBER_QUOTA.rolling24h) }}</strong></div>
          <div class="mcp-stat"><CalendarDays aria-hidden="true" /><span>{{ t('dsh.stats.vipMonthly') }}</span><strong>{{ count(MCP_MEMBER_QUOTA.rolling30d) }}</strong></div>
        </section>
      </header>

      <!-- 登录状态恢复完（已登录或游客）才排主卡：免得游客先看到一闪而过的登录态内容。 -->
      <div v-if="auth.status === 'authenticated' || auth.status === 'anonymous'" class="agent-page-grid">
        <McpAgentSetup class="agent-page-hero" />
        <div class="agent-page-side">
          <McpEndpointCard />
          <McpManualSetup />
          <!-- 额度卡只给已登录的 Free：网站不向游客推介匿名额度（按 IP 的匿名桶只是插件开箱即用的默认体验）。 -->
          <section v-if="auth.isLoggedIn && !auth.isMember" class="agent-card agent-quota">
            <p class="agent-card-text">{{ t('mcp.quota.free') }}</p>
            <div class="agent-card-actions">
              <RouterLink to="/membership" class="agent-btn agent-btn--acid">{{ t('mcp.quota.vipCta') }}</RouterLink>
            </div>
          </section>
        </div>
        <section class="agent-card agent-examples" :aria-labelledby="examplesTitleId">
          <h2 :id="examplesTitleId" class="agent-card-title"><MessageSquareText class="agent-card-icon" aria-hidden="true" />{{ t('agentSetup.mcp.examples.title') }}</h2>
          <p class="agent-card-text">{{ t('agentSetup.mcp.examples.body') }}</p>
          <McpPromptExampleList :examples="examples" mode="copy-only" layout="cards" />
        </section>
      </div>
      <section v-else-if="auth.status === 'initializing'" class="agent-card agent-page-status">
        <p class="agent-card-text">{{ t('mcp.authRestoring') }}</p>
      </section>
      <section v-else class="agent-card agent-page-status">
        <p class="agent-card-error">{{ t('mcp.authDegraded') }}</p>
        <div class="agent-card-actions">
          <button type="button" class="agent-btn" @click="auth.initFromStorage()">{{ t('mcp.authRetry') }}</button>
        </div>
      </section>
    </div>
  </div>
</template>
