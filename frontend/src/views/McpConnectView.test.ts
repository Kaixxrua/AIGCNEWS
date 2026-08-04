import { describe, expect, it } from 'vitest'
import source from './McpConnectView.vue?raw'

const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)?.[1] ?? ''
const template = source.match(/<template>([\s\S]*?)<\/template>/)?.[1] ?? ''

describe('MCP connect view controller boundary', () => {
  it('delegates connection orchestration to useMcpConnectController', () => {
    expect(script).toContain("import { useMcpConnectController } from '../composables/useMcpConnectController'")
    expect(script).toContain('} = useMcpConnectController({')
    expect(script).toContain('isLoggedIn: () => authStore.isLoggedIn')
    expect(script).toContain("navigateToLogin: async () => { await router.push('/login') }")
    expect(script).toContain('translate: t')
  })

  it('loads controller state on mount and disposes it on unmount', () => {
    expect(script).toContain('onMounted(loadTokens)')
    expect(script).toContain('onBeforeUnmount(dispose)')
  })

  it('does not import direct transport, handshake, discovery, or command generation dependencies', () => {
    expect(script).not.toContain("from '../services/mcp/mcpTokenApi'")
    expect(script).not.toContain("from '../features/mcp/mcpHandshake'")
    expect(script).not.toContain("from '../features/mcp/publicToolsModel'")
    expect(script).not.toContain("from '../features/mcp/mcpCommandGenerator'")
    expect(script).not.toContain("from 'axios'")
    expect(script).not.toContain('performPublicMcpHandshake')
    expect(script).not.toContain('generateMcpClientCommand')
    expect(script).not.toMatch(/\b(?:fetch|create|delete)McpToken(?:s)?\b/)
    expect(script).not.toContain('discoveryRunId')
    expect(script).not.toContain('copyTimer')
  })

  it('localizes every human-readable MCP heading and hero label', () => {
    expect(template).toContain("t(`mcp.${pillKey}`)")
    expect(template).toContain("t('mcp.serverEyebrow')")
    expect(template).toContain("t('mcp.publicEndpoint')")
    expect(template).toContain("t('mcp.authenticatedSetup')")
    expect(template).toContain("t('mcp.tokenManagement')")
    expect(template).toContain("t('mcp.routing')")
    expect(template).toContain("t('mcp.aiArtifacts')")
    expect(template).not.toContain('>Public endpoint</p>')
    expect(template).not.toContain('>Authenticated setup</p>')
    expect(template).not.toContain('>Token management</p>')
    expect(template).not.toContain('>MCP-first routing</p>')
  })

  it('localizes client catalog and public tool copy through i18n keys', () => {
    expect(template).toContain('clientDisplayLabel(client)')
    expect(template).toContain('t(client.descriptionKey)')
    expect(template).toContain('clientConfigTarget(clientOption)')
    expect(template).toContain('t(tool.descriptionKey)')
    expect(template).not.toContain('{{ client.label }}')
    expect(template).not.toContain('{{ client.description }}')
    expect(template).not.toContain('{{ clientOption.configPath }}')
    expect(template).not.toContain('{{ tool.description }}')
  })

  it('keeps only presentation formatting in the view while preserving transient command privacy', () => {
    expect(script).toContain('const setupScopeLabel = computed(')
    expect(script).toContain('const setupTargetDescription = computed(')
    expect(script).toContain('const setupResultDescription = computed(')
    expect(script).toContain('const tokenStatusLabel =')
    expect(script).toContain('const formatDate =')
    expect(template).toContain('v-if="transientCommand"')
    expect(template).toContain('@click="copyGeneratedCommand"')
    expect(template).not.toContain('{{ transientCommand }}')
    expect(template).not.toMatch(/(?:v-html|v-text|:value)="transientCommand"/)
  })
})
