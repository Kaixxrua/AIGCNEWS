import { describe, expect, it } from 'vitest'
import source from './GitHubProjectsView.vue?raw'

const functionBody = (name: string, nextName: string) => {
  const start = source.indexOf(`const ${name} =`)
  const end = source.indexOf(`const ${nextName} =`, start + 1)
  expect(start).toBeGreaterThanOrEqual(0)
  expect(end).toBeGreaterThan(start)
  return source.slice(start, end)
}

describe('GitHub projects view orchestration contract', () => {
  it('keeps independent generations for lists, categories, and personal tags', () => {
    expect(source).toContain('const currentRequestId = ref(0)')
    expect(source).toContain('const categoryRequestId = ref(0)')
    expect(source).toContain('const tagRequestId = ref(0)')

    const projects = functionBody('loadProjects', 'resetAndLoad')
    expect(projects).toContain('const requestId = currentRequestId.value + 1')
    expect(projects.match(/requestId !== currentRequestId\.value/g)?.length).toBeGreaterThanOrEqual(3)
    expect(projects).toContain('if (requestId === currentRequestId.value)')

    const categories = functionBody('loadCategories', 'loadTaxonomy')
    expect(categories).toContain('const categorySource = publicSource.value')
    expect(categories).toContain('categorySource !== publicSource.value')

    const tags = functionBody('loadPersonalTags', 'loadCategories')
    expect(tags).toContain('const tagSource = publicSource.value')
    expect(tags).toContain('tagSource !== publicSource.value')
  })

  it('invalidates all pending reads when the kept-alive view stops', () => {
    const stopReads = functionBody('stopViewReads', 'refreshProjectsInBackground')
    expect(stopReads).toContain('window.clearTimeout(searchTimer)')
    expect(stopReads).toContain('currentRequestId.value += 1')
    expect(stopReads).toContain('categoryRequestId.value += 1')
    expect(stopReads).toContain('tagRequestId.value += 1')
    expect(source).toContain('onDeactivated(() =>')
    expect(source).toContain('onBeforeUnmount(stopViewReads)')
  })

  it('optimistically updates favorites and restores both fields after failure', () => {
    const favorite = functionBody('toggleFavorite', 'submitToolWebsite')
    expect(favorite).toContain('const previous = Boolean(repo.is_favorited)')
    expect(favorite).toContain('const previousAt = repo.favorited_at ?? null')
    expect(favorite).toContain('repo.is_favorited = !previous')
    expect(favorite).toContain('repo.is_favorited = previous')
    expect(favorite).toContain('repo.favorited_at = previousAt')
    expect(favorite).toContain("router.push({ path: '/login', query: { redirect: currentProjectsRedirect() } })")
  })

  it('keeps website mutations owner-scoped and refreshes the personal collection', () => {
    const refresh = functionBody('refreshAfterWebsiteMutation', 'reloadAfterCollectionRemoval')
    expect(refresh).toContain("source.value = 'website'")
    expect(refresh).toContain('selectedTag.value = \'\'')
    expect(refresh).toContain('replaceRouteFromState(true)')
    expect(refresh).toContain('loadPersonalTags()')
    expect(refresh).toContain('loadProjects({ clearSuccess: false })')

    const removeStart = source.indexOf('const removeToolWebsite =')
    const removeEnd = source.indexOf('\nwatch(', removeStart)
    expect(removeStart).toBeGreaterThanOrEqual(0)
    expect(removeEnd).toBeGreaterThan(removeStart)
    const remove = source.slice(removeStart, removeEnd)
    expect(remove).toContain('await removeMyToolWebsite(repo.website_id)')
    expect(remove).toContain('await reloadAfterCollectionRemoval()')
  })
})
