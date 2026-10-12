<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useContactPageConfig } from '@/composables/useContactPageConfig'

// The production scene comes from a pinned private release. Keep it intact and
// load it only when a visitor chooses the interactive scene.
const ContactSceneView = defineAsyncComponent(() => import('./ContactPageView.vue'))
const { contactPageConfig: config } = useContactPageConfig()
const { t, locale } = useI18n()
const mode = ref<'video' | 'scene'>('video')
const failedQrEntries = ref<Record<number, boolean>>({})
const videoUrl = 'https://www.bilibili.com/video/BV12Dpj6QEoi/'
const playerUrl = 'https://player.bilibili.com/player.html?bvid=BV12Dpj6QEoi&p=1&autoplay=1&muted=1&danmaku=0'
const copy = computed(() => locale.value.startsWith('en') ? {
  video: 'Concept video', scene: 'Explore the meadow', watch: 'Watch on Bilibili ↗',
  hint: 'Starts muted. Use the player to turn on sound or pause.',
} : {
  video: '概念视频', scene: '探索原野', watch: '在 B 站观看 ↗',
  hint: '默认静音播放，可在播放器中开启声音或暂停。',
})
// Only translate the administrator's known copy; preserve any custom text.
const englishText = new Map([
  ['联系与合作', 'Contact & Collaboration'],
  ['开发者交流群：聊 AI 编程与 Vibe Coding，也聊这个网站和各自的项目。', 'A developer group for AI coding and vibe coding, plus this site and everyone’s own projects.'],
  ['网站及 Vibe Coding 交流群', 'Site & Vibe Coding group'],
  ['点击加入 QQ 群', 'Join us on QQ'],
])
const shown = (text: string) => locale.value.startsWith('en') ? englishText.get(text.trim()) ?? text : text
const isExternal = (href: string) => /^https?:\/\//i.test(href)
</script>

<template>
  <div v-if="config.enabled" class="contact-presentation" :class="{ 'contact-presentation--scene': mode === 'scene' }">
    <div class="presentation-modes" role="group" :aria-label="t('contact.kicker')">
      <button type="button" :aria-pressed="mode === 'video'" @click="mode = 'video'">{{ copy.video }}</button>
      <button type="button" :aria-pressed="mode === 'scene'" @click="mode = 'scene'">{{ copy.scene }}</button>
    </div>

    <!-- Unmount the player on mode/route changes so playback cannot continue in the background. -->
    <template v-if="mode === 'video'">
      <header class="presentation-heading">
        <h1 class="comic-title">{{ shown(config.title) }}</h1>
        <p v-if="config.subtitle">{{ shown(config.subtitle) }}</p>
      </header>
      <div class="presentation-content">
        <section class="concept-video" :aria-label="copy.video">
          <iframe
            :src="playerUrl"
            :title="copy.video"
            allow="autoplay; fullscreen; picture-in-picture"
            allowfullscreen
            referrerpolicy="strict-origin-when-cross-origin"
          />
          <div class="video-caption">
            <p>{{ copy.hint }}</p>
            <a :href="videoUrl" target="_blank" rel="noopener noreferrer">{{ copy.watch }}</a>
          </div>
        </section>

        <aside v-if="config.contactEntries.length" class="presentation-contacts" :aria-label="t('contact.kicker')">
          <p class="contact-note">{{ t('contact.heroNote') }}</p>
          <ul>
            <li v-for="(entry, index) in config.contactEntries" :key="`${index}-${entry.label}`">
              <h2>{{ shown(entry.label) }}</h2>
              <div v-if="entry.qrImageUrl" class="contact-qr">
                <img v-if="!failedQrEntries[index]" :src="entry.qrImageUrl" :alt="shown(entry.label)" loading="lazy" @error="failedQrEntries[index] = true" />
                <p v-else role="img" :aria-label="t('contact.qrUnavailable')">{{ t('contact.qrUnavailable') }}</p>
              </div>
              <a v-if="entry.href" :href="entry.href" :target="isExternal(entry.href) ? '_blank' : undefined" :rel="isExternal(entry.href) ? 'noopener noreferrer' : undefined">
                {{ shown(entry.value) || entry.href }}<span v-if="isExternal(entry.href)" aria-hidden="true"> ↗</span>
              </a>
              <p v-else-if="entry.value">{{ shown(entry.value) }}</p>
              <p v-if="entry.qrImageUrl && !failedQrEntries[index]" class="qr-hint">{{ t('contact.qrHint') }}</p>
            </li>
          </ul>
        </aside>
      </div>
    </template>
    <div v-else class="presentation-scene"><ContactSceneView /></div>
  </div>
</template>

<style scoped>
.contact-presentation {
  height: 100%;
  box-sizing: border-box;
  overflow-y: auto;
  padding: 1.25rem clamp(1rem, 3vw, 2rem) 7rem;
  color: var(--ink);
  background: var(--paper-raised);
}
.presentation-modes { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1.5rem; }
.presentation-modes button {
  min-height: 44px;
  padding: .55rem 1rem;
  border: 2px solid var(--ink);
  border-radius: 4px;
  background: var(--paper-raised);
  color: var(--ink);
  font-family: inherit;
  font-size: .9rem;
  font-weight: 700;
  line-height: 1.4;
  cursor: pointer;
}
.presentation-modes button[aria-pressed='true'] { background: var(--acid); color: #14223c; box-shadow: 3px 3px 0 var(--ink); }
.presentation-modes button:focus-visible, a:focus-visible { outline: 3px solid var(--ink); outline-offset: 4px; }
.presentation-heading { margin-bottom: 1.5rem; }
.presentation-heading h1 { width: fit-content; margin: 0 0 .65rem; font-size: clamp(2rem, 4vw, 3.4rem); line-height: 1.15; }
.presentation-heading > p { max-width: 60rem; margin: 0; color: var(--ink-secondary); line-height: 1.7; white-space: pre-line; }
.presentation-content { display: grid; grid-template-columns: minmax(0, 1fr) minmax(14rem, 18rem); gap: 1.5rem; align-items: start; }
.presentation-content:not(:has(.presentation-contacts)) { grid-template-columns: minmax(0, 1fr); }
.concept-video { min-width: 0; overflow: hidden; border: 2px solid var(--ink); border-radius: 4px; background: var(--paper); box-shadow: 5px 5px 0 var(--ink); }
.concept-video iframe { display: block; width: 100%; aspect-ratio: 16 / 9; border: 0; background: #101318; }
.video-caption { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: .5rem 1rem; padding: .8rem 1rem; }
.video-caption p { margin: 0; font-size: .8rem; color: var(--ink-secondary); line-height: 1.6; }
.video-caption a { flex-shrink: 0; padding: .3rem 0; color: var(--ink); font-size: .85rem; font-weight: 700; text-underline-offset: 3px; }
.presentation-contacts { padding: 1rem; border: 2px solid var(--ink); border-radius: 4px; background: var(--paper); box-shadow: 4px 4px 0 var(--ink); }
.contact-note { margin: 0 0 1rem; font-size: .85rem; line-height: 1.6; color: var(--ink-secondary); }
.presentation-contacts ul { display: grid; gap: 1.25rem; margin: 0; padding: 0; list-style: none; }
.presentation-contacts li + li { padding-top: 1.25rem; border-top: 1px solid var(--rule); }
.presentation-contacts h2 { margin: 0 0 .75rem; font-size: 1rem; line-height: 1.5; }
.presentation-contacts a { display: inline-block; max-width: 100%; padding: .5rem 0; color: var(--ink); font-weight: 700; line-height: 1.5; overflow-wrap: anywhere; text-underline-offset: 4px; }
.presentation-contacts li > p { margin: .35rem 0 0; overflow-wrap: anywhere; }
.contact-qr { width: min(100%, 10rem); margin-bottom: .5rem; padding: .5rem; box-sizing: border-box; background: #fff; color: #14223c; }
.contact-qr img { display: block; width: 100%; height: auto; }
.qr-hint { font-size: .75rem; color: var(--ink-secondary); }
.contact-presentation--scene { display: flex; flex-direction: column; overflow: hidden; padding-bottom: 0; }
.contact-presentation--scene .presentation-modes { flex-shrink: 0; }
.presentation-scene { position: relative; flex: 1; min-height: 0; }
@media (min-width: 64rem) {
  .contact-presentation { background: transparent; }
}
@media (max-width: 63.99rem) {
  .presentation-content { grid-template-columns: minmax(0, 1fr); }
  .presentation-contacts ul { grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr)); }
  .presentation-contacts li + li { padding-top: 0; border-top: 0; }
}
</style>
