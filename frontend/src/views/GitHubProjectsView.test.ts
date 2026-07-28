import { describe, expect, it } from 'vitest'
import source from './GitHubProjectsView.vue?raw'

describe('GitHub projects view orchestration contract', () => {
  it('uses the project catalog controller without request or mutation compatibility wrappers', () => {
    expect(source).toContain("import { useProjectCatalogController } from '../composables/useProjectCatalogController'")
    expect(source).toContain("from '../services/projects/projectApi'")
    expect(source).not.toContain("from '../services/api'")
    expect(source).toContain('const controller = useProjectCatalogController({')
    expect(source).toContain('recommendProject, refreshReads, removeToolWebsite, requiresPersonalLogin')
    expect(source).not.toContain('const removeToolWebsite =')
    expect(source).not.toContain('const refreshProjectsInBackground =')
    expect(source).not.toContain('const defaultSortForSource =')
    expect(source).not.toContain('const defaultSortForScope =')
  })

  it('shares route state refs with the controller', () => {
    expect(source).toContain('routeState: { source, selectedScope, selectedCategory, selectedSubcategory, searchQuery, debouncedQuery, selectedLanguage, selectedTag, sort, page }')
    expect(source).toContain('replaceRouteFromState,')
    expect(source).toContain('currentRedirect: currentProjectsRedirect')
  })

  it('keeps UI orchestration in the view', () => {
    expect(source).toContain('watch(searchQuery,')
    expect(source).toContain('const openAddDialog =')
    expect(source).toContain('const closeAddDialog =')
    expect(source).toContain('const openEditDialog =')
    expect(source).toContain('const closeEditDialog =')
    expect(source).toContain('const hideBrokenLogo =')
  })

  it('preserves kept-alive invalidation and refresh behavior', () => {
    expect(source).toContain('controller.deactivate()')
    expect(source).toContain('controller.activate()')
    expect(source).toContain('onDeactivated(stopViewReads)')
    expect(source).toContain('onBeforeUnmount(stopViewReads)')
    expect(source).toContain('refreshReads({ clearSuccess: false, preserveContent: true })')
  })

  it('closes dialogs only after successful active mutations', () => {
    expect(source).toContain('if (!await controller.submitEditWebsite(websiteId, payload)) return')
    expect(source).toContain('editDialogOpen.value = false')
    expect(source).toContain('if (await controller.submitToolWebsite(request)) addDialogOpen.value = false')
  })
})
