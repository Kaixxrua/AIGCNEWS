<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'
import { useEnrichmentAlertStore } from '@/stores/enrichmentAlertStore'
import GithubCrawlControls from '@/components/monitor/GithubCrawlControls.vue'
import GithubEnrichmentPanel from '@/components/monitor/GithubEnrichmentPanel.vue'
import McpServerConfigPanel from '@/components/monitor/McpServerConfigPanel.vue'
import McpToolCallsPanel from '@/components/monitor/McpToolCallsPanel.vue'
import MonitorAdminActionControls from '@/components/monitor/MonitorAdminActionControls.vue'
import MonitorIngestionControls from '@/components/monitor/MonitorIngestionControls.vue'
import MonitorTaskPanel from '@/components/monitor/MonitorTaskPanel.vue'
import ProviderConfigPanel from '@/components/monitor/ProviderConfigPanel.vue'
import SchedulerConfigPanel from '@/components/monitor/SchedulerConfigPanel.vue'
import XCredentialCard from '@/components/monitor/XCredentialCard.vue'
import XWatchCard from '@/components/monitor/XWatchCard.vue'
import WechatAccountPanel from '@/components/wechat/WechatAccountPanel.vue'
import { useMonitorPageController } from '@/composables/useMonitorPageController'

const { t } = useI18n()
const authStore = useAuthStore()
const enrichmentAlert = useEnrichmentAlertStore()
const {
  tasks, total, page, schedulerStatus, schedulerConfigs, schedulerConfigForm, loadingSchedulerConfigs, savingSchedulerConfig, editingSchedulerJobId, mcpToolCalls, loading, errorMsg, successMsg, providerConfig, providerForm,
  loadingProviderConfig, savingProviderConfig, testingProvider, mcpServers, mcpForm, loadingMcpServers, savingMcpServer,
  testingMcpServerId, deletingMcpServerId, isTaskRunning, totalPages, syncing, generatingBriefing,
  clearingCache, targetDate, maxTargetDate, ingestingByDate, ingestingSource, clearing, showClearConfirm,
  fetchMcpServers, refreshData, goPage, saveProviderConfig, testProviderConnection, resetMcpForm, editMcpServer, saveMcpServer,
  testMcpServer, deleteMcpServer, ingestSingleSource, generateAllBriefings, clearDashboardCache, syncDataNow,
  ingestByDate, clearAllData,
  editSchedulerConfig, cancelSchedulerConfigEdit, saveSchedulerConfig,
  crawlForm, crawling, crawlPolling, crawlStatus, startGithubCrawl,
  enrichmentStatus, loadingEnrichmentStatus, retryingEnrichment, backfillingEnrichment, cancellingEnrichment, enrichmentConcurrency, enrichmentPolling,
  enrichmentCancelWatching,
  enrichmentReasoningEffort, enrichmentEffectiveReasoningEffort, savingEnrichmentReasoningEffort,
  fetchGithubEnrichmentStatus, saveEnrichmentReasoningEffort, retryFailedEnrichments, backfillPendingEnrichments, cancelEnrichment,
} = useMonitorPageController({ isAdmin: computed(() => authStore.isAdmin) })

// 富化重试轮询结束时同步导航 Dock 的失败红点（失败清零或本轮结束时各刷一次）
watch(enrichmentPolling, (polling, wasPolling) => {
  if (wasPolling && !polling) void enrichmentAlert.refresh()
})

onMounted(refreshData)
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

    <!-- Admin 专属：模型服务配置 -->
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

    <!-- Admin 专属：定时任务配置 -->
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

    <!-- Admin 专属：MCP Server 配置 -->
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

    <!-- Admin 专属：X 关注账号 -->
    <XWatchCard v-if="authStore.isAdmin" />

    <!-- Admin 专属：X 账号凭证 -->
    <XCredentialCard v-if="authStore.isAdmin" />

    <!-- Admin 专属：微信公众号 -->
    <WechatAccountPanel v-if="authStore.isAdmin" />

    <!-- Admin 专属：采集控制 -->
    <MonitorIngestionControls
      v-if="authStore.isAdmin"
      v-model:target-date="targetDate"
      :max-target-date="maxTargetDate"
      :ingesting-by-date="ingestingByDate"
      :ingesting-source="ingestingSource"
      @ingest-by-date="ingestByDate"
      @ingest-source="ingestSingleSource"
    />

    <!-- Admin 专属：GitHub 搜索爬取 -->
    <GithubCrawlControls
      v-if="authStore.isAdmin"
      v-model:form="crawlForm"
      :crawling="crawling"
      :crawl-polling="crawlPolling"
      :crawl-status="crawlStatus"
      @start="startGithubCrawl"
    />

    <!-- Admin 专属：GitHub 项目库富化（失败重试与积压补跑入口） -->
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

    <McpToolCallsPanel
      :snapshot="mcpToolCalls"
      :loading="loading"
    />

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
