import type { McpClientOption, McpShellId } from './mcpClientCatalog'

const MCP_SERVER_KEY = 'aigc-news'
const CODEX_TOKEN_ENV = 'AIGC_NEWS_MCP_TOKEN'

function quotePowerShellLiteral(value: string): string {
  return `'${value.replace(/'/g, "''")}'`
}

function quote(value: string, shell: McpShellId): string {
  if (shell === 'bash') return `'${value.replace(/'/g, `'\\''`)}'`
  if (shell === 'powershell') return quotePowerShellLiteral(value)
  return `"${value.replace(/"/g, '""')}"`
}

function encodePowerShellCommand(command: string): string {
  const bytes = new Uint8Array(command.length * 2)
  for (let index = 0; index < command.length; index += 1) {
    const code = command.charCodeAt(index)
    bytes[index * 2] = code & 0xff
    bytes[index * 2 + 1] = code >> 8
  }
  let binary = ''
  bytes.forEach((byte) => { binary += String.fromCharCode(byte) })
  return btoa(binary)
}

function join(shell: McpShellId): string {
  return shell === 'cmd' ? ' & ' : '; '
}

function ignored(shell: McpShellId): string {
  if (shell === 'powershell') return '2>$null'
  return shell === 'cmd' ? '2>nul' : '2>/dev/null'
}

function parentDirectory(path: string): string {
  return path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
}

function powerShellWriteJsonScript(path: string, data: unknown): string {
  const directory = parentDirectory(path)
  const json = JSON.stringify(data)
  const mkdir = directory ? `New-Item -ItemType Directory -Force -Path ${quotePowerShellLiteral(directory)} | Out-Null` : ''
  const outputPath = `$outputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath(${quotePowerShellLiteral(path)})`
  const write = `[System.IO.File]::WriteAllText($outputPath, ${quotePowerShellLiteral(json)}, (New-Object System.Text.UTF8Encoding($false)))`
  return [mkdir, outputPath, write].filter(Boolean).join('; ')
}

function writeJsonCommand(path: string, data: unknown, shell: McpShellId): string {
  const script = powerShellWriteJsonScript(path, data)
  if (shell === 'powershell') return script
  if (shell === 'cmd') return `powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand ${encodePowerShellCommand(script)}`

  const directory = parentDirectory(path)
  const mkdir = directory ? `mkdir -p ${quote(directory, shell)}` : ''
  const write = `printf '%s\\n' ${quote(JSON.stringify(data), shell)} > ${quote(path, shell)}`
  return [mkdir, write].filter(Boolean).join(join(shell))
}

function authenticatedServer(url: string, token: string) {
  return { type: 'http', url, headers: { Authorization: `Bearer ${token}` } }
}

function configFor(option: McpClientOption, url: string, token: string): unknown {
  if (option.format === 'opencode-remote') {
    return {
      $schema: 'https://opencode.ai/config.json',
      mcp: {
        [MCP_SERVER_KEY]: {
          type: 'remote',
          url,
          enabled: true,
          oauth: false,
          headers: { Authorization: `Bearer ${token}` },
        },
      },
    }
  }
  return { mcpServers: { [MCP_SERVER_KEY]: authenticatedServer(url, token) } }
}

function continueYaml(url: string, token: string): string {
  const yamlString = (value: string) => JSON.stringify(value)
  return [
    'name: AIGC NEWS',
    'version: 0.0.1',
    'schema: v1',
    'mcpServers:',
    '  - name: aigc-news',
    '    type: streamable-http',
    `    url: ${yamlString(url)}`,
    '    requestOptions:',
    '      headers:',
    `        Authorization: ${yamlString(`Bearer ${token}`)}`,
    '',
  ].join('\n')
}

function continueCommand(url: string, token: string, shell: McpShellId): string {
  const yaml = continueYaml(url, token)
  const relativePath = '.continue/mcpServers/aigc-news.yaml'
  if (shell === 'bash') {
    const target = '"$HOME/.continue/mcpServers/aigc-news.yaml"'
    const directory = '"$HOME/.continue/mcpServers"'
    return [
      `mkdir -p ${directory}`,
      `(umask 077; tmp=$(mktemp "$HOME/.continue/mcpServers/.aigc-news.yaml.XXXXXX") || exit 1; trap 'rm -f "$tmp"' EXIT; printf '%s' ${quote(yaml, shell)} > "$tmp" && ln "$tmp" ${target}; status=$?; rm -f "$tmp"; trap - EXIT; exit $status)`,
    ].join(join(shell))
  }

  const script = [
    `$outputPath = Join-Path $HOME ${quotePowerShellLiteral(relativePath)}`,
    '$directory = Split-Path -Parent $outputPath',
    'New-Item -ItemType Directory -Force -Path $directory | Out-Null',
    '$temporaryPath = Join-Path $directory (([System.Guid]::NewGuid().ToString()) + \'.tmp\')',
    `$content = ${quotePowerShellLiteral(yaml)}`,
    "$encoding = New-Object System.Text.UTF8Encoding($false)",
    'try { [System.IO.File]::WriteAllText($temporaryPath, $content, $encoding); [System.IO.File]::Move($temporaryPath, $outputPath) } finally { if (Test-Path -LiteralPath $temporaryPath) { Remove-Item -LiteralPath $temporaryPath -Force } }',
  ].join('; ')
  return shell === 'cmd'
    ? `powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand ${encodePowerShellCommand(script)}`
    : script
}

function vscodeCommand(url: string, token: string, shell: McpShellId): string {
  const payload = JSON.stringify({
    name: MCP_SERVER_KEY,
    type: 'http',
    url,
    headers: { Authorization: `Bearer ${token}` },
  })
  const unsupported = 'VS Code CLI does not support --add-mcp. Upgrade VS Code or use MCP: Add Server and select the user scope.'

  if (shell === 'bash') {
    const workflow = [
      "command -v code >/dev/null 2>&1 || { printf '%s\\n' 'VS Code CLI not found. Install VS Code and reopen the terminal.' >&2; exit 1; }",
      `code --help 2>&1 | grep -Eq '^[[:space:]]*--add-mcp([=[:space:]]|$)' || { printf '%s\\n' ${quote(unsupported, shell)} >&2; exit 1; }`,
      `printf '%s' 'Register aigc-news in the VS Code default user profile? This replaces an existing server with the same name. [y/N] '; read -r reply; case "$reply" in [yY]|[yY][eE][sS]) ;; *) printf '%s\\n' 'Cancelled.'; exit 1 ;; esac`,
      `code --add-mcp ${quote(payload, shell)}`,
    ].join(join(shell))
    return `( ${workflow} )`
  }

  const script = [
    "$codeCommand = Get-Command code, code.exe, code.cmd -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $codeCommand) { throw 'VS Code CLI not found. Install VS Code and reopen the terminal.' }",
    "$codeHelp = (& $codeCommand.Source --help 2>&1 | Out-String); if ($codeHelp -notmatch '(?m)^\\s*--add-mcp(?:[=\\s]|$)') { throw " + quotePowerShellLiteral(unsupported) + ' }',
    "$confirmation = Read-Host 'Register aigc-news in the VS Code default user profile? This replaces an existing server with the same name. [y/N]'; if ($confirmation -notmatch '^(?i:y|yes)$') { throw 'Cancelled.' }",
    `& $codeCommand.Source --add-mcp ${quotePowerShellLiteral(payload)}`,
  ].join('; ')
  return shell === 'cmd'
    ? `powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand ${encodePowerShellCommand(script)}`
    : script
}

function codexCommand(url: string, token: string, shell: McpShellId): string {
  const setToken = shell === 'powershell'
    ? `$env:${CODEX_TOKEN_ENV}=${quote(token, shell)}; [Environment]::SetEnvironmentVariable(${quotePowerShellLiteral(CODEX_TOKEN_ENV)}, ${quotePowerShellLiteral(token)}, 'User')`
    : shell === 'cmd'
      ? `set "${CODEX_TOKEN_ENV}=${token}" & setx ${CODEX_TOKEN_ENV} ${quote(token, shell)} >nul`
      : `export ${CODEX_TOKEN_ENV}=${quote(token, shell)}`
  const remove = `codex mcp remove ${MCP_SERVER_KEY} ${ignored(shell)}`
  const add = `codex mcp add ${MCP_SERVER_KEY} --url ${quote(url, shell)} --bearer-token-env-var ${CODEX_TOKEN_ENV}`
  return [setToken, remove, add].join(join(shell))
}

export function generateMcpClientCommand(option: McpClientOption, url: string, token: string, shell: McpShellId): string {
  if (option.format === 'claude-cli') {
    if (shell !== 'bash') {
      const resolveExecutable = "$claudeCommand = Get-Command claude.exe, claude.cmd -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $claudeCommand) { throw 'Claude Code executable not found. Install Claude Code and reopen the terminal.' }"
      const command = [
        resolveExecutable,
        `& $claudeCommand.Source mcp remove --scope user ${MCP_SERVER_KEY} 2>$null`,
        `& $claudeCommand.Source mcp add --scope user --transport http ${MCP_SERVER_KEY} ${quotePowerShellLiteral(url)} --header ${quotePowerShellLiteral(`Authorization: Bearer ${token}`)}`,
      ].join('; ')
      return shell === 'cmd'
        ? `powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand ${encodePowerShellCommand(command)}`
        : command
    }
    return [
      `claude mcp remove --scope user ${MCP_SERVER_KEY} ${ignored(shell)}`,
      `claude mcp add --scope user --transport http ${MCP_SERVER_KEY} ${quote(url, shell)} --header ${quote(`Authorization: Bearer ${token}`, shell)}`,
    ].join(join(shell))
  }
  if (option.format === 'codex-cli') return codexCommand(url, token, shell)
  if (option.format === 'continue-yaml') return continueCommand(url, token, shell)
  if (option.format === 'vscode-cli') return vscodeCommand(url, token, shell)
  return writeJsonCommand(option.configPath, configFor(option, url, token), shell)
}
