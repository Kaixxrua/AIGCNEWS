<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWechatFollowController } from '@/composables/useWechatFollowController'
import WechatFollowBox from '@/components/wechat/WechatFollowBox.vue'
import WechatAccountCard from '@/components/wechat/WechatAccountCard.vue'

defineOptions({ name: 'WechatView' })

const { t } = useI18n()

const {
  error,
  catalog,
  isCatalogLoading,
  isFeedLoading,
  pendingFollowIds,
  expandedArticleKeys,
  selectedAccountId,
  followBoxCollapsed,
  followedAccounts,
  visibleFeed,
  dispose,
  loadCatalog,
  loadFeed,
  toggleFollow,
  articleKey,
  toggleArticleExpanded,
  selectAccount,
  toggleFollowBoxCollapsed,
} = useWechatFollowController()

onMounted(async () => {
  await Promise.all([loadCatalog(), loadFeed()])
})
onBeforeUnmount(dispose)
</script>

<template>
  <div class="wechat-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6 pb-24">
      <!-- 页头 -->
      <div class="stagger-enter flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">{{ t('wechat.feedTitle') }}</h1>
          <p class="wechat-caption mt-0.5 text-sm">{{ t('wechat.feedDescription') }}</p>
        </div>
      </div>

      <p v-if="error" class="wechat-error shrink-0">{{ error }}</p>

      <div class="wechat-body flex min-h-0 flex-1 items-start gap-5">
        <!-- 悬浮关注框（可收缩为左侧细条） -->
        <WechatFollowBox
          :catalog="catalog"
          :loading="isCatalogLoading"
          :pending-follow-ids="pendingFollowIds"
          :collapsed="followBoxCollapsed"
          @toggle-follow="toggleFollow"
          @toggle-collapsed="toggleFollowBoxCollapsed"
        />

        <div class="flex min-w-0 flex-1 flex-col gap-5">
          <!-- 关注账号目录导航 -->
          <nav v-if="followedAccounts.length > 0" class="wechat-directory shrink-0">
            <span class="wechat-directory-label">{{ t('wechat.directoryTitle') }}</span>
            <div class="wechat-directory-items">
              <button
                type="button"
                class="wechat-directory-item"
                :class="{ 'wechat-directory-item--active': selectedAccountId === null }"
                @click="selectAccount(null)"
              >
                {{ t('wechat.directoryAll') }}
              </button>
              <button
                v-for="account in followedAccounts"
                :key="account.id"
                type="button"
                class="wechat-directory-item"
                :class="{ 'wechat-directory-item--active': selectedAccountId === account.id }"
                @click="selectAccount(account.id)"
              >
                {{ account.nickname || t('wechat.unnamedAccount') }}
              </button>
            </div>
          </nav>

          <!-- 账号卡片信息流 -->
          <p v-if="isFeedLoading && visibleFeed.length === 0" class="wechat-empty">
            {{ t('common.loading') }}
          </p>
          <div v-else-if="visibleFeed.length === 0" class="wechat-empty">
            <p>{{ t('wechat.feedEmpty') }}</p>
            <p class="mt-1 text-xs">{{ t('wechat.feedEmptyHint') }}</p>
          </div>
          <template v-else>
            <WechatAccountCard
              v-for="entry in visibleFeed"
              :key="entry.account.id"
              :entry="entry"
              :expanded-article-keys="expandedArticleKeys"
              :article-key="articleKey"
              @toggle-article="toggleArticleExpanded"
            />
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wechat-page {
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.wechat-caption {
  color: var(--ink-muted);
}

.wechat-error {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid var(--error-accent);
  border-radius: 6px;
  color: var(--error-ink);
  background: var(--error-bg);
}

.wechat-directory {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.wechat-directory-label {
  font-size: 12px;
  font-weight: 800;
  color: var(--projects-accent);
  flex-shrink: 0;
}

.wechat-directory-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.wechat-directory-item {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  border-radius: 999px;
  border: 1px solid var(--projects-accent);
  color: var(--projects-accent);
  background: var(--projects-paper-light);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease, color 150ms ease;
}

.wechat-directory-item:hover {
  transform: translate(-1px, -1px);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.wechat-directory-item--active {
  color: var(--projects-on-acid);
  background: var(--projects-acid);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.wechat-empty {
  padding: 32px 20px;
  font-size: 13px;
  text-align: center;
  border: 1px dashed var(--rule);
  border-radius: 8px;
  background: rgb(var(--card-rgb) / 0.3);
  color: var(--ink-muted);
}

@media (max-width: 768px) {
  .wechat-body {
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: reduce) {
  .wechat-page :deep(*),
  .wechat-page :deep(*::before),
  .wechat-page :deep(*::after) {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
</style>
