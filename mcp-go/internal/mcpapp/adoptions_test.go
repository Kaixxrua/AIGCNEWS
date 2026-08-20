package mcpapp

// adoptions_test.go 的校验期望值全部由 Python 权威实现现场生成
// （backend/app/services/mcp/contracts.py 的 SubmitProjectAdoptionInput 经
// 项目 venv 的 pydantic v2 model_validate 实测；服务层 adoption_rate 的
// round(x,4) 真值同法取得），逐字对齐。

import (
	"errors"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/jsonx"
)

// fakeAdoptionRecorder 记录收到的回执并返回预定结果。
type fakeAdoptionRecorder struct {
	receipts []AdoptionReceipt
	recorded RecordedAdoption
	err      error
}

func (f *fakeAdoptionRecorder) RecordAdoption(receipt AdoptionReceipt) (RecordedAdoption, error) {
	f.receipts = append(f.receipts, receipt)
	if f.err != nil {
		return RecordedAdoption{}, f.err
	}
	return f.recorded, nil
}

func adoptionValidateErr(t *testing.T, args map[string]any) string {
	t.Helper()
	_, err := validateSubmitProjectAdoptionArgs(args)
	if err == nil {
		t.Fatalf("validateSubmitProjectAdoptionArgs(%v) 意外通过", args)
	}
	inputErr, ok := err.(ToolInputError)
	if !ok {
		t.Fatalf("错误类型 = %T，应为 ToolInputError", err)
	}
	return inputErr.Message
}

// TestValidateSubmitProjectAdoptionArgsErrors 逐字对齐 pydantic v2 实测文案。
func TestValidateSubmitProjectAdoptionArgsErrors(t *testing.T) {
	cases := []struct {
		name string
		args map[string]any
		want string
	}{
		{"全缺失", map[string]any{},
			"project_full_name: Field required; decision: Field required"},
		{"仅缺 project_full_name", map[string]any{"decision": "adopted"},
			"project_full_name: Field required"},
		{"仅缺 decision", map[string]any{"project_full_name": "owner/repo"},
			"decision: Field required"},
		{"名称过短", map[string]any{"project_full_name": "ab", "decision": "adopted"},
			"project_full_name: String should have at least 3 characters"},
		{"空名strip后过短", map[string]any{"project_full_name": "", "decision": ""},
			"project_full_name: String should have at least 3 characters; decision: Input should be 'adopted', 'reference_only' or 'declined'"},
		{"名称超长", map[string]any{"project_full_name": strings.Repeat("x", 201), "decision": "adopted"},
			"project_full_name: String should have at most 200 characters"},
		{"名称非字符串", map[string]any{"project_full_name": float64(123), "decision": "adopted"},
			"project_full_name: Input should be a valid string"},
		{"名称为null", map[string]any{"project_full_name": nil, "decision": "adopted"},
			"project_full_name: Input should be a valid string"},
		{"decision非枚举", map[string]any{"project_full_name": "owner/repo", "decision": "maybe"},
			"decision: Input should be 'adopted', 'reference_only' or 'declined'"},
		{"decision大小写敏感", map[string]any{"project_full_name": "owner/repo", "decision": "ADOPTED"},
			"decision: Input should be 'adopted', 'reference_only' or 'declined'"},
		{"decision带空白不strip", map[string]any{"project_full_name": "owner/repo", "decision": " adopted "},
			"decision: Input should be 'adopted', 'reference_only' or 'declined'"},
		{"decision非字符串", map[string]any{"project_full_name": "owner/repo", "decision": float64(1)},
			"decision: Input should be 'adopted', 'reference_only' or 'declined'"},
		{"source非枚举", map[string]any{"project_full_name": "owner/repo", "decision": "adopted", "source": "http"},
			"source: Input should be 'mcp', 'rest', 'plugin' or 'hook'"},
		{"source非字符串", map[string]any{"project_full_name": "owner/repo", "decision": "adopted", "source": float64(5)},
			"source: Input should be 'mcp', 'rest', 'plugin' or 'hook'"},
		{"reason超长", map[string]any{"project_full_name": "owner/repo", "decision": "adopted", "reason": strings.Repeat("r", 501)},
			"reason: String should have at most 500 characters"},
		{"query超长", map[string]any{"project_full_name": "owner/repo", "decision": "adopted", "query": strings.Repeat("q", 201)},
			"query: String should have at most 200 characters"},
		{"reason与query皆非字符串", map[string]any{"project_full_name": "owner/repo", "decision": "adopted", "reason": float64(1), "query": nil},
			"reason: Input should be a valid string; query: Input should be a valid string"},
		{"extras按键名排序", map[string]any{"project_full_name": "owner/repo", "decision": "adopted", "extra": float64(1), "zz": float64(2)},
			"extra: Extra inputs are not permitted; zz: Extra inputs are not permitted"},
		{"字段错误先于extras", map[string]any{"a": float64(1), "project_full_name": "ab"},
			"project_full_name: String should have at least 3 characters; decision: Field required; a: Extra inputs are not permitted"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := adoptionValidateErr(t, tc.args); got != tc.want {
				t.Fatalf("错误文案 = %q，应为 %q", got, tc.want)
			}
		})
	}
}

// TestValidateSubmitProjectAdoptionArgsOK 覆盖通过路径的 strip 与默认值。
func TestValidateSubmitProjectAdoptionArgsOK(t *testing.T) {
	input, err := validateSubmitProjectAdoptionArgs(map[string]any{
		"project_full_name": "  owner/repo  ",
		"decision":          "adopted",
	})
	if err != nil {
		t.Fatalf("意外失败: %v", err)
	}
	if input.projectFullName != "owner/repo" || input.decision != "adopted" ||
		input.reason != "" || input.query != "" || input.source != "mcp" {
		t.Fatalf("验证结果 = %+v", input)
	}

	input, err = validateSubmitProjectAdoptionArgs(map[string]any{
		"project_full_name": "owner/repo",
		"decision":          "adopted",
		"reason":            "  hi  ",
		"source":            "hook",
	})
	if err != nil {
		t.Fatalf("意外失败: %v", err)
	}
	if input.reason != "hi" || input.source != "hook" {
		t.Fatalf("验证结果 = %+v", input)
	}

	// 长度边界：strip 后恰好 3 / 200 / 500 / 200 均通过。
	input, err = validateSubmitProjectAdoptionArgs(map[string]any{
		"project_full_name": strings.Repeat("x", 200),
		"decision":          "declined",
		"reason":            strings.Repeat("r", 500),
		"query":             strings.Repeat("q", 200),
		"source":            "rest",
	})
	if err != nil {
		t.Fatalf("意外失败: %v", err)
	}
	if utf8Len(input.projectFullName) != 200 || utf8Len(input.reason) != 500 || utf8Len(input.query) != 200 {
		t.Fatalf("边界长度未保留: %+v", input)
	}
	if _, err = validateSubmitProjectAdoptionArgs(map[string]any{
		"project_full_name": " a/b ", "decision": "adopted",
	}); err != nil {
		t.Fatalf("strip 后恰好 3 字符应通过: %v", err)
	}
}

func utf8Len(s string) int { return len([]rune(s)) }

// TestSubmitProjectAdoptionHappyPath 钉住响应键序、created_at str 形状、
// stats 内部键序与 rate 的 float 形态（对比 pythonDumps 全文字节）。
func TestSubmitProjectAdoptionHappyPath(t *testing.T) {
	recorder := &fakeAdoptionRecorder{recorded: RecordedAdoption{
		ID:              7,
		ProjectFullName: "owner/repo",
		Decision:        "adopted",
		Reason:          "fits",
		Query:           "workflow engine",
		Source:          "mcp",
		CreatedAt:       "2026-08-20 12:34:56.789012+00:00",
		Stats: AdoptionStats{
			WindowDays: 30,
			Window: jsonx.Object{
				{Key: "adopted", Value: 1},
				{Key: "declined", Value: 3},
			},
			Total: jsonx.Object{
				{Key: "adopted", Value: 9},
				{Key: "reference_only", Value: 1},
				{Key: "declined", Value: 22},
			},
		},
	}}
	service := NewAdoptionsService(recorder, "https://radar.example.com")

	result, err := service.Submit(map[string]any{
		"project_full_name": " owner/repo ", "decision": "adopted",
		"reason": "fits", "query": "workflow engine",
	})
	if err != nil {
		t.Fatalf("意外失败: %v", err)
	}
	want := `{"receipt": {"id": 7, "project_full_name": "owner/repo", "decision": "adopted", "created_at": "2026-08-20 12:34:56.789012+00:00"}, "stats": {"window_days": 30, "window": {"adopted": 1, "declined": 3}, "total": {"adopted": 9, "reference_only": 1, "declined": 22}, "window_adoption_rate": 0.25, "total_adoption_rate": 0.2812}, "attribution": "Data provided by AIGC Radar · https://radar.example.com"}`
	if got := pythonDumps(result); got != want {
		t.Fatalf("响应字节 = %s\n应为 %s", got, want)
	}
	// 回执字段透传（strip 后的名称）。
	got := recorder.receipts[0]
	if got != (AdoptionReceipt{ProjectFullName: "owner/repo", Decision: "adopted", Reason: "fits", Query: "workflow engine", Source: "mcp"}) {
		t.Fatalf("回执 = %+v", got)
	}
}

// TestSubmitProjectAdoptionDefaults 钉住缺省填充：reason/query → ""、
// source → "mcp"；created_at 微秒为 0 的 str 形状原样透传；空 stats 的
// rate 为 0.0（Python float，不塌陷为 0）；attribution 空配置回退品牌站点。
func TestSubmitProjectAdoptionDefaults(t *testing.T) {
	recorder := &fakeAdoptionRecorder{recorded: RecordedAdoption{
		ID:              1,
		ProjectFullName: "owner/repo",
		Decision:        "declined",
		CreatedAt:       "2026-08-20 12:34:56+00:00",
		Stats: AdoptionStats{
			WindowDays: 30,
			Window:     jsonx.Object{},
			Total:      jsonx.Object{},
		},
	}}
	service := NewAdoptionsService(recorder, "")

	result, err := service.Submit(map[string]any{
		"project_full_name": "owner/repo", "decision": "declined",
	})
	if err != nil {
		t.Fatalf("意外失败: %v", err)
	}
	want := `{"receipt": {"id": 1, "project_full_name": "owner/repo", "decision": "declined", "created_at": "2026-08-20 12:34:56+00:00"}, "stats": {"window_days": 30, "window": {}, "total": {}, "window_adoption_rate": 0.0, "total_adoption_rate": 0.0}, "attribution": "Data provided by AIGC Radar · https://aigcnews.cn"}`
	if got := pythonDumps(result); got != want {
		t.Fatalf("响应字节 = %s\n应为 %s", got, want)
	}
	if got := recorder.receipts[0]; got != (AdoptionReceipt{
		ProjectFullName: "owner/repo", Decision: "declined",
		Reason: "", Query: "", Source: "mcp",
	}) {
		t.Fatalf("回执缺省填充 = %+v", got)
	}
}

// TestAdoptionRateTruth 对齐 adoption_rate 的 Python 实测值（round(x,4)
// 银行家舍入：1/32=0.03125 → 0.0312）。
func TestAdoptionRateTruth(t *testing.T) {
	cases := []struct {
		counts jsonx.Object
		want   string // pythonDumps(jsonx.Float(rate))
	}{
		{jsonx.Object{}, "0.0"},
		{jsonx.Object{{Key: "adopted", Value: 1}, {Key: "declined", Value: 3}}, "0.25"},
		{jsonx.Object{{Key: "reference_only", Value: 2}}, "0.0"},
		{jsonx.Object{{Key: "adopted", Value: 1}, {Key: "declined", Value: 31}}, "0.0312"},
		{jsonx.Object{{Key: "adopted", Value: 3}, {Key: "declined", Value: 5}, {Key: "reference_only", Value: 8}}, "0.1875"},
		{jsonx.Object{{Key: "adopted", Value: 1}}, "1.0"},
	}
	for _, tc := range cases {
		if got := pythonDumps(jsonx.Float(adoptionRate(tc.counts))); got != tc.want {
			t.Fatalf("adoptionRate(%v) = %s，应为 %s", tc.counts, got, tc.want)
		}
	}
}

// TestSubmitProjectAdoptionErrors：校验失败不落库；仓储错误原样冒泡
// （dispatch 投射 "Tool execution failed."）。
func TestSubmitProjectAdoptionErrors(t *testing.T) {
	recorder := &fakeAdoptionRecorder{}
	service := NewAdoptionsService(recorder, "")
	if _, err := service.Submit(map[string]any{"decision": "adopted"}); err == nil {
		t.Fatal("校验失败应返回错误")
	} else if inputErr, ok := err.(ToolInputError); !ok ||
		inputErr.Message != "project_full_name: Field required" {
		t.Fatalf("错误 = %v", err)
	}
	if len(recorder.receipts) != 0 {
		t.Fatalf("校验失败不应落库: %+v", recorder.receipts)
	}

	boom := errors.New("boom")
	recorder.err = boom
	if _, err := service.Submit(map[string]any{
		"project_full_name": "owner/repo", "decision": "adopted",
	}); !errors.Is(err, boom) {
		t.Fatalf("仓储错误应原样冒泡: %v", err)
	}
}
