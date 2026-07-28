import { describe, expect, it } from 'vitest'
import source from './McpConnectView.vue?raw'

const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)?.[1] ?? ''
const template = source.match(/<template>([\s\S]*?)<\/template>/)?.[1] ?? ''

function functionSource(name: string, nextMarker: string) {
  const start = script.indexOf(`function ${name}`)
  const end = script.indexOf(nextMarker, start)
  expect(start).toBeGreaterThanOrEqual(0)
  expect(end).toBeGreaterThan(start)
  return script.slice(start, end)
}

describe('MCP connect view token and handshake contract', () => {
  it('keeps the generated command transient, hidden, and cleared when its inputs change', () => {
    expect(script).toContain("const transientCommand = ref('')")
    expect(script).toContain("transientCommand.value = generateAuthenticatedCommand(result.token)")
    expect(script.match(/result\.token/g)).toHaveLength(1)
    expect(script).toContain("function clearTransientCommand() {\n  transientCommand.value = ''")
    expect(script).toContain('watch([selectedClient, selectedShell, endpointUrl, clientLabel], clearTransientCommand)')
    expect(script).not.toMatch(/(?:localStorage|sessionStorage)\.(?:setItem|removeItem)/)
    expect(script).not.toMatch(/console\.(?:log|debug|info|warn|error)\s*\(/)
    expect(template).toContain('v-if="transientCommand"')
    expect(template).toContain('@click="copyGeneratedCommand"')
    expect(template).not.toContain('{{ transientCommand }}')
    expect(template).not.toMatch(/(?:v-html|v-text|:value)="transientCommand"/)
  })

  it('uses the exact private scope and redirects logged-out setup before token creation', () => {
    expect(script).toContain("const SCOPE = 'projects:favorites:read'")
    expect(script).toContain('scopes: [SCOPE],')

    const setup = functionSource('startSetup', 'function copyText')
    expect(setup).toContain("if (!authStore.isLoggedIn) { await router.push('/login'); return }")
    expect(setup.indexOf("router.push('/login')")).toBeLessThan(setup.indexOf('createMcpToken({'))
  })

  it('accepts only HTTP(S) endpoints for setup and public handshakes', () => {
    expect(script).toContain("['http:', 'https:'].includes(new URL(normalizedEndpoint.value).protocol)")
    expect(script).toContain("catch { return 'mcp.invalidUrl' }")
    expect(script).toContain('if (endpointWarning.value) { setupError.value = feedbackKey(endpointWarningKey.value); return }')
    expect(script).toContain('if (testing.value || endpointWarning.value) return')
    expect(template).toContain(':disabled="testing || Boolean(endpointWarning)"')
  })

  it('normalizes the exact public handshake result and suppresses stale runs', () => {
    expect(script).toContain("from '../features/mcp/mcpHandshake'")
    expect(script).toContain("from '../features/mcp/publicToolsModel'")

    const handshake = functionSource('testPublicHandshake', '\nonMounted(')
    expect(handshake).toContain('const runId = ++discoveryRunId')
    expect(handshake).toContain('const isActive = () => isActivePublicToolDiscovery(endpoint, runId, discoveryState.value)')
    expect(handshake).toContain('normalizePublicTools(await performPublicMcpHandshake(endpoint, {')
    expect(handshake.match(/if \(!isActive\(\)\) return/g)).toHaveLength(3)

    expect(script).toContain('watch(normalizedEndpoint, (endpoint) => {\n  discoveryRunId += 1')
    expect(script).toContain("discoveryState.value = { status: 'idle', endpoint }")
    expect(script).toContain('onBeforeUnmount(() => { discoveryRunId += 1; clearTransientCommand();')
  })

  it('clears a generated command and removes deleted token metadata', () => {
    const remove = functionSource('removeToken', 'function tokenStatus')
    expect(remove).toContain('clearTransientCommand()')
    expect(remove).toContain('await deleteMcpToken(item.id)')
    expect(remove).toContain('tokens.value = tokens.value.filter((token) => token.id !== item.id)')
    expect(remove.indexOf('clearTransientCommand()')).toBeLessThan(remove.indexOf('await deleteMcpToken(item.id)'))
    expect(remove.indexOf('await deleteMcpToken(item.id)')).toBeLessThan(remove.indexOf('tokens.value = tokens.value.filter'))
  })
})
