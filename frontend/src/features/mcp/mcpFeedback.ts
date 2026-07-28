export type McpFeedback =
  | { kind: 'key'; key: string; params?: Record<string, unknown> }
  | { kind: 'literal'; message: string }
  | null

export type McpFeedbackTranslator = (
  key: string,
  params?: Record<string, unknown>,
) => string

export const feedbackKey = (
  key: string,
  params?: Record<string, unknown>,
): McpFeedback => ({ kind: 'key', key, params })

export const feedbackLiteral = (message: string): McpFeedback => (
  message ? { kind: 'literal', message } : null
)

export const resolveMcpFeedback = (
  feedback: McpFeedback,
  translate: McpFeedbackTranslator,
): string => {
  if (!feedback) return ''
  return feedback.kind === 'literal'
    ? feedback.message
    : translate(feedback.key, feedback.params)
}
