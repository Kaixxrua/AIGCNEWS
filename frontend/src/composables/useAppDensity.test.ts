import { afterEach, describe, expect, it, vi } from 'vitest'

// 偏好是模块级的一份：每个用例重新载入模块，按当时的本机存储读初值。
async function load() {
  vi.resetModules()
  return import('./useAppDensity')
}

describe('useAppDensity', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('starts compact and remembers the comfortable layout', async () => {
    const { APP_DENSITY_KEY, useAppDensity } = await load()
    const { density, comfortable, toggle } = useAppDensity()
    expect(density.value).toBe('compact')
    expect(comfortable.value).toBe(false)
    toggle()
    expect(comfortable.value).toBe(true)
    expect(localStorage.getItem(APP_DENSITY_KEY)).toBe('comfortable')
    toggle()
    expect(density.value).toBe('compact')
    expect(localStorage.getItem(APP_DENSITY_KEY)).toBe('compact')
  })

  it('shares one choice between the masthead toggle and the pages', async () => {
    const { setAppDensity, useAppDensity } = await load()
    const masthead = useAppDensity()
    const page = useAppDensity()
    masthead.toggle()
    expect(page.comfortable.value).toBe(true)
    setAppDensity('compact')
    expect(masthead.comfortable.value).toBe(false)
  })

  it('reads the stored choice and ignores unknown values', async () => {
    localStorage.setItem('app_density', 'comfortable')
    expect((await load()).useAppDensity().comfortable.value).toBe(true)
    localStorage.setItem('app_density', 'roomy')
    expect((await load()).useAppDensity().density.value).toBe('compact')
  })

  it('still switches when storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    const { comfortable, toggle } = (await load()).useAppDensity()
    expect(comfortable.value).toBe(false)
    toggle()
    expect(comfortable.value).toBe(true)
  })

  it('offers the toggle only on pages with a comfortable layout', async () => {
    const { DENSITY_ROUTES } = await load()
    expect([...DENSITY_ROUTES].sort()).toEqual(['membership', 'report', 'ui-library', 'x-board'])
    expect(DENSITY_ROUTES.has('dashboard')).toBe(false)
    expect(DENSITY_ROUTES.has('paper-read')).toBe(false)
  })
})
