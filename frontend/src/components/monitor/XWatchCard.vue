<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useXWatchController } from '@/composables/useXWatchController'
import { formatDate, getStatusConfig } from '@/features/monitor/monitorViewModel'

const { t } = useI18n()

// 自包含面板：状态与请求都留在卡片内部，MonitorView 只需挂载，不占用页面控制器。
const {
  accounts, form, loading, saving, togglingId, testingId, deletingId, errorMsg, noticeMsg,
  loadAccounts, resetForm, editAccount, saveAccount, toggleAccount, testAccount, removeAccount, dispose,
} = useXWatchController({ translate: t })

const updateForm = <K extends keyof typeof form.value>(field: K, value: (typeof form.value)[K]) => {
  form.value = { ...form.value, [field]: value }
}

const getAccountInitial = (screenName: string) => (screenName.trim().slice(0, 1) || 'X').toUpperCase()

onMounted(loadAccounts)
onBeforeUnmount(dispose)
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 overflow-hidden p-0" style="animation-delay: 0.15s">
    <div class="relative border-b border-stone-200/60 bg-gradient-to-br from-white/80 via-stone-50/60 to-stone-100/70 p-5">
      <div class="pointer-events-none absolute right-6 top-4 hidden font-mono text-[52px] font-black leading-none text-stone-300/60 md:block">X</div>
      <div class="relative flex flex-wrap items-start justify-between gap-3">
        <div class="max-w-3xl">
          <div class="flex flex-wrap items-center gap-2">
            <span class="flex h-8 w-8 items-center justify-center rounded-2xl border border-stone-200 bg-stone-900 font-mono text-sm font-bold text-white shadow-sm">𝕏</span>
            <h3 class="text-sm font-semibold text-stone-700">{{ t('monitor.xWatch.title') }}</h3>
            <span class="badge border border-stone-200 bg-white/80 text-stone-500">{{ t('monitor.xWatch.count', { count: accounts.length }) }}</span>
            <span class="badge border border-stone-200 bg-stone-50 text-stone-500">daily · */2h</span>
          </div>
          <p class="mt-2 text-xs leading-5 text-stone-500">{{ t('monitor.xWatch.description') }}</p>
        </div>
        <button class="btn-secondary px-3.5 py-2 text-xs" :disabled="loading" @click="loadAccounts">
          <span class="inline-block h-3 w-3 rounded-full border-2 border-stone-200 border-t-stone-500" :class="loading ? 'animate-spin' : ''" />
          {{ t('monitor.xWatch.refresh') }}
        </button>
      </div>
    </div>

    <div v-if="errorMsg" class="mx-5 mt-4 flex items-center justify-between rounded-2xl border border-rose-100 bg-rose-50 px-4 py-2 text-xs text-rose-600">
      <span>{{ errorMsg }}</span>
      <button class="ml-3 text-rose-400 hover:text-rose-600" @click="errorMsg = ''">✕</button>
    </div>
    <div v-if="noticeMsg" class="mx-5 mt-4 flex items-center justify-between rounded-2xl border border-green-100 bg-green-50 px-4 py-2 text-xs text-green-700">
      <span>{{ noticeMsg }}</span>
      <button class="ml-3 text-green-400 hover:text-green-600" @click="noticeMsg = ''">✕</button>
    </div>

    <div class="grid gap-4 p-5 xl:grid-cols-[minmax(320px,0.95fr)_minmax(420px,1.25fr)]">
      <div class="rounded-[22px] border border-stone-200/70 bg-white/60 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
        <div class="mb-3 flex items-start justify-between gap-2">
          <div>
            <h4 class="text-xs font-semibold uppercase tracking-widest text-stone-400">{{ t(form.id ? 'monitor.xWatch.editAccount' : 'monitor.xWatch.addAccount') }}</h4>
            <p class="mt-1 text-2xs text-stone-400">{{ t('monitor.xWatch.handleHint') }}</p>
          </div>
          <button v-if="form.id" class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-medium text-stone-400 hover:text-stone-700" @click="resetForm">{{ t('monitor.cancelEdit') }}</button>
        </div>
        <div class="space-y-3">
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label class="block">
              <span class="mb-1 block text-xs text-stone-400">{{ t('monitor.xWatch.handle') }}</span>
              <input :value="form.screen_name" class="input w-full py-2 text-xs font-mono" :placeholder="t('monitor.xWatch.handlePlaceholder')" autocomplete="off" @input="updateForm('screen_name', ($event.target as HTMLInputElement).value)" />
            </label>
            <label class="block">
              <span class="mb-1 block text-xs text-stone-400">{{ t('monitor.displayName') }}</span>
              <input :value="form.display_name" class="input w-full py-2 text-xs" placeholder="OpenAI" autocomplete="off" @input="updateForm('display_name', ($event.target as HTMLInputElement).value.trim())" />
            </label>
          </div>
          <label class="block">
            <span class="mb-1 block text-xs text-stone-400">{{ t('monitor.xWatch.note') }}</span>
            <textarea :value="form.note" class="input min-h-[68px] rounded-[18px] py-2 text-xs" :placeholder="t('monitor.xWatch.notePlaceholder')" @input="updateForm('note', ($event.target as HTMLTextAreaElement).value.trim())" />
          </label>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-[150px_minmax(0,1fr)]">
            <label class="block">
              <span class="mb-1 block text-xs text-stone-400">{{ t('monitor.xWatch.sortOrder') }}</span>
              <input :value="form.sort_order" type="number" min="0" class="input w-full py-2 text-xs" @input="updateForm('sort_order', Number(($event.target as HTMLInputElement).value) || 0)" />
            </label>
            <div class="flex items-end pb-1">
              <p class="text-2xs text-stone-400">{{ t('monitor.xWatch.sortHint') }}</p>
            </div>
          </div>
          <div class="rounded-2xl border border-stone-200/70 bg-stone-50/70 px-3 py-2">
            <label class="inline-flex items-center gap-1.5 text-xs text-stone-500">
              <input :checked="form.enabled" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" @change="updateForm('enabled', ($event.target as HTMLInputElement).checked)" />
              {{ t('monitor.xWatch.enabled') }}
            </label>
          </div>
          <button class="btn-primary w-full justify-center" :disabled="saving" @click="saveAccount">
            {{ t(saving ? 'monitor.saving' : form.id ? 'monitor.xWatch.saveAccount' : 'monitor.xWatch.createAccount') }}
          </button>
        </div>
      </div>

      <div class="min-h-[260px] rounded-[22px] border border-stone-200/70 bg-white/45 p-4">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h4 class="text-xs font-semibold uppercase tracking-widest text-stone-400">{{ t('monitor.xWatch.title') }}</h4>
            <p class="mt-1 text-2xs text-stone-400">{{ t('monitor.xWatch.listHint') }}</p>
          </div>
          <span v-if="loading && accounts.length" class="inline-flex items-center gap-1 text-2xs text-stone-400">
            <span class="inline-block h-3 w-3 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />{{ t('monitor.synchronizing') }}
          </span>
        </div>
        <div v-if="loading && !accounts.length" class="flex h-full min-h-[180px] items-center justify-center gap-2 text-sm text-stone-400">
          <span class="inline-block h-4 w-4 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />{{ t('monitor.xWatch.loading') }}
        </div>
        <div v-else-if="!accounts.length" class="flex h-full min-h-[180px] flex-col items-center justify-center rounded-[18px] border border-dashed border-stone-200 bg-white/55 text-center text-sm text-stone-400">
          <p class="font-medium text-stone-500">{{ t('monitor.xWatch.empty') }}</p>
          <p class="mt-1 max-w-sm text-xs">{{ t('monitor.xWatch.emptyHint') }}</p>
        </div>
        <div v-else class="space-y-3">
          <div v-for="account in accounts" :key="account.id" class="rounded-[20px] border border-stone-200/70 bg-white/75 p-3 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
            <div class="flex flex-wrap items-start gap-3">
              <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-stone-200 bg-gradient-to-br from-white to-stone-100 font-mono text-base font-semibold text-stone-700">
                {{ getAccountInitial(account.screen_name) }}
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <p class="truncate text-sm font-semibold text-stone-700">@{{ account.screen_name }}</p>
                  <span v-if="account.display_name" class="truncate text-xs text-stone-400">{{ account.display_name }}</span>
                  <span class="badge border" :class="[getStatusConfig(account.last_test_status).bg, getStatusConfig(account.last_test_status).text]">
                    <span class="status-dot" :class="getStatusConfig(account.last_test_status).dot" />
                    {{ getStatusConfig(account.last_test_status).labelKey ? t(`monitor.${getStatusConfig(account.last_test_status).labelKey}`) : getStatusConfig(account.last_test_status).rawLabel }}
                  </span>
                  <span v-if="!account.enabled" class="badge border border-stone-200 bg-stone-50 text-stone-400">{{ t('monitor.disabled') }}</span>
                </div>
                <div class="mt-2 flex flex-wrap gap-1.5 text-2xs">
                  <span class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-500">{{ t('monitor.xWatch.sortBadge', { order: account.sort_order }) }}</span>
                  <a class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-500 hover:text-stone-700" :href="`https://x.com/${account.screen_name}`" target="_blank" rel="noopener noreferrer">x.com/{{ account.screen_name }} ↗</a>
                  <span v-if="account.last_test_at" class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-400">{{ formatDate(account.last_test_at) }}</span>
                </div>
                <p v-if="account.note" class="mt-2 line-clamp-2 text-xs leading-5 text-stone-500">{{ account.note }}</p>
              </div>
              <div class="flex shrink-0 flex-wrap gap-1.5">
                <button class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-medium text-stone-500 hover:bg-stone-50" @click="editAccount(account)">{{ t('common.edit') }}</button>
                <button
                  class="rounded-full border px-2.5 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
                  :class="account.enabled ? 'border-stone-200 bg-stone-50 text-stone-500 hover:bg-stone-100' : 'border-green-200 bg-green-50 text-green-700 hover:bg-green-100'"
                  :disabled="togglingId !== null"
                  @click="toggleAccount(account)"
                >
                  {{ t(account.enabled ? 'monitor.xWatch.disable' : 'monitor.xWatch.enable') }}
                </button>
                <button
                  class="rounded-full border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-xs font-medium text-cyan-700 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="testingId !== null"
                  @click="testAccount(account)"
                >
                  {{ t(testingId === account.id ? 'monitor.testing' : 'monitor.test') }}
                </button>
                <button class="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50" :disabled="deletingId !== null" @click="removeAccount(account)">{{ t('common.delete') }}</button>
              </div>
            </div>
            <div v-if="account.last_test_message" class="mt-3 rounded-2xl border px-3 py-2 text-xs leading-5" :class="account.last_test_status === 'success' ? 'border-green-100 bg-green-50 text-green-700' : 'border-rose-100 bg-rose-50 text-rose-600'">
              {{ account.last_test_message }}
              <span v-if="account.last_test_at" class="ml-1 opacity-70">· {{ formatDate(account.last_test_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
