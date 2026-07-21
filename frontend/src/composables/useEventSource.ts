export type SseConnectParams = {
  url: string
  body: Record<string, unknown>
  onMessage: (payload: unknown) => void
  onDone?: () => void
  onError?: (error: unknown) => void
}

export type SseConnection = {
  /** 用于终止 SSE 连接的 AbortController */
  controller: AbortController
  /** 连接完成的 Promise */
  promise: Promise<void>
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
  /**
   * 建立 SSE 连接。
   *
   * 返回 SseConnection 对象，包含:
   *   - controller: AbortController，调用 controller.abort() 可终止生成
   *   - promise: 连接完成的 Promise
   */
  const connect = (params: SseConnectParams): SseConnection => {
    const { url, body, onMessage, onDone, onError } = params
    const controller = new AbortController()

    const promise = (async () => {
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
          // 尝试解析响应体获取详细错误信息（如 429 消息限额）
          let detail = `SSE request failed with status ${response.status}`
          try {
            const errorBody = await response.json()
            if (errorBody?.detail?.message) {
              detail = errorBody.detail.message
            } else if (typeof errorBody?.detail === 'string') {
              detail = errorBody.detail
            }
          } catch {
            // 响应体不是 JSON，保持默认消息
          }
          const err = new Error(detail) as Error & { status?: number; errorType?: string }
          err.status = response.status
          if (response.status === 429) {
            err.errorType = 'message_limit_exceeded'
          }
          throw err
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
              return
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
        // AbortError 是用户主动终止，不算错误
        if (error instanceof DOMException && error.name === 'AbortError') {
          onDone?.()
          return
        }
        onError?.(error)
      }
    })()

    return { controller, promise }
  }

  return {
    connect,
  }
}
