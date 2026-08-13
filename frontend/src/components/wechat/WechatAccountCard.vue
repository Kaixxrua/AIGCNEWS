<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { proxiedWechatImageUrl } from '@/features/wechat/wechatArticleHtml'
import type {
  WeChatArticle,
  WeChatArticleDetail,
  WeChatFeedEntry,
} from '@/features/wechat/wechatModel'

defineOptions({ name: 'WechatAccountCard' })

const props = defineProps<{
  entry: WeChatFeedEntry
  /** 全文详情仅管理员（运营者自用）可见；普通用户展示层为摘要 + 原文链接 */
  isAdmin?: boolean
  expandedArticleKeys: Set<string>
  articleKey: (accountId: number, articleId: number | null, stableKey: string) => string
  articleDetails: Map<string, WeChatArticleDetail>
  articleDetailLoading: Set<string>
  articleDetailErrors: Map<string, string>
}>()

const emit = defineEmits<{
  toggleArticle: [key: string, accountId?: number, article?: WeChatArticle]
  retryDetail: [key: string, accountId: number, article: WeChatArticle]
}>()

const { t } = useI18n()

const formatPublishedAt = (value: string | null): string => {
  if (!value) return ''
  return value.slice(0, 16).replace('T', ' ')
}

const keyFor = (article: WeChatArticle): string =>
  props.articleKey(props.entry.account.id, article.id, article.stable_article_key)

// 普通用户展开只切换面板（不携带 article，控制器因此不会请求全文详情）
const onSummaryClick = (article: WeChatArticle) => {
  if (props.isAdmin) {
    emit('toggleArticle', keyFor(article), props.entry.account.id, article)
  } else {
    emit('toggleArticle', keyFor(article))
  }
}

// prefers-reduced-motion 下退回瞬时滚动，与 WechatView 的全局动效豁免保持一致
const scrollBehavior = (): ScrollBehavior =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
    ? 'auto'
    : 'smooth'

// 文首/文末跳转：从点击按钮回溯所在文章行，文首对齐标题行，文末对齐内容收尾锚点
const scrollToArticleEdge = (event: MouseEvent, edge: 'start' | 'end') => {
  const row = (event.currentTarget as HTMLElement | null)?.closest('.article-row')
  const target =
    edge === 'start'
      ? row?.querySelector('.article-summary')
      : row?.querySelector('.article-detail-end')
  target?.scrollIntoView({ behavior: scrollBehavior(), block: edge })
}
</script>

<template>
  <section class="account-card">
    <!-- 账号头 -->
    <header class="account-card-header">
      <img
        v-if="entry.account.avatar_url"
        :src="proxiedWechatImageUrl(entry.account.avatar_url)"
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
          @click="onSummaryClick(article)"
        >
          <span class="article-chevron" :class="{ 'article-chevron--open': expandedArticleKeys.has(keyFor(article)) }">›</span>
          <span class="article-title">{{ article.title || t('wechat.untitledArticle') }}</span>
          <time class="article-time">{{ formatPublishedAt(article.published_at) }}</time>
        </button>

        <Transition name="article-expand">
          <div v-if="expandedArticleKeys.has(keyFor(article))" class="article-detail-shell">
            <div class="article-detail">
              <!-- 文内跳转：竖排悬浮在卡片右缘，sticky 吸附在滚动视口纵向中线，
                   只在管理员全文展开期间可见；容器不拦截指针，避免遮挡正文链接点击 -->
              <div v-if="isAdmin && article.has_content" class="article-nav">
                <button
                  type="button"
                  class="article-nav-btn"
                  :aria-label="t('wechat.backToArticleTop')"
                  :title="t('wechat.backToArticleTop')"
                  @click="scrollToArticleEdge($event, 'start')"
                >
                  ↑
                </button>
                <button
                  type="button"
                  class="article-nav-btn"
                  :aria-label="t('wechat.skipToArticleEnd')"
                  :title="t('wechat.skipToArticleEnd')"
                  @click="scrollToArticleEdge($event, 'end')"
                >
                  ↓
                </button>
              </div>

              <img
                v-if="article.cover_url"
                :src="proxiedWechatImageUrl(article.cover_url)"
                :alt="article.title"
                class="article-cover"
                loading="lazy"
                referrerpolicy="no-referrer"
              />
              <!-- 管理员看全文时不并列摘要（搜狗摘要即正文开头截断，会重复）；
                   普通用户始终显示摘要，全文引导至原文 -->
              <p v-if="article.digest && (!article.has_content || !isAdmin)" class="article-digest">{{ article.digest }}</p>

              <!-- 全文正文（仅管理员；has_content 时懒加载，正文已在服务端+前端两道清洗） -->
              <template v-if="article.has_content && isAdmin">
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

              <p v-if="article.has_content && !isAdmin" class="article-fulltext-hint">
                {{ t('wechat.fullTextRedirect') }}
              </p>
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
              <!-- 文末锚点：「跳到底部」的滚动对齐目标 -->
              <div class="article-detail-end" aria-hidden="true"></div>
            </div>
          </div>
        </Transition>
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
  /* 用 clip 而非 hidden 裁圆角：hidden 会创建滚动容器，
     把卡片内 sticky 元素的吸附目标截获在卡片上，导致文内跳转按钮失效 */
  overflow: clip;
}

.account-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--rule);
}

/* 公众号头像多为"内切圆构图 + 透明四角"的 PNG，圆角方形容器会露出
   透明角、浅色图案浮在框里像裂图；圆形裁剪与构图贴合，视觉即头像 */
.account-card-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
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

/* 展开/收起过渡外壳：grid 行轨 0fr↔1fr 平滑动画高度，长文无封顶（max-height
   方案超出封顶值会跳变）；内层 overflow: clip 裁剪过渡中溢出的内容，clip 不
   创建滚动容器，卡片内 sticky 按钮仍相对页面滚动条吸附 */
.article-detail-shell {
  display: grid;
  grid-template-rows: 1fr;
}

.article-expand-enter-active,
.article-expand-leave-active {
  transition: grid-template-rows 0.28s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.22s ease;
}

.article-expand-enter-from,
.article-expand-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
}

.article-detail {
  min-height: 0;
  overflow: clip;
  padding: 4px 14px 16px 36px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 阅读列：宽屏下把展开详情收进居中的 42rem 栏（约 45 个中文字/行，
   对齐公众号网页版 ~677px 栏宽），窄屏时 max-width 不生效、保持通栏 */
.article-detail > * {
  width: 100%;
  max-width: 42rem;
  margin-inline: auto;
}

/* 文内跳转：竖排悬浮在卡片右缘，sticky 吸附在滚动视口纵向中线（读长文时
   始终可及，且不占正文上方的视觉焦点）；默认实色可读但视觉安静——品牌色
   箭头 + 细边框 + 柔和投影，hover/键盘聚焦时微微浮起。负下边距抵消自身
   在文档流中的占位，正文上端不留空档 */
.article-nav {
  position: sticky;
  top: 50%;
  z-index: 5;
  align-self: flex-end;
  width: auto;
  max-width: none;
  margin-inline: 0;
  margin-right: -6px;
  margin-bottom: -64px; /* = 两颗 28px 按钮 + 8px 间距，与下方尺寸保持一致 */
  display: flex;
  flex-direction: column;
  gap: 8px;
  transform: translateY(-50%);
  pointer-events: none;
}

.article-nav-btn {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  font-size: 14px;
  font-weight: 800;
  line-height: 1;
  border: 1px solid var(--rule);
  border-radius: 50%;
  color: var(--projects-accent);
  background: var(--projects-paper-light);
  box-shadow: 0 1px 5px rgb(0 0 0 / 0.14);
  backdrop-filter: blur(4px);
  transition: transform 150ms ease, box-shadow 150ms ease, border-color 150ms ease;
}

.article-nav-btn:hover,
.article-nav-btn:focus-visible {
  border-color: var(--projects-accent);
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgb(0 0 0 / 0.18);
}

.article-cover {
  width: 100%;
  max-height: 340px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--rule);
}

.article-digest {
  font-size: 12px;
  line-height: 1.6;
  color: var(--ink);
}

.article-fulltext-hint {
  font-size: 11px;
  line-height: 1.6;
  color: var(--ink-muted);
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
