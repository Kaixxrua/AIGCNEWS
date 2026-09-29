import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'
import { i18n } from '@/i18n'
import DisclaimerView from './DisclaimerView.vue'
import PrivacyView from './PrivacyView.vue'

const mountView = async (view: typeof PrivacyView) => {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:any(.*)', component: { template: '<div />' } }] })
  await router.push('/')
  return mount(view, { global: { plugins: [router, i18n] } })
}

beforeEach(() => { i18n.global.locale.value = 'zh-CN' })

describe('legal pages', () => {
  it('keeps the privacy sections in reading order and numbers the contents to match', async () => {
    const wrapper = await mountView(PrivacyView)
    const ids = wrapper.findAll('.legal-body section').map((section) => section.attributes('id'))
    expect(ids).toEqual(['payTitle', 'collectTitle', 'aiTitle', 'useTitle', 'securityTitle', 'cookieTitle', 'minorTitle', 'rightsTitle', 'contactTitle'].map((key) => `legal-${key}`))
    const links = wrapper.findAll('.legal-toc a')
    expect(links.map((link) => link.attributes('href'))).toEqual(ids.map((id) => `#${id}`))
    expect(links[0]!.text()).toBe('01支付与订单信息')
    expect(links[0]!.attributes('aria-current')).toBe('location')
    expect(wrapper.findAll('.legal-fact strong').map((value) => value.text())).toEqual(['48 小时', '10 个', '15 个工作日'])
    expect(wrapper.find('#legal-collectTitle li strong.legal-lead').text()).toBe('邮箱地址：')
    expect(wrapper.find('#legal-collectTitle li').text()).toBe(i18n.global.t('legal.privacy.email'))
    wrapper.unmount()
  })

  it('drops the agreement titles’ own numbering from the contents only', async () => {
    const wrapper = await mountView(DisclaimerView)
    expect(wrapper.find('#legal-aiTitle h2').text()).toBe('一、AI 生成内容免责声明（最重要）')
    expect(wrapper.find('.legal-toc a').text()).toBe('01AI 生成内容免责声明（最重要）')
    expect(wrapper.findAll('.legal-toc a')).toHaveLength(7)
    expect(wrapper.find('.legal-aside #legal-contactTitle .effective').exists()).toBe(true)
    wrapper.unmount()
  })
})
