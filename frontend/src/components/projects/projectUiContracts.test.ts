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

  it('uses a tooltip-enabled icon rail with a mobile text fallback', () => {
    expect(cardSource).not.toContain('project-card__pin')
    expect(cardSource).toContain('<div class="project-card__body">')
    expect(cardSource).toContain('<aside class="project-card__rail"')
    expect(cardSource).toContain('class="project-card__action project-card__link"')
    expect(cardSource).toContain('class="project-card__action-icon"')
    expect(cardSource).toContain('class="project-card__action-label"')
    expect(cardSource).toContain('class="project-card__tooltip" role="tooltip"')
    expect(cardSource).toContain(':aria-describedby="`project-action-${index}-favorite-tooltip`"')
    expect(cardSource).toContain(':aria-label="t(favoriteButtonLabelKey(repo, favoriteBusy, isLoggedIn))"')
    expect(cardSource).toContain(':title="t(recommendButtonLabelKey(repo, recommendBusy))"')
    expect(cardSource).toContain('right: calc(-1 * var(--projects-card-action-size, 40px))')
    expect(cardSource).toContain('margin-right: var(--projects-card-action-size, 40px)')
    expect(cardSource).toContain('border-left: 0')
    expect(cardSource).toContain('border-radius: 0 4px 4px 0')
    expect(cardSource).toContain('width: var(--projects-card-action-size, 40px)')
    expect(cardSource).toContain('min-height: var(--projects-card-action-size, 40px)')
    expect(cardSource).toContain('@container (max-width: 520px)')
    expect(cardSource).not.toMatch(/@container \(max-width: 520px\) \{[\s\S]*?project-card__rail \{ position: static;/)
    expect(cardSource).toContain('flex-wrap: wrap')
    expect(cardSource).toContain(':aria-pressed="Boolean(repo.is_favorited)"')
    expect(cardSource).toContain(':disabled="recommendActionsBusy"')
    expect(viewSource).toContain('--projects-card-action-size: 40px')
    expect(viewSource).not.toMatch(/\.project-card \{\s*position: relative;\s*display: flex;/)
    expect(viewSource).toContain('.project-card--skeleton {')
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
