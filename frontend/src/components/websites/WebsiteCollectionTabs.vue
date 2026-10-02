<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { ensureRecommendedWebsites, useRecommendedWebsitesSnapshot } from '@/composables/recommendedWebsitesSnapshot'
import { useAuthStore } from '@/stores/authStore'

const props = defineProps<{ active: 'recommended' | 'personal' }>()
const { t } = useI18n()
const auth = useAuthStore()
const { requestLogin } = useLoginPrompt()
const recommended = useRecommendedWebsitesSnapshot()
const PERSONAL = '/projects?source=website'

// 站长推荐还空着时先把标签藏起来；管理员留着，好去添加。还没拿到列表时照常显示。
const showRecommended = computed(() => props.active === 'recommended' || auth.isAdmin
  || recommended.value === null || recommended.value.length > 0)
// 「我的网页收藏」登录后才有：游客点这个标签直接弹登录，登录后回到收藏页；站长推荐页的标签旁再说一句为什么。
const guest = computed(() => auth.status === 'anonymous' || auth.status === 'degraded')
const showLoginLine = computed(() => guest.value && props.active === 'recommended')
const openPersonal = (event: MouseEvent, navigate: (event?: MouseEvent) => unknown) => {
  if (!guest.value) return navigate(event)
  event.preventDefault()
  requestLogin(PERSONAL)
}

// 推荐页自己会拉列表；收藏页这边拉一次，好知道要不要藏「站长推荐」。
onMounted(() => { if (props.active === 'personal') void ensureRecommendedWebsites() })
</script>

<template>
  <div class="website-tabs-row" :class="{ 'website-tabs-row--with-login': showLoginLine }">
    <nav class="website-tabs" :aria-label="t('recommendedWebsites.collectionNav')">
      <RouterLink v-if="showRecommended" to="/websites" :aria-current="active === 'recommended' ? 'page' : undefined">{{ t('recommendedWebsites.title') }}</RouterLink>
      <RouterLink v-slot="{ href, navigate }" :to="PERSONAL" custom>
        <a :href="href" :aria-current="active === 'personal' ? 'page' : undefined" @click="openPersonal($event, navigate)">{{ t('projects.source.websiteLabel') }}</a>
      </RouterLink>
    </nav>
    <p v-if="showLoginLine" class="website-tabs-login">
      <span>{{ t('recommendedWebsites.guestLine') }}</span>
      <button type="button" @click="requestLogin(PERSONAL)">{{ t('projects.loginAction') }}</button>
    </p>
  </div>
</template>

<style scoped>
/* 没有登录提示时这一层不占版面，标签条照旧直接排在父容器里。 */
.website-tabs-row { display: contents; }
.website-tabs-row--with-login { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px; min-width: 0; }
.website-tabs { display: flex; width: fit-content; max-width: 100%; gap: 4px; padding: 3px; border-radius: var(--control-radius); background: var(--paper-muted); }
.website-tabs a { display: flex; align-items: center; justify-content: center; min-height: 38px; padding: 4px 12px; border: 1px solid transparent; border-radius: 6px; color: var(--ink-secondary); font-size: 13px; font-weight: 600; white-space: nowrap; }
.website-tabs a[aria-current] { color: var(--projects-on-acid); background: var(--projects-acid); border-color: var(--projects-accent); box-shadow: 2px 2px 0 var(--shadow-hard); }
.website-tabs a:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
/* 按钮跟在句尾；窄屏放不下时整词换行，不单独占一行。 */
.website-tabs-login { min-width: 0; margin: 0; color: var(--ink-secondary); font-size: 13px; line-height: 1.5; }
.website-tabs-login button { margin-inline-start: 10px; color: var(--ink); font-weight: 700; text-decoration: underline; text-underline-offset: 4px; white-space: nowrap; }
.website-tabs-login button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
@media (max-width: 639px) { .website-tabs { width: 100%; } .website-tabs a { flex: 1; padding: 4px 8px; font-size: 12px; } }
</style>
