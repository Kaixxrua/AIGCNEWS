<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/authStore'
import McpServerConfigPanel from '../components/monitor/McpServerConfigPanel.vue'
import MonitorAdminActionControls from '../components/monitor/MonitorAdminActionControls.vue'
import MonitorIngestionControls from '../components/monitor/MonitorIngestionControls.vue'
import MonitorTaskPanel from '../components/monitor/MonitorTaskPanel.vue'
import ProviderConfigPanel from '../components/monitor/ProviderConfigPanel.vue'
import { useMonitorPageController } from '../composables/useMonitorPageController'

const { t } = useI18n()
const authStore = useAuthStore()
const {
  tasks, total, page, schedulerStatus, loading, errorMsg, successMsg, providerConfig, providerForm,
  loadingProviderConfig, savingProviderConfig, mcpServers, mcpForm, loadingMcpServers, savingMcpServer,
  testingMcpServerId, deletingMcpServerId, isTaskRunning, totalPages, syncing, generatingBriefing,
  clearingCache, targetDate, maxTargetDate, ingestingByDate, ingestingSource, clearing, showClearConfirm,
  fetchMcpServers, refreshData, goPage, saveProviderConfig, resetMcpForm, editMcpServer, saveMcpServer,
  testMcpServer, deleteMcpServer, ingestSingleSource, generateAllBriefings, clearDashboardCache, syncDataNow,
  ingestByDate, clearAllData,
} = useMonitorPageController({ isAdmin: computed(() => authStore.isAdmin) })

onMounted(refreshData)
</script>

<template>
  <div class="monitor-view flex h-full min-h-0 flex-col overflow-hidden">
    <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6 pb-24">

    <!-- 页头 -->
    <div class="stagger-enter flex flex-wrap items-center justify-between gap-3 shrink-0">
      <div>
        <h1 class="text-2xl font-bold text-stone-800 tracking-tight font-serif">{{ t('monitor.title') }}</h1>
        <p class="mt-0.5 text-sm text-stone-400">{{ t('monitor.subtitle') }}</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button class="btn-secondary" :disabled="loading" @click="refreshData">
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
    <div v-if="errorMsg" class="shrink-0 glass-card flex items-center justify-between px-5 py-3 text-sm text-rose-600">
      <span>{{ errorMsg }}</span>
      <button class="ml-3 text-rose-400 hover:text-rose-600 transition" @click="errorMsg = ''">
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div v-if="successMsg" class="shrink-0 glass-card flex items-center justify-between px-5 py-3 text-sm text-green-700">
      <span>{{ successMsg }}</span>
      <button class="ml-3 text-green-400 hover:text-green-600 transition" @click="successMsg = ''">
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
