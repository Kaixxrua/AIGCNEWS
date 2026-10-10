<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Play, RefreshCw, Square, Save, Activity } from 'lucide-vue-next'
import { vIndicator } from '@/motion/indicator'
import { vSwap } from '@/motion/swap'
import { api } from '@/services/http/apiClient'

interface Run { id: string; trigger: string; status: string; started_at: string }
interface Event { at: string; kind: string; title: string; data: unknown }
interface Detail extends Run { events: Event[]; report: string }
const runs = ref<Run[]>([])
const selected = ref('')
const detail = ref<Detail | null>(null)
const enabled = ref(false)
const recoveryEnabled = ref(false)
const recoveryActive = ref(false)
const interval = ref(15)
const busy = ref(false)
const loading = ref(true)
const error = ref('')
const saved = ref('')
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
let selectionVersion = 0
const running = computed(() => runs.value.some(run => run.status === 'running'))
const labels: Record<string, string> = { running: '调查中', completed: '已完成', failed: '调查失败', cancelled: '已停止', interrupted: '已中断' }
const tools: Record<string, string> = { health: '依赖健康', tasks: '采集任务', errors: '脱敏错误诊断', scheduler: '调度状态', delivery: '自动交付', x_translations: 'X 译文队列', source_trends: '采集趋势', database: '数据库运行状态', investigation_history: '巡检可靠性', followups: '修复回访记录', knowledge: '故障手册与验证经验' }
const time = (value: string) => new Date(value).toLocaleString()
function followupLabel(event: Event): string {
  if (event.kind !== 'followup_result' || !event.data || typeof event.data !== 'object') return ''
  const status = String((event.data as Record<string, unknown>).status || '')
  return ({ verified: '结果已核实', not_recovered: '观察期内未恢复', inconclusive: '证据不足' } as Record<string, string>)[status] || ''
}

async function select(id: string) {
  const version = ++selectionVersion
  if (selected.value !== id) detail.value = null
  selected.value = id
  try {
    const { data } = await api.get<Detail>(`/ops/ai/runs/${id}`)
    if (!disposed && version === selectionVersion) detail.value = data
  } catch { if (!disposed) error.value = '无法读取巡检记录' }
}
async function refresh(initial = false) {
  try {
    const { data } = await api.get('/ops/ai/runs')
    if (disposed) return
    runs.value = data.items
    recoveryActive.value = data.config.recovery_enabled === true
    if (initial) { enabled.value = data.config.enabled; interval.value = data.config.interval_minutes; recoveryEnabled.value = recoveryActive.value }
    error.value = ''
    const id = selected.value || runs.value[0]?.id
    if (id) await select(id)
  } catch { if (!disposed) error.value = '连接失败，正在重试' }
  finally { loading.value = false }
}
async function poll() {
  await refresh()
  if (!disposed) timer = setTimeout(poll, 2000)
}
async function command(action: 'start' | 'cancel' | 'save') {
  busy.value = true
  error.value = ''; saved.value = ''
  try {
    if (action === 'start') {
      const { data } = await api.post('/ops/ai/runs')
      selected.value = data.id
      detail.value = null
    } else if (action === 'cancel') {
      await api.post(`/ops/ai/runs/${selected.value}/cancel`)
    } else {
      await api.put('/ops/ai/config', { enabled: enabled.value, interval_minutes: interval.value, recovery_enabled: recoveryEnabled.value })
      saved.value = '巡检计划已保存'
    }
    await refresh()
  } catch { error.value = '操作失败，请检查连接或是否已有巡检运行' }
  finally { busy.value = false }
}
onMounted(async () => { await refresh(true); if (!disposed) timer = setTimeout(poll, 2000) })
onUnmounted(() => { disposed = true; selectionVersion++; clearTimeout(timer) })
</script>

<template>
  <section class="ai-ops" aria-label="AI 运维">
    <header class="ai-ops-toolbar monitor-divider">
      <div class="flex items-center gap-2"><Activity :size="18" /><h2 class="text-base font-semibold">AI 运维</h2><span class="monitor-badge">{{ recoveryActive ? '有限自愈' : '只读调查' }}</span></div>
      <div class="flex items-center gap-2">
        <button class="monitor-pagination-btn inline-flex items-center gap-2" :disabled="busy || running || loading" @click="command('start')"><Play :size="14" />立即巡检</button>
        <button class="monitor-pagination-btn" title="刷新" aria-label="刷新" @click="refresh()"><RefreshCw :size="16" /></button>
      </div>
    </header>
    <div class="ai-ops-toolbar monitor-divider">
      <label class="flex items-center gap-2 text-sm"><input v-model="enabled" type="checkbox" :disabled="busy || loading" />自动巡检</label>
      <label class="flex items-center gap-2 text-sm"><input v-model="recoveryEnabled" type="checkbox" :disabled="busy || loading" />有限自动修复</label>
      <span class="text-xs monitor-caption">资讯失败补跑 · 缺失简报补生成 · X 译文重试 · 僵死任务收尾 · 均有频次预算，不改代码与配置</span>
      <label class="flex items-center gap-2 text-sm">间隔（分钟）<input v-model.number="interval" class="monitor-input w-20" type="number" min="5" max="120" :disabled="busy || loading" /></label>
      <button class="monitor-pagination-btn" :disabled="busy || loading || !Number.isInteger(interval) || interval < 5 || interval > 120" title="保存巡检计划" aria-label="保存巡检计划" @click="command('save')"><Save :size="16" /></button>
      <span class="text-xs monitor-caption" role="status">{{ saved }}</span>
    </div>
    <p v-if="error" class="monitor-alert-error p-3 text-sm" role="alert">{{ error }}</p>
    <div class="ai-ops-workspace">
      <aside v-indicator="'.ai-ops-run.selected'" class="ai-ops-history" aria-label="巡检历史">
        <h3 class="text-sm font-semibold p-3">巡检历史</h3>
        <p v-if="!runs.length" class="monitor-caption p-3 text-sm">{{ loading ? '加载中' : '暂无巡检记录' }}</p>
        <button v-for="run in runs" :key="run.id" class="ai-ops-run" :class="{ selected: selected === run.id }" :aria-pressed="selected === run.id" @click="select(run.id)">
          <span class="flex justify-between gap-2"><strong>{{ run.trigger === 'manual' ? '手动巡检' : '自动巡检' }}</strong><span>{{ labels[run.status] || run.status }}</span></span>
          <time class="monitor-caption text-xs">{{ time(run.started_at) }}</time>
        </button>
      </aside>
      <!-- 换了一条巡检记录，读到的活动记录整块依次浮现；同一条轮询刷新时不重播。 -->
      <div v-swap="{ key: detail?.id, stagger: true }" class="ai-ops-detail">
        <template v-if="detail">
          <div class="flex justify-between items-center gap-3 mb-4">
            <h3 class="text-sm font-semibold">活动记录 · {{ labels[detail.status] || detail.status }}</h3>
            <button v-if="detail.status === 'running'" class="monitor-pagination-btn inline-flex items-center gap-2" :disabled="busy" @click="command('cancel')"><Square :size="14" />停止调查</button>
          </div>
          <TransitionGroup tag="ol" name="ai-ops-event" aria-live="polite" aria-relevant="additions" class="ai-ops-events">
            <li v-for="(event, index) in detail.events" :key="index" class="monitor-divider py-3 border-b">
              <div class="flex flex-wrap gap-2 text-sm"><time class="monitor-caption text-xs">{{ time(event.at) }}</time><strong>{{ tools[event.title] || event.title }}</strong><span class="monitor-caption text-xs">{{ { tool_start: '开始查询', tool_result: '证据已记录', model: '模型分析', model_result: '已返回', warning: '提示', error: '失败', policy: '权限检查', action_start: '已准入', action_result: '执行结果', followup_result: '恢复核验' }[event.kind] || event.kind }}</span><span v-if="followupLabel(event)">{{ followupLabel(event) }}</span></div>
              <details v-if="event.data" class="mt-2 text-xs"><summary class="cursor-pointer monitor-caption">查看记录</summary><pre class="monitor-surface-dim p-3 mt-2">{{ JSON.stringify(event.data, null, 2) }}</pre></details>
            </li>
          </TransitionGroup>
          <div v-if="detail.report" class="pt-5"><h3 class="text-sm font-semibold mb-3">{{ detail.status === 'failed' ? '证据摘要' : '调查结论' }}</h3><p class="ai-ops-report text-sm">{{ detail.report }}</p></div>
          <p v-else-if="detail.status !== 'running'" class="monitor-caption text-sm pt-4">本次未生成调查结论。已收集的证据保留在活动记录中。</p>
        </template>
        <p v-else class="monitor-caption text-sm">{{ selected ? '正在读取调查' : '暂无活动' }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ai-ops { min-width: 0; }
.ai-ops-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 14px; padding: 14px 0; border-bottom-width: 1px; }
.ai-ops-toolbar:first-child { justify-content: space-between; }
.ai-ops-workspace { display: grid; grid-template-columns: minmax(210px, 260px) minmax(0, 1fr); min-height: 420px; }
.ai-ops-history { position: relative; isolation: isolate; max-height: 720px; overflow: auto; }
.ai-ops-run { display: grid; gap: 8px; width: 100%; padding: 14px 12px; text-align: left; font-size: 12px; border-bottom: 1px solid var(--border-color, #80808030); }
.ai-ops-run.selected { background: #14b8a614; box-shadow: inset 3px 0 #14b8a6; }
/* 选中底是列表自己的滑动标记（v-indicator），在巡检记录之间弹簧滑动；选中的一条把底让给它。 */
.ai-ops-history[data-indicator-mark]::before { z-index: -1; background: #14b8a614; box-shadow: inset 3px 0 #14b8a6; }
.ai-ops-history[data-indicator] .ai-ops-run.selected { background: transparent; box-shadow: none; }
/* 调查进行中新到的活动记录逐条浮现。 */
.ai-ops-event-enter-active { animation: motion-rise 360ms var(--motion-ease-out) both; }
.ai-ops-detail { min-width: 0; padding: 20px; }
pre, .ai-ops-report { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
pre { max-height: 320px; overflow: auto; }
button:disabled { opacity: .5; cursor: not-allowed; }
@media (max-width: 700px) { .ai-ops-workspace { grid-template-columns: minmax(0, 1fr); } .ai-ops-history { max-height: 220px; } .ai-ops-detail { padding: 16px 0; } }
</style>
