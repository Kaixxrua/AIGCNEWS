<script setup lang="ts">
import { useId } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SameDayPaper } from '@/features/papers/paperHead'

defineProps<{ entries: SameDayPaper[] }>()
const { t } = useI18n()
const headingId = `paper-same-day-${useId()}`
</script>

<template>
  <nav class="paper-same-day" :aria-labelledby="headingId">
    <h2 :id="headingId" class="paper-same-day-title">{{ t('paper.sameDay.title') }}</h2>
    <ol class="paper-same-day-list motion-stagger">
      <li v-for="entry in entries" :key="entry.id">
        <RouterLink
          :to="{ name: 'paper-read', params: { id: entry.id } }"
          class="paper-same-day-link"
          :class="{ 'is-current': entry.current }"
          :aria-current="entry.current ? 'page' : undefined"
        >
          <span class="paper-same-day-rank" aria-hidden="true">{{ entry.rank }}</span>
          <span class="paper-same-day-name">{{ entry.title }}</span>
          <span v-if="entry.upvotes" class="paper-same-day-votes"><span class="sr-only">{{ t('paper.sameDay.upvotes') }}</span>{{ entry.upvotes }}</span>
        </RouterLink>
      </li>
    </ol>
  </nav>
</template>
