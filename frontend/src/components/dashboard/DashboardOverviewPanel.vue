<script setup lang="ts">
import GlassCalendar from '../GlassCalendar.vue'
import {
  isSourceStatCard,
  statCards,
  visitorCards,
  type TabKey,
} from '../../features/dashboard/dashboardViewModel'

defineProps<{
  loading: boolean
  activeTab: TabKey
  currentDate: string
  availableDates: string[]
  getAnimatedValue: (index: number) => string
  getVisitorDisplayValue: (cardKey: string, index: number) => string
}>()

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
            :aria-label="`查看${card.label}排行榜`"
            @click="emit('selectSource', card.key)"
          >
            <span class="flex items-center gap-2">
              <span class="w-6 h-6 rounded-full flex items-center justify-center shrink-0" :class="[card.iconBg, card.iconColor]">
                <span class="w-3 h-3 flex items-center justify-center" v-html="card.icon" />
              </span>
              <span class="text-xs font-medium" :class="card.labelColor || 'text-stone-500'">{{ card.label }}</span>
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
              <span class="text-xs font-medium" :class="card.labelColor">{{ card.label }}</span>
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
            <span class="text-xs font-medium text-stone-400">{{ card.label }}</span>
          </div>
          <span class="text-lg font-bold tabular-nums" :class="card.numColor">{{ getVisitorDisplayValue(card.key, index) }}</span>
        </div>
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
