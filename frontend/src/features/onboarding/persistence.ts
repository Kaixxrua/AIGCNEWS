import { getSafeInternalRedirect } from '@/features/auth/authViewModel'

export type TerminalStatus = 'skipped' | 'completed'
export type OnboardingStatus = 'unseen' | TerminalStatus
export type Owner = 'guest' | `user:${number}`
export interface TerminalRecord { status: TerminalStatus; pending: boolean }
interface Memory {
  browserDone?: boolean
  guest?: TerminalStatus
  users: Record<string, TerminalRecord>
}
export interface TourProgress { step: string; returnTo: string; manual: boolean; scope?: string }
export const MEMORY_KEY = 'aigcnews:onboarding:v1'
const fallback = new Map<string, string>()

function read(key: string, session = false): string | null {
  try { return (session ? sessionStorage : localStorage).getItem(key) }
  catch { return fallback.get(key) ?? null }
}
function write(key: string, value: string | null, session = false) {
  if (value === null) fallback.delete(key)
  else fallback.set(key, value)
  try {
    const storage = session ? sessionStorage : localStorage
    if (value === null) storage.removeItem(key)
    else storage.setItem(key, value)
  } catch { /* Current-tab memory still works when browser storage is blocked. */ }
}
export const isTerminal = (value: unknown): value is TerminalStatus => value === 'skipped' || value === 'completed'
export const mergeStatus = (a: TerminalStatus, b: TerminalStatus): TerminalStatus =>
  a === 'completed' || b === 'completed' ? 'completed' : 'skipped'

function memory(): Memory {
  try {
    const raw = JSON.parse(read(MEMORY_KEY) ?? '{}')
    const users: Memory['users'] = {}
    for (const [key, value] of Object.entries(raw.users ?? {})) {
      const record = value as TerminalRecord | null
      if (/^user:\d+$/.test(key) && record && isTerminal(record.status)) {
        users[key] = { status: record.status, pending: record.pending === true }
      }
    }
    return { browserDone: raw.browserDone === true, guest: isTerminal(raw.guest) ? raw.guest : undefined, users }
  } catch { return { users: {} } }
}
export function readTerminal(owner: Owner): TerminalRecord | undefined {
  const saved = memory()
  return owner === 'guest'
    ? saved.browserDone ? { status: saved.guest ?? 'skipped', pending: false } : undefined
    : saved.users[owner]
}
export function saveTerminal(owner: Owner, status: TerminalStatus, pending = true) {
  const saved = memory()
  saved.browserDone = true
  if (owner === 'guest') saved.guest = saved.guest ? mergeStatus(saved.guest, status) : status
  else {
    const previous = saved.users[owner]
    const merged = previous ? mergeStatus(previous.status, status) : status
    // A stale acknowledgement cannot clear an unsent completion.
    saved.users[owner] = { status: merged, pending: pending || merged !== status }
  }
  write(MEMORY_KEY, JSON.stringify(saved))
}
export function claimGuest(owner: Owner) {
  if (owner === 'guest') return
  const saved = memory()
  if (!saved.guest) return
  const previous = saved.users[owner]
  saved.users[owner] = {
    status: previous ? mergeStatus(previous.status, saved.guest) : saved.guest,
    pending: true,
  }
  // Claim and removal are one storage write; a second account cannot inherit it.
  delete saved.guest
  write(MEMORY_KEY, JSON.stringify(saved))
}
const progressKey = (owner: Owner) => `${MEMORY_KEY}:progress:${owner}`
export function readProgress(owner: Owner): TourProgress | null {
  try {
    const raw = JSON.parse(read(progressKey(owner), true) ?? 'null')
    if (!raw || typeof raw.step !== 'string' || typeof raw.returnTo !== 'string') return null
    return {
      step: raw.step,
      returnTo: getSafeInternalRedirect(raw.returnTo),
      manual: raw.manual === true,
      scope: typeof raw.scope === 'string' ? getSafeInternalRedirect(raw.scope) : undefined,
    }
  } catch { return null }
}
export function saveProgress(owner: Owner, progress: TourProgress | null) {
  write(progressKey(owner), progress ? JSON.stringify(progress) : null, true)
}
