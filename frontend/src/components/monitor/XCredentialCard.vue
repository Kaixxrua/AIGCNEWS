<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useXCredentialController } from '@/composables/useXCredentialController'
import SkeletonBlock from '@/components/SkeletonBlock.vue'
import { formatDate, getStatusConfig } from '@/features/monitor/monitorViewModel'

const { t } = useI18n()

// 自包含面板：凭证状态与请求都留在卡片内部，MonitorView 只需挂载。
const {
  credentials, form, loading, saving, togglingId, testingId, deletingId, errorMsg, noticeMsg,
  loadCredentials, resetForm, editCredential, saveCredential, toggleCredential, testCredential, removeCredential, dispose,
} = useXCredentialController({ translate: t })

const updateForm = <K extends keyof typeof form.value>(field: K, value: (typeof form.value)[K]) => {
  form.value = { ...form.value, [field]: value }
}

const getCredentialInitial = (displayName: string) => (displayName.trim().slice(0, 1) || 'X').toUpperCase()

onMounted(loadCredentials)
onBeforeUnmount(dispose)
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 overflow-hidden p-0" style="animation-delay: 0.2s">
    <div class="monitor-divider relative border-b p-5">
      <div class="pointer-events-none absolute right-6 top-4 hidden font-mono text-[52px] font-black leading-none monitor-watermark md:block">𝕏</div>
      <div class="relative flex flex-wrap items-start justify-between gap-3">
        <div class="max-w-3xl">
          <div class="flex flex-wrap items-center gap-2">
            <span class="monitor-avatar monitor-avatar-accent flex h-8 w-8 items-center justify-center font-mono text-sm shadow-sm">𝕏</span>
            <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.xCredentials.title') }}</h3>
            <span class="monitor-badge">{{ t('monitor.xCredentials.count', { count: credentials.length }) }}</span>
            <span class="monitor-badge monitor-status-running">{{ t('monitor.xCredentials.writeOnly') }}</span>
          </div>
          <p class="monitor-caption mt-2 text-xs leading-5">{{ t('monitor.xCredentials.description') }}</p>
        </div>
        <button class="monitor-btn-secondary" :disabled="loading" @click="loadCredentials">
          <span class="inline-block h-3 w-3 rounded-full border-2 border-current border-t-transparent" :class="loading ? 'animate-spin' : ''" />
          {{ t('monitor.xCredentials.refresh') }}
        </button>
      </div>
    </div>

    <div v-if="errorMsg" class="mx-5 mt-4 flex items-center justify-between rounded-md border px-4 py-2 text-xs monitor-status-error">
      <span>{{ errorMsg }}</span>
      <button class="ml-3 opacity-70 hover:opacity-100" @click="errorMsg = ''">✕</button>
    </div>
    <div v-if="noticeMsg" class="mx-5 mt-4 flex items-center justify-between rounded-md border px-4 py-2 text-xs monitor-status-success">
      <span>{{ noticeMsg }}</span>
      <button class="ml-3 opacity-70 hover:opacity-100" @click="noticeMsg = ''">✕</button>
    </div>

    <div class="grid gap-4 p-5 xl:grid-cols-[minmax(320px,0.95fr)_minmax(420px,1.25fr)]">
      <div class="monitor-surface p-4">
        <div class="mb-3 flex items-start justify-between gap-2">
          <div>
            <h4 class="text-xs font-semibold uppercase tracking-widest monitor-caption">{{ t(form.id ? 'monitor.xCredentials.editCredential' : 'monitor.xCredentials.addCredential') }}</h4>
            <p class="mt-1 text-2xs monitor-caption">{{ t('monitor.xCredentials.secretHint') }}</p>
          </div>
          <button v-if="form.id" class="monitor-btn-ghost" @click="resetForm">{{ t('monitor.cancelEdit') }}</button>
        </div>
        <div class="space-y-3">
          <label class="block">
            <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.xCredentials.displayName') }}</span>
            <input :value="form.display_name" class="input w-full py-2 text-xs" :placeholder="t('monitor.xCredentials.displayNamePlaceholder')" autocomplete="off" @input="updateForm('display_name', ($event.target as HTMLInputElement).value.trim())" />
          </label>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label class="block">
              <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.xCredentials.authToken') }}</span>
              <input :value="form.auth_token" type="password" class="input w-full py-2 text-xs font-mono" :placeholder="t('monitor.xCredentials.authTokenPlaceholder')" autocomplete="new-password" spellcheck="false" @input="updateForm('auth_token', ($event.target as HTMLInputElement).value)" />
            </label>
            <label class="block">
              <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.xCredentials.ct0') }}</span>
              <input :value="form.ct0" type="password" class="input w-full py-2 text-xs font-mono" :placeholder="t('monitor.xCredentials.ct0Placeholder')" autocomplete="new-password" spellcheck="false" @input="updateForm('ct0', ($event.target as HTMLInputElement).value)" />
            </label>
          </div>
          <label class="block">
            <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.xCredentials.note') }}</span>
            <textarea :value="form.note" class="input min-h-[68px] py-2 text-xs" :placeholder="t('monitor.xCredentials.notePlaceholder')" @input="updateForm('note', ($event.target as HTMLTextAreaElement).value.trim())" />
          </label>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-[150px_minmax(0,1fr)]">
            <label class="block">
              <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.xCredentials.sortOrder') }}</span>
              <input :value="form.sort_order" type="number" min="0" class="input w-full py-2 text-xs" @input="updateForm('sort_order', Number(($event.target as HTMLInputElement).value) || 0)" />
            </label>
            <div class="flex items-end pb-1">
              <p class="text-2xs monitor-caption">{{ t('monitor.xCredentials.sortHint') }}</p>
            </div>
          </div>
          <div class="monitor-check-row px-3 py-2">
            <label class="inline-flex items-center gap-1.5 text-xs monitor-caption">
              <input :checked="form.enabled" type="checkbox" class="rounded" @change="updateForm('enabled', ($event.target as HTMLInputElement).checked)" />
              {{ t('monitor.xCredentials.enabled') }}
            </label>
          </div>
          <button class="monitor-btn-primary w-full" :disabled="saving" @click="saveCredential">
            {{ t(saving ? 'monitor.saving' : form.id ? 'monitor.xCredentials.saveCredential' : 'monitor.xCredentials.createCredential') }}
          </button>
        </div>
      </div>

      <div class="monitor-surface flex min-h-[260px] flex-col p-4">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h4 class="text-xs font-semibold uppercase tracking-widest monitor-caption">{{ t('monitor.xCredentials.title') }}</h4>
            <p class="mt-1 text-2xs monitor-caption">{{ t('monitor.xCredentials.listHint') }}</p>
          </div>
          <span v-if="loading && credentials.length" class="inline-flex items-center gap-1 text-2xs monitor-caption">
            <span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />{{ t('monitor.synchronizing') }}
          </span>
        </div>
        <div v-if="loading && !credentials.length" class="flex flex-1 min-h-[180px] flex-col justify-center gap-3 pr-1" role="status" :aria-label="t('common.loading')">
          <SkeletonBlock v-for="i in 4" :key="i" :width="i % 2 ? '88%' : '64%'" height="12px" />
        </div>
        <div v-else-if="!credentials.length" class="monitor-empty flex flex-1 min-h-[180px] flex-col items-center justify-center rounded-md text-center text-sm">
          <p class="font-medium">{{ t('monitor.xCredentials.empty') }}</p>
          <p class="mt-1 max-w-sm text-xs">{{ t('monitor.xCredentials.emptyHint') }}</p>
        </div>
        <div v-else class="space-y-3">
          <div v-for="credential in credentials" :key="credential.id" class="monitor-surface p-3 transition hover:-translate-y-0.5">
            <div class="flex flex-wrap items-start gap-3">
              <div class="monitor-avatar flex h-10 w-10 shrink-0 text-base">
                {{ getCredentialInitial(credential.display_name) }}
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <p class="truncate text-sm font-semibold">{{ credential.display_name || t('monitor.xCredentials.unnamed') }}</p>
                  <span class="badge" :class="[getStatusConfig(credential.last_test_status).bg]">
                    <span class="status-dot" :class="getStatusConfig(credential.last_test_status).dot" />
                    {{ getStatusConfig(credential.last_test_status).labelKey ? t(`monitor.${getStatusConfig(credential.last_test_status).labelKey}`) : getStatusConfig(credential.last_test_status).rawLabel }}
                  </span>
                  <span v-if="!credential.enabled" class="monitor-badge">{{ t('monitor.disabled') }}</span>
                </div>
                <div class="mt-2 flex flex-wrap gap-1.5 text-2xs">
                  <span class="monitor-badge">{{ t('monitor.xCredentials.authToken') }}: {{ credential.auth_token_masked || t('monitor.xCredentials.notConfigured') }}</span>
                  <span class="monitor-badge">{{ t('monitor.xCredentials.ct0') }}: {{ credential.ct0_masked || t('monitor.xCredentials.notConfigured') }}</span>
                  <span class="monitor-badge">{{ t('monitor.xCredentials.sortBadge', { order: credential.sort_order }) }}</span>
                  <span v-if="credential.last_test_at" class="monitor-badge">{{ formatDate(credential.last_test_at) }}</span>
                </div>
                <p v-if="credential.note" class="mt-2 line-clamp-2 text-xs leading-5 monitor-caption">{{ credential.note }}</p>
              </div>
              <div class="flex shrink-0 flex-wrap gap-1.5">
                <button class="monitor-btn-ghost" @click="editCredential(credential)">{{ t('common.edit') }}</button>
                <button
                  class="monitor-btn-secondary"
                  :disabled="togglingId !== null"
                  @click="toggleCredential(credential)"
                >
                  {{ t(credential.enabled ? 'monitor.xCredentials.disable' : 'monitor.xCredentials.enable') }}
                </button>
                <button
                  class="monitor-btn-secondary"
                  :disabled="testingId !== null"
                  @click="testCredential(credential)"
                >
                  {{ t(testingId === credential.id ? 'monitor.testing' : 'monitor.test') }}
                </button>
                <button class="monitor-btn-danger" :disabled="deletingId !== null" @click="removeCredential(credential)">{{ t('common.delete') }}</button>
              </div>
            </div>
            <div v-if="credential.last_test_message" class="mt-3 rounded-md border px-3 py-2 text-xs leading-5" :class="['success', 'succeeded'].includes(credential.last_test_status) ? 'monitor-status-success' : 'monitor-status-error'">
              {{ credential.last_test_message }}
              <span v-if="credential.last_test_at" class="ml-1 opacity-70">· {{ formatDate(credential.last_test_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
