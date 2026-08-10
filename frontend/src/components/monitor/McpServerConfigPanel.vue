<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import {
  MCP_TEST_SCOPE,
  formatDate,
  getMcpAuthPresentation,
  getMcpServerInitial,
  getMcpTransportPresentation,
  getStatusConfig,
  type McpServerConfig,
  type McpServerForm,
} from '@/features/monitor/monitorViewModel'

const { t } = useI18n()

const props = defineProps<{
  servers: McpServerConfig[]
  form: McpServerForm
  loading: boolean
  saving: boolean
  testingServerId: number | null
  deletingServerId: number | null
}>()

const emit = defineEmits<{
  'update:form': [form: McpServerForm]
  refresh: []
  reset: []
  edit: [server: McpServerConfig]
  save: []
  test: [server: McpServerConfig]
  delete: [server: McpServerConfig]
}>()

const formMode = computed(() => (props.form.id ? 'edit' : 'create'))

const updateForm = <K extends keyof McpServerForm>(field: K, value: McpServerForm[K]) => {
  emit('update:form', { ...props.form, [field]: value })
}
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 overflow-hidden p-0" style="animation-delay: 0.1s">
    <div class="monitor-divider relative border-b p-5">
      <div class="pointer-events-none absolute right-6 top-4 hidden font-mono text-[52px] font-black leading-none monitor-watermark md:block">MCP</div>
      <div class="relative flex flex-wrap items-start justify-between gap-3">
        <div class="max-w-3xl">
          <div class="flex flex-wrap items-center gap-2">
            <span class="monitor-avatar monitor-avatar-accent flex h-8 w-8 items-center justify-center text-sm shadow-sm">
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></svg>
            </span>
            <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.mcpTitle') }}</h3>
            <span class="monitor-badge">{{ t('monitor.mcpCount', { count: servers.length }) }}</span>
            <span class="monitor-badge monitor-status-running">Streamable HTTP</span>
          </div>
          <p class="monitor-caption mt-2 text-xs leading-5">{{ t('monitor.mcpDescription') }}</p>
          <div class="mt-3 flex flex-wrap gap-2">
            <span v-for="item in MCP_TEST_SCOPE" :key="item.title" class="monitor-badge">
              <span class="font-mono text-[var(--tech-primary)]">{{ item.title }}</span>
              <span class="monitor-caption">{{ t(`monitor.mcpTestScope.${item.descriptionKey}`) }}</span>
            </span>
          </div>
        </div>
        <button class="monitor-btn-secondary" :disabled="loading" @click="emit('refresh')">
          <span class="inline-block h-3 w-3 rounded-full border-2 border-current border-t-transparent" :class="loading ? 'animate-spin' : ''" />
          {{ t('monitor.refreshMcp') }}
        </button>
      </div>
    </div>

    <div class="grid gap-4 p-5 xl:grid-cols-[minmax(320px,0.95fr)_minmax(420px,1.25fr)]">
      <div class="monitor-surface p-4">
        <div class="mb-3 flex items-start justify-between gap-2">
          <div>
            <h4 class="text-xs font-semibold uppercase tracking-widest monitor-caption">{{ t(formMode === 'edit' ? 'monitor.editServer' : 'monitor.addServer') }}</h4>
            <p class="mt-1 text-2xs monitor-caption">{{ t('monitor.keyHint') }}</p>
          </div>
          <button v-if="formMode === 'edit'" class="monitor-btn-ghost" @click="emit('reset')">{{ t('monitor.cancelEdit') }}</button>
        </div>
        <div class="space-y-3">
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label class="block">
              <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.identifier') }}</span>
              <input :value="form.server_key" class="input w-full py-2 text-xs font-mono" placeholder="github" autocomplete="off" @input="updateForm('server_key', ($event.target as HTMLInputElement).value.trim())" />
            </label>
            <label class="block">
              <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.displayName') }}</span>
              <input :value="form.display_name" class="input w-full py-2 text-xs" placeholder="GitHub MCP" autocomplete="off" @input="updateForm('display_name', ($event.target as HTMLInputElement).value.trim())" />
            </label>
          </div>
          <label class="block">
            <span class="mb-1 block text-xs monitor-caption">Server URL</span>
            <input :value="form.url" type="url" class="input w-full py-2 text-xs font-mono" placeholder="https://example.com/mcp" autocomplete="off" @input="updateForm('url', ($event.target as HTMLInputElement).value.trim())" />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.description') }}</span>
            <textarea :value="form.description" class="input min-h-[82px] py-2 text-xs" :placeholder="t('monitor.descriptionPlaceholder')" @input="updateForm('description', ($event.target as HTMLTextAreaElement).value.trim())" />
          </label>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-[150px_minmax(0,1fr)]">
            <label class="block">
              <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.auth') }}</span>
              <select :value="form.auth_type" class="input w-full py-2 text-xs" @change="updateForm('auth_type', ($event.target as HTMLSelectElement).value as McpServerForm['auth_type'])">
                <option value="none">{{ t('monitor.noAuth') }}</option>
                <option value="bearer">Bearer Token</option>
              </select>
            </label>
            <label class="block">
              <span class="mb-1 flex items-center justify-between text-xs monitor-caption">
                <span>Token</span>
                <span v-if="form.auth_type === 'bearer'" class="text-2xs monitor-caption">{{ t('monitor.tokenWriteOnly') }}</span>
              </span>
              <input :value="form.auth_token" type="password" class="input w-full py-2 text-xs" :disabled="form.auth_type === 'none'" :placeholder="t('monitor.retainToken')" autocomplete="new-password" @input="updateForm('auth_token', ($event.target as HTMLInputElement).value)" />
            </label>
          </div>
          <div class="monitor-check-row px-3 py-2">
            <div class="flex flex-wrap items-center gap-3 text-xs monitor-caption">
              <label class="inline-flex items-center gap-1.5">
                <input :checked="form.enabled" type="checkbox" class="rounded" @change="updateForm('enabled', ($event.target as HTMLInputElement).checked)" />
                {{ t('monitor.enabled') }}
              </label>
              <label v-if="formMode === 'edit'" class="inline-flex items-center gap-1.5">
                <input :checked="form.clear_auth_token" type="checkbox" class="rounded" :disabled="form.auth_type === 'none'" @change="updateForm('clear_auth_token', ($event.target as HTMLInputElement).checked)" />
                {{ t('monitor.clearToken') }}
              </label>
            </div>
            <p class="mt-1 text-2xs monitor-caption">{{ t('monitor.tokenHint') }}</p>
          </div>
          <button class="monitor-btn-primary w-full" :disabled="saving" @click="emit('save')">
            {{ t(saving ? 'monitor.saving' : formMode === 'edit' ? 'monitor.saveServer' : 'monitor.createServer') }}
          </button>
        </div>
      </div>

      <div class="monitor-surface flex min-h-[260px] flex-col p-4">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h4 class="text-xs font-semibold uppercase tracking-widest monitor-caption">Server Registry</h4>
            <p class="mt-1 text-2xs monitor-caption">{{ t('monitor.registryHint') }}</p>
          </div>
          <span v-if="loading && servers.length" class="inline-flex items-center gap-1 text-2xs monitor-caption">
            <span class="inline-block h-3 w-3 rounded-full border-2 border-current border-t-transparent animate-spin" />{{ t('monitor.synchronizing') }}
          </span>
        </div>
        <SpinnerLoader v-if="loading && !servers.length" class="flex-1 min-h-[180px]" />
        <div v-else-if="!servers.length" class="monitor-empty flex flex-1 min-h-[180px] flex-col items-center justify-center rounded-md text-center text-sm">
          <p class="font-medium">{{ t('monitor.emptyServers') }}</p>
          <p class="mt-1 text-xs">{{ t('monitor.emptyServersHint') }}</p>
        </div>
        <div v-else class="space-y-3">
          <div v-for="server in servers" :key="server.id" class="monitor-surface p-3 transition hover:-translate-y-0.5">
            <div class="flex flex-wrap items-start gap-3">
              <div class="monitor-avatar monitor-avatar-accent flex h-10 w-10 shrink-0 text-base">
                {{ getMcpServerInitial(server) }}
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <p class="truncate text-sm font-semibold">{{ server.display_name }}</p>
                  <span class="badge" :class="[getStatusConfig(server.last_test_status).bg]">
                    <span class="status-dot" :class="getStatusConfig(server.last_test_status).dot" />
                    {{ getStatusConfig(server.last_test_status).labelKey ? t(`monitor.${getStatusConfig(server.last_test_status).labelKey}`) : getStatusConfig(server.last_test_status).rawLabel }}
                  </span>
                  <span v-if="!server.enabled" class="monitor-badge">{{ t('monitor.disabled') }}</span>
                  <span v-if="server.auth_token_configured" class="badge monitor-status-success">Token: {{ server.auth_token_masked }}</span>
                </div>
                <p class="mt-1 truncate font-mono text-2xs monitor-caption">{{ server.server_key }} · {{ server.url }}</p>
                <div class="mt-2 flex flex-wrap gap-1.5 text-2xs">
                  <span class="monitor-badge">{{ getMcpTransportPresentation(server.transport).labelKey ? t(`monitor.${getMcpTransportPresentation(server.transport).labelKey}`) : getMcpTransportPresentation(server.transport).label }}</span>
                  <span class="monitor-badge">{{ getMcpAuthPresentation(server.auth_type).labelKey ? t(`monitor.${getMcpAuthPresentation(server.auth_type).labelKey}`) : getMcpAuthPresentation(server.auth_type).label }}</span>
                  <span class="monitor-badge">{{ t('monitor.tools', { count: server.tools?.length || 0 }) }}</span>
                  <span v-if="server.last_test_at" class="monitor-badge">{{ formatDate(server.last_test_at) }}</span>
                </div>
                <p v-if="server.description" class="mt-2 line-clamp-2 text-xs leading-5 monitor-caption">{{ server.description }}</p>
              </div>
              <div class="flex shrink-0 flex-wrap gap-1.5">
                <button class="monitor-btn-ghost" @click="emit('edit', server)">{{ t('common.edit') }}</button>
                <button
                  class="monitor-btn-secondary"
                  :disabled="!!testingServerId || !server.enabled"
                  :title="t(server.enabled ? 'monitor.testEnabledTitle' : 'monitor.testDisabledTitle')"
                  @click="emit('test', server)"
                >
                  {{ t(testingServerId === server.id ? 'monitor.testing' : 'monitor.test') }}
                </button>
                <button class="monitor-btn-danger" :disabled="!!deletingServerId" @click="emit('delete', server)">{{ t('common.delete') }}</button>
              </div>
            </div>
            <div v-if="server.last_test_message" class="mt-3 border px-3 py-2 text-xs leading-5 rounded-md" :class="server.last_test_status === 'success' ? 'monitor-status-success' : 'monitor-status-error'">
              {{ server.last_test_message }}
              <span v-if="server.last_test_at" class="ml-1 opacity-70">· {{ formatDate(server.last_test_at) }}</span>
            </div>
            <div v-if="server.tools?.length" class="mt-3 flex flex-wrap gap-1.5">
              <span v-for="tool in server.tools" :key="`${server.id}-${tool.name}`" class="monitor-badge" :title="tool.description || tool.name">{{ tool.name }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
