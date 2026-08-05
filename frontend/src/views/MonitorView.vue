<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'
import GithubCrawlControls from '@/components/monitor/GithubCrawlControls.vue'
import McpServerConfigPanel from '@/components/monitor/McpServerConfigPanel.vue'
import McpToolCallsPanel from '@/components/monitor/McpToolCallsPanel.vue'
import MonitorAdminActionControls from '@/components/monitor/MonitorAdminActionControls.vue'
import MonitorIngestionControls from '@/components/monitor/MonitorIngestionControls.vue'
import MonitorTaskPanel from '@/components/monitor/MonitorTaskPanel.vue'
import ProviderConfigPanel from '@/components/monitor/ProviderConfigPanel.vue'
import XCredentialCard from '@/components/monitor/XCredentialCard.vue'
import XWatchCard from '@/components/monitor/XWatchCard.vue'
import WechatAccountPanel from '@/components/wechat/WechatAccountPanel.vue'
import { useMonitorPageController } from '@/composables/useMonitorPageController'

const { t } = useI18n()
const authStore = useAuthStore()
const {
  tasks, total, page, schedulerStatus, mcpToolCalls, loading, errorMsg, successMsg, providerConfig, providerForm,
  loadingProviderConfig, savingProviderConfig, mcpServers, mcpForm, loadingMcpServers, savingMcpServer,
  testingMcpServerId, deletingMcpServerId, isTaskRunning, totalPages, syncing, generatingBriefing,
  clearingCache, targetDate, maxTargetDate, ingestingByDate, ingestingSource, clearing, showClearConfirm,
  fetchMcpServers, refreshData, goPage, saveProviderConfig, resetMcpForm, editMcpServer, saveMcpServer,
  testMcpServer, deleteMcpServer, ingestSingleSource, generateAllBriefings, clearDashboardCache, syncDataNow,
  ingestByDate, clearAllData,
  crawlForm, crawling, crawlPolling, crawlStatus, startGithubCrawl,
} = useMonitorPageController({ isAdmin: computed(() => authStore.isAdmin) })

onMounted(refreshData)
</script>

<template>
  <div class="monitor-page monitor-view flex h-full min-h-0 flex-col overflow-hidden">
    <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6 pb-24">

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
      @save="saveProviderConfig"
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
.monitor-page {
  position: relative;
  height: 100%;
  overflow-y: auto;
  padding: 24px 24px 96px;
  color: var(--projects-accent);
  background: var(--projects-paper);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

@media (max-width: 720px) {
  .monitor-page {
    padding: 16px 16px 96px;
  }
}

/* 外层卡片统一为项目库风格 */
.monitor-page :deep(.glass-card) {
  border: 1px solid var(--projects-accent);
  border-radius: 6px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 var(--shadow-hard);
  backdrop-filter: none;
  color: var(--projects-accent);
}

/* 标题层级 */
.monitor-page :deep(.monitor-title) {
  color: var(--projects-accent);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  font-weight: 900;
  letter-spacing: -0.03em;
}

.monitor-page :deep(.monitor-section-title) {
  color: var(--projects-accent);
  font-weight: 800;
}

.monitor-page :deep(.monitor-caption) {
  color: var(--ink-muted);
}

/* 内层 surface（表单面板、列表面板） */
.monitor-page :deep(.monitor-surface) {
  border: 1px solid var(--projects-accent);
  border-radius: 6px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 var(--shadow-hard);
}

.monitor-page :deep(.monitor-surface-dim) {
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: var(--paper-muted);
}

/* 按钮家族 */
.monitor-page :deep(.monitor-btn) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  border-radius: 4px;
  border: 1px solid var(--projects-accent);
  color: var(--projects-accent);
  background: var(--projects-paper-light);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease, color 150ms ease;
}

.monitor-page :deep(.monitor-btn:hover:not(:disabled)) {
  background: var(--acid-soft);
  color: var(--ink);
  transform: translate(-1px, -1px);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.monitor-page :deep(.monitor-btn:disabled) {
  cursor: not-allowed;
  opacity: 0.4;
}

.monitor-page :deep(.monitor-btn-primary) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  border-radius: 4px;
  border: 1px solid var(--projects-accent);
  color: var(--projects-on-acid);
  background: var(--projects-acid);
  box-shadow: 3px 3px 0 var(--shadow-hard);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease;
}

.monitor-page :deep(.monitor-btn-primary:hover:not(:disabled)) {
  background: var(--acid-strong);
  transform: translate(-1px, -1px);
}

.monitor-page :deep(.monitor-btn-primary:disabled) {
  cursor: not-allowed;
  opacity: 0.4;
}

.monitor-page :deep(.monitor-btn-secondary) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  border-radius: 4px;
  border: 1px solid var(--projects-accent);
  color: var(--projects-accent);
  background: var(--projects-paper-light);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease, color 150ms ease;
}

.monitor-page :deep(.monitor-btn-secondary:hover:not(:disabled)) {
  background: var(--acid-soft);
  color: var(--ink);
  transform: translate(-1px, -1px);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.monitor-page :deep(.monitor-btn-secondary:disabled) {
  cursor: not-allowed;
  opacity: 0.4;
}

.monitor-page :deep(.monitor-btn-danger) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  border-radius: 4px;
  border: 1px solid var(--danger-strong);
  color: var(--danger-ink);
  background: var(--danger);
  box-shadow: 3px 3px 0 var(--shadow-hard);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease;
}

.monitor-page :deep(.monitor-btn-danger:hover:not(:disabled)) {
  background: var(--danger-strong);
  transform: translate(-1px, -1px);
}

.monitor-page :deep(.monitor-btn-danger:disabled) {
  cursor: not-allowed;
  opacity: 0.4;
}

.monitor-page :deep(.monitor-btn-ghost) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  border-radius: 4px;
  border: 1px solid transparent;
  color: var(--ink-muted);
  background: transparent;
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease, color 150ms ease, border-color 150ms ease;
}

.monitor-page :deep(.monitor-btn-ghost:hover:not(:disabled)) {
  background: var(--acid-soft);
  color: var(--ink);
  border-color: var(--projects-accent);
  transform: translate(-1px, -1px);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.monitor-page :deep(.monitor-btn-ghost:disabled) {
  cursor: not-allowed;
  opacity: 0.4;
}

/* 徽章 */
.monitor-page :deep(.monitor-badge) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.4;
  border-radius: 4px;
  border: 1px solid var(--projects-accent);
  color: var(--ink-muted);
  background: var(--projects-paper-light);
}

/* 状态徽章 */
.monitor-page :deep(.monitor-status-success) {
  color: var(--success-ink);
  background: var(--success-bg);
  border-color: var(--success-border);
}

.monitor-page :deep(.monitor-status-error) {
  color: var(--error-ink);
  background: var(--error-bg);
  border-color: var(--error-accent);
}

.monitor-page :deep(.monitor-status-running) {
  color: var(--tech-primary);
  background: rgb(var(--tech-primary-rgb) / 0.12);
  border-color: rgb(var(--tech-primary-rgb) / 0.3);
}

.monitor-page :deep(.monitor-status-unknown) {
  color: var(--ink-muted);
  background: var(--paper-muted);
  border-color: var(--rule);
}

.monitor-page :deep(.monitor-status-dot-success) { background: var(--success-ink); }
.monitor-page :deep(.monitor-status-dot-error) { background: var(--error-accent); }
.monitor-page :deep(.monitor-status-dot-running) { background: var(--tech-primary); }
.monitor-page :deep(.monitor-status-dot-unknown) { background: var(--ink-muted); }

/* 顶部提示条 */
.monitor-page :deep(.monitor-alert-success) {
  color: var(--success-ink);
  background: var(--success-bg-strong);
  border-left-width: 3px;
  border-left-color: var(--success-ink);
}

.monitor-page :deep(.monitor-alert-error) {
  color: var(--error-ink);
  background: var(--error-bg-strong);
  border-left-width: 3px;
  border-left-color: var(--error-accent);
}

/* 来源按钮 */
.monitor-page :deep(.monitor-source-btn) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  border-radius: 4px;
  border: 1px solid var(--projects-accent);
  color: var(--projects-accent);
  background: var(--projects-paper-light);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease, color 150ms ease;
}

.monitor-page :deep(.monitor-source-btn:hover:not(:disabled)) {
  background: var(--acid-soft);
  transform: translate(-1px, -1px);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.monitor-page :deep(.monitor-source-btn.active) {
  color: var(--projects-on-acid);
  background: var(--projects-acid);
  box-shadow: 3px 3px 0 var(--shadow-hard);
}

.monitor-page :deep(.monitor-source-btn:disabled) {
  cursor: not-allowed;
  opacity: 0.4;
}

/* 表格 */
.monitor-page :deep(.monitor-table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.monitor-page :deep(.monitor-table thead) {
  background: var(--paper-muted);
}

.monitor-page :deep(.monitor-table th) {
  padding: 10px 16px;
  text-align: left;
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-muted);
  border-bottom: 1px solid var(--rule);
}

.monitor-page :deep(.monitor-table td) {
  padding: 12px 16px;
  color: var(--ink-secondary);
  border-bottom: 1px solid rgb(var(--stone-400-rgb) / 0.15);
}

.monitor-page :deep(.monitor-table tbody tr:hover) {
  background: var(--acid-soft);
}

.monitor-page :deep(.monitor-table tbody tr:nth-child(even)) {
  background: rgb(var(--card-rgb) / 0.35);
}

.monitor-page :deep(.monitor-table tbody tr:nth-child(even):hover) {
  background: var(--acid-soft);
}

/* 分页 */
.monitor-page :deep(.monitor-pagination-btn) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  padding: 5px 9px;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  border-radius: 4px;
  border: 1px solid var(--projects-accent);
  color: var(--projects-accent);
  background: var(--projects-paper-light);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease, color 150ms ease;
}

.monitor-page :deep(.monitor-pagination-btn:hover:not(:disabled)) {
  background: var(--acid-soft);
  transform: translate(-1px, -1px);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.monitor-page :deep(.monitor-pagination-btn.active) {
  color: var(--projects-on-acid);
  background: var(--projects-acid);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.monitor-page :deep(.monitor-pagination-btn:disabled) {
  cursor: not-allowed;
  opacity: 0.3;
}

/* Modal */
.monitor-page :deep(.monitor-modal-backdrop) {
  background: rgba(var(--chat-shadow-rgb) / 0.18);
  backdrop-filter: blur(2px);
}

.monitor-page :deep(.monitor-modal) {
  background: var(--projects-paper-light);
  border: 1px solid var(--projects-accent);
  border-radius: 6px;
  box-shadow: 6px 6px 0 var(--shadow-hard);
}

.monitor-page :deep(.monitor-warning-box) {
  color: var(--error-ink);
  background: var(--error-bg);
  border: 1px solid var(--error-accent);
  border-radius: 4px;
}

/* 表单内部 checkbox/radio 标签区 */
.monitor-page :deep(.monitor-check-row) {
  border: 1px solid var(--rule);
  background: var(--paper-muted);
  border-radius: 6px;
}

/* loading spinner */
.monitor-page :deep(.monitor-spinner) {
  border-color: var(--rule);
  border-top-color: var(--ink-secondary);
}

/* 大背景水印字 */
.monitor-page :deep(.monitor-watermark) {
  color: rgb(var(--stone-400-rgb) / 0.18);
}

/* 头像/initials */
.monitor-page :deep(.monitor-avatar) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--projects-accent);
  border-radius: 6px;
  background: var(--paper-raised);
  color: var(--projects-accent);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.monitor-page :deep(.monitor-avatar-accent) {
  background: var(--projects-acid);
  color: var(--projects-on-acid);
}

/* 输入框在项目纸面上的 focus */
.monitor-page :deep(.input) {
  color: var(--ink);
  background: var(--projects-paper-light);
  border-color: var(--projects-accent);
}

.monitor-page :deep(.input:focus) {
  background: var(--projects-paper-light);
  border-color: var(--projects-accent);
  box-shadow: 3px 3px 0 var(--shadow-hard);
}

/* 空状态虚线框 */
.monitor-page :deep(.monitor-empty) {
  border: 1px dashed var(--rule);
  background: rgb(var(--card-rgb) / 0.3);
  color: var(--ink-muted);
}

/* 分隔线 */
.monitor-page :deep(.monitor-divider) {
  border-color: var(--rule);
}

@media (prefers-reduced-motion: reduce) {
  .monitor-page :deep(*),
  .monitor-page :deep(*::before),
  .monitor-page :deep(*::after) {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
</style>
