<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import type { MembershipUserItem } from '@/features/monitor/monitorModel'
import { formatDate } from '@/features/monitor/monitorViewModel'

const props = defineProps<{
  items: MembershipUserItem[]
  total: number
  page: number
  totalPages: number
  loading: boolean
  query: string
}>()
const emit = defineEmits<{
  'update:query': [value: string]
  'go-page': [page: number]
  edit: [user: MembershipUserItem]
}>()
const { t } = useI18n()
const pageTargets = computed(() => {
  const start = Math.max(1, props.page - 2)
  const end = Math.min(props.totalPages, props.page + 2)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
})
</script>

<template>
  <section class="stagger-enter glass-card overflow-hidden flex flex-col">
    <div class="monitor-divider flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
      <div>
        <h2 class="monitor-section-title">{{ t('monitor.membership.usersTitle') }}</h2>
        <p class="monitor-caption">{{ t('monitor.membership.usersHint') }}</p>
      </div>
      <span class="monitor-badge">{{ t('monitor.totalItems', { count: total }) }}</span>
    </div>
    <div class="flex gap-2 px-5 py-4">
      <input
        :value="query"
        type="search"
        class="input min-w-0 flex-1"
        :placeholder="t('monitor.membership.searchPlaceholder')"
        @input="emit('update:query', ($event.target as HTMLInputElement).value)"
      >
      <button v-if="query" type="button" class="monitor-btn-secondary" @click="emit('update:query', '')">{{ t('common.clear') }}</button>
    </div>
    <div class="overflow-x-auto">
      <table class="monitor-table">
        <thead><tr>
          <th>{{ t('monitor.membership.email') }}</th><th>{{ t('monitor.membership.phone') }}</th>
          <th>{{ t('monitor.membership.username') }}</th><th>{{ t('monitor.membership.role') }}</th>
          <th>{{ t('monitor.membership.tier') }}</th><th>{{ t('monitor.membership.registeredAt') }}</th><th>{{ t('monitor.membership.action') }}</th>
        </tr></thead>
        <tbody>
          <tr v-if="loading"><td colspan="7"><SpinnerLoader class="min-h-[72px]" :size="22" /></td></tr>
          <tr v-else-if="!items.length"><td colspan="7" class="text-center">{{ t('monitor.membership.emptyUsers') }}</td></tr>
          <tr v-for="user in items" v-else :key="user.user_id">
            <td>{{ user.email || '—' }}</td><td>{{ user.phone || '—' }}</td><td>{{ user.username || '—' }}</td>
            <td><span class="badge">{{ user.role }}</span><span v-if="user.disabled" class="badge monitor-status-error ml-1">{{ t('monitor.membership.disabled') }}</span></td>
            <td><span class="badge">{{ user.effective_tier === 'member' ? t('monitor.membership.tierOption.member') : t('monitor.membership.tierOption.free') }}</span><div class="monitor-caption mt-1">{{ formatDate(user.membership_expires_at) }}</div></td>
            <td>{{ formatDate(user.created_at) }}</td>
            <td><button type="button" class="monitor-btn-secondary" @click="emit('edit', user)">{{ t('monitor.membership.editUser') }}</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="totalPages > 1" class="monitor-divider flex flex-wrap items-center justify-between gap-3 border-t px-5 py-3">
      <span class="monitor-caption">{{ t('monitor.pageSummary', { page, totalPages, total }) }}</span>
      <div class="flex items-center gap-1">
        <button class="monitor-pagination-btn" :disabled="page <= 1" @click="emit('go-page', page - 1)">{{ t('monitor.previous') }}</button>
        <button v-for="target in pageTargets" :key="target" class="monitor-pagination-btn" :class="{ active: target === page }" @click="emit('go-page', target)">{{ target }}</button>
        <button class="monitor-pagination-btn" :disabled="page >= totalPages" @click="emit('go-page', page + 1)">{{ t('monitor.next') }}</button>
      </div>
    </div>
  </section>
</template>
