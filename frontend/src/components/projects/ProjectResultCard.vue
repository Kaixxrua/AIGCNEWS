<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ExternalLink, Pencil, Sparkles, Star, Trash2 } from 'lucide-vue-next'
import type { AppLocale } from '@/i18n'
import type { GitHubProjectItem, GitHubProjectSort, ProjectScope } from '@/services/projects/projectApi'
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
} from '@/features/projects/projectPresentation'

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
    class="project-card"
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
.project-card {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 248px;
  flex-direction: column;
  margin-right: var(--projects-card-action-size, 34px);
  overflow: visible;
}

.project-card__body {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 248px;
  flex-direction: column;
  gap: 18px;
  overflow: hidden;
  content-visibility: auto;
  contain-intrinsic-size: auto 520px;
  border: 1px solid var(--projects-accent);
  border-radius: 6px;
  padding: 22px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 var(--shadow-hard);
}

.project-card__body::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(135deg, rgb(var(--card-rgb) / 0.88), transparent 42%),
    radial-gradient(circle at 14% 0%, rgb(var(--stone-400-rgb) / 0.10), transparent 34%);
  opacity: 0.22;
}

.project-card__body { position: relative; }
.project-card__body > * { position: relative; z-index: 1; }
.project-card__header { display: block; min-width: 0; }
.project-card__identity { display: flex; align-items: flex-start; min-width: 0; gap: 12px; }
.project-card__identity > div:last-child { min-width: 0; }
.project-card__identity h2, .project-card__domain { overflow-wrap: anywhere; }
.project-card__logo-shell { position: relative; width: 42px; height: 42px; flex: 0 0 42px; overflow: hidden; border: 1px solid rgb(var(--stone-400-rgb) / 0.22); border-radius: 14px; background: var(--logo-tile); box-shadow: 0 10px 24px rgb(var(--stone-800-rgb) / 0.08); }
.project-card__logo-placeholder, .project-card__logo { position: absolute; inset: 0; width: 100%; height: 100%; }
.project-card__logo-placeholder { display: grid; place-items: center; color: var(--acid-ink); font-size: 16px; font-weight: 800; line-height: 1; }
.project-card__logo { object-fit: cover; background: var(--paper-raised); opacity: 0; transition: opacity 160ms ease; }
.project-card__logo--loaded { opacity: 1; }
.project-card__source { display: inline-flex; width: fit-content; margin-bottom: 7px; border-radius: 999px; padding: 3px 8px; color: var(--projects-accent); background: rgb(var(--stone-100-rgb) / 0.82); border: 1px solid var(--projects-accent-border); font-size: 10px; font-weight: 800; letter-spacing: 0.08em; }
.project-card__header h2 { color: rgb(var(--stone-800-rgb)); font-size: 18px; font-weight: 700; line-height: 1.25; letter-spacing: -0.02em; overflow-wrap: anywhere; }
.project-card__domain { margin-top: 4px; color: var(--projects-warm); font-size: 12px; font-weight: 700; }
.project-card__rail { position: absolute; top: 22px; right: calc(-1 * var(--projects-card-action-size, 34px)); z-index: 3; display: flex; width: var(--projects-card-action-size, 34px); flex-direction: column; gap: 8px; }
.project-card__action { position: relative; display: inline-flex; width: var(--projects-card-action-size, 34px); min-width: var(--projects-card-action-size, 34px); min-height: var(--projects-card-action-size, 34px); box-sizing: border-box; align-items: center; justify-content: center; gap: 5px; flex-shrink: 0; border: 1px solid var(--projects-accent); border-left: 0; border-radius: 0 4px 4px 0; padding: 0; box-shadow: 2px 2px 0 var(--shadow-hard); font-size: 12px; font-weight: 700; line-height: 1.2; text-align: center; text-decoration: none; transition: background 160ms ease, border-color 160ms ease, box-shadow 160ms ease, color 160ms ease, opacity 160ms ease, transform 160ms ease; }
.project-card__action-icon { display: inline-flex; width: 15px; height: 15px; flex: 0 0 15px; }
.project-card__action-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; }
.project-card__link { color: var(--projects-on-acid); background: var(--projects-acid); }
.project-card__favorite { color: var(--projects-favorite-ink); background: var(--projects-paper-light); }
.project-card__recommend { color: var(--projects-recommend-ink); background: var(--projects-paper-light); }
.project-card__edit { color: var(--projects-accent); background: var(--projects-paper-light); }
.project-card__delete { color: var(--error-ink); background: var(--projects-paper-light); }
.project-card__favorite--active, .project-card__recommend--active { color: var(--projects-on-acid); background: var(--projects-acid); }
.project-card__link:hover, .project-card__favorite:hover, .project-card__recommend:hover, .project-card__edit:hover, .project-card__delete:hover { transform: translate(-1px, -1px); box-shadow: 3px 3px 0 var(--shadow-hard); }
.project-card__link:hover, .project-card__link:focus-visible { color: var(--projects-paper-light); background: var(--projects-accent); }
.project-card__favorite:hover, .project-card__favorite:focus-visible { background: var(--projects-favorite-bg); }
.project-card__recommend:hover, .project-card__recommend:focus-visible, .project-card__edit:hover, .project-card__edit:focus-visible { background: var(--projects-acid-soft); }
.project-card__delete:hover, .project-card__delete:focus-visible { background: var(--error-bg-strong); }
.project-card__action:focus-visible { outline: 3px solid var(--projects-acid); outline-offset: 2px; }
.project-card__favorite:disabled, .project-card__recommend:disabled, .project-card__edit:disabled, .project-card__delete:disabled { cursor: wait; opacity: 0.65; transform: none; }
.project-card__tooltip { position: absolute; right: calc(100% + 8px); top: 50%; z-index: 4; width: max-content; max-width: 152px; padding: 5px 8px; color: var(--projects-paper-light); background: var(--projects-accent); border: 1px solid var(--projects-accent); border-radius: 4px; font-size: 11px; font-weight: 700; line-height: 1.35; white-space: normal; pointer-events: none; opacity: 0; visibility: hidden; transform: translateY(-50%) translateX(4px); transition: opacity 140ms ease, visibility 140ms ease, transform 140ms ease; }
.project-card__action:hover .project-card__tooltip, .project-card__action:focus-visible .project-card__tooltip { opacity: 1; visibility: visible; transform: translateY(-50%) translateX(0); }
.project-card__body { transition: transform 180ms ease, box-shadow 180ms ease; }
@media (hover: hover) {
  .project-card:hover .project-card__body, .project-card:focus-within .project-card__body { transform: translate(-2px, -4px) rotate(-0.4deg); box-shadow: 8px 8px 0 var(--shadow-hard); }
  .project-card:hover .project-card__action, .project-card:focus-within .project-card__action { animation: projectCardTabPop 240ms cubic-bezier(0.34, 1.56, 0.64, 1) both; }
  .project-card:hover .project-card__action:nth-child(2), .project-card:focus-within .project-card__action:nth-child(2) { animation-delay: 40ms; }
  .project-card:hover .project-card__action:nth-child(3), .project-card:focus-within .project-card__action:nth-child(3) { animation-delay: 80ms; }
  .project-card:hover .project-card__action:nth-child(4), .project-card:focus-within .project-card__action:nth-child(4) { animation-delay: 120ms; }
  .project-card:hover .project-card__action:nth-child(5), .project-card:focus-within .project-card__action:nth-child(5) { animation-delay: 160ms; }
}
@keyframes projectCardTabPop {
  from { transform: translateX(0); }
  55% { transform: translateX(7px); }
  to { transform: translateX(4px); }
}
.project-card__description { color: rgb(var(--stone-600-rgb)); font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; }
.project-card__tags { display: flex; flex-wrap: wrap; gap: 6px; }
.project-chip { max-width: 100%; padding: 1px 8px; cursor: pointer; white-space: normal; overflow-wrap: anywhere; text-align: left; font-size: 11px; line-height: 1.45; transition: transform 160ms ease, border-color 160ms ease, background 160ms ease, color 160ms ease; }
.project-chip:hover, .project-chip:focus-visible { color: var(--projects-accent); background: var(--projects-recommend-tint); border-color: var(--projects-accent-border); transform: translateY(-1px); outline: none; }
.project-chip--language:hover, .project-chip--language:focus-visible { color: var(--projects-warm); background: var(--projects-favorite-tint); border-color: var(--projects-favorite-border); }
.project-card__stats { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; min-width: 0; margin-top: auto; padding-top: 14px; border-top: 1px dashed rgb(var(--stone-400-rgb) / 0.24); color: rgb(var(--stone-500-rgb)); font-size: 12px; font-weight: 700; }
.project-card__stats span { display: inline-flex; min-width: 0; align-items: center; gap: 5px; overflow-wrap: anywhere; }
.project-card__stats svg { width: 14px; height: 14px; color: var(--projects-warm); }

.project-card { border-radius: 6px; }
.project-card__body::before { mask-image: none; }
.project-card__logo { border-color: var(--projects-accent); border-radius: 4px; box-shadow: none; }
.project-card__source { border-color: var(--projects-accent); border-radius: 4px; color: var(--projects-on-acid); background: var(--projects-acid); box-shadow: none; }
.project-card__action { border-color: var(--projects-accent); border-left-color: transparent; }
.project-card__recommend { color: var(--projects-recommend-ink); background: var(--projects-paper-light); }
.project-card__favorite { color: var(--projects-favorite-ink); background: var(--projects-paper-light); }
.project-card__delete { color: var(--error-ink); background: var(--projects-paper-light); }
.project-card__stats { border-top: 1px solid var(--projects-accent); color: var(--projects-accent); }
.project-card__stats svg { color: var(--projects-accent); }
.project-card__link:hover, .project-card__favorite:hover, .project-card__recommend:hover, .project-card__edit:hover, .project-chip:hover, .project-chip:focus-visible, .project-chip--language:hover, .project-chip--language:focus-visible { border-color: var(--projects-accent); color: var(--projects-accent); background: var(--projects-acid-soft); transform: none; }
.project-card__delete:hover { border-color: var(--error-ink); color: var(--error-ink); background: var(--error-bg); transform: none; }
.project-card__favorite--active, .project-card__recommend--active { border-color: var(--projects-accent); color: var(--projects-on-acid); background: var(--projects-acid); }
.project-card__source-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.project-card__availability { display: inline-flex; align-items: center; min-height: 22px; padding: 2px 7px; border: 1px solid var(--projects-ghost-border); border-radius: 3px; color: var(--projects-ghost-ink-soft); background: var(--projects-ghost-surface); font-size: 11px; font-weight: 800; letter-spacing: .04em; }
.project-card.project-card--not-found .project-card__body { border-color: var(--projects-ghost-line-strong); background: var(--projects-ghost-surface-card); box-shadow: 5px 5px 0 var(--projects-ghost-shadow); }
.project-card.project-card--not-found:hover .project-card__body { border-color: var(--projects-ghost-border-strong); background: var(--projects-ghost-surface-hover); }
.project-card--not-found .project-card__source, .project-card--not-found .project-card__favorite--active, .project-card--not-found .project-card__recommend--active { border-color: var(--projects-ghost-border-strong); color: var(--projects-ghost-ink); background: var(--projects-ghost-surface-active); }
.project-card--not-found h2, .project-card--not-found .project-card__description, .project-card--not-found .project-card__stats, .project-card--not-found .project-card__stats svg, .project-card--not-found .project-card__domain { color: var(--projects-ghost-text); }
.project-card--not-found .project-card__stats { border-top-color: var(--projects-ghost-line-strong); }
.project-card--not-found .project-chip { border-color: var(--projects-ghost-line); color: var(--projects-ghost-text); background: var(--projects-ghost-surface-chip); }

@media (max-width: 720px) {
  .project-card { display: flex; min-width: 0; margin-right: 0; flex-direction: column; }
  .project-card__body { min-height: 0; padding: 22px; }
  .project-card__rail { position: static; width: 100%; min-width: 0; align-items: flex-start; flex-direction: row; flex-wrap: wrap; gap: 7px; padding: 12px 0 0; }
  .project-card__action { width: auto; min-width: var(--projects-card-action-size, 34px); max-width: 100%; border-left: 1px solid var(--projects-accent); border-left-color: var(--projects-accent); border-radius: 4px; padding: 0 10px; }
  .project-card__action-label { position: static; width: auto; height: auto; overflow: visible; clip: auto; clip-path: none; white-space: normal; }
  .project-card__tooltip { display: none; }
}

@keyframes projectCardIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}

.project-card { animation: projectCardIn 0.32s ease both; }
</style>
