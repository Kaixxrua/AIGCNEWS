package mcpapp

// project_search_test.go 的校验期望值全部由 Python 权威实现现场核对
// （backend/app/services/mcp/contracts.py 的 SearchGitHubProjectsInput 经
// 项目 venv 的 pydantic v2 model_validate 实测，2026-08 复跑确认），逐字
// 对齐；service 行为期望值取自 tools.jsonl 第 17 行语料字节与
// fixtures.json 的 project_search_results.generic 段。

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/jsonx"
)

// fakeProjectSearchEngine 记录收到的输入并返回预定结果/错误。
type fakeProjectSearchEngine struct {
	inputs []ProjectSearchInput
	result jsonx.Object
	err    error
}

func (f *fakeProjectSearchEngine) SearchProjects(input ProjectSearchInput) (jsonx.Object, error) {
	f.inputs = append(f.inputs, input)
	if f.err != nil {
		return nil, f.err
	}
	return f.result, nil
}

func projectSearchValidateErr(t *testing.T, args map[string]any) string {
	t.Helper()
	_, err := validateSearchGitHubProjectsArgs(args)
	if err == nil {
		t.Fatalf("validateSearchGitHubProjectsArgs(%v) 意外通过", args)
	}
	inputErr, ok := err.(ToolInputError)
	if !ok {
		t.Fatalf("错误类型 = %T，应为 ToolInputError", err)
	}
	return inputErr.Message
}

// TestValidateSearchGitHubProjectsArgsErrors 逐字对齐 pydantic v2 实测文案
// （spec §1.3 全文案表 + venv 探针复跑确认）。
func TestValidateSearchGitHubProjectsArgsErrors(t *testing.T) {
	languageValueError := "language: Value error, " + repositoryLanguageMessage
	cases := []struct {
		name string
		args map[string]any
		want string
	}{
		{"缺q", map[string]any{},
			"q: Field required"},
		{"q空串", map[string]any{"q": ""},
			"q: String should have at least 1 character"},
		{"q纯空白strip后空", map[string]any{"q": "   "},
			"q: String should have at least 1 character"},
		{"q超长121", map[string]any{"q": strings.Repeat("x", 121)},
			"q: String should have at most 120 characters"},
		{"q非字符串", map[string]any{"q": float64(123)},
			"q: Input should be a valid string"},
		{"q布尔", map[string]any{"q": true},
			"q: Input should be a valid string"},
		{"q为null", map[string]any{"q": nil},
			"q: Input should be a valid string"},
		{"q数组", map[string]any{"q": []any{"a"}},
			"q: Input should be a valid string"},
		{"sort非枚举", map[string]any{"q": "x", "sort": "bogus"},
			"sort: Input should be 'relevance', 'hot', 'stars', 'updated', 'recent' or 'name'"},
		{"sort非字符串", map[string]any{"q": "x", "sort": float64(1)},
			"sort: Input should be 'relevance', 'hot', 'stars', 'updated', 'recent' or 'name'"},
		{"sort带空白不strip", map[string]any{"q": "x", "sort": " stars "},
			"sort: Input should be 'relevance', 'hot', 'stars', 'updated', 'recent' or 'name'"},
		{"lang非枚举", map[string]any{"q": "x", "lang": "fr"},
			"lang: Input should be 'zh' or 'en'"},
		{"lang为null", map[string]any{"q": "x", "lang": nil},
			"lang: Input should be 'zh' or 'en'"},
		{"lang非字符串", map[string]any{"q": "x", "lang": float64(1)},
			"lang: Input should be 'zh' or 'en'"},
		{"language禁用值zh", map[string]any{"q": "x", "language": "zh"},
			languageValueError},
		{"language禁用值zh-CN", map[string]any{"q": "x", "language": "zh-CN"},
			languageValueError},
		{"language禁用值en-US", map[string]any{"q": "x", "language": "en-US"},
			languageValueError},
		{"language禁用值中文", map[string]any{"q": "x", "language": "中文"},
			languageValueError},
		{"language大小写折叠EN", map[string]any{"q": "x", "language": "EN"},
			languageValueError},
		{"language大小写折叠ZH-hans", map[string]any{"q": "x", "language": "ZH-hans"},
			languageValueError},
		{"language带空白strip后禁用", map[string]any{"q": "x", "language": "  ZH  "},
			languageValueError},
		{"language非字符串", map[string]any{"q": "x", "language": float64(5)},
			"language: Input should be a valid string"},
		{"language为null", map[string]any{"q": "x", "language": nil},
			"language: Input should be a valid string"},
		{"language超长65", map[string]any{"q": "x", "language": strings.Repeat("y", 65)},
			"language: String should have at most 64 characters"},
		{"page为0", map[string]any{"q": "x", "page": float64(0)},
			"page: Input should be greater than or equal to 1"},
		{"page负数", map[string]any{"q": "x", "page": float64(-1)},
			"page: Input should be greater than or equal to 1"},
		{"page非整浮点", map[string]any{"q": "x", "page": float64(1.5)},
			"page: Input should be a valid integer"},
		{"page布尔", map[string]any{"q": "x", "page": true},
			"page: Input should be a valid integer"},
		{"page字符串", map[string]any{"q": "x", "page": "3"},
			"page: Input should be a valid integer"},
		{"page为null", map[string]any{"q": "x", "page": nil},
			"page: Input should be a valid integer"},
		{"limit超20", map[string]any{"q": "x", "limit": float64(21)},
			"limit: Input should be less than or equal to 20"},
		{"limit为0", map[string]any{"q": "x", "limit": float64(0)},
			"limit: Input should be greater than or equal to 1"},
		{"extras按键名排序", map[string]any{"q": "x", "unknown": float64(1), "aaa": float64(2)},
			"aaa: Extra inputs are not permitted; unknown: Extra inputs are not permitted"},
		{"generic禁带键走extras", map[string]any{"q": "x", "category": "devtools", "scope": "today", "intent": map[string]any{}},
			"category: Extra inputs are not permitted; intent: Extra inputs are not permitted; scope: Extra inputs are not permitted"},
		{"多字段按定义序", map[string]any{
			"language": "zh", "sort": "bogus", "page": float64(0),
			"limit": float64(21), "extra": float64(1)},
			"q: Field required; " + languageValueError +
				"; sort: Input should be 'relevance', 'hot', 'stars', 'updated', 'recent' or 'name'" +
				"; page: Input should be greater than or equal to 1" +
				"; limit: Input should be less than or equal to 20" +
				"; extra: Extra inputs are not permitted"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := projectSearchValidateErr(t, tc.args); got != tc.want {
				t.Fatalf("错误文案 = %q，应为 %q", got, tc.want)
			}
		})
	}
}

// TestValidateSearchGitHubProjectsArgsOK 覆盖通过路径的默认值、strip 与
// null 语义（expect 值均经 venv 探针实测）。
func TestValidateSearchGitHubProjectsArgsOK(t *testing.T) {
	// 最小入参：model_dump 默认值填充。
	input, err := validateSearchGitHubProjectsArgs(map[string]any{"q": "static site"})
	if err != nil {
		t.Fatalf("意外失败: %v", err)
	}
	want := searchGitHubProjectsInput{q: "static site", lang: "zh", page: 1, limit: 10}
	if input != want {
		t.Fatalf("验证结果 = %+v，应为 %+v", input, want)
	}

	// strip（StrictStr 字段）+ 显式 null sort（Python None → ""）+
	// 显式枚举与数值。
	input, err = validateSearchGitHubProjectsArgs(map[string]any{
		"q":        "  static site  ",
		"language": " Jupyter Notebook ",
		"sort":     nil,
		"lang":     "en",
		"page":     float64(2),
		"limit":    float64(20),
	})
	if err != nil {
		t.Fatalf("意外失败: %v", err)
	}
	want = searchGitHubProjectsInput{
		q: "static site", language: "Jupyter Notebook",
		lang: "en", page: 2, limit: 20,
	}
	if input != want {
		t.Fatalf("验证结果 = %+v，应为 %+v", input, want)
	}

	// sort 六枚举全部合法；未传与 null 同归 ""。
	for _, sortValue := range projectDiscoverySortChoices {
		input, err = validateSearchGitHubProjectsArgs(map[string]any{"q": "x", "sort": sortValue})
		if err != nil || input.sort != sortValue {
			t.Fatalf("sort=%q: err=%v input.sort=%q", sortValue, err, input.sort)
		}
	}

	// q="\x1c" 合法：venv 探针实测 pydantic-core 的 str_strip_whitespace
	// 不剥离 \x1c-\x1f（Unicode White_Space 口径），strip 后长 1。
	input, err = validateSearchGitHubProjectsArgs(map[string]any{"q": "\x1c"})
	if err != nil || input.q != "\x1c" {
		t.Fatalf("q=\\x1c: err=%v input.q=%q", err, input.q)
	}

	// strip 后量长：121 字节含首尾空白，strip 后 120 合法。
	if _, err = validateSearchGitHubProjectsArgs(map[string]any{
		"q": " " + strings.Repeat("x", 120) + "\t",
	}); err != nil {
		t.Fatalf("q 边界意外失败: %v", err)
	}

	// language strip 后 64 合法；空串/纯空白合法（AfterValidator 放行）。
	for _, language := range []string{"  " + strings.Repeat("y", 64) + " ", "", "   ", "C++"} {
		if _, err = validateSearchGitHubProjectsArgs(map[string]any{
			"q": "x", "language": language,
		}); err != nil {
			t.Fatalf("language=%q 意外失败: %v", language, err)
		}
	}
}

// 逐字取自 tools.jsonl 第 17 行响应体的 structuredContent（紧凑形态）；
// genericProjectSearchFixture 是 fixtures.json 的
// project_search_results.generic 段（回放 stub 返回的原始形态，即 handler
// 后处理之前）。
const genericProjectSearchFixture = `{"items":[{"id":"repo-9","full_name":"acme/static-site-gen","url":"https://github.com/acme/static-site-gen","description":"Prompt 工作台","description_zh":"Prompt 工作台","description_en":"A workbench for prompts","category_slug":"prompt-engineering","category_name":"提示工程","category_name_zh":"提示工程","category_name_en":"Prompt Engineering","subcategory_slug":null,"subcategory_name":null,"subcategory_name_zh":null,"subcategory_name_en":null,"tags":[],"tags_zh":[],"tags_en":[],"topics":["prompts"],"language":"TypeScript","stars":500,"forks":12,"pushed_at":"2026-08-01T00:00:00+00:00","score":0.5,"result_origin":"github_api_fallback"}],"total":1,"local_total":0,"page":1,"limit":10,"scope":"all","sort":"stars","fallback_used":true,"result_origin":"github_api_fallback","fallback_policy":"local_first_github_only_when_local_zero"}`

const genericStructuredContent = `{"items":[{"id":"repo-9","full_name":"acme/static-site-gen","url":"https://github.com/acme/static-site-gen","description":"Prompt 工作台","description_zh":"Prompt 工作台","description_en":"A workbench for prompts","category_slug":"prompt-engineering","category_name":"提示工程","category_name_zh":"提示工程","category_name_en":"Prompt Engineering","subcategory_slug":null,"subcategory_name":null,"subcategory_name_zh":null,"subcategory_name_en":null,"tags":[],"tags_zh":[],"tags_en":[],"topics":["prompts"],"language":"TypeScript","stars":500,"forks":12,"pushed_at":"2026-08-01T00:00:00+00:00","score":0.5,"result_origin":"github_api_fallback","detail_url":"https://aigcnews.cn/projects?q=acme%2Fstatic-site-gen&utm_source=mcp&utm_medium=tool","data_source":"aigcnews.cn"}],"total":1,"local_total":0,"page":1,"limit":10,"scope":"all","sort":"stars","fallback_used":true,"result_origin":"github_api_fallback","fallback_policy":"local_first_github_only_when_local_zero","lang":"zh","attribution":"Data provided by AIGC Radar · https://aigcnews.cn"}`

// TestProjectSearchServiceGetCorpusBytes 端到端钉住回放路径：fixture 段经
// jsonx.DecodeOrdered 保序装载 → service 后处理 → 紧凑编码 == 语料
// structuredContent 逐字节（detail_url 的 %2F、lang/attribution 殿后、
// items 原位覆盖、数字字面量原样）。
func TestProjectSearchServiceGetCorpusBytes(t *testing.T) {
	fixture, err := jsonx.DecodeOrdered([]byte(genericProjectSearchFixture))
	if err != nil {
		t.Fatalf("fixture 解码失败: %v", err)
	}
	engine := &fakeProjectSearchEngine{result: fixture.(jsonx.Object)}
	service := NewProjectSearchService(engine, "")

	got, err := service.Get(map[string]any{"q": "static site"})
	if err != nil {
		t.Fatalf("Get 意外失败: %v", err)
	}
	if encoded := string(jsonx.MustMarshalCompact(got)); encoded != genericStructuredContent {
		t.Fatalf("响应字节漂移:\ngot  %s\nwant %s", encoded, genericStructuredContent)
	}

	// 引擎入参：generic 强制段 + 校验默认值（tools.py:271-276）。
	if len(engine.inputs) != 1 {
		t.Fatalf("引擎调用次数 = %d", len(engine.inputs))
	}
	wantInput := ProjectSearchInput{
		Query: "static site", Mode: "generic", Scope: "all",
		Page: 1, Limit: 10,
	}
	if engine.inputs[0] != wantInput {
		t.Fatalf("引擎入参 = %+v，应为 %+v", engine.inputs[0], wantInput)
	}

	// 无共享态：引擎持有的 fixture 对象不得被就地改写（lang/attribution
	// 与 item 追加键只出现在返回值上）。
	for _, pair := range engine.result {
		if pair.Key == "lang" || pair.Key == "attribution" {
			t.Fatalf("引擎结果被就地改写: 键 %q 出现在原对象", pair.Key)
		}
	}
	for _, item := range engine.result[0].Value.([]any) {
		for _, pair := range item.(jsonx.Object) {
			if pair.Key == "detail_url" || pair.Key == "data_source" {
				t.Fatalf("引擎结果被就地改写: item 键 %q 出现在原对象", pair.Key)
			}
		}
	}
}

// TestProjectSearchServiceGetItemsAbsent：items 键缺失 → 追加在原 pairs
// 之后、lang 之前，值为空数组（编码 []）。
func TestProjectSearchServiceGetItemsAbsent(t *testing.T) {
	engine := &fakeProjectSearchEngine{result: jsonx.Object{
		{Key: "total", Value: json.Number("0")},
	}}
	service := NewProjectSearchService(engine, "https://radar.example.com")
	got, err := service.Get(map[string]any{"q": "x"})
	if err != nil {
		t.Fatalf("Get 意外失败: %v", err)
	}
	want := `{"total":0,"items":[],"lang":"zh",` +
		`"attribution":"Data provided by AIGC Radar · https://radar.example.com"}`
	if encoded := string(jsonx.MustMarshalCompact(got)); encoded != want {
		t.Fatalf("got %s, want %s", encoded, want)
	}
}

// TestProjectSearchServiceGetNonDictItemsDropped：isinstance(item, dict)
// 过滤——非 Object 元素静默丢弃；存活元素原位保序 + detail_url/data_source
// 殿后。
func TestProjectSearchServiceGetNonDictItemsDropped(t *testing.T) {
	engine := &fakeProjectSearchEngine{result: jsonx.Object{
		{Key: "items", Value: []any{
			"bogus",
			json.Number("5"),
			jsonx.Object{{Key: "full_name", Value: "owner/repo"}},
		}},
		{Key: "total", Value: json.Number("3")},
	}}
	service := NewProjectSearchService(engine, "")
	got, err := service.Get(map[string]any{"q": "x"})
	if err != nil {
		t.Fatalf("Get 意外失败: %v", err)
	}
	want := `{"items":[{"full_name":"owner/repo",` +
		`"detail_url":"https://aigcnews.cn/projects?q=owner%2Frepo&utm_source=mcp&utm_medium=tool",` +
		`"data_source":"aigcnews.cn"}],"total":3,"lang":"zh",` +
		`"attribution":"Data provided by AIGC Radar · https://aigcnews.cn"}`
	if encoded := string(jsonx.MustMarshalCompact(got)); encoded != want {
		t.Fatalf("got %s, want %s", encoded, want)
	}
}

// TestProjectSearchServiceGetEnFolding：lang=en 时 localize 折叠链生效
// （en 值原位替换、zh 键删除、tags_en 替换 tags），lang/attribution 殿后。
func TestProjectSearchServiceGetEnFolding(t *testing.T) {
	engine := &fakeProjectSearchEngine{result: jsonx.Object{
		{Key: "items", Value: []any{jsonx.Object{
			{Key: "full_name", Value: "acme/rag"},
			{Key: "description", Value: "检索工具"},
			{Key: "description_zh", Value: "检索工具"},
			{Key: "description_en", Value: "RAG toolkit"},
			{Key: "tags", Value: []any{"标签"}},
			{Key: "tags_zh", Value: []any{"标签"}},
			{Key: "tags_en", Value: []any{"rag"}},
		}}},
	}}
	service := NewProjectSearchService(engine, "")
	got, err := service.Get(map[string]any{"q": "rag", "lang": "en"})
	if err != nil {
		t.Fatalf("Get 意外失败: %v", err)
	}
	want := `{"items":[{"full_name":"acme/rag","description":"RAG toolkit",` +
		`"description_en":"RAG toolkit","tags":["rag"],"tags_en":["rag"],` +
		`"detail_url":"https://aigcnews.cn/projects?q=acme%2Frag&utm_source=mcp&utm_medium=tool",` +
		`"data_source":"aigcnews.cn"}],"lang":"en",` +
		`"attribution":"Data provided by AIGC Radar · https://aigcnews.cn"}`
	if encoded := string(jsonx.MustMarshalCompact(got)); encoded != want {
		t.Fatalf("got %s, want %s", encoded, want)
	}
	if engine.inputs[0].Sort != "" || engine.inputs[0].Language != "" {
		t.Fatalf("引擎入参 = %+v", engine.inputs[0])
	}
}

// TestProjectSearchServiceEngineErrorPassthrough：引擎错误原样透传为普通
// error（不包 ToolInputError；dispatch 折叠 "Tool execution failed."）。
func TestProjectSearchServiceEngineErrorPassthrough(t *testing.T) {
	boom := errors.New("db down")
	engine := &fakeProjectSearchEngine{err: boom}
	service := NewProjectSearchService(engine, "")
	_, err := service.Get(map[string]any{"q": "x"})
	if !errors.Is(err, boom) {
		t.Fatalf("err = %v，应原样透传 %v", err, boom)
	}
	if _, ok := err.(ToolInputError); ok {
		t.Fatalf("引擎错误不得包装为 ToolInputError: %v", err)
	}
}

// TestProjectSearchServiceValidationShortCircuits：校验失败产生
// ToolInputError 且不触达引擎。
func TestProjectSearchServiceValidationShortCircuits(t *testing.T) {
	engine := &fakeProjectSearchEngine{}
	service := NewProjectSearchService(engine, "")
	_, err := service.Get(map[string]any{"q": ""})
	inputErr, ok := err.(ToolInputError)
	if !ok {
		t.Fatalf("错误类型 = %T，应为 ToolInputError", err)
	}
	if inputErr.Message != "q: String should have at least 1 character" {
		t.Fatalf("错误文案 = %q", inputErr.Message)
	}
	if len(engine.inputs) != 0 {
		t.Fatalf("校验失败不得调用引擎: %+v", engine.inputs)
	}
}

// TestProjectSearchServiceInputMapping：全字段入参 → 引擎输入逐字段对齐
// （含 generic 强制段与 Sort 枚举原样传递）。
func TestProjectSearchServiceInputMapping(t *testing.T) {
	engine := &fakeProjectSearchEngine{result: jsonx.Object{}}
	service := NewProjectSearchService(engine, "")
	if _, err := service.Get(map[string]any{
		"q":        "vector db",
		"language": "Go",
		"sort":     "hot",
		"lang":     "en",
		"page":     float64(3),
		"limit":    float64(20),
	}); err != nil {
		t.Fatalf("Get 意外失败: %v", err)
	}
	want := ProjectSearchInput{
		Query: "vector db", Mode: "generic", Language: "Go",
		Scope: "all", Sort: "hot", Page: 3, Limit: 20,
	}
	if engine.inputs[0] != want {
		t.Fatalf("引擎入参 = %+v，应为 %+v", engine.inputs[0], want)
	}
}
