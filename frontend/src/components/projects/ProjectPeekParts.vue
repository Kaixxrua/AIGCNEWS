<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight } from 'lucide-vue-next'
import ProjectPeekCurve from './ProjectPeekCurve.vue'
import type { AppLocale } from '@/i18n'
import { formatLocaleDate } from '@/i18n/formatters'
import type { PeekContent, PeekCurveState } from '@/composables/useProjectPeek'
import type { GitHubProjectItem } from '@/services/projects/projectApi'
import { formatProjectLastPush } from '@/features/projects/projectPresentation'
import { shortSha } from '@/features/projects/projectPeek'

/**
 * 速览的正文：README 开头几段（读下去到 GitHub）、默认分支最近一次提交、近 30 天的星标曲线（ProjectPeekCurve）。
 * 悬停速览的卡片和宽屏的详情栏共用：README 一节在前，提交压着曲线包在 .project-peek__side 里，摆成一栏还是两栏由外面定；
 * 不给 curve 时不摆曲线（详情栏把它挪到了一组数字下面）。
 * 还没取到的部分先摆骨架；读不到 GitHub 时最近一次提交退回库里记的最近推送。
 * canRetry 时没取到的地方（取失败、读不到 GitHub、曲线没取到）跟一个重试按钮，发 retry。
 * 点里面去 GitHub 的链接时发 visit，列表据此把这一行记为看过。
 */
const props = defineProps<{
  repo: GitHubProjectItem
  /** 速览查的仓库（owner/repo） */
  repoId: string
  content: PeekContent
  curve?: PeekCurveState
  canRetry?: boolean
}>()

const emit = defineEmits<{
  visit: [repo: GitHubProjectItem]
  retry: []
}>()

const { locale, t } = useI18n()
const appLocale = computed(() => locale.value as AppLocale)

const loading = computed(() => props.content.status === 'loading')
const peek = computed(() => (props.content.status === 'ready' ? props.content.peek : null))
const readmeUrl = computed(() => `https://github.com/${props.repoId}#readme`)
const readmeNote = computed(() => {
  if (props.content.status === 'error') return t('projectPeek.failed')
  if (peek.value?.status !== 'ok') return t('projectPeek.unavailable')
  return t(peek.value.has_readme ? 'projectPeek.noProse' : 'projectPeek.noReadme')
})
// 取失败、读不到 GitHub 都能马上再取；README 本来就没有或没有文字介绍的不用
const readmeRetry = computed(() => Boolean(props.canRetry) && (props.content.status === 'error' || (peek.value !== null && peek.value.status !== 'ok')))

const commit = computed(() => peek.value?.commit ?? null)
const commitSha = computed(() => (commit.value ? shortSha(commit.value.sha) : ''))
const commitAgo = computed(() => (commit.value?.committed_at ? formatProjectLastPush(commit.value.committed_at, appLocale.value) : ''))
const commitTime = computed(() => (commit.value?.committed_at
  ? formatLocaleDate(commit.value.committed_at, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }, appLocale.value)
  : ''))
// 读到了 GitHub 却没有提交是空仓库；读不到 GitHub 时退回库里记的最近推送，连它也没有就不摆这一节
const commitNote = computed(() => {
  if (peek.value?.status === 'ok') return t('projectPeek.noCommit')
  const pushed = props.repo.pushed_at ? formatProjectLastPush(props.repo.pushed_at, appLocale.value) : ''
  return pushed ? t('projectPeek.lastPush', { time: pushed }) : ''
})
</script>

<template>
  <section class="project-peek__part project-peek__part--readme" :aria-busy="loading">
    <h3 class="project-peek__label">{{ t('projectPeek.readme') }}</h3>
    <template v-if="loading">
      <span v-for="line in 4" :key="line" class="project-peek__skeleton" />
    </template>
    <template v-else-if="peek && peek.readme.length">
      <p v-for="(paragraph, index) in peek.readme" :key="index" class="project-peek__readme">{{ paragraph }}</p>
      <a
        class="project-peek__link"
        :href="readmeUrl"
        target="_blank"
        rel="noopener noreferrer"
        @click="emit('visit', repo)"
        @auxclick.middle="emit('visit', repo)"
      >{{ t(peek.readme_more ? 'projectPeek.readMore' : 'projectPeek.readOn') }}<ArrowUpRight :size="13" :stroke-width="2.2" aria-hidden="true" /></a>
    </template>
    <p v-else class="project-peek__note">
      {{ readmeNote }}
      <a
        v-if="peek && peek.has_readme"
        class="project-peek__link"
        :href="readmeUrl"
        target="_blank"
        rel="noopener noreferrer"
        @click="emit('visit', repo)"
        @auxclick.middle="emit('visit', repo)"
      >{{ t('projectPeek.readOn') }}<ArrowUpRight :size="13" :stroke-width="2.2" aria-hidden="true" /></a>
      <button v-if="readmeRetry" type="button" class="project-peek__retry" @click="emit('retry')">{{ t('common.retry') }}</button>
    </p>
  </section>

  <div class="project-peek__side">
    <section v-if="loading || commit || commitNote" class="project-peek__part" :aria-busy="loading">
      <h3 class="project-peek__label">{{ t('projectPeek.lastCommit') }}</h3>
      <template v-if="loading">
        <span class="project-peek__skeleton" />
        <span class="project-peek__skeleton is-short" />
      </template>
      <template v-else-if="commit">
        <a
          class="project-peek__commit"
          :href="commit.url"
          target="_blank"
          rel="noopener noreferrer"
          @click="emit('visit', repo)"
          @auxclick.middle="emit('visit', repo)"
        >{{ commit.message || commitSha }}</a>
        <p class="project-peek__facts">
          <code class="project-peek__sha">{{ commitSha }}</code>
          <span v-if="commit.author">{{ commit.author }}</span>
          <time v-if="commitAgo" :datetime="commit.committed_at" :title="commitTime">{{ commitAgo }}</time>
        </p>
      </template>
      <p v-else class="project-peek__note">{{ commitNote }}</p>
    </section>

    <ProjectPeekCurve v-if="curve" :curve="curve" :can-retry="canRetry" @retry="emit('retry')" />
  </div>
</template>
