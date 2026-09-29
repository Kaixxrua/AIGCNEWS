<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { TopDoc, TweetMediaItem } from '@/features/dashboard/dashboardViewModel'
import { mediaItems } from '@/features/xboard/xBoardViewModel'

const props = withDefaults(defineProps<{
  tweet: TopDoc
  /** 已点击播放的媒体键集合（与 mediaKey 同源）；父组件整体替换 Set 触发更新 */
  playingMedia: Set<string>
  /** wall = 看板卡片媒体区；detail = 详情浮层媒体区（浮层加 px-2 内边距，对齐浮层面板留白） */
  context?: 'wall' | 'detail'
}>(), { context: 'wall' })

const emit = defineEmits<{
  /** 照片点击放大（lightbox 取 item.url 大图变体，宽高决定长图滚动模式） */
  preview: [item: TweetMediaItem]
  /** 视频占位点击播放，键与模板 :key 同源 */
  play: [key: string]
}>()

const { t } = useI18n()

const isVideo = (item: TweetMediaItem) => item.type === 'video' || item.type === 'animated_gif'

// X 式点击播放：视频占位零流量（不经代理拉取元数据），点击后才挂载 <video>。
// 键与父组件播放态同源（`${tweet.url}-${index}`），重载推文时父组件清空避免自动重播。
const mediaKey = (tweet: TopDoc, index: number) => `${tweet.url}-${index}`
const isPlaying = (key: string) => props.playingMedia.has(key)
</script>

<template>
  <!-- 媒体区：看板/详情浮层同一渲染（照片可放大、视频点击播放，键同源不冲突） -->
  <div class="tweet-media-list" :class="{ 'px-2': context === 'detail' }">
    <template v-for="(item, index) in mediaItems(tweet)" :key="mediaKey(tweet, index)">
      <img
        v-if="!isVideo(item)"
        :src="item.thumb_url || item.url"
        :alt="tweet.title"
        loading="lazy"
        decoding="async"
        referrerpolicy="no-referrer"
        class="tweet-photo w-full cursor-zoom-in object-cover"
        :style="item.width && item.height ? { aspectRatio: `${item.width} / ${item.height}` } : {}"
        :aria-label="t('xboard.previewImage')"
        @click="emit('preview', item)"
      />
      <!-- 视频：未点击时渲染零流量占位，点击后挂载 <video> 经代理加载播放 -->
      <video
        v-else-if="isPlaying(mediaKey(tweet, index))"
        :src="item.playback_url || item.url"
        controls
        autoplay
        playsinline
        preload="auto"
        class="w-full bg-stone-900"
        :style="item.width && item.height ? { aspectRatio: `${item.width} / ${item.height}` } : {}"
      />
      <button
        v-else
        type="button"
        class="tweet-video-btn group relative flex w-full items-center justify-center"
        :style="{ aspectRatio: item.width && item.height ? `${item.width} / ${item.height}` : '16 / 9' }"
        :aria-label="t('xboard.playVideo')"
        @click="emit('play', mediaKey(tweet, index))"
      >
        <!-- 服务端抽帧封面；加载失败（404/网络）隐藏 img，回退深色占位 -->
        <img
          v-if="item.poster_url"
          :src="item.poster_url"
          :alt="tweet.title"
          loading="lazy"
          decoding="async"
          referrerpolicy="no-referrer"
          class="absolute inset-0 h-full w-full object-cover"
          @error="($event.target as HTMLImageElement).style.display = 'none'"
        />
        <span class="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.08),transparent_60%)]" />
        <span class="tweet-play relative flex h-14 w-14 items-center justify-center">
          <svg class="ml-1 h-6 w-6" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
        </span>
        <span v-if="item.type === 'animated_gif'" class="tweet-gif-badge absolute left-2 top-2 px-1.5 py-0.5 text-2xs font-bold uppercase tracking-wide">GIF</span>
      </button>
    </template>
  </div>
</template>

<style scoped>
/* 媒体块：内嵌 + 墨边 + 小圆角 */
.tweet-media-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 12px 0;
}

.tweet-media-list > * {
  display: block;
  overflow: hidden;
  border: 1px solid var(--ink);
  border-radius: 5px;
}

/* 视频占位保持深色语义底；播放键走 btn-primary 的墨底酸绿反转，
   方形圆角（主题去胶囊化），hover 硬边位移反馈 */
.tweet-video-btn {
  cursor: pointer;
  background: linear-gradient(150deg, #2a2723, #100e0c);
}

.tweet-play {
  border: 1px solid var(--ink);
  border-radius: var(--control-radius);
  background: var(--ink);
  color: var(--acid);
  transition:
    transform 150ms ease,
    background 150ms ease,
    color 150ms ease,
    box-shadow 150ms ease;
}

.tweet-video-btn:hover .tweet-play {
  background: var(--acid);
  color: var(--projects-on-acid);
  box-shadow: 2px 2px 0 var(--shadow-hard);
  transform: translate(-1px, -1px);
}

.tweet-gif-badge {
  border: 1px solid var(--ink);
  border-radius: 4px;
  background: var(--acid);
  color: var(--projects-on-acid);
}
</style>
