<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AssessmentClaim, ProjectAssessment } from '@/features/projects/projectAssessment'

const props = defineProps<{ assessment?: ProjectAssessment | null; repoId: string }>()
const { locale, t } = useI18n()
const groups = ['value', 'audience', 'setup', 'limitations'] as const
const copy = (claim: AssessmentClaim) => locale.value === 'zh-CN' ? claim.text_zh : claim.text_en
const evidence = computed(() => {
  const review = props.assessment
  if (!review) return []
  return [...new Map([
    ...(review.relevance_evidence ? [review.relevance_evidence] : []),
    ...groups.flatMap(key => review[key]),
  ].map(claim => [claim.source + claim.quote, claim])).values()]
})
const sourceUrl = (source: AssessmentClaim['source']) => /^[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+$/.test(props.repoId)
  ? `https://github.com/${props.repoId}${source === 'readme' ? '#readme' : ''}` : undefined
const date = computed(() => props.assessment?.assessed_at.slice(0, 10))
</script>

<template>
  <section class="project-assessment" :aria-label="t('projectAssessment.title')">
    <header>
      <h3>{{ t('projectAssessment.title') }}</h3>
      <span :class="{ 'is-evaluate': assessment?.decision === 'evaluate' }">{{ t(`projectAssessment.${assessment?.decision ?? 'unassessed'}`) }}</span>
    </header>
    <template v-if="assessment">
      <p v-if="assessment.relevance_evidence" class="project-assessment__relevance">{{ copy(assessment.relevance_evidence) }}</p>
      <dl>
        <div v-for="key in groups" :key="key">
          <dt>{{ t(`projectAssessment.${key}`) }}</dt>
          <dd>
            <p v-for="claim in assessment[key]" :key="claim.text_en">{{ copy(claim) }}</p>
            <p v-if="!assessment[key].length" class="project-assessment__note">{{ t('projectAssessment.unknown') }}</p>
          </dd>
        </div>
      </dl>
      <p class="project-assessment__license">{{ assessment.license_spdx_id && assessment.license_spdx_id !== 'NOASSERTION' ? t('projectAssessment.license') + ' · ' + assessment.license_spdx_id : t('projectAssessment.licenseUnknown') }}</p>
      <details v-if="evidence.length" class="project-assessment__evidence">
        <summary>{{ t('projectAssessment.sources') }}</summary>
        <figure v-for="claim in evidence" :key="claim.source + claim.quote">
          <blockquote>{{ claim.quote }}</blockquote>
          <figcaption><a :href="sourceUrl(claim.source)" target="_blank" rel="noopener noreferrer">{{ claim.source === 'readme' ? 'README' : 'GitHub' }} ↗</a></figcaption>
        </figure>
      </details>
      <p class="project-assessment__note">{{ t('projectAssessment.basis') }} <time :datetime="assessment.assessed_at">{{ t('projectAssessment.asOf', { date }) }}</time></p>
    </template>
    <p v-else class="project-assessment__note">{{ t('projectAssessment.pending') }}</p>
  </section>
</template>

<style scoped>
.project-assessment { grid-column: 1 / -1; min-width: 0; padding: 14px; border: 1px solid var(--ink-border, #ccc); border-radius: 10px; color: var(--ink-primary); background: var(--surface-page, transparent); font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
header { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
h3 { margin: 0; font-size: 14px; font-weight: 750; }
header span { padding: 1px 7px; border: 1px solid currentColor; border-radius: 4px; font-size: 11px; }
header .is-evaluate { color: var(--ink-primary); background: var(--accent-lime, #e4f57a); }
dl, dd, p, figure { margin: 0; }
dl > div { margin: 10px 0; }
dt { font-weight: 700; }
dd p + p { margin-top: 4px; }
.project-assessment__relevance, .project-assessment__license { margin: 8px 0; }
.project-assessment__note { color: var(--ink-secondary); font-size: 12px; }
summary { cursor: pointer; font-weight: 600; padding: 6px 0; }
figure { margin: 8px 0; }
blockquote { margin: 0; padding-left: 10px; border-left: 2px solid var(--ink-border, #ccc); white-space: pre-wrap; }
figcaption { margin: 3px 0 0 12px; font-size: 12px; }
a { color: inherit; text-decoration: underline; }
time { white-space: nowrap; }
</style>
