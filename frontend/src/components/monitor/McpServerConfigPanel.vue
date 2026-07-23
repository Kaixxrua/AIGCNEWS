<script setup lang="ts">
import { computed } from 'vue'
import {
  MCP_TEST_SCOPE,
  formatDate,
  getMcpAuthLabel,
  getMcpServerInitial,
  getMcpTransportLabel,
  getStatusConfig,
  type McpServerConfig,
  type McpServerForm,
} from '../../features/monitor/monitorViewModel'

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
    <div class="relative border-b border-stone-200/60 bg-gradient-to-br from-white/80 via-cyan-50/35 to-stone-50/70 p-5">
      <div class="pointer-events-none absolute right-6 top-4 hidden font-mono text-[52px] font-black leading-none text-cyan-100/70 md:block">MCP</div>
      <div class="relative flex flex-wrap items-start justify-between gap-3">
        <div class="max-w-3xl">
          <div class="flex flex-wrap items-center gap-2">
            <span class="flex h-8 w-8 items-center justify-center rounded-2xl border border-cyan-100 bg-white/80 text-cyan-700 shadow-sm">
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></svg>
            </span>
            <h3 class="text-sm font-semibold text-stone-700">MCP Server 集成</h3>
            <span class="badge border border-stone-200 bg-white/80 text-stone-500">{{ servers.length }} 个配置</span>
            <span class="badge border border-cyan-100 bg-cyan-50 text-cyan-700">Streamable HTTP</span>
          </div>
          <p class="mt-2 text-xs leading-5 text-stone-500">集中保存外部 MCP Server 连接信息，用于后续工具发现与智能工作流接入。当前仅支持 HTTP / Streamable HTTP；测试流程只做握手与工具清单读取，不执行任意工具。</p>
          <div class="mt-3 flex flex-wrap gap-2">
            <span v-for="item in MCP_TEST_SCOPE" :key="item.title" class="rounded-full border border-white/80 bg-white/70 px-3 py-1 text-2xs text-stone-500 shadow-sm">
              <span class="font-mono text-cyan-700">{{ item.title }}</span>
              <span class="ml-1 text-stone-400">{{ item.description }}</span>
            </span>
          </div>
        </div>
        <button class="btn-secondary px-3.5 py-2 text-xs" :disabled="loading" @click="emit('refresh')">
          <span class="inline-block h-3 w-3 rounded-full border-2 border-stone-200 border-t-stone-500" :class="loading ? 'animate-spin' : ''" />
          刷新 MCP
        </button>
      </div>
    </div>

    <div class="grid gap-4 p-5 xl:grid-cols-[minmax(320px,0.95fr)_minmax(420px,1.25fr)]">
      <div class="rounded-[22px] border border-stone-200/70 bg-white/60 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
        <div class="mb-3 flex items-start justify-between gap-2">
          <div>
            <h4 class="text-xs font-semibold uppercase tracking-widest text-stone-400">{{ formMode === 'edit' ? '编辑 Server' : '新增 Server' }}</h4>
            <p class="mt-1 text-2xs text-stone-400">Key 会自动按后端规则规范为小写字母、数字、下划线或短横线。</p>
          </div>
          <button v-if="formMode === 'edit'" class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-medium text-stone-400 hover:text-stone-700" @click="emit('reset')">取消编辑</button>
        </div>
        <div class="space-y-3">
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label class="block">
              <span class="mb-1 block text-xs text-stone-400">标识 Key</span>
              <input :value="form.server_key" class="input w-full py-2 text-xs font-mono" placeholder="github" autocomplete="off" @input="updateForm('server_key', ($event.target as HTMLInputElement).value.trim())" />
            </label>
            <label class="block">
              <span class="mb-1 block text-xs text-stone-400">显示名称</span>
              <input :value="form.display_name" class="input w-full py-2 text-xs" placeholder="GitHub MCP" autocomplete="off" @input="updateForm('display_name', ($event.target as HTMLInputElement).value.trim())" />
            </label>
          </div>
          <label class="block">
            <span class="mb-1 block text-xs text-stone-400">Server URL</span>
            <input :value="form.url" type="url" class="input w-full py-2 text-xs font-mono" placeholder="https://example.com/mcp" autocomplete="off" @input="updateForm('url', ($event.target as HTMLInputElement).value.trim())" />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs text-stone-400">说明</span>
            <textarea :value="form.description" class="input min-h-[82px] rounded-[18px] py-2 text-xs" placeholder="这个 MCP Server 提供哪些工具 / 适合什么场景" @input="updateForm('description', ($event.target as HTMLTextAreaElement).value.trim())" />
          </label>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-[150px_minmax(0,1fr)]">
            <label class="block">
              <span class="mb-1 block text-xs text-stone-400">鉴权方式</span>
              <select :value="form.auth_type" class="input w-full py-2 text-xs" @change="updateForm('auth_type', ($event.target as HTMLSelectElement).value as McpServerForm['auth_type'])">
                <option value="none">无需鉴权</option>
                <option value="bearer">Bearer Token</option>
              </select>
            </label>
            <label class="block">
              <span class="mb-1 flex items-center justify-between text-xs text-stone-400">
                <span>Token</span>
                <span v-if="form.auth_type === 'bearer'" class="text-2xs text-stone-300">只写入，不回显</span>
              </span>
              <input :value="form.auth_token" type="password" class="input w-full py-2 text-xs" :disabled="form.auth_type === 'none'" placeholder="留空则保留当前 Token" autocomplete="new-password" @input="updateForm('auth_token', ($event.target as HTMLInputElement).value)" />
            </label>
          </div>
          <div class="rounded-2xl border border-stone-200/70 bg-stone-50/70 px-3 py-2">
            <div class="flex flex-wrap items-center gap-3 text-xs text-stone-500">
              <label class="inline-flex items-center gap-1.5">
                <input :checked="form.enabled" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" @change="updateForm('enabled', ($event.target as HTMLInputElement).checked)" />
                启用此 Server
              </label>
              <label v-if="formMode === 'edit'" class="inline-flex items-center gap-1.5">
                <input :checked="form.clear_auth_token" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" :disabled="form.auth_type === 'none'" @change="updateForm('clear_auth_token', ($event.target as HTMLInputElement).checked)" />
                清空当前 Token
              </label>
            </div>
            <p class="mt-1 text-2xs text-stone-400">Bearer Token 会以密文形式保存；列表中仅显示脱敏值。</p>
          </div>
          <button class="btn-primary w-full justify-center" :disabled="saving" @click="emit('save')">
            {{ saving ? '保存中…' : formMode === 'edit' ? '保存 MCP Server' : '新增 MCP Server' }}
          </button>
        </div>
      </div>

      <div class="min-h-[260px] rounded-[22px] border border-stone-200/70 bg-white/45 p-4">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h4 class="text-xs font-semibold uppercase tracking-widest text-stone-400">Server Registry</h4>
            <p class="mt-1 text-2xs text-stone-400">测试成功后会缓存最多 20 个工具名称与描述。</p>
          </div>
          <span v-if="loading && servers.length" class="inline-flex items-center gap-1 text-2xs text-stone-400">
            <span class="inline-block h-3 w-3 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />同步中
          </span>
        </div>
        <div v-if="loading && !servers.length" class="flex h-full min-h-[180px] items-center justify-center gap-2 text-sm text-stone-400">
          <span class="inline-block h-4 w-4 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />加载 MCP Server…
        </div>
        <div v-else-if="!servers.length" class="flex h-full min-h-[180px] flex-col items-center justify-center rounded-[18px] border border-dashed border-stone-200 bg-white/55 text-center text-sm text-stone-400">
          <p class="font-medium text-stone-500">暂无 MCP Server 配置</p>
          <p class="mt-1 text-xs">添加后可在这里测试连接并查看可用工具。</p>
        </div>
        <div v-else class="space-y-3">
          <div v-for="server in servers" :key="server.id" class="rounded-[20px] border border-stone-200/70 bg-white/75 p-3 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
            <div class="flex flex-wrap items-start gap-3">
              <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-stone-200 bg-gradient-to-br from-white to-cyan-50 font-serif text-base font-semibold text-cyan-700">
                {{ getMcpServerInitial(server) }}
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <p class="truncate text-sm font-semibold text-stone-700">{{ server.display_name }}</p>
                  <span class="badge border" :class="[getStatusConfig(server.last_test_status).bg, getStatusConfig(server.last_test_status).text]">
                    <span class="status-dot" :class="getStatusConfig(server.last_test_status).dot" />
                    {{ getStatusConfig(server.last_test_status).label }}
                  </span>
                  <span v-if="!server.enabled" class="badge border border-stone-200 bg-stone-50 text-stone-400">已停用</span>
                  <span v-if="server.auth_token_configured" class="badge border border-green-100 bg-green-50 text-green-700">Token: {{ server.auth_token_masked }}</span>
                </div>
                <p class="mt-1 truncate font-mono text-2xs text-stone-400">{{ server.server_key }} · {{ server.url }}</p>
                <div class="mt-2 flex flex-wrap gap-1.5 text-2xs">
                  <span class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-500">{{ getMcpTransportLabel(server.transport) }}</span>
                  <span class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-500">{{ getMcpAuthLabel(server.auth_type) }}</span>
                  <span class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-500">工具 {{ server.tools?.length || 0 }}</span>
                  <span v-if="server.last_test_at" class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-400">{{ formatDate(server.last_test_at) }}</span>
                </div>
                <p v-if="server.description" class="mt-2 line-clamp-2 text-xs leading-5 text-stone-500">{{ server.description }}</p>
              </div>
              <div class="flex shrink-0 flex-wrap gap-1.5">
                <button class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-medium text-stone-500 hover:bg-stone-50" @click="emit('edit', server)">编辑</button>
                <button
                  class="rounded-full border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-xs font-medium text-cyan-700 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="!!testingServerId || !server.enabled"
                  :title="server.enabled ? '执行 initialize / initialized / tools/list' : 'Server 已停用，请先启用后测试'"
                  @click="emit('test', server)"
                >
                  {{ testingServerId === server.id ? '测试中…' : '测试' }}
                </button>
                <button class="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50" :disabled="!!deletingServerId" @click="emit('delete', server)">删除</button>
              </div>
            </div>
            <div v-if="server.last_test_message" class="mt-3 rounded-2xl border px-3 py-2 text-xs leading-5" :class="server.last_test_status === 'success' ? 'border-green-100 bg-green-50 text-green-700' : 'border-rose-100 bg-rose-50 text-rose-600'">
              {{ server.last_test_message }}
              <span v-if="server.last_test_at" class="ml-1 opacity-70">· {{ formatDate(server.last_test_at) }}</span>
            </div>
            <div v-if="server.tools?.length" class="mt-3 flex flex-wrap gap-1.5">
              <span v-for="tool in server.tools" :key="`${server.id}-${tool.name}`" class="badge border border-stone-200 bg-stone-50 text-stone-600" :title="tool.description || tool.name">{{ tool.name }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
