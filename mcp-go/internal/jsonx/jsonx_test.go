package jsonx

import (
	"bytes"
	"testing"
)

func TestMarshalCompactPythonVisibleUnicode(t *testing.T) {
	got := MustMarshalCompact(map[string]any{
		"text": "<&> 中文  ",
	})
	want := []byte(`{"text":"<&> 中文  "}`)
	if !bytes.Equal(got, want) {
		t.Fatalf("MarshalCompact = %q, want %q", got, want)
	}
}

func TestObjectPreservesMemberOrder(t *testing.T) {
	got := MustMarshalCompact(Object{
		{Key: "jsonrpc", Value: "2.0"},
		{Key: "id", Value: 1},
		{Key: "result", Value: Object{{Key: "ok", Value: true}}},
	})
	want := []byte(`{"jsonrpc":"2.0","id":1,"result":{"ok":true}}`)
	if !bytes.Equal(got, want) {
		t.Fatalf("ordered object = %q, want %q", got, want)
	}
}

func TestMarshalCompactNoWhitespace(t *testing.T) {
	got := MustMarshalCompact(map[string]any{"b": []int{1, 2}, "a": true})
	if bytes.ContainsAny(got, " \n\t\r") {
		t.Fatalf("unexpected whitespace: %q", got)
	}
}

// Float 必须逐字复刻 CPython repr/json.dumps 的浮点编码。
// 期望值来自 CPython repr（与 json.dumps 输出一致）。
func TestFloatPythonRepr(t *testing.T) {
	cases := []struct {
		in   float64
		want string
	}{
		{1.0, "1.0"},
		{0.95, "0.95"},
		{42.5, "42.5"},
		{0.5, "0.5"},
		{-1.0, "-1.0"},
		{3.14, "3.14"},
		{100.0, "100.0"},
		{0.0001, "0.0001"},           // exp=-4 仍定点
		{0.00001, "1e-05"},           // exp=-5 切科学计数，指数两位
		{1e15, "1000000000000000.0"}, // exp=15 仍定点
		{1e16, "1e+16"},              // exp=16 切科学计数
		{1e20, "1e+20"},              // 尾 .0 省略
		{1.5e20, "1.5e+20"},
		{1.5e-20, "1.5e-20"},
		{-2.5e-8, "-2.5e-08"},
		{1234567890123456.0, "1234567890123456.0"},
		{1.2345678901234568e+16, "1.2345678901234568e+16"},
		{2.2250738585072014e-308, "2.2250738585072014e-308"},
	}
	for _, tc := range cases {
		if got := pythonFloat(tc.in); got != tc.want {
			t.Errorf("pythonFloat(%v) = %s, want %s", tc.in, got, tc.want)
		}
	}
}

// Float 经 Object/数组任意深度都要生效；裸 float64 保持 Go 原生
// （请求 id 回显依赖：JSON 整数解码后仍输出整数形态）。
func TestFloatInsideOrderedStructures(t *testing.T) {
	got := MustMarshalCompact(Object{
		{Key: "score", Value: Float(1.0)},
		{Key: "scores", Value: []any{Float(42.5), Float(0.5)}},
		{Key: "id", Value: float64(1)},
	})
	want := `{"score":1.0,"scores":[42.5,0.5],"id":1}`
	if string(got) != want {
		t.Fatalf("got %s, want %s", got, want)
	}
}
