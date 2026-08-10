<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
import { linkCardImageUrl } from '@/features/xboard/xBoardViewModel'

withDefaults(defineProps<{
  card: NonNullable<TopDoc['link_card']>
  /** wall = 看板卡片；detail = 详情浮层。仅外层留白不同，与 TweetQuoteCard 同一约定。 */
  context?: 'wall' | 'detail'
}>(), { context: 'wall' })

const { t } = useI18n()
</script>

<template>
  <!-- 链接预览卡：整卡跳目标页（与 X 点击卡片行为一致）；缩略图缺失或
       非 twimg 镜像时降级为纯文本卡（标题/描述/域名仍完整可点） -->
  <a
    class="tweet-linkcard block"
    :class="context === 'detail' ? 'mx-4 my-2' : 'mx-1 mt-2'"
    :href="card.url"
    target="_blank"
    rel="noopener noreferrer"
    :aria-label="t('xboard.openLinkCard')"
    @click.stop
  >
    <img
      v-if="linkCardImageUrl(card)"
      :src="linkCardImageUrl(card)"
      :alt="card.title"
      loading="lazy"
      decoding="async"
      referrerpolicy="no-referrer"
      class="tweet-linkcard-image w-full object-cover"
      :style="card.image_width && card.image_height ? { aspectRatio: `${card.image_width} / ${card.image_height}` } : {}"
      @error="($event.target as HTMLImageElement).style.display = 'none'"
    />
    <span class="tweet-linkcard-body block px-3 py-2">
      <span class="tweet-linkcard-title block truncate text-xs font-semibold">{{ card.title }}</span>
      <span v-if="card.description" class="tweet-linkcard-desc mt-0.5 block text-2xs leading-4">{{ card.description }}</span>
      <span v-if="card.domain" class="tweet-linkcard-domain mt-0.5 block text-2xs">{{ card.domain }}</span>
    </span>
  </a>
</template>

<style scoped>
/* 链接预览卡：与引用卡同一「静态即浮起态」配方（墨边 + 纸面 + 2px 硬影），
   hover 换 acid-soft 底色；整卡是锚点，跳目标页而非放大详情 */
.tweet-linkcard {
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

.tweet-linkcard:hover {
  background: var(--acid-soft);
}

/* 缩略图：--rule 细边维持内嵌区层级低于主卡媒体；高宽比由落库元数据
   内联给出（防布局抖动），缺省交给自然高度 */
.tweet-linkcard-image {
  max-height: 260px;
  border-bottom: 1px solid var(--rule);
}

.tweet-linkcard-title {
  color: var(--ink);
}

/* 描述限两行：与 X 卡片描述截断一致，超出省略 */
.tweet-linkcard-desc {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  color: var(--ink-secondary);
}

.tweet-linkcard-domain {
  color: var(--ink-muted);
}
</style>
