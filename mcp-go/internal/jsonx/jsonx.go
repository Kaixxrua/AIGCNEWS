// Package jsonx 提供 MCP 线格式所需的 JSON 编码边界。
//
// encoding/json 负责请求解码；响应编码集中在紧凑 JSON + Python
// json.dumps(ensure_ascii=False) 兼容语义：有序键对（Object）、不转义
// <、>、&、U+2028/U+2029、float64 按 CPython repr 规则输出（1.0 不塌陷为
// 1，科学计数阈值与指数两位对齐 Python）。
// 任何响应不得在业务包里直接 fmt.Sprintf JSON。
package jsonx

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"
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
//
// float64 刻意保持 encoding/json 原生形态（整值浮点输出 "1"）：请求 id 回显
// 依赖该行为（JSON 整数经 Unmarshal 落入 float64，Python 侧是 int）。Python
// float 语义的值（score/raw_score 等）由产生方显式包 Float 标记类型。
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

// Float 标记"此值在 Python 侧是 float"：json.dumps 用 float.__repr__ 编码，
// 整值浮点输出 "1.0" 而非 Go 的 "1"。Go 请求解码丢失 int/float 区分
// （统一 float64），故该语义只能由值的产生方（fixture 装载器、pg 适配器、
// 工具处理器）显式声明。
type Float float64

// MarshalJSON 见 pythonFloat。
func (f Float) MarshalJSON() ([]byte, error) { return []byte(pythonFloat(float64(f))), nil }

// pythonFloat 复刻 CPython float_repr（json.dumps 对 float 的编码）：
// 最短往返十进制（与 Go strconv 同 digits），定点/科学计数的切换阈值为
// 十进制指数 -4 <= exp < 16；定点至少一位小数（"1.0"），科学计数省略
// 尾 .0 且指数恒带符号、至少两位（"1e+20"、"1e-05"）。
// NaN/Inf 按 json.dumps 默认 allow_nan=True 输出 NaN/Infinity/-Infinity。
func pythonFloat(f float64) string {
	switch {
	case math.IsNaN(f):
		return "NaN"
	case math.IsInf(f, 1):
		return "Infinity"
	case math.IsInf(f, -1):
		return "-Infinity"
	}
	// 'e' 格式给出 d.ddde±xx：mantissa 首位的十进制指数即 Python 的判定量。
	sci := strconv.FormatFloat(f, 'e', -1, 64)
	mantissa, expText, _ := strings.Cut(sci, "e")
	exp, _ := strconv.Atoi(expText)
	negative := strings.HasPrefix(mantissa, "-")
	digits := strings.ReplaceAll(strings.TrimPrefix(mantissa, "-"), ".", "")
	var out string
	if exp >= -4 && exp < 16 {
		switch {
		case exp >= 0 && len(digits) > exp+1:
			out = digits[:exp+1] + "." + digits[exp+1:]
		case exp >= 0:
			out = digits + strings.Repeat("0", exp+1-len(digits)) + ".0"
		default:
			out = "0." + strings.Repeat("0", -exp-1) + digits
		}
	} else {
		mant := digits[:1]
		if len(digits) > 1 {
			mant += "." + digits[1:]
		}
		sign := "+"
		if exp < 0 {
			sign = "-"
			exp = -exp
		}
		out = fmt.Sprintf("%se%s%02d", mant, sign, exp)
	}
	if negative {
		out = "-" + out
	}
	return out
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
