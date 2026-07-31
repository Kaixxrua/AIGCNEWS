import { describe, expect, it } from 'vitest'
import filtersSource from './ProjectFiltersPanel.vue?raw'
import paginationSource from './ProjectPagination.vue?raw'
import cardSource from './ProjectResultCard.vue?raw'
import addDialogSource from './ToolWebsiteAddDialog.vue?raw'
import editDialogSource from './ToolWebsiteEditDialog.vue?raw'
import viewSource from '../../views/GitHubProjectsView.vue?raw'

const cssVariableFallback = (source: string, variable: string, fallback: string) => {
  expect(source).toContain(`var(${variable}, ${fallback})`)
}

describe('project UI sizing contracts', () => {
  it('uses one page-scoped control height contract for filter controls', () => {
    expect(filtersSource).toContain('class="projects-source-tab"')
    expect(filtersSource).toContain('min-height: var(--projects-control-height, 44px)')
    expect(filtersSource).toContain('height: var(--projects-control-height, 44px)')
    expect(filtersSource).toContain('min-height: var(--projects-control-compact-height, 36px)')
    expect(filtersSource).toContain('padding-right: 112px')
    expect(filtersSource).toContain('overflow-x: auto')
  })

  it('normalizes card actions within a group while allowing narrow cards to wrap', () => {
    expect(cardSource).toContain('class="project-card__action project-card__link"')
    expect(cardSource).toContain('class="project-card__action project-card__favorite"')
    expect(cardSource).toContain('width: var(--projects-card-action-width, 152px)')
    expect(cardSource).toContain('min-height: var(--projects-control-compact-height, 36px)')
    expect(cardSource).toContain('@container (max-width: 520px)')
    expect(cardSource).toContain('min-width: 124px')
  })

  it('keeps pagination controls equal-height with responsive wrapping', () => {
    expect(paginationSource).toContain('projects-pagination__button')
    cssVariableFallback(paginationSource, '--projects-control-height', '44px')
    expect(paginationSource).toContain('height: var(--projects-control-height, 44px)')
    expect(paginationSource).toContain('flex-wrap: wrap')
  })

  it('normalizes dialog tabs and footer actions without relying on parent scoped styles', () => {
    expect(addDialogSource).toContain('class="tool-modal__actions"')
    expect(editDialogSource).toContain('class="tool-modal__actions"')
    expect(viewSource).toContain('.projects-add-btn')
    expect(viewSource).toContain('.projects-login-prompt__action')
    expect(viewSource).not.toContain('.projects-add-submit')
  })
})
