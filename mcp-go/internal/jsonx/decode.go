package jsonx

// decode.go 提供保序 JSON 解码（DecodeOrdered），是回放 fixture 装载的
// 字节级前置件（PR 2.7 search_github_projects 起由 replay 装载器消费）。
//
// 动机：encoding/json 解进 map[string]any 会丢失键序（Go map 迭代序随机），
// 数字统一 float64 化还会泯灭 int/float 的原始字面量区分（fixture 的
// "score": 0.5 与 "stars": 500 必须各自原样穿过解码—投影—编码全链路；
// float64 中转会把 1e3/1.50 之类字面量重排、大整数失精度）。回放门禁逐
// 字节比对响应体，故新增本解码器：
//
//   - object → Object（Pair.Value 递归为 Object/[]any/json.Number/string/
//     bool/nil），键序 = 盘上顺序；
//   - array → 非 nil []any（空数组是 []any{} 不是 nil——null 与 [] 字节
//     不同，MarshalCompact 分别输出 null 与 []）；
//   - number → json.Number（保留原字面量，绝不转 float64）；
//   - 顶层可以是任意 JSON 值；拒绝尾随垃圾（对齐 Python json.loads）；
//     语法错误返回 error。
//
// 已记录近似：同一对象内重复键不去重（Python json.loads 是后者覆盖前者、
// 键位取先现）；fixtures.json 为录制产物，无重复键。
import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
)

// DecodeOrdered 把 data 解码为保序值树（见包注释的类型映射）。
func DecodeOrdered(data []byte) (any, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	value, err := decodeOrderedValue(decoder)
	if err != nil {
		return nil, err
	}
	// json.Decoder 只读一个值；Python json.loads 对尾随垃圾报错，显式对齐。
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		if err == nil {
			return nil, fmt.Errorf("jsonx: trailing data after top-level value")
		}
		return nil, err
	}
	return value, nil
}

// decodeOrderedValue 消费令牌流中的下一个完整 JSON 值（递归下降）。
func decodeOrderedValue(decoder *json.Decoder) (any, error) {
	token, err := decoder.Token()
	if err != nil {
		return nil, err
	}
	delim, isDelim := token.(json.Delim)
	if !isDelim {
		// 标量：string/bool/nil/json.Number（UseNumber 保字面量）。
		return token, nil
	}
	switch delim {
	case '{':
		object := Object{}
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return nil, err
			}
			key, ok := keyToken.(string)
			if !ok {
				return nil, fmt.Errorf("jsonx: object key decoded as %T, want string", keyToken)
			}
			value, err := decodeOrderedValue(decoder)
			if err != nil {
				return nil, err
			}
			object = append(object, Pair{Key: key, Value: value})
		}
		if err := expectClosingDelim(decoder, '}'); err != nil {
			return nil, err
		}
		return object, nil
	case '[':
		// 非 nil 空切片：空数组编码 []，nil 切片编码 null。
		array := make([]any, 0)
		for decoder.More() {
			value, err := decodeOrderedValue(decoder)
			if err != nil {
				return nil, err
			}
			array = append(array, value)
		}
		if err := expectClosingDelim(decoder, ']'); err != nil {
			return nil, err
		}
		return array, nil
	default:
		return nil, fmt.Errorf("jsonx: unexpected delimiter %q", delim)
	}
}

// expectClosingDelim 消费容器的闭合分隔符；json.Decoder 本身保证分隔符
// 配对，此复检仅作防御（错位时 Token 已先行报错，本分支不可达）。
func expectClosingDelim(decoder *json.Decoder, want json.Delim) error {
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	delim, ok := token.(json.Delim)
	if !ok || delim != want {
		return fmt.Errorf("jsonx: closing delimiter = %v, want %q", token, want)
	}
	return nil
}
