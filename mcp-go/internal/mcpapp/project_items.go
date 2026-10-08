package mcpapp

// project_items.go 移植项目条目的投影管线（search_my_project_favorites 与
// PR 2.7/2.8 的项目搜索工具共用）：
//   - backend/app/services/project_discovery.py:48-50   _clipped
//   - backend/app/services/project_discovery.py:53-63   _bounded_strings
//   - backend/app/services/project_discovery.py:83-115  public_project_item
//   - backend/app/services/project_discovery.py:118-147 localize_project_item
//   - backend/app/services/mcp/inbound/attribution.py:46-61
//     tag_project_data_source / enrich_project_detail_url
//
// 字节级行为准绳（backend/tests/parity/corpus/tools.jsonl）：
//   - public_project_item 输出 30 键有序（见 publicProjectItem），随后
//     localize（en 时原位替换/删 zh 键）→ enrich（末尾 detail_url）→
//     tag（末尾 data_source）；
//   - stars/forks/daily_star_growth 是 Python int；hot_score 与
//     growth_suspicion_score 恒为 Python float（0 输出 "0.0"，包
//     jsonx.Float）；*_available/is_recommended 是 Python bool；
//   - _clipped 先按 Python str.split() 折叠任意 Unicode 空白（含
//     \x1c-\x1f——Python 的空白表比 Go unicode.IsSpace 多这四个），
//     超长按 rune 截 limit-1、rstrip 后追加 "…"；
//   - _bounded_strings 仅 list/tuple 输入有效，最多 4 条、每条
//     clipped(40)、去重、丢空。
//
// 已记录的近似（语料未覆盖，正常 DB 行不触发）：
//   - str(value) 对非标量（list/dict）的 Python repr 未复刻，Go 侧退化为
//     fmt %v；文本列实际只会出现 string/NULL；
//   - Python int()/float() 接受 "1_0" 下划线形态与 Unicode 数字，
//     Go Atoi/ParseFloat 拒绝——int 强转失败时 Python 会抛错使整次调用
//     500，Go 按 0 折叠（DB 行恒为合法数值）；
//   - Python int 任意精度，Go int64 溢出路径按错误处理。

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"unicode"

	"aigcnews/mcp-go/internal/jsonx"
)

// pythonSpace 复刻 Python str.isspace()/split()/strip() 的空白表：
// unicode.IsSpace 并集 \x1c-\x1f（FS/GS/RS/US，Python 因历史原因计入，
// Unicode White_Space 属性不含）。
func pythonSpace(r rune) bool {
	return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f)
}

// pythonFields 等价 Python str.split()（无参）：按空白游程切分，丢弃空段。
func pythonFields(s string) []string {
	return strings.FieldsFunc(s, pythonSpace)
}

// pythonTrim / pythonTrimRight 等价 Python str.strip()/str.rstrip()（无参）。
func pythonTrim(s string) string {
	return strings.TrimFunc(s, pythonSpace)
}
func pythonTrimRight(s string) string {
	return strings.TrimRightFunc(s, pythonSpace)
}

// pythonTruthy 复刻 Python 真值判定：nil/False/数值 0/""/空容器为假，
// 其余为真（字符串 "0"/"false" 为真）。json.Number 来自回放 fixture 的
// UseNumber 解码，按数值零判定。
func pythonTruthy(value any) bool {
	switch v := value.(type) {
	case nil:
		return false
	case bool:
		return v
	case string:
		return v != ""
	case json.Number:
		f, err := v.Float64()
		return err == nil && f != 0
	case float64:
		return v != 0
	case float32:
		return v != 0
	case int:
		return v != 0
	case int64:
		return v != 0
	case []any:
		return len(v) > 0
	case map[string]any:
		return len(v) > 0
	default:
		return true
	}
}

// orValue 复刻 Python `a or b`：a 为真取 a，否则取 b。
func orValue(primary, fallback any) any {
	if pythonTruthy(primary) {
		return primary
	}
	return fallback
}

// pythonStringify 复刻 str(value)（value 已过 `or ""` 真值折叠后的分支）：
// string 原样；bool → "True"/"False"；json.Number 整值保留字面量、浮点
// 形态按 Python float repr；float64 按 Python float repr（整值浮点
// "7.0"）；int/int64 十进制。非标量退化为 %v（见文件头近似）。
func pythonStringify(value any) string {
	switch v := value.(type) {
	case nil:
		return ""
	case string:
		return v
	case bool:
		if v {
			return "True"
		}
		return "False"
	case json.Number:
		text := v.String()
		if strings.ContainsAny(text, ".eE") {
			if f, err := strconv.ParseFloat(text, 64); err == nil {
				return string(jsonx.MustMarshalCompact(jsonx.Float(f)))
			}
		}
		return text
	case float64:
		return string(jsonx.MustMarshalCompact(jsonx.Float(v)))
	case float32:
		return string(jsonx.MustMarshalCompact(jsonx.Float(float64(v))))
	case int:
		return strconv.Itoa(v)
	case int64:
		return strconv.FormatInt(v, 10)
	default:
		return fmt.Sprintf("%v", v)
	}
}

// pythonIntStrict 复刻 Python int(value)（真值已由调用方保证）：
// bool → 1/0；json.Number 整数直取、含 .eE 按 float 向零截断；
// float64 向零截断（与 Python int(float) 一致）；string strip 后按
// 可选符号十进制解析。其余类型/解析失败返回 ok=false（对应 Python 抛
// TypeError/ValueError）。
func pythonIntStrict(value any) (int, bool) {
	switch v := value.(type) {
	case bool:
		if v {
			return 1, true
		}
		return 0, true
	case json.Number:
		text := v.String()
		if strings.ContainsAny(text, ".eE") {
			f, err := strconv.ParseFloat(text, 64)
			if err != nil {
				return 0, false
			}
			return int(f), true
		}
		n, err := strconv.ParseInt(text, 10, 64)
		if err != nil {
			return 0, false
		}
		return int(n), true
	case float64:
		return int(v), true
	case float32:
		return int(v), true
	case int:
		return v, true
	case int64:
		return int(v), true
	case string:
		n, err := strconv.Atoi(pythonTrim(v))
		if err != nil {
			return 0, false
		}
		return n, true
	default:
		return 0, false
	}
}

// pythonIntOrZero 复刻 int(x or 0)：假值 → 0；真值按 int() 强转，
// 不可强转按 0 折叠（Python 会抛错 500，见文件头近似）。
func pythonIntOrZero(value any) int {
	if !pythonTruthy(value) {
		return 0
	}
	n, ok := pythonIntStrict(value)
	if !ok {
		return 0
	}
	return n
}

// pythonFloatOrZero 复刻 float(x or 0)：假值 → 0；bool → 1.0/0.0；
// json.Number/float64/int 直取；string strip 后 ParseFloat；不可强转
// 按 0 折叠（同 int 的近似口径）。
func pythonFloatOrZero(value any) float64 {
	if !pythonTruthy(value) {
		return 0
	}
	switch v := value.(type) {
	case bool:
		if v {
			return 1
		}
		return 0
	case json.Number:
		f, err := v.Float64()
		if err != nil {
			return 0
		}
		return f
	case float64:
		return v
	case float32:
		return float64(v)
	case int:
		return float64(v)
	case int64:
		return float64(v)
	case string:
		f, err := strconv.ParseFloat(pythonTrim(v), 64)
		if err != nil {
			return 0
		}
		return f
	default:
		return 0
	}
}

// clipped 复刻 _clipped：" ".join(str(value or "").split())；
// 超长按 rune 截 limit-1、rstrip、追加 "…"。None/假值 → ""。
func clipped(value any, limit int) string {
	text := ""
	if pythonTruthy(value) {
		text = pythonStringify(value)
	}
	text = strings.Join(pythonFields(text), " ")
	runes := []rune(text)
	if len(runes) <= limit {
		return text
	}
	return pythonTrimRight(string(runes[:limit-1])) + "…"
}

// boundedStrings 复刻 _bounded_strings（max_items=4）：非 list/tuple
// 输入返回空列表；每条 clipped(40)，丢空、去重（保持先现序）、最多 4 条。
// 返回非 nil 切片：空结果编码为 [] 而非 null。
func boundedStrings(value any) []any {
	var list []any
	switch values := value.(type) {
	case []any:
		list = values
	case []string:
		for _, item := range values {
			list = append(list, item)
		}
	}
	items := make([]any, 0, 4)
	seen := make(map[string]bool, 4)
	for _, raw := range list {
		item := clipped(raw, 40)
		if item != "" && !seen[item] {
			seen[item] = true
			items = append(items, item)
		}
		if len(items) >= 4 {
			break
		}
	}
	return items
}

// publicProjectItem 复刻 public_project_item：30 键有序投影，键序逐字
// 对齐 Python dict 插入序。
func publicProjectItem(row map[string]any) jsonx.Object {
	tagsOrigin := "system"
	if origin, ok := row["tags_origin"].(string); ok && origin == "user" {
		tagsOrigin = "user"
	}
	return jsonx.Object{
		{Key: "id", Value: row["id"]},
		{Key: "full_name", Value: clipped(orValue(row["full_name"], row["title"]), 160)},
		{Key: "url", Value: clipped(row["url"], 500)},
		{Key: "description", Value: clipped(row["description"], 320)},
		{Key: "description_zh", Value: clipped(row["description_zh"], 160)},
		{Key: "description_en", Value: clipped(row["description_en"], 320)},
		{Key: "category_slug", Value: clipped(orValue(row["category_slug"], row["category"]), 64)},
		{Key: "category_name", Value: clipped(orValue(row["category_name_zh"], row["category_name"]), 80)},
		{Key: "category_name_zh", Value: clipped(orValue(row["category_name_zh"], row["category_name"]), 80)},
		{Key: "category_name_en", Value: clipped(row["category_name_en"], 80)},
		{Key: "subcategory_slug", Value: clipped(orValue(row["subcategory_slug"], row["subcategory"]), 64)},
		{Key: "subcategory_name", Value: clipped(orValue(row["subcategory_name_zh"], row["subcategory_name"]), 80)},
		{Key: "subcategory_name_zh", Value: clipped(orValue(row["subcategory_name_zh"], row["subcategory_name"]), 80)},
		{Key: "subcategory_name_en", Value: clipped(row["subcategory_name_en"], 80)},
		{Key: "tags", Value: boundedStrings(row["tags"])},
		{Key: "tags_zh", Value: boundedStrings(row["tags_zh"])},
		{Key: "tags_en", Value: boundedStrings(row["tags_en"])},
		{Key: "tags_origin", Value: tagsOrigin},
		{Key: "topics", Value: boundedStrings(row["topics"])},
		{Key: "language", Value: clipped(row["language"], 64)},
		{Key: "license", Value: clipped(orValue(row["license_spdx_id"], row["license"]), 64)},
		{Key: "stars", Value: pythonIntOrZero(row["stars"])},
		{Key: "forks", Value: pythonIntOrZero(row["forks"])},
		{Key: "pushed_at", Value: row["pushed_at"]},
		{Key: "daily_star_growth", Value: pythonIntOrZero(row["daily_star_growth"])},
		{Key: "daily_growth_available", Value: pythonTruthy(row["daily_growth_available"])},
		{Key: "hot_score", Value: jsonx.Float(pythonFloatOrZero(row["hot_score"]))},
		{Key: "growth_suspicion_score", Value: jsonx.Float(pythonFloatOrZero(row["growth_suspicion_score"]))},
		{Key: "is_recommended", Value: pythonTruthy(row["is_recommended"])},
		{Key: "result_origin", Value: clipped(orValue(row["result_origin"], "aigc_news_local"), 40)},
	}
}

// PublicProjectItem 导出 publicProjectItem：生产检索引擎
// （internal/projectsearch，PR 2.7/2.8）对仓储 normalize 行与 GitHub
// fallback 归一化行做同一 30 键有序投影；本包处理器沿用私有原形。
// 输入是 map（仓储行/归一化行），输出是保序 jsonx.Object。
func PublicProjectItem(row map[string]any) jsonx.Object {
	return publicProjectItem(row)
}

// objectValue 按键取 jsonx.Object 的值（缺键 → nil，对齐 dict.get）。
func objectValue(item jsonx.Object, key string) any {
	for _, pair := range item {
		if pair.Key == key {
			return pair.Value
		}
	}
	return nil
}

// localizeProjectItem 复刻 localize_project_item：lang != "en" 原样返回；
// en 时 description/category_name/subcategory_name 被对应 *_en 值原位替换
// （仅当 en 值 strip 后非空），tags 被 tags_en 替换（仅当 tags_en 是非空
// list，且按 Python list() 语义复制），并删除 description_zh /
// category_name_zh / subcategory_name_zh / tags_zh 四键，其余键原位保序。
func localizeProjectItem(item jsonx.Object, lang string) jsonx.Object {
	if lang != "en" {
		return item
	}
	replacements := map[string]any{}
	for _, pair := range [][2]string{
		{"description", "description_en"},
		{"category_name", "category_name_en"},
		{"subcategory_name", "subcategory_name_en"},
	} {
		if english, ok := objectValue(item, pair[1]).(string); ok && pythonTrim(english) != "" {
			replacements[pair[0]] = english
		}
	}
	if tagsEN, ok := objectValue(item, "tags_en").([]any); ok && len(tagsEN) > 0 {
		replacements["tags"] = append([]any{}, tagsEN...)
	}
	dropped := map[string]bool{
		"description_zh":      true,
		"category_name_zh":    true,
		"subcategory_name_zh": true,
		"tags_zh":             true,
	}
	projected := make(jsonx.Object, 0, len(item))
	for _, pair := range item {
		if dropped[pair.Key] {
			continue
		}
		if replacement, ok := replacements[pair.Key]; ok {
			pair.Value = replacement
		}
		projected = append(projected, pair)
	}
	return projected
}

// enrichProjectDetailURL 复刻 attribution.enrich_project_detail_url：
// full_name strip 后非空 → 末尾追加项目库过滤视图回链（full_name 经
// urllib.parse.quote(safe=”) 编码，即包内 pythonQuote）；否则
// detail_url 为 nil（JSON null）。
func enrichProjectDetailURL(item jsonx.Object, base string) jsonx.Object {
	fullName, _ := objectValue(item, "full_name").(string)
	fullName = pythonTrim(fullName)
	var detailURL any
	if fullName != "" {
		detailURL = base + "/projects?q=" + pythonQuote(fullName) + "&utm_source=mcp&utm_medium=tool"
	}
	return append(item, jsonx.Pair{Key: "detail_url", Value: detailURL})
}

// tagProjectDataSource 复刻 attribution.tag_project_data_source：
// 末尾追加 data_source="aigcnews.cn"（MCP_PROJECT_DATA_SOURCE）。
func tagProjectDataSource(item jsonx.Object) jsonx.Object {
	return append(item, jsonx.Pair{Key: "data_source", Value: "aigcnews.cn"})
}
