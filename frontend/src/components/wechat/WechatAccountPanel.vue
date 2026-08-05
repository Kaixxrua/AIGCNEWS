<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWechatController } from '@/composables/useWechatController'
import WechatLoginDialog from '@/components/wechat/WechatLoginDialog.vue'

const { t } = useI18n()
const controller = useWechatController()

onMounted(() => {
  controller.refreshSession()
  controller.loadAccounts()
})
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 overflow-hidden p-0" style="animation-delay: 0.25s">
    <div class="monitor-divider relative border-b p-5">
      <div class="relative flex flex-wrap items-start justify-between gap-3">
        <div class="max-w-3xl">
          <div class="flex flex-wrap items-center gap-2">
            <span class="monitor-avatar monitor-avatar-accent flex h-8 w-8 items-center justify-center font-mono text-sm shadow-sm">微</span>
            <h3 class="monitor-section-title text-sm font-semibold">{{ t('wechat.panelTitle') }}</h3>
            <span v-if="controller.hasSession.value" class="monitor-badge monitor-status-running">{{ t('wechat.connected') }}</span>
            <span v-else class="monitor-badge">{{ t('wechat.disconnected') }}</span>
          </div>
          <p class="monitor-caption mt-2 text-xs leading-5">{{ t('wechat.panelDescription') }}</p>
        </div>
        <div class="flex gap-2">
          <button class="monitor-btn-secondary" :disabled="controller.isLoading.value" @click="controller.loadAccounts">
            {{ t('wechat.refresh') }}
          </button>
          <button class="monitor-btn-primary" @click="controller.openLoginDialog">
            {{ controller.hasSession.value ? t('wechat.reconnect') : t('wechat.login') }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="controller.error.value" class="mx-5 mt-4 flex items-center justify-between rounded-md border px-4 py-2 text-xs monitor-status-error">
      <span>{{ controller.error.value }}</span>
      <button class="ml-3 opacity-70 hover:opacity-100" @click="controller.clearError()">✕</button>
    </div>
    <div v-if="controller.notice.value" class="mx-5 mt-4 flex items-center justify-between rounded-md border px-4 py-2 text-xs monitor-status-success">
      <span>{{ controller.notice.value }}</span>
      <button class="ml-3 opacity-70 hover:opacity-100" @click="controller.notice.value = ''">✕</button>
    </div>

    <div class="p-5">
      <div class="monitor-surface mb-4 p-4">
        <h4 class="text-xs font-semibold uppercase tracking-widest monitor-caption">{{ t('wechat.savedAccounts') }}</h4>
        <div v-if="!controller.accounts.value.length" class="monitor-empty mt-3 flex h-32 flex-col items-center justify-center rounded-md text-center text-sm">
          <p>{{ t('wechat.noAccounts') }}</p>
        </div>
        <div v-else class="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="account in controller.accounts.value"
            :key="account.id ?? account.fakeid"
            class="monitor-surface cursor-pointer p-3 transition hover:-translate-y-0.5"
            :class="{ 'ring-1 ring-current': controller.selectedAccount.value?.id === account.id }"
            @click="controller.selectAccount(account); controller.loadArticles()"
          >
            <div class="flex items-start gap-3">
              <img v-if="account.avatar_url" :src="account.avatar_url" class="h-10 w-10 rounded-full object-cover" />
              <div v-else class="monitor-avatar flex h-10 w-10 shrink-0 text-base">
                {{ (account.nickname || account.alias || '微').slice(0, 1) }}
              </div>
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-semibold">{{ account.nickname || account.alias || t('wechat.unnamedAccount') }}</p>
                <p class="text-2xs monitor-caption">{{ account.signature }}</p>
                <span class="mt-1 inline-block text-2xs monitor-badge">{{ account.last_sync_status }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="controller.selectedAccount.value" class="monitor-surface p-4">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h4 class="text-xs font-semibold uppercase tracking-widest monitor-caption">
            {{ t('wechat.articlesTitle', { name: controller.selectedAccount.value.nickname || controller.selectedAccount.value.alias }) }}
          </h4>
          <button class="monitor-btn-primary" :disabled="controller.isSyncing.value" @click="controller.submitSync">
            {{ controller.isSyncing.value ? t('wechat.syncing') : t('wechat.sync') }}
          </button>
        </div>
        <div v-if="!controller.articles.value.length" class="monitor-empty flex h-32 flex-col items-center justify-center rounded-md text-center text-sm">
          <p>{{ t('wechat.noArticles') }}</p>
        </div>
        <div v-else class="space-y-3">
          <a
            v-for="article in controller.articles.value"
            :key="article.stable_article_key"
            :href="article.article_url"
            target="_blank"
            rel="noopener noreferrer"
            class="monitor-surface block p-3 transition hover:-translate-y-0.5"
          >
            <p class="text-sm font-semibold">{{ article.title || t('wechat.untitledArticle') }}</p>
            <p class="mt-1 line-clamp-2 text-xs monitor-caption">{{ article.digest }}</p>
            <div class="mt-2 flex flex-wrap gap-2 text-2xs monitor-caption">
              <span v-if="article.author">{{ article.author }}</span>
              <span v-if="article.published_at">{{ article.published_at }}</span>
            </div>
          </a>
        </div>
      </div>
    </div>

    <WechatLoginDialog v-model="controller.isLoginDialogOpen.value" :controller="controller" />
  </div>
</template>
