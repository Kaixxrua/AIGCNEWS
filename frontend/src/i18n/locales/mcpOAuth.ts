import i18n from '@/i18n'

/**
 * MCP OAuth 同意页（/oauth/authorize）的文案独立成文件，沿用 notFound.ts 的注入方式：主 locale 表由其他
 * 工作流维护，这里在页面初始化时经 mergeLocaleMessage 注入 mcpOAuth.*。
 * 错误文案按 OAuth 错误码给（后端的 error_description 只有中文），未知错误码用 errors.unknown。
 */

type McpOAuthMessages = {
  mcpOAuth: {
    title: string
    description: string
    checking: string
    loading: string
    loginTitle: string
    loginBody: string
    login: string
    degraded: string
    retry: string
    requesting: string
    unnamedClient: string
    unverifiedName: string
    account: string
    switchAccount: string
    returnTo: {
      loopback: string
      web: string
      app: string
    }
    grantsTitle: string
    grants: {
      tools: string
      favorites: string
      tracking: string
    }
    tokenNote: string
    approve: string
    deny: string
    returning: {
      approved: string
      denied: string
      error: string
    }
    returningHint: string
    openClient: string
    errorTitle: string
    backToClient: string
    errorCode: string
    errors: {
      framed: string
      invalid_client: string
      invalid_redirect_uri: string
      invalid_request: string
      unsupported_response_type: string
      invalid_target: string
      temporarily_unavailable: string
      unknown: string
    }
  }
}

const enUS: McpOAuthMessages = {
  mcpOAuth: {
    title: 'Authorize an MCP client',
    description: 'Let an AI client connect to AIGC Radar MCP as you',
    checking: 'Checking your sign-in…',
    loading: 'Reading the authorization request…',
    loginTitle: 'Sign in to continue',
    loginBody: 'An MCP client is asking to connect to your AIGCNEWS account. Sign in first, then decide whether to allow it.',
    login: 'Sign in',
    degraded: 'We can’t confirm your sign-in right now.',
    retry: 'Try again',
    requesting: 'is asking to access your account',
    unnamedClient: 'Unnamed client',
    unverifiedName: 'The client picked this name itself and we can’t verify it. Only allow it if you just started connecting from your own MCP client.',
    account: 'Signed in as {account}',
    switchAccount: 'Use another account',
    returnTo: {
      loopback: 'Afterwards you go back to the client on this computer ({host}).',
      web: 'Afterwards you go to the website {host}.',
      app: 'Afterwards the app link {host} opens.',
    },
    grantsTitle: 'If you allow it, the client can:',
    grants: {
      tools: 'Use the AIGC Radar MCP search tools as you; calls count toward your MCP quota',
      favorites: 'Read the projects you have favorited',
      tracking: 'Read your tracked topics and projects',
    },
    tokenNote: 'The client gets its own token; authorizing the same client again replaces it.',
    approve: 'Allow',
    deny: 'Deny',
    returning: {
      approved: 'Allowed. Taking you back to the client…',
      denied: 'Denied. Letting the client know…',
      error: 'Taking the error back to the client…',
    },
    returningHint: 'You can close this page. If the client doesn’t respond, open it again with the link below.',
    openClient: 'Open the client again',
    errorTitle: 'Authorization can’t go ahead',
    backToClient: 'Back to the client',
    errorCode: 'Error code: {code}',
    errors: {
      framed: 'For your safety this page can’t be shown inside another site. Open the address directly in your browser.',
      invalid_client: 'This client isn’t registered, or its registration has expired. Start connecting again from your MCP client.',
      invalid_redirect_uri: 'The return address doesn’t match what the client registered, so authorization was stopped for safety.',
      invalid_request: 'The authorization request is incomplete or malformed. Start connecting again from your MCP client.',
      unsupported_response_type: 'The client asked for an authorization type this site doesn’t support.',
      invalid_target: 'The client asked for a service that isn’t this site’s MCP server.',
      temporarily_unavailable: 'Authorization is unavailable or busy right now. Try again shortly.',
      unknown: 'Authorization didn’t finish. Try again shortly.',
    },
  },
}

const zhCN: McpOAuthMessages = {
  mcpOAuth: {
    title: '授权 MCP 客户端',
    description: '让 AI 客户端以你的身份连接 AIGC Radar MCP',
    checking: '正在确认登录状态…',
    loading: '正在读取授权请求…',
    loginTitle: '登录后继续授权',
    loginBody: '有 MCP 客户端请求连接你的 AIGCNEWS 账号。先登录，再决定是否同意。',
    login: '登录',
    degraded: '暂时无法确认你的登录状态。',
    retry: '重试',
    requesting: '请求访问你的账号',
    unnamedClient: '未命名客户端',
    unverifiedName: '名称由客户端自己填写，本站无法核实。只有在你刚从自己的 MCP 客户端发起连接时才同意。',
    account: '当前账号：{account}',
    switchAccount: '换个账号',
    returnTo: {
      loopback: '授权后回到这台电脑上的客户端（{host}）。',
      web: '授权后跳转到网站 {host}。',
      app: '授权后打开应用链接 {host}。',
    },
    grantsTitle: '同意后，它可以：',
    grants: {
      tools: '以你的身份使用 AIGC Radar MCP 的检索工具，调用次数计入你的 MCP 额度',
      favorites: '读取你收藏的项目',
      tracking: '读取你的情报追踪',
    },
    tokenNote: '同意后会给这个客户端签发一枚专属 Token，同一客户端再次授权时替换旧的那枚。',
    approve: '同意',
    deny: '拒绝',
    returning: {
      approved: '已同意，正在回到客户端…',
      denied: '已拒绝，正在通知客户端…',
      error: '正在把错误带回客户端…',
    },
    returningHint: '可以关闭这个页面了。客户端没有反应的话，点下面的链接再打开一次。',
    openClient: '再次打开客户端',
    errorTitle: '无法完成授权',
    backToClient: '返回客户端',
    errorCode: '错误代码：{code}',
    errors: {
      framed: '为了安全，授权页不能嵌在其他网页里打开。请在浏览器里直接打开这个地址。',
      invalid_client: '这个客户端没有登记，或者登记已失效。请回到 MCP 客户端重新发起连接。',
      invalid_redirect_uri: '回调地址与客户端登记的不一致，为了安全已停止授权。',
      invalid_request: '授权请求不完整或格式不对。请回到 MCP 客户端重新发起连接。',
      unsupported_response_type: '客户端请求的授权方式本站不支持。',
      invalid_target: '客户端请求的不是本站的 MCP 服务。',
      temporarily_unavailable: '授权服务暂时不可用或请求过于频繁，请稍后再试。',
      unknown: '授权没有完成，请稍后再试。',
    },
  },
}

let installed = false

export function installMcpOAuthMessages(): void {
  if (installed) return
  installed = true
  i18n.global.mergeLocaleMessage('en-US', enUS)
  i18n.global.mergeLocaleMessage('zh-CN', zhCN)
}
