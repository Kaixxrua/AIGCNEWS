<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatLocaleDate } from '@/i18n/formatters'
import { vIndicator } from '@/motion/indicator'
import { vSwap } from '@/motion/swap'

const { t } = useI18n()

const props = defineProps<{
  modelValue?: string
  availableDates?: string[]
  todayDate?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [date: string]
}>()

const todayStr = computed(() => props.todayDate || new Date(Date.now() + 8 * 3_600_000).toISOString().slice(0, 10))
const viewYear = ref(Number(todayStr.value.slice(0, 4)))
const viewMonth = ref(Number(todayStr.value.slice(5, 7)) - 1)

const monthLabel = computed(() => formatLocaleDate(new Date(viewYear.value, viewMonth.value, 1), { year: 'numeric', month: 'long' }))
const weekdayLabels = computed(() => Array.from({ length: 7 }, (_, day) => formatLocaleDate(new Date(2023, 0, day + 1), { weekday: 'narrow' })))

// 翻月方向：日期网格与月份标题从翻页的方向滑入。
const monthStep = ref(0)
const monthKey = computed(() => viewYear.value * 12 + viewMonth.value)

const prevMonth = () => {
  monthStep.value = -1
  if (viewMonth.value === 0) { viewMonth.value = 11; viewYear.value-- }
  else { viewMonth.value-- }
}

const nextMonth = () => {
  monthStep.value = 1
  if (viewMonth.value === 11) { viewMonth.value = 0; viewYear.value++ }
  else { viewMonth.value++ }
}

const availableSet = computed(() => new Set(props.availableDates ?? []))

interface CalendarDay {
  date: string
  day: number
  inMonth: boolean
  isToday: boolean
  hasSnapshot: boolean
}

// 快照清单只用于提示数据可用性；缺少快照的历史日期仍可查询并展示空态。
const canSelectDate = (day: CalendarDay) => day.date <= todayStr.value

const calendarDays = computed<CalendarDay[]>(() => {
  const year = viewYear.value
  const month = viewMonth.value
  const firstDay = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const daysInPrevMonth = new Date(year, month, 0).getDate()
  const days: CalendarDay[] = []

  for (let i = firstDay - 1; i >= 0; i--) {
    const d = daysInPrevMonth - i
    const m = month === 0 ? 12 : month
    const y = month === 0 ? year - 1 : year
    const dateStr = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    days.push({ date: dateStr, day: d, inMonth: false, isToday: dateStr === todayStr.value, hasSnapshot: availableSet.value.has(dateStr) })
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    days.push({ date: dateStr, day: d, inMonth: true, isToday: dateStr === todayStr.value, hasSnapshot: availableSet.value.has(dateStr) })
  }

  // 最多显示 35 格（5 行），减少日历高度
  const totalCells = days.length <= 35 ? 35 : 42
  const remaining = totalCells - days.length
  for (let d = 1; d <= remaining; d++) {
    const m = month === 11 ? 1 : month + 2
    const y = month === 11 ? year + 1 : year
    const dateStr = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    days.push({ date: dateStr, day: d, inMonth: false, isToday: dateStr === todayStr.value, hasSnapshot: availableSet.value.has(dateStr) })
  }

  return days
})

const selectedDate = computed(() => props.modelValue || '')

const selectDate = (day: CalendarDay) => {
  if (!canSelectDate(day)) return
  emit('update:modelValue', day.date)
}
</script>

<template>
  <div class="dash-calendar stagger-enter flex flex-col px-2 py-1.5" style="animation-delay: 0.2s">
    <div class="flex items-center justify-between mb-1">
      <h3 v-swap="{ key: monthKey, x: monthStep * 8, y: 0 }" class="text-2xs font-semibold text-stone-700 tracking-tight font-serif">{{ monthLabel }}</h3>
      <div class="flex items-center gap-0.5">
        <button
          class="cal-nav"
          :aria-label="t('dashboard.previousMonth')" @click="prevMonth"
        >
          <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <button
          class="cal-nav"
          :aria-label="t('dashboard.nextMonth')" @click="nextMonth"
        >
          <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </div>
    </div>

    <div class="grid grid-cols-7">
      <span
        v-for="(label, weekdayIndex) in weekdayLabels"
        :key="weekdayIndex"
        class="text-center font-medium text-stone-400 select-none" style="font-size: 12px; line-height: 20px"
      >
        {{ label }}
      </span>
    </div>

    <!-- 选中日期的荧光块由 v-indicator 画在网格上，换日期时从旧格子弹到新格子。 -->
    <div v-indicator="{ active: '.calendar-day--active', flip: true }" v-swap="{ key: monthKey, x: monthStep * 18, y: 0 }" class="calendar-days grid grid-cols-7">
      <button
        v-for="(day, idx) in calendarDays"
        :key="idx"
        class="calendar-day"
        :class="{
          'text-stone-300': !day.inMonth,
          'text-stone-600': day.inMonth && selectedDate !== day.date && !day.isToday && canSelectDate(day),
          'calendar-day--today': day.isToday && selectedDate !== day.date,
          'calendar-day--active': selectedDate === day.date,
          'calendar-day--has-snapshot': day.hasSnapshot && selectedDate !== day.date,
          'calendar-day--disabled': !canSelectDate(day) && selectedDate !== day.date,
        }"
        :disabled="!canSelectDate(day)"
        :aria-label="day.date"
        :aria-pressed="selectedDate === day.date"
        :title="day.hasSnapshot ? t('dashboard.snapshotAvailable', { date: day.date }) : day.date"
        @click="selectDate(day)"
      >
        {{ day.day }}
        <span
          v-if="day.hasSnapshot && selectedDate !== day.date"
          class="snapshot-dot"
        />
      </button>
    </div>
  </div>
</template>

<style scoped>
/* 使用共享纸面与控件尺寸，日期选择保留强调色。 */
.dash-calendar {
  border: 1px solid var(--rule);
  border-radius: var(--module-radius);
  background: var(--paper-light);
  box-shadow: none;
}

.cal-nav {
  display: flex;
  height: 28px;
  width: 28px;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 4px;
  color: var(--muted, #797a70);
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}

.cal-nav:hover {
  border-color: var(--ink);
  background: var(--acid-soft);
  color: var(--ink);
}

.calendar-day {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 26px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 4px;
  transition: background-color 0.15s ease, color 0.15s ease;
  cursor: pointer;
  user-select: none;
}

.calendar-day:hover:not(:disabled) {
  color: var(--ink);
  background: var(--acid-soft);
  box-shadow: inset 0 0 0 1px var(--ink);
}

.calendar-day--disabled,
.calendar-day:disabled {
  cursor: default;
  opacity: 0.30;
  pointer-events: none;
}

.calendar-day--today {
  color: var(--ink);
  font-weight: 700;
  box-shadow: inset 0 0 0 1px var(--ink);
}

.calendar-day--active {
  color: var(--acid-ink) !important;
  background: var(--acid) !important;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px var(--ink) !important;
}

.calendar-days { position: relative; isolation: isolate; }
.calendar-days::before { z-index: -1; border-radius: 4px; background: var(--acid); box-shadow: inset 0 0 0 1px var(--ink); }
.calendar-days[data-indicator] .calendar-day--active { background: transparent !important; box-shadow: none !important; }

.calendar-day--active:hover {
  color: var(--acid-ink) !important;
  background: var(--acid) !important;
}

.calendar-day--has-snapshot {
  font-weight: 700;
}

.snapshot-dot {
  position: absolute;
  bottom: 1px;
  left: 50%;
  transform: translateX(-50%);
  width: 3px;
  height: 3px;
  border-radius: 1px;
  background: var(--ink);
  pointer-events: none;
}
@media (max-width: 1023px) {
  .cal-nav { width: 44px; height: 44px; }
  .calendar-day { height: 44px; }
}
</style>
