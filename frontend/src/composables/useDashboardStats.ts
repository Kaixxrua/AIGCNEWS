import { computed, ref } from 'vue'
import {
  statCards,
  visitorCards,
  type Stats,
} from '@/features/dashboard/dashboardViewModel'

export const useDashboardStats = (getStats: () => Stats) => {
  const statValues = ref<number[]>(statCards.map(() => 0))
  const visitorValues = ref<number[]>(visitorCards.map(() => 0))

  const updateVisitorSources = (nextStats: Stats) => {
    visitorValues.value = visitorCards.map(card => {
      const key = card.key as keyof Stats
      return Number(nextStats[key] ?? 0)
    })
  }

  const updateStatSources = (nextStats: Stats) => {
    statValues.value = statCards.map(card => {
      if (card.key === 'total') return Number(nextStats.total_documents ?? 0)
      return Number(nextStats.source_counts?.[card.key] ?? 0)
    })
    updateVisitorSources(nextStats)
  }

  const userParts = computed(() => {
    const stats = getStats()
    return {
      registered: Number(stats.registered_users ?? 0),
      today: Number(stats.today_registered_users ?? 0),
    }
  })

  const mcpTotalCalls = computed(() => Number(getStats().mcp_total_calls ?? 0))

  return {
    statValues,
    visitorValues,
    userParts,
    mcpTotalCalls,
    updateStatSources,
    updateVisitorSources,
  }
}
