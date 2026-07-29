<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AppLocale } from '../../i18n'
import type { GitHubProjectItem, GitHubProjectSort, ProjectScope } from '../../services/projects/projectApi'
import {
  projectDescription,
  favoriteButtonLabel,
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
  recommendButtonLabel,
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
const displayTags = computed(() => projectDisplayTags(props.repo, props.isPersonalView, locale.value as AppLocale))
const description = computed(() => projectDescription(
  props.repo, locale.value as AppLocale,
  t(isWebsite(props.repo) ? 'projects.fallbackWebsite' : 'projects.fallbackProject'),
))
</script>

<template>
  <article
    class="project-card glass-card card-hover stagger-enter"
    :class="{ 'project-card--not-found': !isWebsite(repo) && repo.availability_status === 'not_found' }"
    :style="{ animationDelay: `${Math.min(index, 12) * 36}ms` }"
  >
    <div class="project-card__pin" :class="isWebsite(repo) ? 'project-card__pin--website' : ''" aria-hidden="true" />

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
      <div class="project-card__actions">
        <a
          v-if="projectUrl(repo)"
          class="project-card__link"
          :href="projectUrl(repo)"
          target="_blank"
          rel="noopener noreferrer"
          :aria-label="t(isWebsite(repo) ? 'projects.openWebsite' : 'projects.openRepository')"
        >
          {{ projectLinkLabelKey(repo) ? t(`projects.${projectLinkLabelKey(repo)}`) : 'GitHub' }}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M7 17L17 7" />
            <path d="M9 7h8v8" />
          </svg>
        </a>
        <button
          v-if="canRecommend"
          type="button"
          class="project-card__recommend"
          :class="repo.is_recommended ? 'project-card__recommend--active' : ''"
          :aria-pressed="Boolean(repo.is_recommended)"
          :disabled="recommendActionsBusy"
          @click="emit('recommend', repo)"
        >
          {{ recommendButtonLabel(repo, recommendBusy) }}
        </button>
        <button
          v-if="!isWebsite(repo)"
          type="button"
          class="project-card__favorite"
          :class="repo.is_favorited ? 'project-card__favorite--active' : ''"
          :aria-pressed="Boolean(repo.is_favorited)"
          :disabled="favoriteActionsBusy || !canFavorite"
          @click="emit('favorite', repo)"
        >
          <span>{{ repo.is_favorited ? '★' : '☆' }}</span>
          {{ favoriteButtonLabel(repo, favoriteBusy, isLoggedIn) }}
        </button>
        <button
          v-if="canEdit"
          type="button"
          class="project-card__edit"
          :disabled="savingEdit"
          @click="emit('edit', repo)"
        >
          {{ t('projects.edit') }}
        </button>
        <button
          v-if="showDelete"
          type="button"
          class="project-card__delete"
          :disabled="deleting"
          @click="emit('delete', repo)"
        >
          {{ deleting ? t('common.processing') : t('projects.delete') }}
        </button>
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
  </article>
</template>

<style scoped>
.project-card {
  position: relative;
  display: flex;
  min-height: 248px;
  flex-direction: column;
  gap: 18px;
  overflow: hidden;
  padding: 22px;
}

.project-card::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.88), transparent 42%),
    radial-gradient(circle at 14% 0%, rgba(168, 162, 158, 0.10), transparent 34%);
  opacity: 0.92;
}

.project-card > * { position: relative; z-index: 1; }
.project-card__pin { position: absolute; top: 14px; right: 16px; width: 8px; height: 8px; border-radius: 999px; background: var(--projects-accent); box-shadow: 0 0 0 5px var(--projects-accent-soft); }
.project-card__pin--website { background: var(--projects-warm); box-shadow: 0 0 0 5px var(--projects-warm-soft); }
.project-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding-right: 14px; }
.project-card__identity { display: flex; align-items: flex-start; min-width: 0; gap: 12px; }
.project-card__logo-shell { position: relative; width: 42px; height: 42px; flex: 0 0 42px; overflow: hidden; border: 1px solid rgba(168, 162, 158, 0.22); border-radius: 14px; background: var(--acid-soft); box-shadow: 0 10px 24px rgba(41, 37, 36, 0.08); }
.project-card__logo-placeholder, .project-card__logo { position: absolute; inset: 0; width: 100%; height: 100%; }
.project-card__logo-placeholder { display: grid; place-items: center; color: var(--acid-ink); font-size: 16px; font-weight: 800; line-height: 1; }
.project-card__logo { object-fit: cover; background: var(--paper-raised); opacity: 0; transition: opacity 160ms ease; }
.project-card__logo--loaded { opacity: 1; }
.project-card__source { display: inline-flex; width: fit-content; margin-bottom: 7px; border-radius: 999px; padding: 3px 8px; color: var(--projects-accent); background: rgba(245, 245, 244, 0.82); border: 1px solid var(--projects-accent-border); font-size: 10px; font-weight: 800; letter-spacing: 0.08em; }
.project-card__header h2 { color: #292524; font-size: 18px; font-weight: 700; line-height: 1.25; letter-spacing: -0.02em; overflow-wrap: anywhere; }
.project-card__domain { margin-top: 4px; color: var(--projects-warm); font-size: 12px; font-weight: 700; }
.project-card__actions { display: flex; align-items: flex-end; flex-direction: column; gap: 7px; flex-shrink: 0; }
.project-card__link, .project-card__favorite, .project-card__recommend, .project-card__edit, .project-card__delete { display: inline-flex; align-items: center; justify-content: center; gap: 5px; flex-shrink: 0; border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 700; transition: all 160ms ease; }
.project-card__link { color: #44403c; background: rgba(255, 255, 255, 0.74); border: 1px solid rgba(168, 162, 158, 0.24); }
.project-card__favorite { color: #a16207; background: rgba(255, 251, 235, 0.76); border: 1px solid rgba(245, 158, 11, 0.24); }
.project-card__recommend { color: #be123c; background: rgba(255, 241, 242, 0.78); border: 1px solid rgba(244, 63, 94, 0.24); }
.project-card__edit { color: var(--projects-accent); background: rgba(236, 254, 255, 0.76); border: 1px solid var(--projects-accent-border); }
.project-card__favorite--active { color: #78350f; background: rgba(254, 243, 199, 0.92); border-color: rgba(245, 158, 11, 0.42); box-shadow: 0 8px 18px rgba(245, 158, 11, 0.12); }
.project-card__recommend--active { color: #9f1239; background: rgba(255, 228, 230, 0.95); border-color: rgba(244, 63, 94, 0.42); box-shadow: 0 8px 18px rgba(244, 63, 94, 0.12); }
.project-card__delete { color: #57534e; background: rgba(245, 245, 244, 0.76); border: 1px solid rgba(168, 162, 158, 0.24); }
.project-card__link:hover, .project-card__favorite:hover, .project-card__recommend:hover, .project-card__edit:hover, .project-card__delete:hover { transform: translateY(-1px); }
.project-card__link:hover { color: #292524; background: rgba(255, 255, 255, 0.96); border-color: rgba(87, 83, 78, 0.30); }
.project-card__favorite:hover { color: #78350f; background: rgba(254, 243, 199, 0.98); border-color: rgba(245, 158, 11, 0.46); }
.project-card__recommend:hover { color: #9f1239; background: rgba(255, 228, 230, 0.98); border-color: rgba(244, 63, 94, 0.46); }
.project-card__edit:hover { color: #155e75; background: rgba(207, 250, 254, 0.92); border-color: rgba(6, 182, 212, 0.36); }
.project-card__delete:hover { color: #292524; background: rgba(231, 229, 228, 0.82); border-color: rgba(87, 83, 78, 0.30); }
.project-card__favorite:disabled, .project-card__recommend:disabled, .project-card__edit:disabled, .project-card__delete:disabled { cursor: wait; opacity: 0.65; transform: none; }
.project-card__link svg { width: 13px; height: 13px; }
.project-card__description { display: -webkit-box; min-height: 60px; overflow: hidden; color: #57534e; font-size: 14px; line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.project-card__tags { display: flex; flex-wrap: wrap; gap: 7px; }
.project-chip { cursor: pointer; transition: transform 160ms ease, border-color 160ms ease, background 160ms ease, color 160ms ease; }
.project-chip:hover, .project-chip:focus-visible { color: var(--projects-accent); background: rgba(236, 254, 255, 0.76); border-color: var(--projects-accent-border); transform: translateY(-1px); outline: none; }
.project-chip--language:hover, .project-chip--language:focus-visible { color: var(--projects-warm); background: rgba(255, 251, 235, 0.86); border-color: rgba(245, 158, 11, 0.28); }
.project-card__stats { display: flex; align-items: center; gap: 10px; margin-top: auto; padding-top: 14px; border-top: 1px dashed rgba(168, 162, 158, 0.24); color: #78716c; font-size: 12px; font-weight: 700; }
.project-card__stats span { display: inline-flex; align-items: center; gap: 5px; }
.project-card__stats svg { width: 14px; height: 14px; color: var(--projects-warm); }

.project-card { border-radius: 6px; }
.project-card::before { opacity: .22; mask-image: none; }
.project-card__pin { width: 12px; height: 12px; border: 1px solid #11110f; border-radius: 2px; background: var(--projects-acid); box-shadow: none; }
.project-card__pin--website { background: var(--projects-acid); }
.project-card__logo { border-color: #11110f; border-radius: 4px; box-shadow: none; }
.project-card__source { border-color: #11110f; border-radius: 4px; color: #11110f; background: var(--projects-acid); box-shadow: none; }
.project-card__link, .project-card__favorite, .project-card__recommend, .project-card__edit, .project-card__delete { border-color: #11110f; border-radius: 4px; background: var(--projects-paper-light); box-shadow: none; }
.project-card__stats { border-top: 1px solid #11110f; color: #11110f; }
.project-card__stats svg { color: #11110f; }
.project-card__link:hover, .project-card__favorite:hover, .project-card__recommend:hover, .project-card__edit:hover, .project-chip:hover, .project-chip:focus-visible, .project-chip--language:hover, .project-chip--language:focus-visible { border-color: #11110f; color: #11110f; background: var(--projects-acid-soft); transform: none; }
.project-card__delete:hover { border-color: #991b1b; color: #991b1b; background: #fef2f2; transform: none; }
.project-card__favorite--active, .project-card__recommend--active { border-color: #11110f; color: #11110f; background: var(--projects-acid); box-shadow: none; }
.project-card__source-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.project-card__availability { display: inline-flex; align-items: center; min-height: 22px; padding: 2px 7px; border: 1px solid #666; border-radius: 3px; color: #444; background: #e5e5e5; font-size: 11px; font-weight: 800; letter-spacing: .04em; }
.project-card.project-card--not-found { border-color: #8a8a85; background: #e7e7e2; box-shadow: 5px 5px 0 #a5a5a0; }
.project-card.project-card--not-found:hover { border-color: #666662; background: #deded9; }
.project-card--not-found .project-card__pin, .project-card--not-found .project-card__source, .project-card--not-found .project-card__favorite--active, .project-card--not-found .project-card__recommend--active { border-color: #666662; color: #333; background: #b8b8b3; }
.project-card--not-found h2, .project-card--not-found .project-card__description, .project-card--not-found .project-card__stats, .project-card--not-found .project-card__stats svg, .project-card--not-found .project-card__domain { color: #555550; }
.project-card--not-found .project-card__stats { border-top-color: #8a8a85; }
.project-card--not-found .project-chip { border-color: #888883; color: #555550; background: #d6d6d1; }

@media (max-width: 720px) {
  .project-card { min-width: 0; }
  .project-card__header { flex-direction: column; padding-right: 0; }
  .project-card__actions { align-items: flex-start; flex-direction: row; flex-wrap: wrap; }
  .project-card__stats { flex-wrap: wrap; }
}
</style>
