import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import GlassCalendar from './GlassCalendar.vue'

enableAutoUnmount(afterEach)

const mountCalendar = (availableDates?: string[]) => mount(GlassCalendar, {
  props: { modelValue: '2026-09-09', availableDates },
  global: { plugins: [i18n] },
})

describe('GlassCalendar date selection', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 9, 12))
  })

  afterEach(() => vi.useRealTimers())

  it('lets yesterday be selected when it is missing from the snapshot list', async () => {
    const wrapper = mountCalendar(['2026-09-09', '2026-09-07'])
    const yesterday = wrapper.get<HTMLButtonElement>('button[title="2026-09-08"]')

    expect(yesterday.element.disabled).toBe(false)
    expect(yesterday.find('.snapshot-dot').exists()).toBe(false)
    await yesterday.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([['2026-09-08']])
    await wrapper.setProps({ modelValue: '2026-09-08' })
    expect(yesterday.classes()).toContain('calendar-day--active')
    expect(yesterday.classes()).not.toContain('calendar-day--disabled')
  })

  it.each([
    { state: 'not loaded', dates: undefined },
    { state: 'empty', dates: [] },
  ])('allows history and returning to today when snapshot metadata is $state', async ({ dates }) => {
    const wrapper = mountCalendar(dates)
    const yesterday = wrapper.get<HTMLButtonElement>('button[title="2026-09-08"]')
    expect(yesterday.element.disabled).toBe(false)
    await yesterday.trigger('click')
    await wrapper.setProps({ modelValue: '2026-09-08' })

    const today = wrapper.get<HTMLButtonElement>('button[title="2026-09-09"]')
    expect(today.element.disabled).toBe(false)
    await today.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([['2026-09-08'], ['2026-09-09']])
  })

  it('keeps future dates disabled even if snapshot metadata includes them', async () => {
    const wrapper = mountCalendar(['2026-09-10'])
    const tomorrow = wrapper.get<HTMLButtonElement>('button[title^="2026-09-10"]')

    expect(tomorrow.element.disabled).toBe(true)
    await tomorrow.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.get('button[aria-label="下个月"]').trigger('click')
    expect(wrapper.findAll<HTMLButtonElement>('.calendar-day').every(day => day.element.disabled)).toBe(true)
  })

  it('updates snapshot indicators without disabling the selected historical date', async () => {
    const wrapper = mountCalendar(['2026-09-07'])
    const archived = wrapper.get<HTMLButtonElement>('button[title^="2026-09-07"]')
    expect(archived.find('.snapshot-dot').exists()).toBe(true)
    await archived.trigger('click')
    await wrapper.setProps({ modelValue: '2026-09-07', availableDates: [] })

    expect(archived.element.disabled).toBe(false)
    expect(archived.classes()).toContain('calendar-day--active')
    const yesterday = wrapper.get('button[title="2026-09-08"]')
    await wrapper.setProps({ availableDates: ['2026-09-08'] })
    expect(yesterday.find('.snapshot-dot').exists()).toBe(true)
    await yesterday.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([['2026-09-07'], ['2026-09-08']])
  })

  it.each([
    { today: new Date(2026, 8, 1, 12), yesterday: '2026-08-31' },
    { today: new Date(2026, 0, 1, 12), yesterday: '2025-12-31' },
    { today: new Date(2024, 2, 1, 12), yesterday: '2024-02-29' },
  ])('allows yesterday across a month or year boundary ($yesterday)', async ({ today, yesterday }) => {
    vi.setSystemTime(today)
    const wrapper = mountCalendar([])
    const day = wrapper.get<HTMLButtonElement>(`button[title="${yesterday}"]`)

    expect(day.element.disabled).toBe(false)
    await day.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[yesterday]])
  })
})
