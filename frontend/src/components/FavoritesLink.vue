<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Star } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { showToast } from '@/composables/useToast'
import {
  addMyToolWebsite,
  fetchMyProjectCollection,
  removeMyToolWebsite,
} from '@/services/projects/projectApi'

/** 顶栏「收藏本站」开关 —— 实心星=已收藏；点击把本站加入/移出个人网页收藏（项目库「我的网页」）。
    未登录点击先弹登录，登录成功后自动完成本次收藏。 */
const { t } = useI18n()
const route = useRoute()
const authStore = useAuthStore()
const { requestLogin } = useLoginPrompt()

const favorited = ref(false)
const websiteId = ref<number | string | null>(null)
const busy = ref(false)
const pendingAfterLogin = ref(false)

const normalizeHost = (raw: string | null | undefined): string => {
  if (!raw) return ''
  try {
    return new URL(raw).hostname.replace(/^www\./, '').toLowerCase()
  } catch {
    return ''
  }
}
const siteHost = () => normalizeHost(window.location.origin)

/** 登录后探测本站是否已在个人网页收藏里；失败保持现状、不打扰。 */
const syncState = async () => {
  if (!authStore.isLoggedIn) {
    favorited.value = false
    websiteId.value = null
    return
  }
  try {
    const res = await fetchMyProjectCollection({ source: 'website', page: 1, page_size: 60, sort: 'recent' })
    const hit = res.items.find((item) => normalizeHost(item.url) === siteHost())
    favorited.value = Boolean(hit)
    websiteId.value = hit?.website_id ?? null
  } catch {
    /* 状态探测失败静默处理，星星保持当前显示 */
  }
}

const errorDetail = (error: unknown): string => {
  const candidate = error as { response?: { data?: { detail?: unknown } }; message?: unknown }
  const detail = candidate?.response?.data?.detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message?: unknown }).message ?? candidate?.message ?? error)
  }
  return String(detail ?? candidate?.message ?? error)
}

const toggle = async () => {
  if (busy.value) return
  if (!authStore.isLoggedIn) {
    pendingAfterLogin.value = true
    requestLogin(route.fullPath)
    return
  }
  busy.value = true
  try {
    if (favorited.value) {
      if (websiteId.value == null) await syncState()
      if (websiteId.value == null) return
      await removeMyToolWebsite(websiteId.value)
      favorited.value = false
      websiteId.value = null
      showToast(t('masthead.favoriteSiteRemoved'))
    } else {
      const res = await addMyToolWebsite(window.location.origin)
      favorited.value = true
      websiteId.value = res.item?.website_id ?? websiteId.value
      showToast(res.duplicate ? t('masthead.favoriteSiteDuplicate') : t('masthead.favoriteSiteAdded'))
    }
  } catch (error) {
    showToast(errorDetail(error) || t('masthead.favoriteSiteFailed'))
  } finally {
    busy.value = false
  }
}

watch(
  () => authStore.isLoggedIn,
  (loggedIn) => {
    if (loggedIn && pendingAfterLogin.value) {
      pendingAfterLogin.value = false
      void toggle()
      return
    }
    void syncState()
  },
)

onMounted(() => { void syncState() })
</script>

<template>
  <button
    type="button"
    class="favorites-link"
    :class="{ 'favorites-link--active': favorited }"
    :aria-pressed="favorited"
    :disabled="busy"
    :aria-label="t(favorited ? 'masthead.unfavoriteSite' : 'masthead.favoriteSite')"
    :title="t(favorited ? 'masthead.unfavoriteSite' : 'masthead.favoriteSite')"
    @click="toggle"
  >
    <Star
      class="favorites-link__icon"
      :size="18"
      :stroke-width="1.8"
      :fill="favorited ? 'currentColor' : 'none'"
      aria-hidden="true"
    />
  </button>
</template>

<style scoped>
.favorites-link {
  display: inline-grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  color: var(--ink-muted);
  background: transparent;
  cursor: pointer;
  transition: color 150ms ease, background-color 150ms ease, transform 150ms ease;
}

.favorites-link:hover {
  color: var(--ink);
  background: var(--acid-soft);
  transform: rotate(-3deg);
}

.favorites-link:active { transform: rotate(-3deg) scale(0.92); }
.favorites-link:focus-visible { outline: 2px solid var(--acid); outline-offset: 2px; }
.favorites-link:disabled { cursor: wait; opacity: 0.6; }

.favorites-link--active,
.favorites-link--active:hover {
  color: var(--acid);
  background: var(--acid-soft);
}

@media (prefers-reduced-motion: reduce) {
  .favorites-link { transition: none; }
  .favorites-link:hover,
  .favorites-link:active { transform: none; }
}
</style>
