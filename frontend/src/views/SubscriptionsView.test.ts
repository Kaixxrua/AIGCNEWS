import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SUBSCRIPTION_SOURCES } from '@/features/subscriptions/subscriptionsModel'
import SubscriptionsView from './SubscriptionsView.vue'

const controllerSpy = vi.hoisted(() => vi.fn())
const ctlBox = vi.hoisted(() => ({ current: null as null | Record<string, any> }))
const confirmSpy = vi.hoisted(() => vi.fn())
const authBox = vi.hoisted(() => ({ isMember: false, isAdmin: false }))

vi.mock('@/stores/authStore', () => ({ useAuthStore: () => authBox }))

vi.mock('@/composables/useSubscriptionsController', async () => {
  const { computed, ref } = await import('vue')
  ctlBox.current = {
    channels: ref([]),
    subscriptions: ref([]),
    loading: ref(false),
    error: ref(''),
    notice: ref(''),
    emailInput: ref(''),
    otpChannelId: ref(null),
    otpCode: ref(''),
    webhookInput: ref(''),
    discordInput: ref(''),
    telegramLink: ref(null),
    telegramPolling: ref(false),
    channelFormBusy: ref(false),
    newChannelId: ref(null),
    newSource: ref('all'),
    newFrequency: ref('daily'),
    subscriptionFormBusy: ref(false),
    busyChannelIds: ref(new Set()),
    busySubscriptionIds: ref(new Set()),
    feedToken: ref(''),
    rssBusy: ref(false),
    bindableChannels: computed(() =>
      (ctlBox.current?.channels.value ?? []).filter((c: any) => c.verified && c.status === 'active'),
    ),
    canSubmitEmail: ref(true),
    canSubmitOtp: ref(false),
    canSubmitWebhook: ref(true),
    canSubmitDiscord: ref(true),
    canConnectTelegram: ref(true),
    canSubmitSubscription: ref(true),
    loadAll: vi.fn(),
    submitEmailChannel: vi.fn(),
    submitOtp: vi.fn(),
    submitWebhookChannel: vi.fn(),
    submitDiscordChannel: vi.fn(),
    connectTelegram: vi.fn(),
    toggleChannel: vi.fn(),
    removeChannel: vi.fn(),
    sendTest: vi.fn(),
    submitSubscription: vi.fn(),
    toggleSubscription: vi.fn(),
    removeSubscription: vi.fn(),
    rssLinkFor: vi.fn(),
    copyRssLink: vi.fn(),
    rssBriefingLinkFor: vi.fn(),
    copyBriefingRssLink: vi.fn(),
    rotateFeedToken: vi.fn(),
  }
  return { useSubscriptionsController: controllerSpy.mockReturnValue(ctlBox.current) }
})

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      subscriptions: {
        title: '我的订阅',
        description: '绑定推送渠道，按来源与频率订阅，新内容自动送达',
        refresh: '刷新',
        channels: {
          title: '推送渠道',
          count: '{count} 个渠道',
          emailLabel: '邮箱',
          emailTitle: '添加邮箱渠道',
          emailPlaceholder: "you{'@'}example.com",
          emailSubmit: '发送验证码',
          otpHint: '验证码已发送到邮箱，5 分钟内有效',
          otpPlaceholder: '6 位验证码',
          otpSubmit: '完成验证',
          webhookTitle: '添加 Webhook 渠道',
          webhookPlaceholder: 'https:// 开头的机器人 Webhook 地址',
          webhookSubmit: '验证并添加',
          webhookHint: '按域名自动识别',
          discordTitle: '添加 Discord Webhook',
          discordPlaceholder: 'https://discord.com/api/webhooks/...',
          discordSubmit: '验证并添加',
          discordHint: '使用 Discord Incoming Webhook，添加时会发送一条验证消息。',
          telegramTitle: '连接 Telegram',
          telegramConnect: '打开 Telegram 连接',
          telegramPending: '等待你打开 Telegram 链接…',
          vipOnly: '仅对有效会员和管理员开放',
          verified: '已验证',
          unverified: '未验证',
          disabled: '已停用',
          enable: '启用',
          disable: '停用',
          test: '发送测试',
          delete: '删除',
          deleteConfirm: '删除该渠道将同时删除其全部订阅，确定删除？',
          empty: '还没有渠道',
          platform: { wecom: '企业微信', dingtalk: '钉钉', lark: '飞书', generic: '通用 Webhook', discord: 'Discord', telegram: 'Telegram' },
        },
        subs: {
          title: '订阅',
          count: '{count} 条订阅',
          source: '来源',
          channel: '渠道',
          selectChannel: '选择渠道',
          noBindableChannel: '暂无可用渠道',
          create: '创建订阅',
          quotaHint: '免费档最多订阅 1 个日报模块；',
          quotaUpgrade: '开通会员解锁全部模块 →',
          paused: '已暂停',
          pause: '暂停',
          resume: '恢复',
          delete: '删除',
          deleteConfirm: '确定删除该订阅？',
          rssCopy: '复制 RSS 订阅链接',
          rssReset: '重置 RSS 链接',
          rssResetConfirm: '重置后旧 RSS 链接立即失效，需要到阅读器里换成新链接。确定重置？',
          rssTitle: 'RSS 简报订阅',
          rssHintMember: '速览链接内含你的专属 token，请勿公开分享。',
          rssHintFree: '每日综合简报全文公开可订；开通会员独享速览版。',
          rssBriefingFull: '每日简报 · 全文',
          rssBriefingDigest: '每日简报 · 速览',
          rssDigestUpsell: '速览版为会员权益 →',
          rssAdvancedTitle: '按来源订阅原始条目（高级）',
          rssAdvancedHint: '公开源为近 48 小时摘要；会员链接带 token。',
          empty: '还没有订阅',
        },
        sources: { all: '全部', arxiv: 'arXiv 论文', dailyhot: '全网热榜' },
        notice: {
          'otp-sent': '验证码已发送，请查收邮件',
          'channel-verified': '渠道验证成功',
          'webhook-created': 'Webhook 渠道已验证并添加',
          'test-sent': '测试消息已发送',
          'subscription-created': '订阅已创建',
          'subscription-deleted': '订阅已删除',
          'channel-deleted': '渠道已删除',
          'discord-created': 'Discord Webhook 已验证并添加',
          'telegram-link-created': 'Telegram 链接已打开，请在 Telegram 中完成连接',
          'telegram-connected': 'Telegram 已连接',
          'rss-copied': 'RSS 链接已复制，粘贴到阅读器即可订阅',
          'rss-rotated': 'RSS 链接已重置，旧链接已失效',
        },
        errors: { 'load-failed': '加载失败，请稍后重试', 'request-failed': '操作失败，请稍后重试', 'quota-exceeded': '免费档最多订阅 1 个日报模块，开通会员解锁全部 8 个模块。', 'vip-required': 'Telegram 和 Discord 渠道仅对有效会员开放。' },
      },
    },
  },
  missingWarn: false,
  fallbackWarn: false,
})

const mountView = async () => {
  const wrapper = mount(SubscriptionsView, {
    global: { plugins: [i18n], stubs: { RouterLink: RouterLinkStub } },
  })
  await flushPromises()
  return wrapper
}

const ctl = () => ctlBox.current as Record<string, any>

const emailChannel = {
  id: 1,
  channel_type: 'email',
  target: 'me@example.com',
  verified: true,
  status: 'active',
  created_at: '2026-08-01T00:00:00Z',
}
const webhookChannel = {
  id: 2,
  channel_type: 'webhook',
  target: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc',
  verified: true,
  status: 'active',
  created_at: '2026-08-01T00:00:00Z',
}
const subscription = {
  id: 9,
  channel_id: 1,
  channel_type: 'email',
  target: 'me@example.com',
  source: 'dailyhot',
  frequency: 'daily',
  status: 'active',
  created_at: '2026-08-01T00:00:00Z',
}

beforeEach(() => {
  ctl().channels.value = []
  ctl().subscriptions.value = []
  ctl().error.value = ''
  ctl().notice.value = ''
  ctl().emailInput.value = ''
  ctl().otpChannelId.value = null
  ctl().otpCode.value = ''
  ctl().webhookInput.value = ''
  ctl().discordInput.value = ''
  ctl().telegramLink.value = null
  ctl().telegramPolling.value = false
  ctl().busyChannelIds.value = new Set()
  ctl().busySubscriptionIds.value = new Set()
  for (const fn of [
    ctl().loadAll,
    ctl().submitEmailChannel,
    ctl().submitOtp,
    ctl().submitWebhookChannel,
    ctl().submitDiscordChannel,
    ctl().connectTelegram,
    ctl().toggleChannel,
    ctl().removeChannel,
    ctl().sendTest,
    ctl().submitSubscription,
    ctl().toggleSubscription,
    ctl().removeSubscription,
    ctl().copyRssLink,
    ctl().copyBriefingRssLink,
    ctl().rotateFeedToken,
  ]) {
    fn.mockClear()
  }
  confirmSpy.mockReset()
  vi.stubGlobal('confirm', confirmSpy)
  controllerSpy.mockClear()
  authBox.isMember = false
  authBox.isAdmin = false
  ctl().newSource.value = 'all'
})

describe('SubscriptionsView rendering', () => {
  it('loads channel and subscription state on mount', async () => {
    const wrapper = await mountView()

    expect(controllerSpy).toHaveBeenCalledOnce()
    expect(ctl().loadAll).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('我的订阅')
    expect(wrapper.text()).toContain('推送渠道')
    expect(wrapper.text()).toContain('还没有渠道')
    expect(wrapper.text()).toContain('还没有订阅')
  })

  it('renders channels with platform labels and verification badges', async () => {
    ctl().channels.value = [emailChannel, webhookChannel, { ...emailChannel, id: 3, verified: false, target: 'pending@example.com' }]
    const wrapper = await mountView()
    const text = wrapper.text()

    expect(text).toContain('me@example.com')
    expect(text).toContain('企业微信')
    expect(text).toContain('邮箱')
    expect(text).toContain('已验证')
    expect(text).toContain('未验证')
    expect(text).toContain('3 个渠道')
  })

  it('renders subscriptions with localized source', async () => {
    ctl().subscriptions.value = [subscription]
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('全网热榜')
    expect(wrapper.text()).toContain('me@example.com')
  })

  it('maps notice and error tokens to localized messages', async () => {
    ctl().notice.value = 'webhook-created'
    ctl().error.value = 'request-failed'
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('Webhook 渠道已验证并添加')
    expect(wrapper.text()).toContain('操作失败，请稍后重试')
  })

  it('shows the otp step only while a channel awaits verification', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).not.toContain('验证码已发送到邮箱')

    ctl().otpChannelId.value = 7
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('验证码已发送到邮箱')
  })
})

describe('SubscriptionsView interactions', () => {
  it('forwards form submissions to the controller', async () => {
    const wrapper = await mountView()

    const emailForm = wrapper.findAll('form')[0]!
    await emailForm.trigger('submit.prevent')
    expect(ctl().submitEmailChannel).toHaveBeenCalledTimes(1)

    const webhookForm = wrapper.findAll('form')[1]!
    await webhookForm.trigger('submit.prevent')
    expect(ctl().submitWebhookChannel).toHaveBeenCalledTimes(1)

    const discordForm = wrapper.findAll('form')[2]!
    await discordForm.trigger('submit.prevent')
    expect(ctl().submitDiscordChannel).toHaveBeenCalledTimes(1)

    const subscriptionForm = wrapper.findAll('form')[3]!
    await subscriptionForm.trigger('submit.prevent')
    expect(ctl().submitSubscription).toHaveBeenCalledTimes(1)
  })

  it('forwards channel row actions', async () => {
    ctl().channels.value = [webhookChannel]
    const wrapper = await mountView()

    const disableButton = wrapper.findAll('button').find((button) => button.text() === '停用')
    expect(disableButton).toBeDefined()
    await disableButton!.trigger('click')
    expect(ctl().toggleChannel).toHaveBeenCalledWith(webhookChannel)

    const testButton = wrapper.findAll('button').find((button) => button.attributes('title') === '发送测试')
    expect(testButton).toBeDefined()
    await testButton!.trigger('click')
    expect(ctl().sendTest).toHaveBeenCalledWith(webhookChannel)

    confirmSpy.mockReturnValue(false)
    const deleteButton = wrapper.findAll('button').find((button) => button.attributes('title') === '删除')
    expect(deleteButton).toBeDefined()
    await deleteButton!.trigger('click')
    expect(ctl().removeChannel).not.toHaveBeenCalled()

    confirmSpy.mockReturnValue(true)
    await deleteButton!.trigger('click')
    expect(ctl().removeChannel).toHaveBeenCalledWith(webhookChannel)
  })

  it('requires confirmation before deleting a subscription', async () => {
    ctl().subscriptions.value = [subscription]
    const wrapper = await mountView()

    const pauseButton = wrapper.findAll('button').find((button) => button.text() === '暂停')
    await pauseButton!.trigger('click')
    expect(ctl().toggleSubscription).toHaveBeenCalledWith(subscription)

    confirmSpy.mockReturnValue(false)
    const deleteButton = wrapper.findAll('button').find((button) => button.attributes('title') === '删除')
    await deleteButton!.trigger('click')
    expect(ctl().removeSubscription).not.toHaveBeenCalled()

    confirmSpy.mockReturnValue(true)
    await deleteButton!.trigger('click')
    expect(ctl().removeSubscription).toHaveBeenCalledWith(subscription)
  })

  it('hides the test action for unverified or disabled channels', async () => {
    ctl().channels.value = [
      { ...emailChannel, id: 4, verified: false },
      { ...emailChannel, id: 5, status: 'disabled', target: 'off@example.com' },
    ]
    const wrapper = await mountView()

    expect(wrapper.findAll('button').some((button) => button.attributes('title') === '发送测试')).toBe(false)
    expect(wrapper.text()).toContain('已停用')
  })

  it('copies the RSS link for a subscription row with the caller membership flag', async () => {
    ctl().subscriptions.value = [subscription]
    authBox.isMember = true
    const wrapper = await mountView()

    // 订阅行内的 RSS 按钮只有图标没有文字，与直订卡片里的文字 pill 区分
    const rssButton = wrapper
      .findAll('button')
      .find((button) => button.attributes('title') === '复制 RSS 订阅链接' && button.text() === '')
    expect(rssButton).toBeDefined()
    await rssButton!.trigger('click')
    // 视图只透传 source 与会员标记；URL 形态由 controller 决定
    expect(ctl().copyRssLink).toHaveBeenCalledWith('dailyhot', true)
  })

  it('passes isMember=false when a free user copies the RSS link', async () => {
    ctl().subscriptions.value = [subscription]
    authBox.isMember = false
    const wrapper = await mountView()

    const rssButton = wrapper
      .findAll('button')
      .find((button) => button.attributes('title') === '复制 RSS 订阅链接' && button.text() === '')
    await rssButton!.trigger('click')
    expect(ctl().copyRssLink).toHaveBeenCalledWith('dailyhot', false)
  })

  it('offers briefing RSS buttons plus collapsed source pills without any channel or subscription', async () => {
    // 零渠道零订阅也能直接拿 RSS 链接——直订与推送渠道完全解耦；
    // 简报为主推，8 个原始条目源收在默认折叠的高级区
    authBox.isMember = false
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('RSS 简报订阅')
    expect(wrapper.text()).toContain('每日综合简报全文公开可订')
    const fullButton = wrapper.findAll('button').find((button) => button.text() === '每日简报 · 全文')
    expect(fullButton).toBeDefined()
    await fullButton!.trigger('click')
    expect(ctl().copyBriefingRssLink).toHaveBeenCalledWith(false)

    // 免费用户不显示速览按钮，改显示会员转化入口（RouterLinkStub 无 href，按 to 断言）
    expect(wrapper.findAll('button').some((button) => button.text() === '每日简报 · 速览')).toBe(false)
    const upsell = wrapper
      .findAllComponents(RouterLinkStub)
      .find((link) => link.props('to') === '/membership')
    expect(upsell).toBeDefined()
    expect(upsell!.text()).toContain('速览版为会员权益')

    const advanced = wrapper.find('details')
    expect(advanced.text()).toContain('按来源订阅原始条目（高级）')
    const pills = advanced
      .findAll('button')
      .filter((button) => button.attributes('title') === '复制 RSS 订阅链接')
    expect(pills.length).toBe(SUBSCRIPTION_SOURCES.length)
  })

  it('offers members the digest button and copies full or digest briefing links', async () => {
    authBox.isMember = true
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('速览链接内含你的专属 token')
    // 会员无 upsell 链接（quota 转化入口对会员同样隐藏）
    expect(
      wrapper.findAllComponents(RouterLinkStub).some((link) => link.props('to') === '/membership'),
    ).toBe(false)

    const fullButton = wrapper.findAll('button').find((button) => button.text() === '每日简报 · 全文')
    await fullButton!.trigger('click')
    expect(ctl().copyBriefingRssLink).toHaveBeenCalledWith(false)

    const digestButton = wrapper.findAll('button').find((button) => button.text() === '每日简报 · 速览')
    expect(digestButton).toBeDefined()
    await digestButton!.trigger('click')
    expect(ctl().copyBriefingRssLink).toHaveBeenCalledWith(true)
  })

  it('copies per-source member RSS links from the collapsed advanced section', async () => {
    authBox.isMember = true
    const wrapper = await mountView()

    const allPill = wrapper
      .find('details')
      .findAll('button')
      .find((button) => button.text() === '全部')
    expect(allPill).toBeDefined()
    await allPill!.trigger('click')
    expect(ctl().copyRssLink).toHaveBeenCalledWith('all', true)
  })

  it('shows the RSS reset entry only to members and requires confirmation', async () => {
    ctl().subscriptions.value = [subscription]
    authBox.isMember = false
    const freeWrapper = await mountView()
    expect(freeWrapper.text()).not.toContain('重置 RSS 链接')
    freeWrapper.unmount()

    // authStore mock 非响应式：会员形态须在挂载前就位（与 quota 测试同法）
    authBox.isMember = true
    const wrapper = await mountView()
    const resetButton = wrapper.findAll('button').find((button) => button.text() === '重置 RSS 链接')
    expect(resetButton).toBeDefined()

    confirmSpy.mockReturnValue(false)
    await resetButton!.trigger('click')
    expect(ctl().rotateFeedToken).not.toHaveBeenCalled()

    confirmSpy.mockReturnValue(true)
    await resetButton!.trigger('click')
    expect(ctl().rotateFeedToken).toHaveBeenCalledTimes(1)
  })
})

describe('SubscriptionsView membership quota gating', () => {
  const createButton = (wrapper: any) =>
    wrapper.findAll('button').find((button: any) => button.text() === '创建订阅')

  it('disables create and shows the upgrade hint when a free user is at the limit', async () => {
    ctl().channels.value = [emailChannel]
    ctl().subscriptions.value = [subscription]
    ctl().newSource.value = 'all'
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('免费档最多订阅 1 个日报模块')
    expect(createButton(wrapper)!.attributes('disabled')).toBeDefined()
  })

  it('keeps create enabled for an already-active source (same-module change)', async () => {
    ctl().channels.value = [emailChannel]
    ctl().subscriptions.value = [subscription]
    ctl().newSource.value = 'dailyhot'
    const wrapper = await mountView()

    expect(wrapper.text()).not.toContain('免费档最多订阅 1 个日报模块')
    expect(createButton(wrapper)!.attributes('disabled')).toBeUndefined()
  })

  it('never gates members', async () => {
    authBox.isMember = true
    ctl().channels.value = [emailChannel]
    ctl().subscriptions.value = [subscription]
    ctl().newSource.value = 'all'
    const wrapper = await mountView()

    expect(wrapper.text()).not.toContain('免费档最多订阅 1 个日报模块')
    expect(createButton(wrapper)!.attributes('disabled')).toBeUndefined()
  })

  it('maps the quota-exceeded token to the localized upgrade message', async () => {
    ctl().error.value = 'quota-exceeded'
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('免费档最多订阅 1 个日报模块，开通会员解锁全部 8 个模块。')
  })
})
