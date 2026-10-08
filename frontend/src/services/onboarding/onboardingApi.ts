import { isTerminal, type OnboardingStatus, type TerminalStatus } from '@/features/onboarding/persistence'

// Capture the session token explicitly: queued guest sync must never be sent
// with a different account's token after logout/login in another tab or dialog.
async function request(token: string, status?: TerminalStatus): Promise<OnboardingStatus> {
  const response = await fetch('/api/auth/me/onboarding', {
    method: status ? 'PUT' : 'GET',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: status ? JSON.stringify({ status }) : undefined,
    cache: 'no-store',
    credentials: 'same-origin',
    signal: AbortSignal.timeout(10_000),
  })
  if (!response.ok) throw new Error('Onboarding sync failed')
  const body: { status?: unknown } = await response.json()
  if (body.status !== 'unseen' && !isTerminal(body.status)) throw new Error('Invalid onboarding status')
  if (status && body.status === 'unseen') throw new Error('Onboarding update was not saved')
  return body.status
}
export const fetchOnboarding = (token: string) => request(token)
export const updateOnboarding = (token: string, status: TerminalStatus) => request(token, status)
