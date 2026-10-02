import { ref, toRaw } from 'vue'
import {
  createRecommendedWebsite, deleteRecommendedWebsite, fetchRecommendedWebsites, updateRecommendedWebsite,
  type RecommendedWebsite, type RecommendedWebsiteInput,
} from '@/services/site/recommendedWebsiteApi'
import { rememberRecommendedWebsites, useRecommendedWebsitesSnapshot } from './recommendedWebsitesSnapshot'

const defaultApi = { createRecommendedWebsite, deleteRecommendedWebsite, fetchRecommendedWebsites, updateRecommendedWebsite }
type Options = {
  api?: typeof defaultApi
  isAdmin: () => boolean
  t: (key: string) => string
}

export function useRecommendedWebsites({ api = defaultApi, isAdmin, t }: Options) {
  // 先摆出上次拿到的列表（比如路由守卫刚拉过），load 再静默换成最新的。
  const snapshot = useRecommendedWebsitesSnapshot()
  const websites = ref<RecommendedWebsite[]>(snapshot.value ? [...toRaw(snapshot.value)] : [])
  const loading = ref(false)
  const saving = ref(false)
  const deletingId = ref<number | null>(null)
  const error = ref('')
  const editError = ref('')
  let generation = 0
  let disposed = false

  const load = async () => {
    if (saving.value || deletingId.value !== null) return
    const request = ++generation
    loading.value = true
    error.value = ''
    try {
      const items = await api.fetchRecommendedWebsites()
      if (!disposed && request === generation) {
        websites.value = items
        rememberRecommendedWebsites(items)
      }
    } catch {
      if (!disposed && request === generation) error.value = t('recommendedWebsites.loadError')
    } finally {
      if (!disposed && request === generation) loading.value = false
    }
  }

  const save = async (id: number | null, input: RecommendedWebsiteInput) => {
    if (!isAdmin() || saving.value || deletingId.value !== null) return false
    saving.value = true
    error.value = ''
    editError.value = ''
    ++generation
    try {
      const saved = id === null
        ? await api.createRecommendedWebsite(input)
        : await api.updateRecommendedWebsite(id, input)
      if (disposed) return false
      const rest = websites.value.filter(item => item.id !== saved.id)
      websites.value = [...rest, saved].sort((a, b) => a.sort_order - b.sort_order || b.id - a.id)
      rememberRecommendedWebsites(websites.value)
      return true
    } catch (cause) {
      if (!disposed) {
        const status = (cause as { response?: { status?: number } }).response?.status
        editError.value = t(status === 409 ? 'recommendedWebsites.duplicate' : 'recommendedWebsites.saveError')
      }
      return false
    } finally {
      saving.value = false
      loading.value = false
    }
  }

  const remove = async (id: number) => {
    if (!isAdmin() || saving.value || deletingId.value !== null) return false
    deletingId.value = id
    error.value = ''
    ++generation
    try {
      await api.deleteRecommendedWebsite(id)
      if (disposed) return false
      websites.value = websites.value.filter(item => item.id !== id)
      rememberRecommendedWebsites(websites.value)
      return true
    } catch {
      if (!disposed) error.value = t('recommendedWebsites.deleteError')
      return false
    } finally {
      deletingId.value = null
      loading.value = false
    }
  }

  const dispose = () => { disposed = true; ++generation }
  return { websites, loading, saving, deletingId, error, editError, load, save, remove, dispose }
}
