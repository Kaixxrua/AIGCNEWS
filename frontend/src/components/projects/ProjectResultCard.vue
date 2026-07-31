<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ExternalLink, Pencil, Sparkles, Star, Trash2 } from 'lucide-vue-next'
import type { AppLocale } from '../../i18n'
import type { GitHubProjectItem, GitHubProjectSort, ProjectScope } from '../../services/projects/projectApi'
import {
  projectDescription,
  favoriteButtonLabelKey,
  formattedProjectHotScore,
  formatProjectCount,
  formatProjectShortDate,
  projectDisplayTags,
  isWebsite,
  projectDailyGrowth,
  projectDailyGrowthTitle,
  projectLinkLabelKey,
  projectLogoKey,
  projectName,
  projectSourceBadgeKey,
  projectUrl,
  recommendButtonLabelKey,
  shouldShowProjectHotScore,
  websiteLogoInitial,
  type ProjectChip,
} from '../../features/projects/projectPresentation'

const { locale, t } = useI18n()

const props = defineProps<{
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
    class="project-card stagger-enter"
    :class="{ 'project-card--not-found': !isWebsite(repo) && repo.availability_status === 'not_found' }"
    :style="{ animationDelay: `${Math.min(index, 12) * 36}ms` }"
  >
    <div class="project-card__body">
      <header class="project-card__header">
        <div class="project-card__identity">
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
            <h2 :title="projectName(repo)">{{ projectName(repo) }}</h2>
            <p v-if="isWebsite(repo) && repo.domain" class="project-card__domain">{{ repo.domain }}</p>
          </div>
        </div>
      </header>

      <p class="project-card__description">
        {{ description }}
      </p>

      <div class="project-card__tags" :aria-label="t('projects.categoryTags')">
        <button
          v-for="chip in displayTags"
          :key="`${chip.type}:${chip.value}`"
          type="button"
          class="badge-default project-chip"
          :class="`project-chip--${chip.type}`"
          @click="emit('chipClick', chip)"
        >
          {{ chip.label }}
        </button>
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
          <span :title="projectDailyGrowthTitle(repo)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M3 17l6-6 4 4 8-8" />
              <path d="M15 7h6v6" />
            </svg>
            {{ t('projects.todayGrowth', { count: formatProjectCount(projectDailyGrowth(repo), locale as AppLocale) }) }}
          </span>
          <span v-if="shouldShowProjectHotScore(repo, sort, scope)" :title="t('projects.hotScoreTitle')">
            {{ t('projects.hotScore', { score: formattedProjectHotScore(repo) }) }}
          </span>
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
        </template>
      </footer>
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
        <ExternalLink class="project-card__action-icon" :size="18" :stroke-width="1.8" aria-hidden="true" />
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
        <Sparkles class="project-card__action-icon" :size="18" :stroke-width="1.8" aria-hidden="true" />
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
        <Star class="project-card__action-icon" :size="18" :stroke-width="1.8" :fill="repo.is_favorited ? 'currentColor' : 'none'" aria-hidden="true" />
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
        <Pencil class="project-card__action-icon" :size="18" :stroke-width="1.8" aria-hidden="true" />
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
        <Trash2 class="project-card__action-icon" :size="18" :stroke-width="1.8" aria-hidden="true" />
        <span class="project-card__action-label">{{ deleting ? t('common.processing') : t('projects.delete') }}</span>
        <span :id="`project-action-${index}-delete-tooltip`" class="project-card__tooltip" role="tooltip">{{ deleting ? t('common.processing') : t('projects.delete') }}</span>
      </button>
    </aside>
  </article>
</template>

<style scoped>
.project-card {
  container-type: inline-size;
  position: relative;
  min-width: 0;
  min-height: 248px;
  margin-right: var(--projects-card-action-size, 40px);
  overflow: visible;
}

.project-card__body {
  display: flex;
  min-width: 0;
  min-height: 248px;
  flex-direction: column;
  gap: 18px;
  overflow: hidden;
  border: 1px solid #11110f;
  border-radius: 6px;
  padding: 22px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 #11110f;
}

.project-card__body::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.88), transparent 42%),
    radial-gradient(circle at 14% 0%, rgba(168, 162, 158, 0.10), transparent 34%);
  opacity: 0.22;
}

.project-card__body { position: relative; }
.project-card__body > * { position: relative; z-index: 1; }
.project-card__header { display: block; min-width: 0; }
.project-card__identity { display: flex; align-items: flex-start; min-width: 0; gap: 12px; }
.project-card__identity > div:last-child { min-width: 0; }
.project-card__identity h2, .project-card__domain { overflow-wrap: anywhere; }
.project-card__logo-shell { position: relative; width: 42px; height: 42px; flex: 0 0 42px; overflow: hidden; border: 1px solid rgba(168, 162, 158, 0.22); border-radius: 14px; background: var(--acid-soft); box-shadow: 0 10px 24px rgba(41, 37, 36, 0.08); }
.project-card__logo-placeholder, .project-card__logo { position: absolute; inset: 0; width: 100%; height: 100%; }
.project-card__logo-placeholder { display: grid; place-items: center; color: var(--acid-ink); font-size: 16px; font-weight: 800; line-height: 1; }
.project-card__logo { object-fit: cover; background: var(--paper-raised); opacity: 0; transition: opacity 160ms ease; }
.project-card__logo--loaded { opacity: 1; }
.project-card__source { display: inline-flex; width: fit-content; margin-bottom: 7px; border-radius: 999px; padding: 3px 8px; color: var(--projects-accent); background: rgba(245, 245, 244, 0.82); border: 1px solid var(--projects-accent-border); font-size: 10px; font-weight: 800; letter-spacing: 0.08em; }
.project-card__header h2 { color: #292524; font-size: 18px; font-weight: 700; line-height: 1.25; letter-spacing: -0.02em; overflow-wrap: anywhere; }
.project-card__domain { margin-top: 4px; color: var(--projects-warm); font-size: 12px; font-weight: 700; }
.project-card__rail { position: absolute; top: 22px; right: calc(-1 * var(--projects-card-action-size, 40px)); z-index: 3; display: flex; width: var(--projects-card-action-size, 40px); flex-direction: column; gap: 7px; }
.project-card__action { position: relative; display: inline-flex; width: var(--projects-card-action-size, 40px); min-width: var(--projects-card-action-size, 40px); min-height: var(--projects-card-action-size, 40px); box-sizing: border-box; align-items: center; justify-content: center; gap: 5px; flex-shrink: 0; border: 1px solid #11110f; border-left: 0; border-radius: 0 4px 4px 0; padding: 0; font-size: 12px; font-weight: 700; line-height: 1.2; text-align: center; text-decoration: none; transition: background 160ms ease, border-color 160ms ease, color 160ms ease, opacity 160ms ease, transform 160ms ease; }
.project-card__action-icon { display: inline-flex; width: 18px; height: 18px; flex: 0 0 18px; }
.project-card__action-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; }
.project-card__link { color: #11110f; background: var(--projects-acid); }
.project-card__favorite { color: #78350f; background: var(--projects-paper-light); }
.project-card__recommend { color: #155e75; background: #ecfeff; }
.project-card__edit { color: var(--projects-accent); background: #ecfeff; }
.project-card__delete { color: #991b1b; background: #fef2f2; }
.project-card__favorite--active, .project-card__recommend--active { color: #11110f; background: var(--projects-acid); }
.project-card__link:hover, .project-card__favorite:hover, .project-card__recommend:hover, .project-card__edit:hover, .project-card__delete:hover { transform: translateY(-1px); }
.project-card__link:hover, .project-card__link:focus-visible { color: #fffdf5; background: #11110f; }
.project-card__favorite:hover, .project-card__favorite:focus-visible { background: #fef3c7; }
.project-card__recommend:hover, .project-card__recommend:focus-visible, .project-card__edit:hover, .project-card__edit:focus-visible { background: var(--projects-acid-soft); }
.project-card__delete:hover, .project-card__delete:focus-visible { background: #fee2e2; }
.project-card__action:focus-visible { outline: 3px solid var(--projects-acid); outline-offset: 2px; }
.project-card__favorite:disabled, .project-card__recommend:disabled, .project-card__edit:disabled, .project-card__delete:disabled { cursor: wait; opacity: 0.65; transform: none; }
.project-card__tooltip { position: absolute; right: calc(100% + 8px); top: 50%; z-index: 4; width: max-content; max-width: 152px; padding: 5px 8px; color: var(--projects-paper-light); background: #11110f; border: 1px solid #11110f; border-radius: 4px; font-size: 11px; font-weight: 700; line-height: 1.35; white-space: normal; pointer-events: none; opacity: 0; visibility: hidden; transform: translateY(-50%) translateX(4px); transition: opacity 140ms ease, visibility 140ms ease, transform 140ms ease; }
.project-card__action:hover .project-card__tooltip, .project-card__action:focus-visible .project-card__tooltip { opacity: 1; visibility: visible; transform: translateY(-50%) translateX(0); }
.project-card__description { display: -webkit-box; min-height: 60px; overflow: hidden; color: #57534e; font-size: 14px; line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.project-card__tags { display: flex; flex-wrap: wrap; gap: 7px; }
.project-chip { max-width: 100%; cursor: pointer; white-space: normal; overflow-wrap: anywhere; text-align: left; transition: transform 160ms ease, border-color 160ms ease, background 160ms ease, color 160ms ease; }
.project-chip:hover, .project-chip:focus-visible { color: var(--projects-accent); background: rgba(236, 254, 255, 0.76); border-color: var(--projects-accent-border); transform: translateY(-1px); outline: none; }
.project-chip--language:hover, .project-chip--language:focus-visible { color: var(--projects-warm); background: rgba(255, 251, 235, 0.86); border-color: rgba(245, 158, 11, 0.28); }
.project-card__stats { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; min-width: 0; margin-top: auto; padding-top: 14px; border-top: 1px dashed rgba(168, 162, 158, 0.24); color: #78716c; font-size: 12px; font-weight: 700; }
.project-card__stats span { display: inline-flex; min-width: 0; align-items: center; gap: 5px; overflow-wrap: anywhere; }
.project-card__stats svg { width: 14px; height: 14px; color: var(--projects-warm); }

.project-card { border-radius: 6px; }
.project-card__body::before { mask-image: none; }
.project-card__logo { border-color: #11110f; border-radius: 4px; box-shadow: none; }
.project-card__source { border-color: #11110f; border-radius: 4px; color: #11110f; background: var(--projects-acid); box-shadow: none; }
.project-card__action { border-color: #11110f; border-left-color: transparent; box-shadow: none; }
.project-card__recommend { color: #155e75; background: #ecfeff; }
.project-card__favorite { color: #78350f; background: var(--projects-paper-light); }
.project-card__delete { color: #991b1b; background: #fef2f2; }
.project-card__stats { border-top: 1px solid #11110f; color: #11110f; }
.project-card__stats svg { color: #11110f; }
.project-card__link:hover, .project-card__favorite:hover, .project-card__recommend:hover, .project-card__edit:hover, .project-chip:hover, .project-chip:focus-visible, .project-chip--language:hover, .project-chip--language:focus-visible { border-color: #11110f; color: #11110f; background: var(--projects-acid-soft); transform: none; }
.project-card__delete:hover { border-color: #991b1b; color: #991b1b; background: #fef2f2; transform: none; }
.project-card__favorite--active, .project-card__recommend--active { border-color: #11110f; color: #11110f; background: var(--projects-acid); box-shadow: none; }
.project-card__source-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.project-card__availability { display: inline-flex; align-items: center; min-height: 22px; padding: 2px 7px; border: 1px solid #666; border-radius: 3px; color: #444; background: #e5e5e5; font-size: 11px; font-weight: 800; letter-spacing: .04em; }
.project-card.project-card--not-found .project-card__body { border-color: #8a8a85; background: #e7e7e2; box-shadow: 5px 5px 0 #a5a5a0; }
.project-card.project-card--not-found:hover .project-card__body { border-color: #666662; background: #deded9; }
.project-card--not-found .project-card__source, .project-card--not-found .project-card__favorite--active, .project-card--not-found .project-card__recommend--active { border-color: #666662; color: #333; background: #b8b8b3; }
.project-card--not-found h2, .project-card--not-found .project-card__description, .project-card--not-found .project-card__stats, .project-card--not-found .project-card__stats svg, .project-card--not-found .project-card__domain { color: #555550; }
.project-card--not-found .project-card__stats { border-top-color: #8a8a85; }
.project-card--not-found .project-chip { border-color: #888883; color: #555550; background: #d6d6d1; }

@media (max-width: 720px) {
  .project-card { display: flex; min-width: 0; margin-right: 0; flex-direction: column; }
  .project-card__body { min-height: 0; padding: 22px; }
  .project-card__rail { position: static; width: 100%; min-width: 0; align-items: flex-start; flex-direction: row; flex-wrap: wrap; gap: 7px; padding: 12px 0 0; }
  .project-card__action { width: auto; min-width: var(--projects-card-action-size, 40px); max-width: 100%; border-left: 1px solid #11110f; border-left-color: #11110f; border-radius: 4px; padding: 0 10px; }
  .project-card__action-label { position: static; width: auto; height: auto; overflow: visible; clip: auto; clip-path: none; white-space: normal; }
  .project-card__tooltip { display: none; }
}

@container (max-width: 520px) {
  .project-card { display: flex; margin-right: 0; flex-direction: column; }
  .project-card__body { min-height: 0; padding: 22px; }
  .project-card__rail { position: static; width: 100%; min-width: 0; align-items: flex-start; flex-direction: row; flex-wrap: wrap; gap: 7px; padding: 12px 0 0; }
  .project-card__action { width: auto; min-width: var(--projects-card-action-size, 40px); max-width: 100%; border-left: 1px solid #11110f; border-left-color: #11110f; border-radius: 4px; padding: 0 10px; }
  .project-card__action-label { position: static; width: auto; height: auto; overflow: visible; clip: auto; clip-path: none; white-space: normal; }
  .project-card__tooltip { display: none; }
  .project-card__stats { flex-wrap: wrap; }
}
</style>
