// Package jsonx 提供 MCP 线格式所需的 JSON 编码边界。
//
// encoding/json 负责请求解码；响应编码暂时使用紧凑 JSON，但集中在本包，
// PR 1.4/Phase 2 将在这里补齐 Python json.dumps 的键序与浮点 repr 规则。
// 任何响应不得在业务包里直接 fmt.Sprintf JSON。
package jsonx

import (
	"bytes"
	"encoding/json"
	"fmt"
)

// Pair is one ordered JSON object member.
type Pair struct {
	Key   string
	Value any
}

// Object preserves member order while remaining usable as an encoding/json value.
type Object []Pair

func (o Object) MarshalJSON() ([]byte, error) {
	var buf bytes.Buffer
	buf.WriteByte('{')
	for i, pair := range o {
		if i > 0 {
			buf.WriteByte(',')
		}
		key, err := MarshalCompact(pair.Key)
		if err != nil {
			return nil, err
		}
		value, err := MarshalCompact(pair.Value)
		if err != nil {
			return nil, err
		}
		buf.Write(key)
		buf.WriteByte(':')
		buf.Write(value)
	}
	buf.WriteByte('}')
	return buf.Bytes(), nil
}

// MarshalCompact 编码 JSON，关闭 encoding/json 默认 HTML 转义，保持 Python
// ensure_ascii=False 对 <、>、&、U+2028/U+2029 的可见字符语义。
func MarshalCompact(value any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "")
	if err := enc.Encode(value); err != nil {
		return nil, err
	}
	out := bytes.TrimSuffix(buf.Bytes(), []byte{'\n'})
	// encoding/json 即使 SetEscapeHTML(false) 仍强制转义 U+2028/U+2029；
	// Python ensure_ascii=False 不转义，线格式必须还原为 UTF-8 字节。
	escaped2028 := []byte{'\\', 'u', '2', '0', '2', '8'}
	escaped2029 := []byte{'\\', 'u', '2', '0', '2', '9'}
	out = bytes.ReplaceAll(out, escaped2028, []byte{0xe2, 0x80, 0xa8})
	out = bytes.ReplaceAll(out, escaped2029, []byte{0xe2, 0x80, 0xa9})
	return out, nil
}

// MustMarshalCompact 只用于静态/已知合法响应；编码失败表示程序契约错误，
// 以 panic 暴露，而不是发出半截 JSON。外部输入仍必须使用 MarshalCompact。
func MustMarshalCompact(value any) []byte {
	out, err := MarshalCompact(value)
	if err != nil {
		panic(fmt.Sprintf("jsonx: marshal failed: %v", err))
	}
	return out
}
