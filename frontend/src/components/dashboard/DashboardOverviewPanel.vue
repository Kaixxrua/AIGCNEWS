<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import GlassCalendar from '@/components/GlassCalendar.vue'
import {
  isSourceStatCard,
  statCards,
  visitorCards,
  type TabKey,
} from '@/features/dashboard/dashboardViewModel'

defineProps<{
  loading: boolean
  activeTab: TabKey
  currentDate: string
  availableDates: string[]
  getAnimatedValue: (index: number) => string
  getVisitorDisplayValue: (cardKey: string, index: number) => string
}>()

const { t } = useI18n()

const emit = defineEmits<{
  selectSource: [key: TabKey]
  dateChange: [date: string]
}>()
</script>

<template>
  <div v-if="loading" class="flex flex-col gap-2 shrink-0 md:flex-row md:items-start">
    <div class="flex-1 flex flex-col gap-2">
      <div class="grid gap-2 grid-cols-2 sm:grid-cols-3">
        <div v-for="i in 6" :key="i" class="glass-card h-[44px] animate-pulse" />
      </div>
      <div class="grid gap-2 grid-cols-2">
        <div v-for="i in 2" :key="'v'+i" class="glass-card h-[44px] animate-pulse" />
      </div>
    </div>
    <div class="w-[170px] shrink-0 glass-card h-[150px] animate-pulse" />
  </div>

  <div v-else class="flex flex-col gap-2 shrink-0 md:flex-row md:items-start">
    <div class="flex-1 flex flex-col gap-2">
      <!-- 6 个数据源卡片 -->
      <div class="grid gap-2 grid-cols-2 sm:grid-cols-3">
        <template v-for="(card, index) in statCards" :key="card.key">
          <button
            v-if="isSourceStatCard(card.key)"
            type="button"
            class="dashboard-source-card stagger-enter h-[44px] px-2.5 flex items-center justify-between transition-colors"
            :class="[activeTab === card.key ? 'dashboard-source-card--active' : '', 'glass-card card-hover']"
            :style="{ animationDelay: (index * 0.08 + 0.1) + 's' }"
            :aria-pressed="activeTab === card.key"
            :aria-label="t('dashboard.sourceRanking', { source: t(`dashboard.stats.${card.labelKey}`) })"
            @click="emit('selectSource', card.key)"
          >
            <span class="flex items-center gap-2">
              <span class="w-6 h-6 rounded-full flex items-center justify-center shrink-0" :class="[card.iconBg, card.iconColor]">
                <span class="w-3 h-3 flex items-center justify-center" v-html="card.icon" />
              </span>
              <span class="text-xs font-medium" :class="card.labelColor || 'text-stone-500'">{{ t(`dashboard.stats.${card.labelKey}`) }}</span>
            </span>
            <span class="text-lg font-bold tabular-nums" :class="card.numColor">{{ getAnimatedValue(index) }}</span>
          </button>
          <div
            v-else
            class="stagger-enter h-[44px] px-2.5 flex items-center justify-between transition-colors rounded-xl shadow-sm"
            :class="card.cardBg"
            :style="{ animationDelay: (index * 0.08 + 0.1) + 's' }"
          >
            <span class="flex items-center gap-2">
              <span class="w-6 h-6 rounded-full flex items-center justify-center shrink-0" :class="[card.iconBg, card.iconColor]">
                <span class="w-3 h-3 flex items-center justify-center" v-html="card.icon" />
              </span>
              <span class="text-xs font-medium" :class="card.labelColor">{{ t(`dashboard.stats.${card.labelKey}`) }}</span>
            </span>
            <span class="text-lg font-bold tabular-nums" :class="card.numColor">{{ getAnimatedValue(index) }}</span>
          </div>
        </template>
      </div>

      <!-- 2 个运营统计卡片 -->
      <div class="grid gap-2 grid-cols-2">
        <div
          v-for="(card, index) in visitorCards"
          :key="card.key"
          class="stagger-enter glass-card h-[44px] px-2.5 flex items-center justify-between transition-colors"
          :style="{ animationDelay: (index * 0.08 + 0.6) + 's' }"
        >
          <div class="flex items-center gap-2">
            <div class="w-6 h-6 rounded-full flex items-center justify-center shrink-0" :class="[card.iconBg, card.iconColor]">
              <span class="w-3 h-3 flex items-center justify-center" v-html="card.icon" />
            </div>
            <span class="text-xs font-medium text-stone-400">{{ t(`dashboard.stats.${card.labelKey}`) }}</span>
          </div>
          <span class="text-lg font-bold tabular-nums" :class="card.numColor">{{ getVisitorDisplayValue(card.key, index) }}</span>
        </div>
      </div>
      <!-- 快捷入口 -->
      <div class="grid gap-2">
        <RouterLink
          to="/wechat"
          class="stagger-enter glass-card card-hover flex h-[44px] items-center justify-between px-2.5 transition-colors"
          :style="{ animationDelay: '0.7s' }"
        >
          <span class="flex items-center gap-2">
            <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
              <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9.5 4C5.36 4 2 6.91 2 10.5c0 1.96 1.13 3.72 2.94 4.96L4 19l3.85-1.93c.67.18 1.38.28 2.12.28.23 0 .46-.01.68-.03"/>
                <path d="M14.5 9c3.87 0 7 2.69 7 6s-3.13 6-7 6c-.63 0-1.24-.06-1.83-.18L11 21.5l.5-2.5c-1.5-1.1-2.5-2.77-2.5-4.62 0-3.31 3.13-6 7-6z"/>
              </svg>
            </span>
            <span class="text-xs font-medium text-stone-500">{{ t('wechat.panelTitle') }}</span>
          </span>
          <svg class="h-4 w-4 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </RouterLink>
      </div>
    </div>

    <!-- 日历 -->
    <div class="w-full shrink-0 md:w-[170px]">
      <GlassCalendar
        :model-value="currentDate"
        :available-dates="availableDates"
        @update:model-value="emit('dateChange', $event)"
      />
    </div>
  </div>
</template>
