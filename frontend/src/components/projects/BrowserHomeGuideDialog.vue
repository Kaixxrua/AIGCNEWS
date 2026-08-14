<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

defineProps<{
  open: boolean
  active: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const siteUrl = window.location.origin
const isMac = /mac/i.test(window.navigator.platform)
const bookmarkShortcut = computed(() => (isMac ? '⌘ + D' : 'Ctrl + D'))

const copied = ref(false)
let copiedTimer: number | undefined

const copyUrl = async () => {
  try {
    await navigator.clipboard.writeText(siteUrl)
  } catch {
    const input = document.createElement('input')
    input.value = siteUrl
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    input.remove()
  }
  copied.value = true
  window.clearTimeout(copiedTimer)
  copiedTimer = window.setTimeout(() => { copied.value = false }, 2000)
}

const close = () => emit('close')

const selectUrl = (event: FocusEvent) => {
  (event.target as HTMLInputElement).select()
}
</script>

<template>
  <Teleport to="body">
    <Transition name="tool-modal">
      <div v-if="active && open" class="tool-modal" role="presentation" @click.self="close">
        <div class="tool-modal__panel home-guide" role="dialog" :aria-label="t('projects.dialog.homeGuide.title')">
          <button type="button" class="tool-modal__close" :aria-label="t('projects.dialog.homeGuide.close')" @click="close">×</button>
          <p class="projects-kicker">BROWSER HOME</p>
          <h2>{{ t('projects.dialog.homeGuide.title') }}</h2>
          <p class="tool-modal__hint">{{ t('projects.dialog.homeGuide.hint') }}</p>

          <div class="home-guide__url">
            <input :value="siteUrl" type="text" readonly :aria-label="t('projects.dialog.homeGuide.siteUrl')" @focus="selectUrl" />
            <button type="button" class="projects-add-submit" @click="copyUrl">
              {{ copied ? t('projects.dialog.homeGuide.copied') : t('projects.dialog.homeGuide.copy') }}
            </button>
          </div>

          <section class="home-guide__section">
            <h3>{{ t('projects.dialog.homeGuide.bookmarkTitle') }}</h3>
            <p>
              {{ t('projects.dialog.homeGuide.bookmarkHint', { shortcut: bookmarkShortcut }) }}
              <kbd>{{ bookmarkShortcut }}</kbd>
            </p>
          </section>

          <section class="home-guide__section">
            <h3>{{ t('projects.dialog.homeGuide.homeTitle') }}</h3>
            <ul>
              <li>{{ t('projects.dialog.homeGuide.chrome') }}</li>
              <li>{{ t('projects.dialog.homeGuide.firefox') }}</li>
              <li>{{ t('projects.dialog.homeGuide.safari') }}</li>
            </ul>
          </section>

          <div class="tool-modal__actions">
            <button type="button" class="projects-add-submit" @click="close">{{ t('projects.dialog.homeGuide.done') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped src="./toolWebsiteDialog.css"></style>

<style scoped>
.home-guide__url {
  display: flex;
  gap: 10px;
  margin-top: 22px;
}

.home-guide__url input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  padding: 12px 16px;
  color: rgb(var(--stone-800-rgb));
  background: var(--projects-paper-light);
  box-shadow: none;
  outline: none;
  font-size: 14px;
}

.home-guide__url input:focus {
  box-shadow: 0 0 0 3px var(--projects-acid);
}

.home-guide__url .projects-add-submit {
  min-height: 0;
  flex-shrink: 0;
}

.home-guide__section {
  margin-top: 24px;
  border-top: 1px dashed rgb(var(--stone-400-rgb));
  padding-top: 18px;
}

.home-guide__section h3 {
  margin: 0 0 10px;
  color: var(--projects-accent);
  font-size: 13px;
  font-weight: 900;
  letter-spacing: .08em;
}

.home-guide__section p,
.home-guide__section li {
  color: rgb(var(--stone-600-rgb));
  font-size: 13px;
  line-height: 1.9;
}

.home-guide__section ul {
  margin: 0;
  padding-left: 18px;
}

.home-guide__section kbd {
  display: inline-block;
  margin-left: 6px;
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  padding: 2px 8px;
  color: var(--projects-accent);
  background: var(--projects-acid-soft);
  font-family: inherit;
  font-size: 12px;
  font-weight: 800;
}

@media (max-width: 720px) {
  .home-guide__url {
    flex-direction: column;
  }
}
</style>
