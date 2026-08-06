<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { WeChatCatalogAccount } from '@/features/wechat/wechatModel'

defineOptions({ name: 'WechatFollowBox' })

const props = defineProps<{
  catalog: WeChatCatalogAccount[]
  loading: boolean
  pendingFollowIds: Set<number>
  collapsed: boolean
}>()

const emit = defineEmits<{
  toggleFollow: [account: WeChatCatalogAccount]
  toggleCollapsed: []
}>()

const { t } = useI18n()
</script>

<template>
  <!-- 收缩态：左侧细条，点击展开 -->
  <button
    v-if="props.collapsed"
    type="button"
    class="follow-rail"
    :aria-label="t('wechat.expandFollowBox')"
    @click="emit('toggleCollapsed')"
  >
    <span class="follow-rail-icon">›</span>
    <span class="follow-rail-text">{{ t('wechat.catalogTitle') }}</span>
  </button>

  <!-- 展开态：悬浮关注框 -->
  <aside v-else class="follow-box">
    <div class="follow-box-header">
      <h2 class="follow-box-title">{{ t('wechat.catalogTitle') }}</h2>
      <button
        type="button"
        class="follow-box-collapse"
        :aria-label="t('wechat.collapseFollowBox')"
        @click="emit('toggleCollapsed')"
      >
        ‹
      </button>
    </div>

    <p v-if="props.loading" class="follow-box-empty">{{ t('common.loading') }}</p>
    <p v-else-if="props.catalog.length === 0" class="follow-box-empty">
      {{ t('wechat.catalogEmpty') }}
    </p>

    <ul v-else class="follow-box-list">
      <li v-for="account in props.catalog" :key="account.id" class="follow-box-item">
        <img
          v-if="account.avatar_url"
          :src="account.avatar_url"
          :alt="account.nickname"
          class="follow-box-avatar"
          loading="lazy"
          referrerpolicy="no-referrer"
        />
        <span v-else class="follow-box-avatar follow-box-avatar--placeholder">
          {{ (account.nickname || '?').slice(0, 1) }}
        </span>
        <span class="follow-box-name" :title="account.nickname">
          {{ account.nickname || t('wechat.unnamedAccount') }}
        </span>
        <button
          type="button"
          class="follow-box-btn"
          :class="{ 'follow-box-btn--followed': account.followed }"
          :disabled="props.pendingFollowIds.has(account.id)"
          @click="emit('toggleFollow', account)"
        >
          {{ account.followed ? t('wechat.followed') : t('wechat.follow') }}
        </button>
      </li>
    </ul>
  </aside>
</template>

<style scoped>
.follow-box {
  position: sticky;
  top: 24px;
  align-self: flex-start;
  width: 260px;
  max-height: calc(100vh - 140px);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--projects-accent);
  border-radius: 8px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 var(--shadow-hard);
  overflow: hidden;
  flex-shrink: 0;
}

.follow-box-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--rule);
}

.follow-box-title {
  font-size: 13px;
  font-weight: 800;
  color: var(--projects-accent);
}

.follow-box-collapse {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  font-size: 16px;
  font-weight: 800;
  line-height: 1;
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  color: var(--projects-accent);
  background: var(--projects-paper-light);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease;
}

.follow-box-collapse:hover {
  background: var(--acid-soft);
  transform: translate(-1px, -1px);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.follow-box-empty {
  padding: 16px 12px;
  font-size: 12px;
  color: var(--ink-muted);
}

.follow-box-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.follow-box-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px;
  border-radius: 6px;
  transition: background 150ms ease;
}

.follow-box-item:hover {
  background: rgb(var(--card-rgb) / 0.5);
}

.follow-box-avatar {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--projects-accent);
  object-fit: cover;
  flex-shrink: 0;
  background: var(--paper-raised);
}

.follow-box-avatar--placeholder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 800;
  color: var(--projects-accent);
}

.follow-box-name {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  font-weight: 700;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.follow-box-btn {
  flex-shrink: 0;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  border-radius: 4px;
  border: 1px solid var(--projects-accent);
  color: var(--projects-on-acid);
  background: var(--projects-acid);
  box-shadow: 2px 2px 0 var(--shadow-hard);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease;
}

.follow-box-btn:hover:not(:disabled) {
  transform: translate(-1px, -1px);
}

.follow-box-btn:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.follow-box-btn--followed {
  color: var(--projects-accent);
  background: var(--projects-paper-light);
  box-shadow: none;
}

.follow-rail {
  position: sticky;
  top: 24px;
  align-self: flex-start;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 36px;
  padding: 12px 4px;
  border: 1px solid var(--projects-accent);
  border-radius: 8px;
  background: var(--projects-paper-light);
  box-shadow: 3px 3px 0 var(--shadow-hard);
  color: var(--projects-accent);
  flex-shrink: 0;
  transition: transform 150ms ease, box-shadow 150ms ease;
}

.follow-rail:hover {
  transform: translate(-1px, -1px);
  box-shadow: 4px 4px 0 var(--shadow-hard);
}

.follow-rail-icon {
  font-size: 16px;
  font-weight: 800;
  line-height: 1;
}

.follow-rail-text {
  font-size: 11px;
  font-weight: 700;
  writing-mode: vertical-rl;
  letter-spacing: 2px;
}

@media (max-width: 768px) {
  .follow-box {
    position: static;
    width: 100%;
    max-height: 320px;
  }

  .follow-rail {
    position: static;
    flex-direction: row;
    width: auto;
    padding: 8px 12px;
  }

  .follow-rail-text {
    writing-mode: horizontal-tb;
    letter-spacing: normal;
  }
}
</style>
