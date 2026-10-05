import i18n from '@/i18n'

/**
 * 每页 <title> 与 meta description 的文案，沿用 pwa.ts 的注入方式：主 locale 表由其他
 * 工作流维护，这里在 installPageHead 时经 mergeLocaleMessage 注入 seo.*。
 * 标题只写页名，品牌后缀由 seo/pageHead.ts 统一拼；首页沿用 index.html 的品牌标题。
 * 没写描述的页面用 descriptions.default。
 */

type SeoMessages = {
  seo: {
    titles: {
      home: string
      projects: string
      websiteCollection: string
      websites: string
      uiLibrary: string
      report: string
      xboard: string
      mcp: string
      dsh: string
      subscriptions: string
      membership: string
      checkout: string
      contact: string
      monitor: string
      paper: string
      disclaimer: string
      privacy: string
      register: string
      oauth: string
      notFound: string
    }
    descriptions: {
      default: string
      projects: string
      websites: string
      uiLibrary: string
      report: string
      xboard: string
      mcp: string
      dsh: string
      membership: string
      disclaimer: string
      privacy: string
    }
  }
}

const zhCN: SeoMessages = {
  seo: {
    titles: {
      home: 'AIGCNEWS · AIGC Radar — arXiv 论文、GitHub AI 项目、榜单与每日简报',
      projects: 'GitHub AI 项目库',
      websiteCollection: '我的网页收藏',
      websites: '站长推荐网页',
      uiLibrary: 'UI 灵感库',
      report: '每日 AIGC 简报',
      xboard: 'X 动态',
      mcp: 'AIGC Radar MCP 接入',
      dsh: 'DSH 插件',
      subscriptions: '情报追踪',
      membership: '会员',
      checkout: '开通会员',
      contact: '联系合作',
      monitor: '监控',
      paper: '论文',
      disclaimer: '用户协议与免责声明',
      privacy: '隐私政策',
      register: '注册',
      oauth: '登录',
      notFound: '页面不存在',
    },
    descriptions: {
      default: 'AIGCNEWS（AIGC Radar）：AI 垂直资讯索引——arXiv 论文、GitHub AI 项目库、日/周/月榜单与每日简报。',
      projects: 'GitHub 上的 AI 开源项目：按星标增长排出日榜、周榜、月榜，附项目简介与分类。',
      websites: '站长挑选的 AI 工具与资讯网站。',
      uiLibrary: '宽松许可的开源 UI 组件、区块与模板：在线预览，按类型、风格与框架筛选，也可以经 MCP 取用源码。',
      report: '每天汇总 arXiv 论文、GitHub 项目与 AI 圈动态的每日简报（AI 生成，仅供参考）。',
      xboard: 'AI 研究者、公司与开发者在 X 上的最新推文，附中文翻译。',
      mcp: '用 MCP 把 AIGC Radar 的论文、项目与 UI 素材检索接进 Claude、Cursor 等 AI 客户端。',
      dsh: 'AIGC Radar 的 DSH 插件：在 DSH 里直接检索 AI 论文、项目与资讯。',
      membership: 'AIGCNEWS 会员：持续追踪关注的 AI 主题与项目，接收个人简报，并享更高的 MCP/API 额度。',
      disclaimer: 'AIGCNEWS 用户协议与免责声明。',
      privacy: 'AIGCNEWS 隐私政策：我们收集哪些信息、如何使用和保护。',
    },
  },
}

const enUS: SeoMessages = {
  seo: {
    titles: {
      home: 'AIGCNEWS · AIGC Radar — arXiv papers, GitHub AI projects, rankings and daily briefings',
      projects: 'GitHub AI Projects',
      websiteCollection: 'My Websites',
      websites: 'Recommended Websites',
      uiLibrary: 'UI Library',
      report: 'Daily AIGC Briefing',
      xboard: 'X Board',
      mcp: 'AIGC Radar MCP',
      dsh: 'DSH Plugin',
      subscriptions: 'Tracking',
      membership: 'Membership',
      checkout: 'Checkout',
      contact: 'Contact',
      monitor: 'Monitor',
      paper: 'Paper',
      disclaimer: 'User Agreement and Disclaimer',
      privacy: 'Privacy Policy',
      register: 'Sign up',
      oauth: 'Sign in',
      notFound: 'Page not found',
    },
    descriptions: {
      default: 'AIGCNEWS (AIGC Radar): an AI news index — arXiv papers, a GitHub AI project library, daily/weekly/monthly rankings and daily briefings.',
      projects: 'Open-source AI projects on GitHub, ranked daily, weekly and monthly by star growth, with summaries and categories.',
      websites: 'AI tools and news sites picked by the editor.',
      uiLibrary: 'Permissively licensed open-source UI components, blocks and templates: live previews, filters by type, style and framework, and source access over MCP.',
      report: 'A daily briefing on arXiv papers, GitHub projects and what is happening in AI (AI-generated, for reference only).',
      xboard: 'The latest posts on X from AI researchers, companies and developers.',
      mcp: 'Connect AIGC Radar paper, project and UI search to Claude, Cursor and other AI clients over MCP.',
      dsh: 'The AIGC Radar plugin for DSH: search AI papers, projects and news right inside DSH.',
      membership: 'AIGCNEWS membership: track the AI topics and projects you follow, get a personal briefing and higher MCP/API limits.',
      disclaimer: 'The AIGCNEWS user agreement and disclaimer.',
      privacy: 'The AIGCNEWS privacy policy: what we collect, and how we use and protect it.',
    },
  },
}

let installed = false

export function installSeoMessages(): void {
  if (installed) return
  installed = true
  i18n.global.mergeLocaleMessage('en-US', enUS)
  i18n.global.mergeLocaleMessage('zh-CN', zhCN)
}
