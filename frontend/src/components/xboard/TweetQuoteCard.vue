<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ExternalLink } from 'lucide-vue-next'
import type { TopDoc, TweetMediaItem } from '@/features/dashboard/dashboardViewModel'
import { displayQuoteText, quoteAvatarUrl, quoteMediaItems, quoteTextSegments } from '@/features/xboard/xBoardViewModel'

const props = withDefaults(defineProps<{
  quote: NonNullable<TopDoc['quote']>
  /** wall = 看板卡片（activate = 放大主推详情）；detail = 详情浮层（activate = 下钻被引推文详情）。
      两上下文的 aria-label 与外层留白不同，由父组件按场景指定。 */
  context?: 'wall' | 'detail'
  /** 紧凑排版（桌面推文墙）：引用正文并掉空行，多件配图排成一行等宽的方帧（胶片） */
  compact?: boolean
  /** 纯文字：不排引用配图 */
  textOnly?: boolean
}>(), { context: 'wall', compact: false, textOnly: false })

const emit = defineEmits<{
  /** 整卡激活（点击/回车）：wall 打开主推详情，detail 下钻被引推文 */
  activate: []
}>()

const { t, locale } = useI18n()

const ariaLabel = computed(() => t(props.context === 'detail' ? 'xboard.openQuoteDetail' : 'xboard.openDetail'))

const isVideo = (item: TweetMediaItem) => item.type === 'video' || item.type === 'animated_gif'

// 引用卡片内只渲染缩略图（整卡点击跳被引推文，不内嵌播放）：视频用封面，
// 照片用 small 变体降载；无封面（非 twimg 直链等）不渲染该媒体位
const quoteMediaThumb = (item: TweetMediaItem) => (isVideo(item) ? (item.poster_url ?? '') : (item.thumb_url || item.url))

const media = computed(() => (props.textOnly ? [] : quoteMediaItems(props.quote)))
const strip = computed(() => props.compact && media.value.length > 1)
</script>

<template>
  <!-- 引用推文卡片：↗ 钮显式直跳被引推文；整卡 activate 由父组件按上下文接线 -->
  <div
    role="button"
    tabindex="0"
    class="tweet-quote block cursor-pointer"
    :class="context === 'detail' ? 'mx-4 my-2' : 'mx-1 mt-2'"
    :aria-label="ariaLabel"
    @click="emit('activate')"
    @keydown.enter="emit('activate')"
  >
    <span class="tweet-quote-head flex items-center gap-1.5 px-3 pt-2">
      <img
        v-if="quoteAvatarUrl(quote)"
        :src="quoteAvatarUrl(quote)"
        :alt="quote.author_name || quote.author"
        loading="lazy"
        decoding="async"
        referrerpolicy="no-referrer"
        class="tweet-quote-avatar h-4 w-4 shrink-0 object-cover"
      />
      <span class="tweet-quote-name truncate text-xs font-semibold">{{ quote.author_name || `@${quote.author}` }}</span>
      <span v-if="quote.author" class="tweet-quote-handle truncate text-2xs">@{{ quote.author }}</span>
      <a
        class="tweet-icon-btn tweet-quote-jump ml-auto"
        :href="quote.url"
        target="_blank"
        rel="noopener noreferrer"
        :aria-label="t('xboard.viewOnX')"
        @click.stop
        @keydown.enter.stop
      ><ExternalLink class="h-3 w-3" /></a>
    </span>
    <span v-if="displayQuoteText(quote, locale)" class="tweet-quote-text block whitespace-pre-line px-3 pt-1 text-2xs leading-4">
      <template v-for="(seg, segIndex) in quoteTextSegments(quote, locale, compact)" :key="segIndex">
        <span v-if="seg.isUrl || seg.isMention" class="tweet-quote-link">{{ seg.text }}</span>
        <span v-else>{{ seg.text }}</span>
      </template>
    </span>
    <span v-if="media.length" class="tweet-quote-media block px-3 pb-2 pt-1.5" :class="{ 'tweet-quote-media--strip': strip }">
      <template v-for="(item, mediaIndex) in media" :key="mediaIndex">
        <img
          v-if="quoteMediaThumb(item)"
          :src="quoteMediaThumb(item)"
          :alt="quote.text || quote.author"
          loading="lazy"
          decoding="async"
          referrerpolicy="no-referrer"
          class="tweet-quote-photo w-full object-cover"
          :style="!strip && item.width && item.height ? { aspectRatio: `${item.width} / ${item.height}` } : {}"
          @error="($event.target as HTMLImageElement).style.display = 'none'"
        />
      </template>
    </span>
  </div>
</template>

<style scoped>
/* 引用推文卡片：静态即浮起态（墨边 + 纸面 + 2px 硬影，chip 配方），
   让可点的内嵌卡始终有「卡片感」；hover 按主题惯例换 acid-soft 底色
   （与主卡/text 段 hover 同一词汇），不做位移 */
.tweet-quote {
  overflow: hidden;
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--projects-paper-light);
  box-shadow: 2px 2px 0 var(--shadow-hard);
  transition:
    border-color 150ms ease,
    background 150ms ease,
    box-shadow 150ms ease;
}

.tweet-quote:hover {
  background: var(--acid-soft);
}

/* 主题去胶囊化：引用头像与外推头像同方（4px 圆角 + --rule 细边） */
.tweet-quote-avatar {
  border: 1px solid var(--rule);
  border-radius: 4px;
}

.tweet-quote-handle {
  color: var(--ink-muted);
}

/* 被引作者名与外推 handle 同墨色（stone-700 无主题映射，不走原灰色） */
.tweet-quote-name {
  color: var(--ink);
}

/* 引用正文颜色：原依赖看板页的 text-stone-600 → --ink-secondary 映射，
   随组件抽取内聚为组件自身规则 */
.tweet-quote-text {
  color: var(--ink-secondary);
}

/* 卡头动作钮（跳转）：quiet 小方钮，hover acid 反转——与看板卡头按钮同配方 */
.tweet-icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.375rem;
  height: 1.375rem;
  border: 1px solid var(--rule);
  border-radius: 4px;
  color: var(--ink-muted);
  cursor: pointer;
  transition:
    background 150ms ease,
    border-color 150ms ease,
    color 150ms ease;
}

.tweet-icon-btn:hover {
  border-color: var(--ink);
  background: var(--acid);
  color: var(--projects-on-acid);
}

/* 引用卡显式跳转钮：复用卡头动作钮配方但小一号，对齐引用区轻量层级 */
.tweet-quote-jump {
  width: 1.25rem;
  height: 1.25rem;
  flex-shrink: 0;
}

/* 引用正文里的链接不可独点（整卡已是锚点），下划线仅作视觉标识 */
.tweet-quote-link {
  text-decoration: underline;
  text-underline-offset: 2px;
  word-break: break-all;
}

/* 引用媒体：--rule 细边保持内嵌区的视觉层级低于主卡媒体（--ink） */
.tweet-quote-photo {
  max-height: 220px;
  border: 1px solid var(--rule);
  border-radius: 5px;
}

/* 胶片：多件配图排成一行等宽的方帧，帧高不过引用配图限高 */
.tweet-quote-media--strip {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.tweet-quote-media--strip > .tweet-quote-photo {
  flex: 1 1 0;
  min-width: 0;
  aspect-ratio: 1;
  max-height: var(--tweet-quote-media-max, 110px);
}
</style>
