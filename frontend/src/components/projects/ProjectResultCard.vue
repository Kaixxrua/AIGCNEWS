<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import ProjectLogo from './ProjectLogo.vue'
import ProjectHeat from './ProjectHeat.vue'
import { ExternalLink, Pencil, Sparkles, Star, Trash2 } from 'lucide-vue-next'
import type { AppLocale } from '@/i18n'
import type { GitHubProjectItem, GitHubProjectSort, ProjectScope } from '@/services/projects/projectApi'
import {
  projectDescription,
  favoriteButtonLabelKey,
  formatProjectCount,
  formatProjectLastPush,
  formatProjectShortDate,
  projectDisplayTags,
  isWebsite,
  projectGrowthLabel,
  projectGrowthTitle,
  projectHeatAvailable,
  projectLastPushTitle,
  projectLinkLabelKey,
  projectLogoKey,
  projectName,
  projectNameParts,
  projectSourceBadgeKey,
  projectUrl,
  recommendButtonLabelKey,
  websiteLogoInitial,
  type ProjectChip,
} from '@/features/projects/projectPresentation'

const { locale, t } = useI18n()
const isMobile = useMediaQuery('(max-width: 767px)')

const props = defineProps<{
  catalogLayout?: boolean
  repo: GitHubProjectItem
  index: number
  isPersonalView: boolean
  canFavorite: boolean
  canRecommend: boolean
  canEdit: boolean
  showDelete: boolean
  isLoggedIn: boolean
  favoriteBusy: boolean
  favoriteActionsBusy: boolean
  recommendBusy: boolean
  recommendActionsBusy: boolean
  savingEdit: boolean
  deleting: boolean
  logoLoaded: boolean
  logoBroken: boolean
  sort: GitHubProjectSort
  scope: ProjectScope
}>()

const emit = defineEmits<{
  chipClick: [chip: ProjectChip]
  favorite: [repo: GitHubProjectItem]
  recommend: [repo: GitHubProjectItem]
  edit: [repo: GitHubProjectItem]
  delete: [repo: GitHubProjectItem]
  logoLoaded: [repo: GitHubProjectItem]
  logoBroken: [repo: GitHubProjectItem]
}>()

const allTagsVisible = ref(false)
const nameParts = computed(() => projectNameParts(props.repo))
const logoKey = computed(() => projectLogoKey(props.repo))
const websiteLogoUrl = computed(() => (
  logoKey.value && !props.logoBroken ? (props.repo.image_url || '') : ''
))
const displayTags = computed(() => projectDisplayTags(
  props.repo,
  props.isPersonalView,
  locale.value as AppLocale,
  {
    project: t('projects.genericProjectTag'),
    website: t('projects.genericWebsiteTag'),
  },
))
const description = computed(() => projectDescription(
  props.repo, locale.value as AppLocale,
  t(isWebsite(props.repo) ? 'projects.fallbackWebsite' : 'projects.fallbackProject'),
))
</script>

<template>
  <article
    class="project-card"
    :class="{ 'project-card--catalog': catalogLayout, 'project-card--recommended': repo.is_recommended, 'project-card--not-found': !isWebsite(repo) && repo.availability_status === 'not_found' }"
    :style="{ animationDelay: `${Math.min(index, 12) * 36}ms` }"
  >
    <div class="project-card__body">
      <header class="project-card__header">
        <div class="project-card__identity">
          <ProjectLogo v-if="!isWebsite(repo)" class="project-card__github-logo" :logo="repo.image_url" :repository-url="projectUrl(repo)" :name="projectName(repo)" :unavailable="repo.availability_status === 'not_found'" />
          <div v-if="isWebsite(repo)" class="project-card__logo-shell">
            <span class="project-card__logo-placeholder" aria-hidden="true">
              {{ websiteLogoInitial(repo) }}
            </span>
            <img
              v-if="websiteLogoUrl"
              class="project-card__logo"
              :class="logoLoaded ? 'project-card__logo--loaded' : ''"
              :src="repo.image_url || ''"
              :alt="t('projects.iconAlt', { name: projectName(repo) })"
              width="42"
              height="42"
              decoding="async"
              :loading="index < 6 ? 'eager' : 'lazy'"
              referrerpolicy="no-referrer"
              @load="emit('logoLoaded', repo)"
              @error="emit('logoBroken', repo)"
            />
          </div>
          <div>
            <div class="project-card__source-row">
              <span class="project-card__source">{{ projectSourceBadgeKey(repo) ? t(`projects.${projectSourceBadgeKey(repo)}`) : 'GitHub' }}</span>
              <span
                v-if="!isWebsite(repo) && repo.availability_status === 'not_found'"
                class="project-card__availability"
              >
                {{ t('projects.unavailable') }}
              </span>
            </div>
            <h2 :title="projectName(repo)"><template v-for="(part, partIndex) in nameParts" :key="partIndex"><span class="project-card__name-part">{{ part }}</span><wbr /></template></h2>
            <p v-if="isWebsite(repo) && repo.domain" class="project-card__domain">{{ repo.domain }}</p>
          </div>
        </div>
      </header>

      <p class="project-card__description">
        {{ description }}
      </p>

      <details class="project-card__details" :open="catalogLayout || !isMobile">
        <summary>{{ t('projects.mobileDetails') }}</summary>
        <div class="project-card__metadata">
      <div class="project-card__tags" :aria-label="t('projects.categoryTags')">
        <div class="project-card__tag-list">
        <button
          v-for="chip in (allTagsVisible ? displayTags : displayTags.slice(0, 3))"
          :key="`${chip.type}:${chip.value}`"
          type="button"
          class="badge-default project-chip"
          :class="`project-chip--${chip.type}`"
          @click="emit('chipClick', chip)"
        >
          {{ chip.label }}
        </button>
        </div>
      <button v-if="displayTags.length > 3" type="button" class="project-chip project-chip--more" :aria-expanded="allTagsVisible" :aria-label="t(allTagsVisible ? 'projects.fewerTags' : 'projects.moreTags')" @click="allTagsVisible = !allTagsVisible">{{ allTagsVisible ? '−' : `+${displayTags.length - 3}` }}</button>
      </div>

      <footer class="project-card__stats" :aria-label="t(isWebsite(repo) ? 'projects.websiteInfo' : 'projects.githubMetrics')">
        <template v-if="isWebsite(repo)">
          <span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="M3 12h18" />
              <path d="M12 3a13.5 13.5 0 0 1 0 18" />
              <path d="M12 3a13.5 13.5 0 0 0 0 18" />
            </svg>
            {{ repo.domain || t('projects.websiteFavorite') }}
          </span>
          <span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M8 2v4" />
              <path d="M16 2v4" />
              <rect x="3" y="4" width="18" height="18" rx="2" />
              <path d="M3 10h18" />
            </svg>
            {{ t('projects.collectedOn', { date: formatProjectShortDate(repo.first_seen_at, t('projects.collectedFallback'), locale as AppLocale) }) }}
          </span>
        </template>
        <template v-else>
          <span>
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="m12 2.2 2.9 5.88 6.5.94-4.7 4.58 1.1 6.47L12 17.02l-5.8 3.05 1.1-6.47-4.7-4.58 6.5-.94L12 2.2Z" />
            </svg>
            {{ t('projects.stars', { count: formatProjectCount(repo.stars, locale as AppLocale) }) }}
          </span>
          <span :title="projectGrowthTitle(repo, t, locale as AppLocale)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M3 17l6-6 4 4 8-8" />
              <path d="M15 7h6v6" />
            </svg>
            {{ projectGrowthLabel(repo, t, locale as AppLocale) }}
          </span>
          <ProjectHeat :score="repo.hot_score" :available="projectHeatAvailable(repo)" />
          <span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="6" cy="5" r="2" />
              <circle cx="18" cy="5" r="2" />
              <circle cx="12" cy="19" r="2" />
              <path d="M6 7v3a5 5 0 0 0 5 5h1" />
              <path d="M18 7v3a5 5 0 0 1-5 5h-1" />
              <path d="M12 15v2" />
            </svg>
            {{ t('projects.forks', { count: formatProjectCount(repo.forks, locale as AppLocale) }) }}
          </span>
          <span v-if="repo.pushed_at" :title="projectLastPushTitle(repo, t, locale as AppLocale)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            {{ formatProjectLastPush(repo.pushed_at, locale as AppLocale) }}
          </span>
        </template>
      </footer>
        </div>
      </details>
    </div>

    <aside class="project-card__rail" :aria-label="t('projects.cardActions')">
      <a
        v-if="projectUrl(repo)"
        :id="`project-action-${index}-link`"
        class="project-card__action project-card__link"
        :href="projectUrl(repo)"
        target="_blank"
        rel="noopener noreferrer"
        :aria-label="t(isWebsite(repo) ? 'projects.openWebsite' : 'projects.openRepository')"
        :title="t(isWebsite(repo) ? 'projects.openWebsite' : 'projects.openRepository')"
        :aria-describedby="`project-action-${index}-link-tooltip`"
      >
        <ExternalLink class="project-card__action-icon" :size="15" :stroke-width="1.8" aria-hidden="true" />
        <span class="project-card__action-label">{{ projectLinkLabelKey(repo) ? t(`projects.${projectLinkLabelKey(repo)}`) : 'GitHub' }}</span>
        <span :id="`project-action-${index}-link-tooltip`" class="project-card__tooltip" role="tooltip">{{ t(isWebsite(repo) ? 'projects.openWebsite' : 'projects.openRepository') }}</span>
      </a>
      <button
        v-if="canRecommend"
        :id="`project-action-${index}-recommend`"
        type="button"
        class="project-card__action project-card__recommend"
        :class="repo.is_recommended ? 'project-card__recommend--active' : ''"
        :aria-label="t(recommendButtonLabelKey(repo, recommendBusy))"
        :title="t(recommendButtonLabelKey(repo, recommendBusy))"
        :aria-describedby="`project-action-${index}-recommend-tooltip`"
        :aria-pressed="Boolean(repo.is_recommended)"
        :disabled="recommendActionsBusy"
        @click="emit('recommend', repo)"
      >
        <Sparkles class="project-card__action-icon" :size="15" :stroke-width="1.8" aria-hidden="true" />
        <span class="project-card__action-label">{{ t(recommendButtonLabelKey(repo, recommendBusy)) }}</span>
        <span :id="`project-action-${index}-recommend-tooltip`" class="project-card__tooltip" role="tooltip">{{ t(recommendButtonLabelKey(repo, recommendBusy)) }}</span>
      </button>
      <button
        v-if="!isWebsite(repo)"
        :id="`project-action-${index}-favorite`"
        type="button"
        class="project-card__action project-card__favorite"
        :class="repo.is_favorited ? 'project-card__favorite--active' : ''"
        :aria-label="t(favoriteButtonLabelKey(repo, favoriteBusy, isLoggedIn))"
        :title="t(favoriteButtonLabelKey(repo, favoriteBusy, isLoggedIn))"
        :aria-describedby="`project-action-${index}-favorite-tooltip`"
        :aria-pressed="Boolean(repo.is_favorited)"
        :disabled="favoriteActionsBusy || !canFavorite"
        @click="emit('favorite', repo)"
      >
        <Star class="project-card__action-icon" :size="15" :stroke-width="1.8" :fill="repo.is_favorited ? 'currentColor' : 'none'" aria-hidden="true" />
        <span class="project-card__action-label">{{ t(favoriteButtonLabelKey(repo, favoriteBusy, isLoggedIn)) }}</span>
        <span :id="`project-action-${index}-favorite-tooltip`" class="project-card__tooltip" role="tooltip">{{ t(favoriteButtonLabelKey(repo, favoriteBusy, isLoggedIn)) }}</span>
      </button>
      <button
        v-if="canEdit"
        :id="`project-action-${index}-edit`"
        type="button"
        class="project-card__action project-card__edit"
        :aria-label="t('projects.edit')"
        :title="t('projects.edit')"
        :aria-describedby="`project-action-${index}-edit-tooltip`"
        :disabled="savingEdit"
        @click="emit('edit', repo)"
      >
        <Pencil class="project-card__action-icon" :size="15" :stroke-width="1.8" aria-hidden="true" />
        <span class="project-card__action-label">{{ t('projects.edit') }}</span>
        <span :id="`project-action-${index}-edit-tooltip`" class="project-card__tooltip" role="tooltip">{{ t('projects.edit') }}</span>
      </button>
      <button
        v-if="showDelete"
        :id="`project-action-${index}-delete`"
        type="button"
        class="project-card__action project-card__delete"
        :aria-label="deleting ? t('common.processing') : t('projects.delete')"
        :title="deleting ? t('common.processing') : t('projects.delete')"
        :aria-describedby="`project-action-${index}-delete-tooltip`"
        :disabled="deleting"
        @click="emit('delete', repo)"
      >
        <Trash2 class="project-card__action-icon" :size="15" :stroke-width="1.8" aria-hidden="true" />
        <span class="project-card__action-label">{{ deleting ? t('common.processing') : t('projects.delete') }}</span>
        <span :id="`project-action-${index}-delete-tooltip`" class="project-card__tooltip" role="tooltip">{{ deleting ? t('common.processing') : t('projects.delete') }}</span>
      </button>
    </aside>
  </article>
</template>

<style scoped>
.project-card__github-logo { width: 42px; height: 42px; flex-basis: 42px; }
.project-card { position: relative; display: flex; flex-direction: column; min-width: 0; margin-right: 40px; border-radius: 7px; }
/* 换分类、翻页或搜索后新的一批卡片依次浮起，先后由模板按名次下发的 animationDelay 决定。 */
.project-card { animation: motion-rise 360ms var(--motion-ease-out) backwards; }
.project-card__body { position: relative; display: flex; flex: 1; flex-direction: column; gap: 14px; min-width: 0; min-height: 280px; padding: 18px; border: 1px solid var(--projects-accent); border-radius: 7px; background: var(--projects-paper-light); box-shadow: 3px 3px 0 var(--shadow-hard); transition: box-shadow 160ms ease, transform 160ms ease; }
.project-card:hover .project-card__body, .project-card:focus-within .project-card__body { box-shadow: 4px 4px 0 var(--shadow-hard); }
.project-card--recommended .project-card__body { background: var(--projects-acid-soft); }
.project-card__header, .project-card__identity > div:last-child { min-width: 0; }
.project-card__identity { display: flex; align-items: flex-start; gap: 12px; }
.project-card__identity h2 { margin-top: 8px; color: var(--ink); font-size: 18px; font-weight: 750; line-height: 1.35; letter-spacing: -.025em; overflow-wrap: anywhere; }
.project-card__name-part { display: inline-block; max-width: 100%; vertical-align: top; }
.project-card__source-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.project-card__source { display: inline-flex; align-items: center; min-height: 24px; padding: 2px 7px; border: 1px solid var(--projects-accent); border-radius: 4px; color: var(--projects-on-acid); background: var(--projects-acid); font-size: 11px; font-weight: 750; line-height: 1.4; }
.project-card--recommended .project-card__source::before { content: '✦'; margin-right: 5px; }
.project-card__domain { margin-top: 4px; color: var(--tone-blue); font-size: 12px; overflow-wrap: anywhere; }
.project-card__logo-shell { position: relative; width: 42px; height: 42px; flex: 0 0 42px; overflow: hidden; border: 1px solid var(--projects-accent); border-radius: 7px; background: var(--tone-blue-soft); }
.project-card__logo-placeholder, .project-card__logo { position: absolute; inset: 0; width: 100%; height: 100%; }
.project-card__logo-placeholder { display: grid; place-items: center; color: var(--tone-blue); font-size: 16px; font-weight: 750; }
.project-card__logo { object-fit: cover; opacity: 0; transition: opacity 160ms ease; }
.project-card__logo--loaded { opacity: 1; }
.project-card__description { color: var(--ink-secondary); font-size: 14px; line-height: 1.7; overflow-wrap: anywhere; }
.project-card__details { margin-top: auto; }
.project-card__details > summary { display: none; }
.project-card__metadata { display: flex; flex-direction: column; gap: 14px; }
.project-card__tags { display: flex; align-items: flex-start; gap: 6px; }
.project-card__tag-list { display: flex; flex: 1; min-width: 0; flex-wrap: wrap; align-items: center; gap: 6px; }
.project-chip { max-width: 100%; min-height: 20px; padding: 1px 6px; color: var(--badge-default-ink); background: var(--badge-default-bg); border: 1px solid var(--badge-default-border); border-radius: 4px; font-size: 11px; font-weight: 600; line-height: 1.45; text-align: left; white-space: normal; overflow-wrap: anywhere; cursor: pointer; transition: border-color 160ms ease, background-color 160ms ease, color 160ms ease; }
.project-chip:hover { color: var(--projects-accent); background: var(--projects-acid-soft); border-color: var(--projects-accent); }
.project-chip--more { flex-shrink: 0; min-width: 24px; padding: 1px 4px; color: var(--ink-secondary); background: transparent; border-color: transparent; font-variant-numeric: tabular-nums; text-align: center; }
.project-card__stats { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; margin-top: auto; padding-top: 12px; border-top: 1px solid var(--rule); color: var(--ink-secondary); font-size: 12px; line-height: 1.5; font-variant-numeric: tabular-nums; }
.project-card__stats span { display: inline-flex; align-items: center; min-width: 0; gap: 4px; overflow-wrap: anywhere; }
.project-card__stats span:first-child { color: var(--ink); font-weight: 700; }
.project-card__stats span:nth-child(2) { color: var(--tone-mint); }
.project-card__stats svg { width: 13px; height: 13px; flex-shrink: 0; }
.project-card__stats span:first-child svg { color: var(--tone-amber); }
.project-card__rail { position: absolute; top: 20px; right: -40px; z-index: 3; display: flex; flex-direction: column; align-items: stretch; width: 40px; gap: 8px; }
.project-card__action { position: relative; display: inline-flex; align-items: center; justify-content: center; width: 40px; min-height: 40px; padding: 0; border: 1px solid var(--projects-accent); border-left: 0; border-radius: 0 6px 6px 0; color: var(--ink); background: var(--projects-paper-light); box-shadow: 2px 2px 0 var(--shadow-hard); text-decoration: none; transition: transform 160ms ease, box-shadow 160ms ease; }
.project-card__action:hover { transform: translateX(3px); box-shadow: 3px 3px 0 var(--shadow-hard); }
.project-card__action:disabled { cursor: not-allowed; opacity: .55; transform: none; }
.project-card__action:focus-visible, .project-chip:focus-visible { outline: 2px solid var(--projects-accent); outline-offset: 3px; }
.project-card__action-icon { width: 16px; height: 16px; flex-shrink: 0; }
.project-card__action-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.project-card__link { color: var(--projects-on-acid); background: var(--projects-acid); }
.project-card__favorite { color: var(--tone-amber); background: var(--tone-amber-soft); }
.project-card__recommend { color: var(--tone-mint); background: var(--tone-mint-soft); }
.project-card__edit { color: var(--tone-blue); background: var(--tone-blue-soft); }
.project-card__delete { color: var(--error-ink); background: var(--error-bg); }
.project-card__favorite--active { color: var(--projects-on-acid); background: var(--projects-acid); }
.project-card__recommend--active { color: var(--paper-raised); background: var(--tone-mint); }
.project-card__tooltip { position: absolute; top: 50%; right: calc(100% + 10px); z-index: 4; transform: translateY(-50%); width: max-content; max-width: 168px; padding: 6px 8px; border-radius: 5px; color: var(--paper-raised); background: var(--ink); font-size: 12px; line-height: 1.4; opacity: 0; visibility: hidden; pointer-events: none; }
.project-card__action:hover .project-card__tooltip, .project-card__action:focus-visible .project-card__tooltip { opacity: 1; visibility: visible; }
.project-card__availability { padding: 2px 6px; border: 1px solid var(--projects-ghost-border); border-radius: 4px; color: var(--projects-ghost-ink); background: var(--projects-ghost-surface); font-size: 11px; }
.project-card--not-found .project-card__body { background: var(--projects-ghost-surface-card); border-color: var(--projects-ghost-border); box-shadow: 3px 3px 0 var(--projects-ghost-shadow); }
.project-card--not-found .project-card__source, .project-card--not-found .project-chip { color: var(--projects-ghost-ink); background: var(--projects-ghost-surface-chip); border-color: var(--projects-ghost-border); }
@media (max-width: 1023px) and (min-width: 768px) {
  .project-card { margin-right: 44px; }
  .project-card__rail { width: 44px; right: -44px; }
  .project-card__action { width: 44px; min-height: 44px; }
}
@media (max-width: 767px) {
  .project-card { margin-right: 0; }
  .project-chip--more { min-width: 44px; }
  .project-card__body { min-height: 0; }
  .project-card__rail { position: static; width: auto; flex-direction: row; flex-wrap: wrap; gap: 10px; padding-top: 12px; }
  .project-card__action { width: auto; min-width: 44px; min-height: 44px; gap: 6px; padding: 8px 12px; border: 1px solid var(--projects-accent); border-radius: 6px; }
  .project-card__action-label { position: static; width: auto; height: auto; overflow: visible; clip-path: none; font-size: 13px; }
  .project-card__tooltip { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .project-card__body, .project-card__action, .project-card__logo { transition: none; }
  .project-card:hover .project-card__body, .project-card:focus-within .project-card__body, .project-card__action:hover { transform: none; }
}
</style>
