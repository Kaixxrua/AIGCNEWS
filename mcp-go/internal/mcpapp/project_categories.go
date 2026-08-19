package mcpapp

import (
	"fmt"

	"aigcnews/mcp-go/internal/jsonx"
)

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

// Get 校验并返回分类树。返回值是 jsonx.Object：键序逐字对齐 Python 侧
// dict 插入序（dispatch 不再做保序重排，责任在处理器）。
func (s *ProjectCategoriesService) Get(arguments map[string]any) (any, error) {
	if len(arguments) != 0 {
		for key := range arguments {
			return nil, ToolInputError{Message: fmt.Sprintf("%s: Extra inputs are not permitted", key)}
		}
	}
	result, err := s.repository.GetProjectCategories()
	if err != nil {
		return nil, err
	}
	return orderedCategoryResult(result), nil
}

// orderedCategoryResult 复刻 Python _tool_get_project_categories 的键序：
// 顶层 items/total/today_count/recommended_count/min_stars/source/attribution；
// 类目 slug/name/name_zh/name_en/project_count/subcategories；
// 子类目 slug/name/name_zh/name_en/project_count。
func orderedCategoryResult(result map[string]any) jsonx.Object {
	items := []any{}
	if raw, ok := result["items"].([]any); ok {
		for _, item := range raw {
			category, ok := item.(map[string]any)
			if !ok {
				continue
			}
			subcategories := []any{}
			if rawSub, ok := category["subcategories"].([]any); ok {
				for _, sub := range rawSub {
					if value, ok := sub.(map[string]any); ok {
						subcategories = append(subcategories, jsonx.Object{
							{Key: "slug", Value: value["slug"]},
							{Key: "name", Value: value["name"]},
							{Key: "name_zh", Value: value["name_zh"]},
							{Key: "name_en", Value: value["name_en"]},
							{Key: "project_count", Value: value["project_count"]},
						})
					}
				}
			}
			items = append(items, jsonx.Object{
				{Key: "slug", Value: category["slug"]},
				{Key: "name", Value: category["name"]},
				{Key: "name_zh", Value: category["name_zh"]},
				{Key: "name_en", Value: category["name_en"]},
				{Key: "project_count", Value: category["project_count"]},
				{Key: "subcategories", Value: subcategories},
			})
		}
	}
	return jsonx.Object{
		{Key: "items", Value: items},
		{Key: "total", Value: intValue(result["total"])},
		{Key: "today_count", Value: intValue(result["today_count"])},
		{Key: "recommended_count", Value: intValue(result["recommended_count"])},
		{Key: "min_stars", Value: publicProjectMinStars},
		{Key: "source", Value: "github"},
		{Key: "attribution", Value: "Data provided by AIGC Radar · https://aigcnews.cn"},
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
