<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatLocaleDate } from '@/i18n/formatters'

const { t } = useI18n()

const props = defineProps<{
  modelValue?: string
  availableDates?: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [date: string]
}>()

const today = new Date()
const viewYear = ref(today.getFullYear())
const viewMonth = ref(today.getMonth())

const monthLabel = computed(() => formatLocaleDate(new Date(viewYear.value, viewMonth.value, 1), { year: 'numeric', month: 'long' }))
const weekdayLabels = computed(() => Array.from({ length: 7 }, (_, day) => formatLocaleDate(new Date(2023, 0, day + 1), { weekday: 'narrow' })))

const prevMonth = () => {
  if (viewMonth.value === 0) { viewMonth.value = 11; viewYear.value-- }
  else { viewMonth.value-- }
}

const nextMonth = () => {
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

const calendarDays = computed<CalendarDay[]>(() => {
  const year = viewYear.value
  const month = viewMonth.value
  const firstDay = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const daysInPrevMonth = new Date(year, month, 0).getDate()
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  const days: CalendarDay[] = []

  for (let i = firstDay - 1; i >= 0; i--) {
    const d = daysInPrevMonth - i
    const m = month === 0 ? 12 : month
    const y = month === 0 ? year - 1 : year
    const dateStr = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    days.push({ date: dateStr, day: d, inMonth: false, isToday: dateStr === todayStr, hasSnapshot: availableSet.value.has(dateStr) })
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    days.push({ date: dateStr, day: d, inMonth: true, isToday: dateStr === todayStr, hasSnapshot: availableSet.value.has(dateStr) })
  }

  // 最多显示 35 格（5 行），减少日历高度
  const totalCells = days.length <= 35 ? 35 : 42
  const remaining = totalCells - days.length
  for (let d = 1; d <= remaining; d++) {
    const m = month === 11 ? 1 : month + 2
    const y = month === 11 ? year + 1 : year
    const dateStr = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    days.push({ date: dateStr, day: d, inMonth: false, isToday: dateStr === todayStr, hasSnapshot: availableSet.value.has(dateStr) })
  }

  return days
})

const selectedDate = computed(() => props.modelValue || '')

const selectDate = (day: CalendarDay) => {
  if (!day.hasSnapshot) return
  emit('update:modelValue', day.date)
}
</script>

<template>
  <div
    class="stagger-enter flex flex-col rounded-xl px-2 py-1.5"
    style="
      background: rgba(255, 255, 255, 0.85);
      backdrop-filter: blur(16px) saturate(180%);
      -webkit-backdrop-filter: blur(16px) saturate(180%);
      border: 1px solid rgba(168, 162, 158, 0.20);
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.03);
      animation-delay: 0.15s;
    "
  >
    <div class="flex items-center justify-between mb-1">
      <h3 class="text-2xs font-semibold text-stone-700 tracking-tight font-serif">{{ monthLabel }}</h3>
      <div class="flex items-center gap-0.5">
        <button
          class="flex h-5 w-5 items-center justify-center rounded-full text-stone-500 transition hover:bg-accent-soft hover:text-ink"
          :aria-label="t('dashboard.previousMonth')" @click="prevMonth"
        >
          <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <button
          class="flex h-5 w-5 items-center justify-center rounded-full text-stone-500 transition hover:bg-accent-soft hover:text-ink"
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
        class="text-center font-medium text-stone-400 select-none" style="font-size: 9px; line-height: 16px"
      >
        {{ label }}
      </span>
    </div>

    <div class="grid grid-cols-7">
      <button
        v-for="(day, idx) in calendarDays"
        :key="idx"
        class="calendar-day"
        :class="{
          'text-stone-300': !day.inMonth,
          'text-stone-600': day.inMonth && selectedDate !== day.date && !day.isToday && day.hasSnapshot,
          'calendar-day--today': day.isToday && selectedDate !== day.date,
          'calendar-day--active': selectedDate === day.date,
          'calendar-day--has-snapshot': day.hasSnapshot && selectedDate !== day.date,
          'calendar-day--disabled': !day.hasSnapshot && selectedDate !== day.date,
        }"
        :disabled="!day.hasSnapshot"
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
.calendar-day {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 20px;
  font-size: 9px;
  font-weight: 500;
  border-radius: 50%;
  transition: all 0.15s ease;
  cursor: pointer;
  user-select: none;
}

.calendar-day:hover:not(:disabled) {
  color: var(--acid-ink);
  background: var(--acid-soft);
}

.calendar-day--disabled,
.calendar-day:disabled {
  cursor: default;
  opacity: 0.30;
  pointer-events: none;
}

.calendar-day--today {
  color: #44403c; /* stone-700 */
  font-weight: 700;
  background: #f5f5f4; /* stone-100 */
}

.calendar-day--active {
  color: var(--acid-ink) !important;
  background: var(--acid) !important;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px var(--rule-strong);
}

.calendar-day--active:hover {
  color: var(--acid-ink) !important;
  background: var(--acid) !important;
}

.calendar-day--has-snapshot {
  font-weight: 700;
}

.snapshot-dot {
  position: absolute;
  bottom: 0px;
  left: 50%;
  transform: translateX(-50%);
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: #a8a29e; /* stone-400 */
  pointer-events: none;
}
</style>
