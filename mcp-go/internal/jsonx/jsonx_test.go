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
