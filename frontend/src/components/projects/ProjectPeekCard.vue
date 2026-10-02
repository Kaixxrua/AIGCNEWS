<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Star } from 'lucide-vue-next'
import ProjectPeekParts from './ProjectPeekParts.vue'
import type { AppLocale } from '@/i18n'
import { formatLocaleNumber } from '@/i18n/formatters'
import type { PeekContent, PeekCurveState } from '@/composables/useProjectPeek'
import type { GitHubProjectItem } from '@/services/projects/projectApi'
import { formatProjectCount, projectName } from '@/features/projects/projectPresentation'
import type { PeekPlacement } from '@/features/projects/projectPeek'

/**
 * 榜单悬停速览的卡片：README 开头几段（读下去到 GitHub）、默认分支最近一次提交、近 30 天的星标曲线（正文见 ProjectPeekParts）。
 * 榜单够宽时分两栏，左边 README，右边提交压着曲线（.project-peek__side），卡片矮到大多数行旁边都放得下。
 * 摆在行的下面或上面（上面时底边贴着行、往上长），高不过那一边看得见的地方，再多就在卡片里滚。
 * 点卡片里去 GitHub 的链接时发 visit，列表据此把这一行记为看过。
 */
const props = defineProps<{
  repo: GitHubProjectItem
  /** 速览查的仓库（owner/repo） */
  repoId: string
  content: PeekContent
  curve: PeekCurveState
  placement: PeekPlacement
}>()

const emit = defineEmits<{
  visit: [repo: GitHubProjectItem]
}>()

const { locale, t } = useI18n()
const appLocale = computed(() => locale.value as AppLocale)

const name = computed(() => projectName(props.repo) || props.repoId)
const nameParts = computed(() => {
  const slash = name.value.indexOf('/')
  return slash > 0 ? { owner: name.value.slice(0, slash + 1), repo: name.value.slice(slash + 1) } : { owner: '', repo: name.value }
})
const starsText = computed(() => formatProjectCount(props.repo.stars, appLocale.value))
const starsTitle = computed(() => t('projectChart.starsTitle', { count: formatLocaleNumber(Number(props.repo.stars ?? 0), appLocale.value) }))

const style = computed(() => ({ top: `${props.placement.top}px`, '--peek-max': `${props.placement.maxHeight}px` }))
</script>

<template>
  <aside
    class="project-peek"
    :class="{ 'project-peek--above': placement.above }"
    :style="style"
    :aria-label="t('projectPeek.label', { name })"
    data-project-peek
  >
    <div class="project-peek__scroll">
      <header class="project-peek__head">
        <span class="project-peek__name"><span class="project-peek__owner">{{ nameParts.owner }}</span><wbr />{{ nameParts.repo }}</span>
        <span class="project-peek__stars" :title="starsTitle"><Star :size="12" :stroke-width="2" aria-hidden="true" />{{ starsText }}</span>
      </header>

      <ProjectPeekParts :repo="repo" :repo-id="repoId" :content="content" :curve="curve" @visit="emit('visit', $event)" />
    </div>
  </aside>
</template>
