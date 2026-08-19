<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useEnrichmentAlertStore } from '@/stores/enrichmentAlertStore'
import GithubCrawlControls from '@/components/monitor/GithubCrawlControls.vue'
import GithubEnrichmentPanel from '@/components/monitor/GithubEnrichmentPanel.vue'
import ErrorLogPanel from '@/components/monitor/ErrorLogPanel.vue'
import McpServerConfigPanel from '@/components/monitor/McpServerConfigPanel.vue'
import McpToolCallsPanel from '@/components/monitor/McpToolCallsPanel.vue'
import MembershipGrantPanel from '@/components/monitor/MembershipGrantPanel.vue'
import MonitorAdminActionControls from '@/components/monitor/MonitorAdminActionControls.vue'
import MonitorIngestionControls from '@/components/monitor/MonitorIngestionControls.vue'
import MonitorSectionNav from '@/components/monitor/MonitorSectionNav.vue'
import MonitorTaskPanel from '@/components/monitor/MonitorTaskPanel.vue'
import ProviderConfigPanel from '@/components/monitor/ProviderConfigPanel.vue'
import SchedulerConfigPanel from '@/components/monitor/SchedulerConfigPanel.vue'
import SiteContactPageConfigPanel from '@/components/monitor/SiteContactPageConfigPanel.vue'
import SmtpConfigPanel from '@/components/monitor/SmtpConfigPanel.vue'
import EmailPoolConfigPanel from '@/components/monitor/EmailPoolConfigPanel.vue'
import XCredentialCard from '@/components/monitor/XCredentialCard.vue'
import XWatchCard from '@/components/monitor/XWatchCard.vue'
import WechatAccountPanel from '@/components/wechat/WechatAccountPanel.vue'
import { useMonitorPageController } from '@/composables/useMonitorPageController'
import {
  DEFAULT_MONITOR_SECTION,
  MONITOR_NAV,
  normalizeMonitorSection,
  type MonitorSectionKey,
} from '@/features/monitor/monitorViewModel'

const { t } = useI18n()
const authStore = useAuthStore()
const enrichmentAlert = useEnrichmentAlertStore()
const {
  tasks, total, page, errorLogs, errorLogsTotal, errorLogsPage, errorLogsTotalPages, schedulerStatus, schedulerConfigs, schedulerConfigForm, loadingSchedulerConfigs, savingSchedulerConfig, editingSchedulerJobId, mcpToolCalls, loading, errorMsg, successMsg, providerConfig, providerForm,
  loadingProviderConfig, savingProviderConfig, testingProvider, smtpConfig, smtpForm, loadingSmtpConfig, savingSmtpConfig, testingSmtp,
  emailPoolConfig, emailPoolForm, loadingEmailPoolConfig, savingEmailPoolConfig, testingEmailPool, mcpServers, mcpForm, loadingMcpServers, savingMcpServer,
  siteContactPageConfig, siteContactPageForm, loadingSiteContactPage, savingSiteContactPage,
  membershipForm, grantingMembership, membershipLastResult, grantMembership,
  testingMcpServerId, deletingMcpServerId, isTaskRunning, totalPages, syncing, generatingBriefing,
  clearingCache, targetDate, maxTargetDate, ingestingByDate, ingestingSource, clearing, showClearConfirm,
  dispose, fetchMcpServers, refreshData, goPage, goErrorLogsPage, saveProviderConfig, testProviderConnection, saveSmtpConfig, testSmtpConfig, saveEmailPoolConfig, testEmailPoolConfig, resetMcpForm, editMcpServer, saveMcpServer,
  saveSiteContactPageConfig,
  testMcpServer, deleteMcpServer, ingestSingleSource, generateAllBriefings, clearDashboardCache, syncDataNow,
  ingestByDate, clearAllData,
  editSchedulerConfig, cancelSchedulerConfigEdit, saveSchedulerConfig,
  crawlForm, crawling, crawlPolling, crawlStatus, startGithubCrawl,
  enrichmentStatus, loadingEnrichmentStatus, retryingEnrichment, backfillingEnrichment, cancellingEnrichment, enrichmentConcurrency, enrichmentPolling,
  enrichmentCancelWatching,
  enrichmentReasoningEffort, enrichmentEffectiveReasoningEffort, savingEnrichmentReasoningEffort,
  fetchGithubEnrichmentStatus, saveEnrichmentReasoningEffort, retryFailedEnrichments, backfillPendingEnrichments, cancelEnrichment,
} = useMonitorPageController({ isAdmin: computed(() => authStore.isAdmin) })

const route = useRoute()
const router = useRouter()

// 激活分组：URL ?section= 为单一事实源，非法值白名单回落
const activeSection = ref<MonitorSectionKey>(normalizeMonitorSection(route.query.section))
const isReplacingRoute = ref(false)

// 登录态恢复窗口兜底：非 admin 过滤掉 adminOnly 叶子，空大类整体移除
const visibleSections = computed(() =>
  MONITOR_NAV
    .map(category => ({
      ...category,
      children: category.children.filter(leaf => !leaf.adminOnly || authStore.isAdmin),
    }))
    .filter(category => category.children.length > 0)
)
const currentSection = computed<MonitorSectionKey>(() =>
  visibleSections.value.some(category => category.children.some(leaf => leaf.key === activeSection.value))
    ? activeSection.value
    : DEFAULT_MONITOR_SECTION
)
// 富化失败红点挂「GitHub 富化」叶子，与导航 Dock 红点同源
const navAlertKeys = computed<MonitorSectionKey[]>(() =>
  enrichmentAlert.hasFailures ? ['enrichment'] : []
)

const selectSection = (key: MonitorSectionKey) => { activeSection.value = key }

// 状态 → URL：replace 不刷历史；默认组省略参数保持 URL 干净
watch(activeSection, (section) => {
  if (route.name !== 'monitor') return
  const current = normalizeMonitorSection(route.query.section)
  if (current === section && (section !== DEFAULT_MONITOR_SECTION || !route.query.section)) return
  const query = { ...route.query }
  if (section === DEFAULT_MONITOR_SECTION) delete query.section
  else query.section = section
  isReplacingRoute.value = true
  void router.replace({ query }).finally(() => {
    window.setTimeout(() => { isReplacingRoute.value = false }, 0)
  })
})

// URL → 状态（浏览器前进/后退）：防回环靠标志位 + ref 同值不触发
watch(() => route.query.section, (value) => {
  if (isReplacingRoute.value) return
  activeSection.value = normalizeMonitorSection(value)
})

// 登录态恢复窗口中若判定为非 admin，强制回落默认组
watch(() => authStore.isAdmin, (isAdmin) => {
  if (!isAdmin) activeSection.value = DEFAULT_MONITOR_SECTION
})

// 富化重试轮询结束时同步导航 Dock 的失败红点（失败清零或本轮结束时各刷一次）
watch(enrichmentPolling, (polling, wasPolling) => {
  if (wasPolling && !polling) void enrichmentAlert.refresh()
})

onMounted(refreshData)
// 卸载统一停链：爬取/富化轮询与 delayedRefresh 等一次性延时回调
onUnmounted(dispose)
</script>

<template>
  <div class="monitor-page monitor-view flex h-full min-h-0 flex-col overflow-hidden">
    <div class="flex flex-col gap-5">

    <!-- 页头 -->
    <div class="stagger-enter flex flex-wrap items-center justify-between gap-3 shrink-0">
      <div>
        <h1 class="monitor-title text-2xl font-bold tracking-tight">{{ t('monitor.title') }}</h1>
        <p class="monitor-caption mt-0.5 text-sm">{{ t('monitor.subtitle') }}</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button class="monitor-btn-secondary" :disabled="loading" @click="refreshData">
          <svg class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
          {{ t(loading ? 'common.refreshing' : 'common.refresh') }}
        </button>
        <!-- Admin 专属：同步 / 强制同步 / 清空数据 -->
        <MonitorAdminActionControls
          v-if="authStore.isAdmin"
          v-model:show-clear-confirm="showClearConfirm"
          :syncing="syncing"
          :task-running="isTaskRunning"
          :generating-briefing="generatingBriefing"
          :clearing-cache="clearingCache"
          :clearing="clearing"
          @sync="syncDataNow"
          @generate-briefings="generateAllBriefings"
          @clear-dashboard-cache="clearDashboardCache"
          @clear-all-data="clearAllData"
        />
      </div>
    </div>

    <!-- 消息提示 -->
    <div v-if="errorMsg" class="shrink-0 glass-card monitor-alert-error flex items-center justify-between px-5 py-3 text-sm">
      <span>{{ errorMsg }}</span>
      <button class="ml-3 opacity-70 hover:opacity-100 transition" @click="errorMsg = ''">
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div v-if="successMsg" class="shrink-0 glass-card monitor-alert-success flex items-center justify-between px-5 py-3 text-sm">
      <span>{{ successMsg }}</span>
      <button class="ml-3 opacity-70 hover:opacity-100 transition" @click="successMsg = ''">
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>

    <!-- 二级导航 + 分组面板 -->
    <div class="monitor-body">
      <MonitorSectionNav
        v-if="authStore.isAdmin"
        :sections="visibleSections"
        :active="currentSection"
        :alert-keys="navAlertKeys"
        @select="selectSection"
      />

      <div class="monitor-section-panels">
        <!-- ═══ 监控（非 admin 唯一可见大类） ═══ -->
        <template v-if="currentSection === 'tasks'">
          <MonitorTaskPanel
            :is-admin="authStore.isAdmin"
            :scheduler-status="schedulerStatus"
            :tasks="tasks"
            :total="total"
            :page="page"
            :total-pages="totalPages"
            :loading="loading"
            @go-page="goPage"
          />
        </template>
        <template v-else-if="currentSection === 'mcp-calls'">
          <McpToolCallsPanel
            :snapshot="mcpToolCalls"
            :loading="loading"
          />
        </template>
        <template v-else-if="currentSection === 'errors'">
          <ErrorLogPanel
            v-if="authStore.isAdmin"
            :error-logs="errorLogs"
            :total="errorLogsTotal"
            :page="errorLogsPage"
            :total-pages="errorLogsTotalPages"
            :loading="loading"
            @go-page="goErrorLogsPage"
          />
        </template>

        <!-- ═══ 采集（Admin 专属） ═══ -->
        <template v-else-if="currentSection === 'collect'">
          <MonitorIngestionControls
            v-if="authStore.isAdmin"
            v-model:target-date="targetDate"
            :max-target-date="maxTargetDate"
            :ingesting-by-date="ingestingByDate"
            :ingesting-source="ingestingSource"
            @ingest-by-date="ingestByDate"
            @ingest-source="ingestSingleSource"
          />
        </template>
        <template v-else-if="currentSection === 'crawl'">
          <GithubCrawlControls
            v-if="authStore.isAdmin"
            v-model:form="crawlForm"
            :crawling="crawling"
            :crawl-polling="crawlPolling"
            :crawl-status="crawlStatus"
            @start="startGithubCrawl"
          />
        </template>
        <template v-else-if="currentSection === 'enrichment'">
          <GithubEnrichmentPanel
            v-if="authStore.isAdmin"
            :status="enrichmentStatus"
            :loading="loadingEnrichmentStatus"
            :retrying="retryingEnrichment"
            :backfilling="backfillingEnrichment"
            :cancelling="cancellingEnrichment"
            :cancel-watching="enrichmentCancelWatching"
            :polling="enrichmentPolling"
            :concurrency="enrichmentConcurrency"
            :reasoning-effort="enrichmentReasoningEffort"
            :effective-reasoning-effort="enrichmentEffectiveReasoningEffort"
            :saving-reasoning-effort="savingEnrichmentReasoningEffort"
            @refresh="fetchGithubEnrichmentStatus"
            @retry="retryFailedEnrichments"
            @backfill="backfillPendingEnrichments"
            @cancel="cancelEnrichment"
            @update-concurrency="(value) => (enrichmentConcurrency = value)"
            @update-reasoning-effort="saveEnrichmentReasoningEffort"
          />
        </template>

        <!-- ═══ 账号源（Admin 专属） ═══ -->
        <template v-else-if="currentSection === 'x-watch'">
          <XWatchCard v-if="authStore.isAdmin" />
        </template>
        <template v-else-if="currentSection === 'x-credentials'">
          <XCredentialCard v-if="authStore.isAdmin" />
        </template>
        <template v-else-if="currentSection === 'wechat'">
          <WechatAccountPanel v-if="authStore.isAdmin" />
        </template>

        <!-- ═══ 配置（Admin 专属） ═══ -->
        <template v-else-if="currentSection === 'provider'">
          <ProviderConfigPanel
            v-if="authStore.isAdmin"
            :config="providerConfig"
            :form="providerForm"
            :loading="loadingProviderConfig"
            :saving="savingProviderConfig"
            :testing="testingProvider"
            @save="saveProviderConfig"
            @test="testProviderConnection"
          />
        </template>
        <template v-else-if="currentSection === 'scheduler'">
          <SchedulerConfigPanel
            v-if="authStore.isAdmin"
            :configs="schedulerConfigs"
            :form="schedulerConfigForm"
            :loading="loadingSchedulerConfigs"
            :saving="savingSchedulerConfig"
            :editing-job-id="editingSchedulerJobId"
            @edit="editSchedulerConfig"
            @cancel="cancelSchedulerConfigEdit"
            @save="saveSchedulerConfig"
          />
        </template>
        <template v-else-if="currentSection === 'smtp'">
          <SmtpConfigPanel
            v-if="authStore.isAdmin"
            :config="smtpConfig"
            :form="smtpForm"
            :loading="loadingSmtpConfig"
            :saving="savingSmtpConfig"
            :testing="testingSmtp"
            @save="saveSmtpConfig"
            @test="testSmtpConfig"
          />
          <EmailPoolConfigPanel
            v-if="authStore.isAdmin"
            :config="emailPoolConfig"
            :form="emailPoolForm"
            :loading="loadingEmailPoolConfig"
            :saving="savingEmailPoolConfig"
            :testing="testingEmailPool"
            @save="saveEmailPoolConfig"
            @test="testEmailPoolConfig"
          />
        </template>
        <template v-else-if="currentSection === 'mcp-server'">
          <McpServerConfigPanel
            v-if="authStore.isAdmin"
            v-model:form="mcpForm"
            :servers="mcpServers"
            :loading="loadingMcpServers"
            :saving="savingMcpServer"
            :testing-server-id="testingMcpServerId"
            :deleting-server-id="deletingMcpServerId"
            @refresh="fetchMcpServers"
            @reset="resetMcpForm"
            @edit="editMcpServer"
            @save="saveMcpServer"
            @test="testMcpServer"
            @delete="deleteMcpServer"
          />
        </template>
        <template v-else-if="currentSection === 'contact-page'">
          <SiteContactPageConfigPanel
            v-if="authStore.isAdmin"
            :config="siteContactPageConfig"
            :form="siteContactPageForm"
            :loading="loadingSiteContactPage"
            :saving="savingSiteContactPage"
            @save="saveSiteContactPageConfig"
          />
        </template>
        <template v-else-if="currentSection === 'membership'">
          <MembershipGrantPanel
            v-if="authStore.isAdmin"
            :form="membershipForm"
            :granting="grantingMembership"
            :last-result="membershipLastResult"
            @save="grantMembership"
          />
        </template>
      </div>
    </div>
    </div>
  </div>
</template>

<style scoped>
/* 仅保留页级布局；monitor-* 子面板类契约已上移至 src/style.css 全局层 */
.monitor-page {
  position: relative;
  height: 100%;
  overflow-y: auto;
  padding: 24px 24px 64px;
  color: var(--projects-accent);
  background: var(--projects-paper);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

@media (max-width: 720px) {
  .monitor-page {
    padding: 16px 16px 64px;
  }
}
</style>
