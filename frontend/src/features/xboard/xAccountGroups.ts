export interface XAccountOption {
  handle: string
  displayName: string
}

const ACCOUNT_GROUPS = [
  { id: 'openai', handles: ['openai', 'chatgptapp', 'openaidevs', 'codexreleases', 'codexresets_', 'thsottiaux'] },
  { id: 'anthropic', handles: ['anthropicai', 'claudeai', 'claudedevs'] },
  { id: 'google', handles: ['googleai', 'googledeepmind', 'geminiapp'] },
  { id: 'xai', handles: ['xai', 'spacexai', 'grok'] },
  { id: 'benchmarks', handles: ['arena', 'artificialanlys'] },
  { id: 'alibaba', handles: ['alibaba_qwen'] },
  { id: 'deepseek', handles: ['deepseek_ai'] },
  { id: 'meta', handles: ['aiatmeta'] },
  { id: 'moonshot', handles: ['kimi_moonshot'] },
  { id: 'minimax', handles: ['minimax_ai'] },
  { id: 'zai', handles: ['zai_org'] },
  { id: 'mistral', handles: ['mistralai'] },
  { id: 'tencent', handles: ['tencenthunyuan'] },
  { id: 'bytedance', handles: ['dreamina_ai'] },
  { id: 'kuaishou', handles: ['kling_ai'] },
  { id: 'suno', handles: ['suno'] },
  { id: 'perplexity', handles: ['perplexity_ai'] },
  { id: 'tools', handles: ['cursor_ai', 'opencode'] },
  { id: 'community', handles: ['huggingface', 'producthunt'] },
  { id: 'other', handles: [] },
] as const

type AccountGroupId = typeof ACCOUNT_GROUPS[number]['id']
const GROUP_BY_HANDLE = new Map<string, AccountGroupId>(
  ACCOUNT_GROUPS.flatMap((group) => group.handles.map((handle) => [handle, group.id] as const)),
)

/** Use stable handles, not editable display names; newly added accounts remain visible under Other. */
export const groupXAccounts = (accounts: readonly XAccountOption[]) => {
  const groups = ACCOUNT_GROUPS.map(({ id }) => ({ id, accounts: [] as XAccountOption[] }))
  for (const account of accounts) {
    const id = GROUP_BY_HANDLE.get(account.handle.replace(/^@/, '').toLowerCase()) ?? 'other'
    groups.find((group) => group.id === id)!.accounts.push(account)
  }
  return groups.filter((group) => group.accounts.length > 0)
}
