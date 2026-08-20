package jsonx

// decode_test.go 钉住 DecodeOrdered 的保序/保字面量语义：回放 fixture
// 经它装载后重编码必须逐字节还原（tools.jsonl 第 17 行门禁的前置件）。

import (
	"encoding/json"
	"testing"
)

// 逐字取自 backend/tests/parity/corpus/fixtures.json 的
// project_search_results.generic（紧凑形态；盘上为 indent=2，解码语义相同）。
const genericFixtureJSON = `{"items":[{"id":"repo-9","full_name":"acme/static-site-gen","url":"https://github.com/acme/static-site-gen","description":"Prompt 工作台","description_zh":"Prompt 工作台","description_en":"A workbench for prompts","category_slug":"prompt-engineering","category_name":"提示工程","category_name_zh":"提示工程","category_name_en":"Prompt Engineering","subcategory_slug":null,"subcategory_name":null,"subcategory_name_zh":null,"subcategory_name_en":null,"tags":[],"tags_zh":[],"tags_en":[],"topics":["prompts"],"language":"TypeScript","stars":500,"forks":12,"pushed_at":"2026-08-01T00:00:00+00:00","score":0.5,"result_origin":"github_api_fallback"}],"total":1,"local_total":0,"page":1,"limit":10,"scope":"all","sort":"stars","fallback_used":true,"result_origin":"github_api_fallback","fallback_policy":"local_first_github_only_when_local_zero"}`

// 保序解码后经 MarshalCompact 必须逐字节还原 fixture（键序、数字字面量、
// null、空数组全保真）。
func TestDecodeOrderedFixtureRoundTrip(t *testing.T) {
	value, err := DecodeOrdered([]byte(genericFixtureJSON))
	if err != nil {
		t.Fatalf("DecodeOrdered 失败: %v", err)
	}
	object, ok := value.(Object)
	if !ok {
		t.Fatalf("顶层类型 = %T，应为 Object", value)
	}
	if got := string(MustMarshalCompact(object)); got != genericFixtureJSON {
		t.Fatalf("往返编码字节漂移:\ngot  %s\nwant %s", got, genericFixtureJSON)
	}
}

// 类型映射：object→Object（键序）、array→非 nil []any、number→
// json.Number 原字面量、null→nil。
func TestDecodeOrderedTypesAndLiterals(t *testing.T) {
	value, err := DecodeOrdered([]byte(
		`{"list":[1,0.5,"x",true,null,{"nested":[]},[2.50]],"empty_obj":{},"empty_arr":[],"big":1000000000000000,"exp":1e3,"neg":-0}`))
	if err != nil {
		t.Fatalf("DecodeOrdered 失败: %v", err)
	}
	object := value.(Object)
	if len(object) != 6 ||
		object[0].Key != "list" || object[1].Key != "empty_obj" ||
		object[2].Key != "empty_arr" || object[3].Key != "big" ||
		object[4].Key != "exp" || object[5].Key != "neg" {
		t.Fatalf("顶层键序/键数异常: %+v", object)
	}

	list := object[0].Value.([]any)
	if len(list) != 7 {
		t.Fatalf("list 长度 = %d", len(list))
	}
	if n, ok := list[0].(json.Number); !ok || n.String() != "1" {
		t.Fatalf("list[0] = %#v，应为 json.Number(1)", list[0])
	}
	if n, ok := list[1].(json.Number); !ok || n.String() != "0.5" {
		t.Fatalf("list[1] = %#v，应为 json.Number(0.5)", list[1])
	}
	if s, ok := list[2].(string); !ok || s != "x" {
		t.Fatalf("list[2] = %#v", list[2])
	}
	if b, ok := list[3].(bool); !ok || !b {
		t.Fatalf("list[3] = %#v", list[3])
	}
	if list[4] != nil {
		t.Fatalf("list[4] = %#v，应为 nil", list[4])
	}
	nested, ok := list[5].(Object)
	if !ok || len(nested) != 1 || nested[0].Key != "nested" {
		t.Fatalf("嵌套 object 异常: %#v", list[5])
	}
	if arr, ok := nested[0].Value.([]any); !ok || arr == nil || len(arr) != 0 {
		t.Fatalf("嵌套空数组 = %#v，应为非 nil 空 []any", nested[0].Value)
	}
	if arr, ok := list[6].([]any); !ok || len(arr) != 1 {
		t.Fatalf("list[6] = %#v", list[6])
	} else if n, ok := arr[0].(json.Number); !ok || n.String() != "2.50" {
		t.Fatalf("小数原字面量丢失: %#v", arr[0])
	}

	if emptyObj, ok := object[1].Value.(Object); !ok || emptyObj == nil || len(emptyObj) != 0 {
		t.Fatalf("empty_obj = %#v，应为非 nil 空 Object", object[1].Value)
	}
	if emptyArr, ok := object[2].Value.([]any); !ok || emptyArr == nil || len(emptyArr) != 0 {
		t.Fatalf("empty_arr = %#v，应为非 nil 空 []any", object[2].Value)
	}
	if n := object[3].Value.(json.Number); n.String() != "1000000000000000" {
		t.Fatalf("大整数字面量 = %q", n)
	}
	if n := object[4].Value.(json.Number); n.String() != "1e3" {
		t.Fatalf("指数字面量 = %q", n)
	}
	if n := object[5].Value.(json.Number); n.String() != "-0" {
		t.Fatalf("负零字面量 = %q", n)
	}

	// 空数组/空对象编码分别为 [] 与 {}（null 只在显式 null 处出现）。
	if got := string(MustMarshalCompact(object)); got !=
		`{"list":[1,0.5,"x",true,null,{"nested":[]},[2.50]],"empty_obj":{},"empty_arr":[],"big":1000000000000000,"exp":1e3,"neg":-0}` {
		t.Fatalf("重编码漂移: %s", got)
	}
}

// 顶层可以是任意 JSON 值；空数组解码为非 nil 切片（编码 [] 而非 null）。
func TestDecodeOrderedTopLevelValues(t *testing.T) {
	cases := []struct {
		in   string
		want any
	}{
		{`null`, nil},
		{`true`, true},
		{`"s"`, "s"},
		{`123`, json.Number("123")},
	}
	for _, tc := range cases {
		got, err := DecodeOrdered([]byte(tc.in))
		if err != nil {
			t.Fatalf("DecodeOrdered(%q) 失败: %v", tc.in, err)
		}
		if got != tc.want {
			t.Fatalf("DecodeOrdered(%q) = %#v，应为 %#v", tc.in, got, tc.want)
		}
	}

	got, err := DecodeOrdered([]byte(` [ ] `))
	if err != nil {
		t.Fatalf("DecodeOrdered 空数组失败: %v", err)
	}
	arr, ok := got.([]any)
	if !ok || arr == nil || len(arr) != 0 {
		t.Fatalf("空数组 = %#v，应为非 nil 空 []any", got)
	}
	if string(MustMarshalCompact(arr)) != "[]" {
		t.Fatalf("空数组编码应为 []，got %s", MustMarshalCompact(arr))
	}
}

// 尾随垃圾与语法错误一律报错（对齐 Python json.loads）。
func TestDecodeOrderedRejectsGarbage(t *testing.T) {
	for _, in := range []string{
		"",        // 空输入
		"   ",     // 纯空白
		`{} {}`,   // 第二个顶层值
		`{} x`,    // 尾随垃圾
		`[1] ,`,   // 尾随逗号
		`{"a":}`,  // 缺值
		`{"a":1`,  // 未闭合
		`[1 2]`,   // 缺逗号
		`{"a":1]`, // 错位分隔符
		`nul`,     // 非法字面量
	} {
		if value, err := DecodeOrdered([]byte(in)); err == nil {
			t.Fatalf("DecodeOrdered(%q) 意外通过: %#v", in, value)
		}
	}
}
