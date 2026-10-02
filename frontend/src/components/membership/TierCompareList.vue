<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, X } from 'lucide-vue-next'
import { compareColumn, type CompareTier } from '@/features/membership/membershipCompare'

// 桌面对比表里一档的那一列：逐行和左侧的行名对齐。行名那一列只给眼睛看，读屏从每格开头的隐藏行名读出这一格是哪项权益。
const props = defineProps<{ tier: CompareTier }>()
const { t } = useI18n()
const entries = computed(() => compareColumn(props.tier))
</script>

<template>
  <ul class="tier-features tier-features--compare">
    <li v-for="entry in entries" :key="entry.row" :class="{ 'tier-feature--excluded': !entry.included }">
      <Check v-if="entry.included" :size="14" :stroke-width="2.5" class="tier-check" aria-hidden="true" />
      <X v-else :size="14" :stroke-width="2.5" class="tier-x" aria-hidden="true" />
      <span class="tier-cell">
        <span class="sr-only">{{ t('membership.compare.rowLabel', { label: t(`membership.compare.rows.${entry.row}`) }) }}</span>
        <span v-for="line in entry.lines" :key="line" class="tier-cell-line">{{ t(`membership.compare.cells.${line}`) }}</span>
        <span v-if="!entry.lines.length" class="sr-only">{{ entry.included ? t('membership.compare.included') : t('membership.compare.excluded') }}</span>
      </span>
    </li>
  </ul>
</template>
