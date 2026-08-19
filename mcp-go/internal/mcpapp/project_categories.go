package mcpapp

import "fmt"

// ToolInputError is returned when a tool argument violates its schema.
type ToolInputError struct{ Message string }

func (e ToolInputError) Error() string { return e.Message }

const publicProjectMinStars = 500

// ProjectCategoriesRepository supplies the public GitHub project taxonomy.
// Keeping the repository boundary explicit lets the handler remain independent
// of storage while the Postgres adapter is introduced incrementally.
type ProjectCategoriesRepository interface {
	GetProjectCategories() (map[string]any, error)
}

type ProjectCategoriesService struct {
	repository ProjectCategoriesRepository
}

func NewProjectCategoriesService(repository ProjectCategoriesRepository) *ProjectCategoriesService {
	return &ProjectCategoriesService{repository: repository}
}

func (s *ProjectCategoriesService) Get(arguments map[string]any) (map[string]any, error) {
	if len(arguments) != 0 {
		for key := range arguments {
			return nil, ToolInputError{Message: fmt.Sprintf("%s: Extra inputs are not permitted", key)}
		}
	}
	result, err := s.repository.GetProjectCategories()
	if err != nil {
		return nil, err
	}
	return mapCategoryResult(result), nil
}

func mapCategoryResult(result map[string]any) map[string]any {
	items, _ := result["items"].([]any)
	total := intValue(result["total"])
	today := intValue(result["today_count"])
	recommended := intValue(result["recommended_count"])
	return map[string]any{
		"items":             items,
		"total":             total,
		"today_count":       today,
		"recommended_count": recommended,
		"min_stars":         publicProjectMinStars,
		"source":            "github",
		"attribution":       "Data provided by AIGC Radar · https://aigcnews.cn",
	}
}

func intValue(value any) int {
	switch n := value.(type) {
	case int:
		return n
	case int64:
		return int(n)
	case float64:
		return int(n)
	default:
		return 0
	}
}

// StaticProjectCategoriesRepository is the bootstrapping repository used until
// the Postgres catalog adapter is wired. Its shape mirrors the parity fixture.
type StaticProjectCategoriesRepository struct{}

func (StaticProjectCategoriesRepository) GetProjectCategories() (map[string]any, error) {
	return map[string]any{
		"items": []any{
			map[string]any{
				"slug": "agents", "name": "智能体", "name_zh": "智能体", "name_en": "Agents", "project_count": 128,
				"subcategories": []any{map[string]any{
					"slug": "agent-frameworks", "name": "智能体框架", "name_zh": "智能体框架", "name_en": "Agent Frameworks", "project_count": 64,
				}},
			},
			map[string]any{
				"slug": "rag", "name": "检索增强", "name_zh": "检索增强", "name_en": "Retrieval-Augmented Generation", "project_count": 96,
				"subcategories": []any{},
			},
		},
		"total": 2, "today_count": 3, "recommended_count": 1,
	}, nil
}

func NewProjectCategoriesHandlers(repository ProjectCategoriesRepository) Handlers {
	service := NewProjectCategoriesService(repository)
	return Handlers{"get_project_categories": service.Get}
}
