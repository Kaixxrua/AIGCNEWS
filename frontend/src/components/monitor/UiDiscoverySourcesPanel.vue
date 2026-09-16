<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import { createUiDiscoverySourceForm, type UiDiscoverySource, type UiDiscoverySourceForm } from '@/features/monitor/monitorModel'
import { monitorApi } from '@/services/monitor/monitorApi'

const { t } = useI18n()
const builtin = ref<UiDiscoverySource[]>([])
const custom = ref<UiDiscoverySource[]>([])
const form = ref<UiDiscoverySourceForm>(createUiDiscoverySourceForm())
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const editing = computed(() => form.value.id !== null)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const result = await monitorApi.fetchUiDiscoverySources()
    builtin.value = result.builtin
    custom.value = result.custom
  } catch {
    error.value = t('monitor.uiSources.loadFailed')
  } finally {
    loading.value = false
  }
}

const reset = () => { form.value = createUiDiscoverySourceForm() }
const edit = (source: UiDiscoverySource) => { form.value = createUiDiscoverySourceForm(source) }
const save = async () => {
  saving.value = true
  error.value = ''
  try {
    await monitorApi.saveUiDiscoverySource(form.value)
    reset()
    await load()
  } catch (reason: any) {
    error.value = reason?.response?.data?.detail || t('monitor.uiSources.saveFailed')
  } finally {
    saving.value = false
  }
}
const remove = async (source: UiDiscoverySource) => {
  if (typeof source.id !== 'number' || !window.confirm(t('monitor.uiSources.deleteConfirm', { name: source.name }))) return
  try {
    await monitorApi.deleteUiDiscoverySource(source.id)
    if (form.value.id === source.id) reset()
    await load()
  } catch {
    error.value = t('monitor.uiSources.deleteFailed')
  }
}
const target = (source: UiDiscoverySource) => source.kind === 'github'
  ? `https://github.com/${source.repository}`
  : source.kind === 'x' ? source.profile_url || '' : source.feed_url || ''
const detail = (source: UiDiscoverySource) => source.kind === 'github'
  ? source.path_patterns.join(', ')
  : source.kind === 'x' ? t('monitor.uiSources.xWindow') : source.feed_url || ''
const location = (source: UiDiscoverySource) => source.repository || source.feed_url || `@${source.handle}`

onMounted(load)
</script>

<template>
  <div class="stagger-enter glass-card flex flex-col p-5">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.uiSources.title') }}</h3>
        <p class="monitor-caption mt-1 text-xs">{{ t('monitor.uiSources.description') }}</p>
      </div>
      <span class="monitor-badge">{{ t('monitor.uiSources.schedule') }}</span>
    </div>

    <p class="monitor-surface-dim monitor-caption mt-4 p-3 text-xs">{{ t('monitor.uiSources.publicationHint') }}</p>
    <p v-if="error" class="monitor-alert-error mt-3 rounded px-3 py-2 text-xs">{{ error }}</p>
    <SpinnerLoader v-if="loading" class="min-h-[120px]" />

    <div v-else class="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div class="overflow-x-auto">
        <table class="monitor-table">
          <thead><tr>
            <th>{{ t('monitor.uiSources.name') }}</th>
            <th>{{ t('monitor.uiSources.type') }}</th>
            <th>{{ t('monitor.uiSources.location') }}</th>
            <th>{{ t('monitor.uiSources.scope') }}</th>
            <th>{{ t('monitor.schedulerConfig.status') }}</th>
            <th class="text-right">{{ t('common.edit') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="source in [...builtin, ...custom]" :key="`${source.editable === false ? 'builtin' : 'custom'}-${source.id}`">
              <td class="text-xs font-medium">
                {{ source.name }}
                <span v-if="source.editable === false" class="monitor-badge ml-1">{{ t('monitor.uiSources.builtin') }}</span>
              </td>
              <td class="text-xs">{{ t(`monitor.uiSources.${source.kind}`) }}</td>
              <td class="max-w-[260px] text-xs">
                <a class="underline decoration-dotted underline-offset-2" :href="target(source)" target="_blank" rel="noopener noreferrer">
                  {{ location(source) }}
                </a>
              </td>
              <td class="max-w-[280px] truncate text-xs monitor-caption" :title="detail(source)">{{ detail(source) }}</td>
              <td><span class="badge" :class="source.enabled ? 'monitor-status-success' : 'monitor-status-unknown'">{{ source.enabled ? t('monitor.schedulerConfig.active') : t('monitor.schedulerConfig.paused') }}</span></td>
              <td class="text-right whitespace-nowrap">
                <template v-if="source.editable !== false">
                  <button class="monitor-btn-ghost" @click="edit(source)">{{ t('common.edit') }}</button>
                  <button class="monitor-btn-ghost monitor-status-error" @click="remove(source)">{{ t('common.delete') }}</button>
                </template>
                <span v-else class="text-2xs monitor-caption">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <form class="monitor-surface space-y-3 p-4" @submit.prevent="save">
        <div class="flex items-center justify-between gap-2">
          <h4 class="text-sm font-semibold">{{ t(editing ? 'monitor.uiSources.editTitle' : 'monitor.uiSources.addTitle') }}</h4>
          <button v-if="editing" type="button" class="monitor-btn-ghost" @click="reset">{{ t('common.cancel') }}</button>
        </div>
        <label class="block text-xs">
          <span class="monitor-caption">{{ t('monitor.uiSources.name') }}</span>
          <input v-model="form.name" required maxlength="120" class="input mt-1 w-full rounded border px-3 py-2" />
        </label>
        <label class="block text-xs">
          <span class="monitor-caption">{{ t('monitor.uiSources.type') }}</span>
          <select v-model="form.kind" class="input mt-1 w-full rounded border px-3 py-2">
            <option value="github">{{ t('monitor.uiSources.github') }}</option>
            <option value="feed">{{ t('monitor.uiSources.feed') }}</option>
          </select>
        </label>
        <template v-if="form.kind === 'github'">
          <label class="block text-xs">
            <span class="monitor-caption">{{ t('monitor.uiSources.repository') }}</span>
            <input v-model="form.repository" required placeholder="owner/repository" class="input mt-1 w-full rounded border px-3 py-2" />
          </label>
          <label class="block text-xs">
            <span class="monitor-caption">{{ t('monitor.uiSources.patterns') }}</span>
            <textarea v-model="form.pathPatterns" required rows="4" placeholder="components/*.tsx" class="input mt-1 w-full rounded border px-3 py-2" />
            <span class="monitor-caption mt-1 block text-2xs">{{ t('monitor.uiSources.patternsHint') }}</span>
          </label>
        </template>
        <label v-else class="block text-xs">
          <span class="monitor-caption">{{ t('monitor.uiSources.feedUrl') }}</span>
          <input v-model="form.feedUrl" required type="url" placeholder="https://example.com/feed.xml" class="input mt-1 w-full rounded border px-3 py-2" />
          <span class="monitor-caption mt-1 block text-2xs">{{ t('monitor.uiSources.feedHint') }}</span>
        </label>
        <label class="flex items-center gap-2 text-xs"><input v-model="form.enabled" type="checkbox" />{{ t('monitor.schedulerConfig.enabled') }}</label>
        <button class="monitor-btn-primary w-full" :disabled="saving" type="submit">{{ saving ? t('common.processing') : t('common.save') }}</button>
      </form>
    </div>
  </div>
</template>
