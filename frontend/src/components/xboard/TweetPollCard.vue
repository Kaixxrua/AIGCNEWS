<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TweetPoll } from '@/features/dashboard/dashboardViewModel'

const props = withDefaults(defineProps<{
  poll: TweetPoll
  url: string
  context?: 'wall' | 'detail'
}>(), { context: 'wall' })
const { t, locale } = useI18n()
const total = computed(() => props.poll.total_votes)
const maxVotes = computed(() => Math.max(...props.poll.choices.map((choice) => choice.votes ?? 0)))
const percentage = (votes: number | null) => (
  votes === null || total.value === null ? null : (total.value > 0 ? votes / total.value * 100 : 0)
)
const formatPercent = (value: number) => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }).format(value) + '%'
</script>

<template>
  <section
    class="tweet-poll"
    :class="context === 'detail' ? 'mx-4 my-2' : 'mx-1 mt-2'"
    :aria-label="t('xboard.pollResults')"
  >
    <ol class="tweet-poll-choices">
      <li
        v-for="(choice, index) in poll.choices"
        :key="index"
        class="tweet-poll-choice"
        :class="{ 'tweet-poll-choice--winner': poll.is_final && total && choice.votes === maxVotes }"
      >
        <span
          class="tweet-poll-bar"
          :style="{ width: (percentage(choice.votes) ?? 0) + '%' }"
          aria-hidden="true"
        />
        <span class="tweet-poll-label">{{ choice.label }}</span>
        <span v-if="percentage(choice.votes) !== null" class="tweet-poll-percent">
          {{ formatPercent(percentage(choice.votes)!) }}
        </span>
      </li>
    </ol>
    <p class="tweet-poll-footer">
      <span>{{ total === null ? t('xboard.pollNoCounts') : t('xboard.pollVotes', { count: total.toLocaleString(locale) }) }} · {{ t(poll.is_final ? 'xboard.pollFinal' : 'xboard.pollCurrent') }}</span>
      <a :href="url" target="_blank" rel="noopener noreferrer" @click.stop>{{ t('xboard.viewOnX') }}</a>
    </p>
  </section>
</template>

<style scoped>
.tweet-poll { color: var(--ink); font-size: 12px; line-height: 18px; }
.tweet-poll-choices { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
.tweet-poll-choice { position: relative; display: flex; align-items: center; gap: 8px; overflow: hidden; min-height: 32px; padding: 6px 10px; border: 1px solid var(--rule); border-radius: 4px; }
.tweet-poll-bar { position: absolute; inset: 0 auto 0 0; background: var(--rule); opacity: 0.55; }
.tweet-poll-choice--winner { font-weight: 700; border-color: var(--ink); }
.tweet-poll-choice--winner .tweet-poll-bar { background: var(--acid); opacity: 0.55; }
.tweet-poll-label { position: relative; flex: 1; min-width: 0; overflow-wrap: anywhere; }
.tweet-poll-percent { position: relative; flex: none; font-variant-numeric: tabular-nums; }
.tweet-poll-footer { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; margin-top: 6px; color: var(--ink-muted); font-size: 11px; }
.tweet-poll-footer a { text-decoration: underline; text-underline-offset: 2px; }
.tweet-poll-footer a:hover { color: var(--ink); }
</style>
