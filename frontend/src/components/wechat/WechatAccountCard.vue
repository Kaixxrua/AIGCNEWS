<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type {
  WeChatArticle,
  WeChatArticleDetail,
  WeChatFeedEntry,
} from '@/features/wechat/wechatModel'

defineOptions({ name: 'WechatAccountCard' })

const props = defineProps<{
  entry: WeChatFeedEntry
  expandedArticleKeys: Set<string>
  articleKey: (accountId: number, articleId: number | null, stableKey: string) => string
  articleDetails: Map<string, WeChatArticleDetail>
  articleDetailLoading: Set<string>
  articleDetailErrors: Map<string, string>
}>()

const emit = defineEmits<{
  toggleArticle: [key: string, accountId: number, article: WeChatArticle]
  retryDetail: [key: string, accountId: number, article: WeChatArticle]
}>()

const { t } = useI18n()

const formatPublishedAt = (value: string | null): string => {
  if (!value) return ''
  return value.slice(0, 16).replace('T', ' ')
}

const keyFor = (article: WeChatArticle): string =>
  props.articleKey(props.entry.account.id, article.id, article.stable_article_key)
</script>

<template>
  <section class="account-card">
    <!-- 账号头 -->
    <header class="account-card-header">
      <img
        v-if="entry.account.avatar_url"
        :src="entry.account.avatar_url"
        :alt="entry.account.nickname"
        class="account-card-avatar"
        loading="lazy"
        referrerpolicy="no-referrer"
      />
      <span v-else class="account-card-avatar account-card-avatar--placeholder">
        {{ (entry.account.nickname || '?').slice(0, 1) }}
      </span>
      <div class="account-card-meta">
        <h3 class="account-card-name">
          {{ entry.account.nickname || t('wechat.unnamedAccount') }}
        </h3>
        <p v-if="entry.account.signature" class="account-card-signature">
          {{ entry.account.signature }}
        </p>
      </div>
    </header>

    <!-- 最近消息（默认折叠，点击展开详情） -->
    <p v-if="entry.articles.length === 0" class="account-card-empty">
      {{ t('wechat.noRecentArticles') }}
    </p>
    <ul v-else class="account-card-articles">
      <li v-for="article in entry.articles" :key="keyFor(article)" class="article-row">
        <button
          type="button"
          class="article-summary"
          :aria-expanded="expandedArticleKeys.has(keyFor(article))"
          @click="emit('toggleArticle', keyFor(article), entry.account.id, article)"
        >
          <span class="article-chevron" :class="{ 'article-chevron--open': expandedArticleKeys.has(keyFor(article)) }">›</span>
          <span class="article-title">{{ article.title || t('wechat.untitledArticle') }}</span>
          <time class="article-time">{{ formatPublishedAt(article.published_at) }}</time>
        </button>

        <div v-if="expandedArticleKeys.has(keyFor(article))" class="article-detail">
          <img
            v-if="article.cover_url"
            :src="article.cover_url"
            :alt="article.title"
            class="article-cover"
            loading="lazy"
            referrerpolicy="no-referrer"
          />
          <p v-if="article.digest" class="article-digest">{{ article.digest }}</p>

          <!-- 全文正文（has_content 时懒加载，正文已在服务端+前端两道清洗） -->
          <template v-if="article.has_content">
            <p
              v-if="articleDetailLoading.has(keyFor(article)) && !articleDetails.has(keyFor(article))"
              class="article-content-loading"
            >
              {{ t('wechat.fullTextLoading') }}
            </p>
            <p v-else-if="articleDetailErrors.has(keyFor(article))" class="article-content-error">
              {{ articleDetailErrors.get(keyFor(article)) }}
              <button
                type="button"
                class="article-content-retry"
                @click="emit('retryDetail', keyFor(article), entry.account.id, article)"
              >
                {{ t('wechat.retry') }}
              </button>
            </p>
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div
              v-else-if="articleDetails.has(keyFor(article))"
              class="prose-content wechat-article-content"
              v-html="articleDetails.get(keyFor(article))?.content_html"
            ></div>
          </template>

          <p v-if="article.author" class="article-author">{{ article.author }}</p>
          <a
            v-if="article.article_url"
            :href="article.article_url"
            target="_blank"
            rel="noopener"
            class="article-link"
          >
            {{ t('wechat.readOriginal') }} ↗
          </a>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.account-card {
  border: 1px solid var(--projects-accent);
  border-radius: 8px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 var(--shadow-hard);
  overflow: hidden;
}

.account-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--rule);
}

.account-card-avatar {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  border: 1px solid var(--projects-accent);
  object-fit: cover;
  flex-shrink: 0;
  background: var(--paper-raised);
}

.account-card-avatar--placeholder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 800;
  color: var(--projects-on-acid);
  background: var(--projects-acid);
}

.account-card-meta {
  flex: 1;
  min-width: 0;
}

.account-card-name {
  font-size: 14px;
  font-weight: 800;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.account-card-signature {
  margin-top: 2px;
  font-size: 11px;
  color: var(--ink-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.account-card-empty {
  padding: 14px;
  font-size: 12px;
  color: var(--ink-muted);
}

.account-card-articles {
  display: flex;
  flex-direction: column;
}

.article-row + .article-row {
  border-top: 1px dashed var(--rule);
}

.article-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 14px;
  text-align: left;
  transition: background 150ms ease;
}

.article-summary:hover {
  background: rgb(var(--card-rgb) / 0.5);
}

.article-chevron {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 800;
  color: var(--projects-accent);
  transition: transform 150ms ease;
}

.article-chevron--open {
  transform: rotate(90deg);
}

.article-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.article-time {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--ink-muted);
}

.article-detail {
  padding: 0 14px 12px 36px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.article-cover {
  width: 100%;
  max-height: 160px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--rule);
}

.article-digest {
  font-size: 12px;
  line-height: 1.6;
  color: var(--ink);
}

.article-author {
  font-size: 11px;
  color: var(--ink-muted);
}

.article-content-loading {
  font-size: 12px;
  color: var(--ink-muted);
}

.article-content-error {
  font-size: 12px;
  color: var(--danger-ink, #b3261e);
}

.article-content-retry {
  margin-left: 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--projects-accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.article-content-retry:hover {
  color: var(--acid-strong);
}

.article-link {
  align-self: flex-start;
  font-size: 12px;
  font-weight: 700;
  color: var(--projects-accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.article-link:hover {
  color: var(--acid-strong);
}
</style>
