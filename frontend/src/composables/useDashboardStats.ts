import { computed, ref } from 'vue'
import { useTransition, TransitionPresets } from '@vueuse/core'
import {
  statCards,
  visitorCards,
  type Stats,
} from '../features/dashboard/dashboardViewModel'

export const useDashboardStats = (getStats: () => Stats) => {
  const countUpDisabled = ref(false)
  const statSources = ref(statCards.map(() => 0))
  const visitorSources = ref(visitorCards.map(() => 0))

  const animatedStats = statCards.map((_, index) => {
    const source = computed(() => statSources.value[index])
    return useTransition(source, {
      duration: 1000,
      transition: TransitionPresets.easeOutCubic,
      disabled: countUpDisabled,
    })
  })

  const animatedVisitors = visitorCards.map((_, index) => {
    const source = computed(() => visitorSources.value[index])
    return useTransition(source, {
      duration: 1200,
      transition: TransitionPresets.easeOutCubic,
      disabled: countUpDisabled,
    })
  })

  const updateVisitorSources = (nextStats: Stats) => {
    visitorSources.value = visitorCards.map(card => {
      const key = card.key as keyof Stats
      return Number(nextStats[key] ?? 0)
    })
  }

  const updateStatSources = (nextStats: Stats) => {
    statSources.value = statCards.map(card => {
      if (card.key === 'total') return Number(nextStats.total_documents ?? 0)
      return Number(nextStats.source_counts?.[card.key] ?? 0)
    })
    updateVisitorSources(nextStats)
  }

  const disableCountUp = () => {
    countUpDisabled.value = true
  }

  const getAnimatedValue = (index: number): string => {
    const transition = animatedStats[index]
    const value = transition ? transition.value : 0
    return Math.round(value ?? 0).toString()
  }

  const getVisitorAnimatedValue = (index: number): string => {
    const transition = animatedVisitors[index]
    const value = transition ? transition.value : 0
    return Math.round(value ?? 0).toLocaleString()
  }

  const getUserCountParts = (): string => {
    const stats = getStats()
    const registered = Number(stats.registered_users ?? 0).toLocaleString()
    const todayRegistered = Number(stats.today_registered_users ?? 0).toLocaleString()
    return `${registered}+${todayRegistered}`
  }

  const getVisitorDisplayValue = (cardKey: string, index: number): string => {
    if (cardKey === 'user_count') return getUserCountParts()
    return getVisitorAnimatedValue(index)
  }

  return {
    updateStatSources,
    updateVisitorSources,
    disableCountUp,
    getAnimatedValue,
    getVisitorDisplayValue,
  }
}
