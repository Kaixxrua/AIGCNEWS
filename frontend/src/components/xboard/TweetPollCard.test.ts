import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'
import en from '@/i18n/locales/en-US'
import zh from '@/i18n/locales/zh-CN'
import type { TweetPoll } from '@/features/dashboard/dashboardViewModel'
import TweetLinkCard from './TweetLinkCard.vue'

const poll: TweetPoll = {
  choices: [
    { label: '5h limits, 2X week usage', votes: 79775 },
    { label: 'no 5h limits, same usage', votes: 91040 },
    { label: 'show result', votes: 69828 },
  ],
  total_votes: 240643,
  is_final: true,
}
const render = (value = poll, locale = 'zh-CN') => mount(TweetLinkCard, {
  props: { card: { url: 'https://x.com/i/status/2109152716954222849', title: 'Pro users', poll: value } },
  global: { plugins: [createI18n({ legacy: false, locale, messages: { 'zh-CN': zh, 'en-US': en } })] },
})

describe('X poll cards', () => {
  it('shows every choice, percentages, total and the final winner in place of a link preview', () => {
    const wrapper = render()
    expect(wrapper.findAll('.tweet-poll-label').map((el) => el.text())).toEqual(poll.choices.map((choice) => choice.label))
    expect(wrapper.findAll('.tweet-poll-percent').map((el) => el.text())).toEqual(['33.2%', '37.8%', '29%'])
    expect(wrapper.get('.tweet-poll-choice--winner').text()).toContain('no 5h limits')
    expect(wrapper.text()).toContain('240,643 次投票 · 最终结果')
    expect(wrapper.get('a').attributes('href')).toBe('https://x.com/i/status/2109152716954222849')
    expect(wrapper.find('.tweet-linkcard').exists()).toBe(false)
  })

  it('handles zero votes without NaN, invented winners or voting buttons', () => {
    const wrapper = render({ ...poll, total_votes: 0, is_final: false, choices: poll.choices.map((choice) => ({ ...choice, votes: 0 })) }, 'en-US')
    expect(wrapper.findAll('.tweet-poll-percent').map((el) => el.text())).toEqual(['0%', '0%', '0%'])
    expect(wrapper.text()).toContain('0 votes · Current results')
    expect(wrapper.find('.tweet-poll-choice--winner').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('keeps labels but hides percentages when X has not supplied all counts, and escapes labels', () => {
    const wrapper = render({ ...poll, total_votes: null, is_final: false, choices: [{ label: '<img src=x onerror=alert(1)>', votes: null }, ...poll.choices.slice(1)] })
    expect(wrapper.text()).toContain('票数暂不可用')
    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.tweet-poll-percent').exists()).toBe(false)
    expect(wrapper.find('.tweet-poll-choice--winner').exists()).toBe(false)
  })
})
