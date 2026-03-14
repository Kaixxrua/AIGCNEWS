export type SseConnectParams = {
  url: string
  body: Record<string, unknown>
  onMessage: (payload: unknown) => void
  onDone?: () => void
  onError?: (error: unknown) => void
}

function parseSseEvent(rawEvent: string): unknown | null {
  const lines = rawEvent.split('\n')
  const dataLines: string[] = []

  for (const line of lines) {
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  }

  if (dataLines.length === 0) return null

  const dataText = dataLines.join('\n').trim()
  if (!dataText) return null

  if (dataText === '[DONE]') {
    return { type: 'done' }
  }

  try {
    return JSON.parse(dataText)
  } catch {
    return { type: 'content', data: dataText }
  }
}

export function useEventSource() {
  const connect = async ({ url, body, onMessage, onDone, onError }: SseConnectParams) => {
    const controller = new AbortController()

    try {
      // 从 localStorage 读取 token，附加到 Authorization header
      const token = localStorage.getItem('auth_token')
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        'Cache-Control': 'no-cache',
      }
      if (token) {
        headers['Authorization'] = `Bearer ${token}`
      }

      const response = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error(`SSE request failed with status ${response.status}`)
      }

      if (!response.body) {
        throw new Error('SSE response body is empty')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()

        if (done) {
          break
        }

        buffer += decoder.decode(value, { stream: true })

        // 兼容 \n\n 和 \r\n\r\n 两种 SSE 分隔
        const normalized = buffer.replace(/\r\n/g, '\n')
        const events = normalized.split('\n\n')
        buffer = events.pop() ?? ''

        for (const rawEvent of events) {
          const parsed = parseSseEvent(rawEvent)
          if (!parsed) continue

          if (
            typeof parsed === 'object' &&
            parsed !== null &&
            'type' in parsed &&
            (parsed as { type: string }).type === 'done'
          ) {
            onDone?.()
            return controller
          }

          onMessage(parsed)
        }
      }

      const finalChunk = decoder.decode()
      if (finalChunk) {
        buffer += finalChunk
      }

      if (buffer.trim()) {
        const parsed = parseSseEvent(buffer.replace(/\r\n/g, '\n'))
        if (parsed) {
          onMessage(parsed)
        }
      }

      onDone?.()
    } catch (error) {
      onError?.(error)
    }

    return controller
  }

  return {
    connect,
  }
}
