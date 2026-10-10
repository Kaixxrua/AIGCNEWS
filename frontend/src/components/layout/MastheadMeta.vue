<script setup lang="ts">
import { computed } from 'vue'
import { useNow } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import RollingNumber from '@/components/dashboard/RollingNumber.vue'
import { useTodayNewCount } from '@/composables/useTodayNewCount'

/* 顶栏报头信息：日期 + 今日更新计数，报纸刊头式两行小字。
   定位在顶栏左区（绝对定位，不参与居中 flex 排布），窄屏隐藏避免挤压字标。
   计数的数据源、实时推送（SSE 事件流）与滚筒动画均与首页仪表盘一致（见 useTodayNewCount）。 */
const { t, locale } = useI18n()
const { todayNewCount } = useTodayNewCount()

/* 今日统计使用北京时间；定期刷新，长驻页面也能跨日。 */
const now = useNow({ interval: 30_000 })
const dateLine = computed(() =>
  new Intl.DateTimeFormat(locale.value, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    weekday: 'short',
    timeZone: 'Asia/Shanghai',
  }).format(now.value),
)
</script>

<template>
  <div class="masthead-meta">
    <span class="masthead-meta__date">{{ dateLine }}</span>
    <span class="masthead-meta__today">
      {{ t('masthead.todayNew') }}
      <RollingNumber :value="todayNewCount" class="masthead-meta__count" />
    </span>
  </div>
</template>

<style scoped>
.masthead-meta {
  position: absolute;
  left: 24px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  gap: 1px;
  font-size: 10px;
  line-height: 1.25;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  user-select: none;
  pointer-events: none;
  white-space: nowrap;
}

.masthead-meta__today {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}

.masthead-meta__count {
  font-weight: 800;
  letter-spacing: 0;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

/* 窄屏隐藏：避免与居中字标/工具组挤压 */
@media (max-width: 767px) {
  .masthead-meta {
    display: none;
  }
}
</style>
