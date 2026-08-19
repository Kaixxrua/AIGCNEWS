package mcpapp

// documents_test.go 的期望值全部由 Python 权威实现现场生成
// （backend/app/services/mcp/contracts.py 的 SearchPapersInput /
// SearchDocumentsInput 经 pydantic v2 model_validate 实测），逐字对齐。

import (
	"strings"
	"testing"
)

// validateErr 跑校验并断言失败，返回 "; " 连接后的完整错误串。
func validateErr(t *testing.T, args map[string]any, withSource bool) string {
	t.Helper()
	_, err := validateSearchDocumentsArgs(args, withSource)
	if err == nil {
		t.Fatalf("validateSearchDocumentsArgs(%v, %v) 意外通过", args, withSource)
	}
	inputErr, ok := err.(ToolInputError)
	if !ok {
		t.Fatalf("错误类型 = %T，应为 ToolInputError", err)
	}
	return inputErr.Message
}

func TestValidateSearchDocumentsArgsErrors(t *testing.T) {
	cases := []struct {
		name       string
		args       map[string]any
		withSource bool
		want       string
	}{
		{"缺 q", map[string]any{}, false, "q: Field required"},
		{"q 非字符串数字", map[string]any{"q": float64(123)}, false, "q: Input should be a valid string"},
		{"q 非字符串数组", map[string]any{"q": []any{"agent"}}, false, "q: Input should be a valid string"},
		{"q 全空白", map[string]any{"q": "   "}, false, "q: String should have at least 1 character"},
		{"q 超 200 字符", map[string]any{"q": strings.Repeat("x", 201)}, false, "q: String should have at most 200 characters"},
		{"page 字符串", map[string]any{"q": "agent", "page": "2"}, false, "page: Input should be a valid integer"},
		{"page 零", map[string]any{"q": "agent", "page": float64(0)}, false, "page: Input should be greater than or equal to 1"},
		{"page 非整值", map[string]any{"q": "agent", "page": 1.5}, false, "page: Input should be a valid integer"},
		{"page 布尔", map[string]any{"q": "agent", "page": true}, false, "page: Input should be a valid integer"},
		{"limit 零", map[string]any{"q": "agent", "limit": float64(0)}, false, "limit: Input should be greater than or equal to 1"},
		{"limit 超 20", map[string]any{"q": "agent", "limit": float64(21)}, false, "limit: Input should be less than or equal to 20"},
		{"papers 拒 source", map[string]any{"q": "agent", "source": "arxiv"}, false, "source: Extra inputs are not permitted"},
		{"documents 缺 q 带 source", map[string]any{"source": "arxiv"}, true, "q: Field required"},
		{"source 枚举外", map[string]any{"q": "agent", "source": "bilibili"}, true,
			"source: Input should be 'all', 'arxiv', 'github', 'news', 'producthunt', 'hackernews' or 'x'"},
		{"source 数字", map[string]any{"q": "agent", "source": float64(42)}, true,
			"source: Input should be 'all', 'arxiv', 'github', 'news', 'producthunt', 'hackernews' or 'x'"},
		{"source null", map[string]any{"q": "agent", "source": nil}, true,
			"source: Input should be 'all', 'arxiv', 'github', 'news', 'producthunt', 'hackernews' or 'x'"},
		{"source 大写", map[string]any{"q": "agent", "source": "ALL"}, true,
			"source: Input should be 'all', 'arxiv', 'github', 'news', 'producthunt', 'hackernews' or 'x'"},
		// 多错误：字段定义序 q → source → page → limit，extras 最后（按键名排序，
		// Python 按输入序——语料未覆盖多 extra 顺序，已记录近似）。
		{"多错误字段序", map[string]any{"page": "x", "source": "bad"}, true,
			"q: Field required; source: Input should be 'all', 'arxiv', 'github', 'news', 'producthunt', 'hackernews' or 'x'; page: Input should be a valid integer"},
		{"多 extra 键序", map[string]any{"q": "agent", "foo": float64(1), "bar": float64(2)}, false,
			"bar: Extra inputs are not permitted; foo: Extra inputs are not permitted"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := validateErr(t, tc.args, tc.withSource); got != tc.want {
				t.Errorf("错误串 = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestValidateSearchDocumentsArgsOK(t *testing.T) {
	// 默认值与空白裁剪（pydantic str_strip_whitespace）。
	input, err := validateSearchDocumentsArgs(map[string]any{"q": "  agent  "}, true)
	if err != nil {
		t.Fatalf("意外失败: %v", err)
	}
	if input.q != "agent" || input.source != "all" || input.page != 1 || input.limit != 10 {
		t.Errorf("默认值/裁剪错误: %+v", input)
	}

	input, err = validateSearchDocumentsArgs(
		map[string]any{"q": "agent", "source": "arxiv", "page": float64(2), "limit": float64(5)}, true)
	if err != nil {
		t.Fatalf("意外失败: %v", err)
	}
	if input.q != "agent" || input.source != "arxiv" || input.page != 2 || input.limit != 5 {
		t.Errorf("显式值错误: %+v", input)
	}

	// 已记录近似：Go JSON 解码无法区分 1 与 1.0，整值浮点按整数接受
	// （Python strict 拒绝 1.0；语料未覆盖此形状）。
	if _, err := validateSearchDocumentsArgs(
		map[string]any{"q": "agent", "page": 1.0, "limit": 20.0}, false); err != nil {
		t.Fatalf("整值浮点应被近似接受: %v", err)
	}
}
