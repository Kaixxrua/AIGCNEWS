package mcpapp

// adoptions.go 移植 submit_project_adoption 工具（写路径）：
//   - backend/app/services/mcp/contracts.py:250-280
//     SubmitProjectAdoptionInput（pydantic v2 strict + str_strip_whitespace +
//     extra="forbid"；decision/source 为 Literal）
//   - backend/app/services/mcp/inbound/tools.py:439-461
//     _tool_submit_project_adoption（薄：构造 receipt dict →
//     context.adoptions.record → 投影 receipt/stats/attribution）
//   - backend/app/services/project_adoptions.py:36-53
//     ProjectAdoptionService.record（decision 白名单复检、stats 挂接与
//     adoption_rate 复用率）
//
// 认证：application.py:205-209 的匿名短路仅覆盖 search_my_project_favorites，
// 本工具走普通 ToolHandler（匿名可写），attribution 经 publicBaseURL 注入。
//
// 字节级行为要点：
//   - 校验文案逐字复刻 pydantic v2（字段定义序 project_full_name → decision
//     → reason → query → source，extras 殿后按键名排序，多错 "; " 连接）；
//     Literal 字段不经 str_strip_whitespace（已用项目 venv 的 pydantic
//     实测：" adopted " 报 Literal 文案而非去空白后接受）。
//   - created_at 是 str(datetime) 形状（"2026-08-20 12:34:56.789012+00:00"，
//     微秒为 0 时省略小数段），由 postgres 适配器从 RETURNING 的 time.Time
//     格式化后传入（与 favorites 链路的 isoTimestamp "Z" 形态不同，勿混用）。
//   - stats 键序：window_days, window, total（仓储 dict 插入序），随后服务层
//     追加 window_adoption_rate, total_adoption_rate；嵌套 window/total 按
//     SQL 行序保序（jsonx.Object）。两个 rate 是 Python float（round(x,4)
//     恒返 float），经 jsonx.Float 输出（0.0 不塌陷为 0）。
//   - 响应键序：receipt{id, project_full_name, decision, created_at},
//     stats, attribution。
//
// 已记录的近似（与 documents.go/favorites.go 同口径）：
//   - extras 报错按键名排序（Python 按输入序，Go map 无法保留）。
//   - str_strip_whitespace 用 strings.TrimSpace（Python 空白表多 \x1c-\x1f）。
//   - round(x, 4) 用 math.RoundToEven(x*1e4)/1e4 近似 Python 的十进制正确
//     舍入；回执计数为小整数比，tie 情形（如 1/32=0.03125→0.0312）已实测一致。

import (
	"fmt"
	"math"
	"sort"
	"strings"
	"unicode/utf8"

	"aigcnews/mcp-go/internal/jsonx"
)

// AdoptionReceipt 是写入仓储的回执字段（对齐 tools.py:444-450 构造的
// dict；reason/query/source 的缺省填充在入参校验完成，此处恒为完整形态）。
type AdoptionReceipt struct {
	ProjectFullName string
	Decision        string
	Reason          string
	Query           string
	Source          string
}

// AdoptionStats 是仓储 get_project_adoption_stats 的返回形状（未含服务层
// 追加的两个 rate）；Window/Total 按 SQL 行序保序。
type AdoptionStats struct {
	WindowDays int
	Window     jsonx.Object // decision → count
	Total      jsonx.Object // decision → count
}

// RecordedAdoption 是 record_project_adoption 的 RETURNING 行（_COLUMNS 序
// id, project_full_name, decision, reason, query, source, created_at）加上
// 服务层挂接的 stats。CreatedAt 已是 str(datetime) 形状字符串（适配器职责）。
type RecordedAdoption struct {
	ID              int64
	ProjectFullName string
	Decision        string
	Reason          string
	Query           string
	Source          string
	CreatedAt       string
	Stats           AdoptionStats
}

// AdoptionRecorder 是采纳回执的存储边界（生产=Postgres，单测=fake）。
// 一次调用完成 Python service.record 的仓储段：INSERT … RETURNING 后接
// get_project_adoption_stats（since_days 默认 30）的两条聚合查询。
// 无 ctx 形参：Python 语义是 asyncio.to_thread 跑到完。
type AdoptionRecorder interface {
	RecordAdoption(receipt AdoptionReceipt) (RecordedAdoption, error)
}

// AdoptionsService 装配 submit_project_adoption 的校验、写库与响应投影。
type AdoptionsService struct {
	recorder AdoptionRecorder
	// publicBaseURL 仅来自 PUBLIC_BASE_URL 配置（attribution._base_url：
	// 绝不从请求派生 origin），接线时已 TrimRight("/")。
	publicBaseURL string
}

func NewAdoptionsService(recorder AdoptionRecorder, publicBaseURL string) *AdoptionsService {
	return &AdoptionsService{recorder: recorder, publicBaseURL: publicBaseURL}
}

// adoptionDecisions 逐字复刻 ADOPTION_DECISIONS（services/project_adoptions.py:12）。
var adoptionDecisions = []string{"adopted", "reference_only", "declined"}

// adoptionSources 逐字复刻 AdoptionSource Literal（contracts.py:251）。
var adoptionSources = []string{"mcp", "rest", "plugin", "hook"}

// Submit 是 submit_project_adoption 工具处理器（匹配 dispatch.go 的
// ToolHandler；匿名可调用，无身份短路）。
func (s *AdoptionsService) Submit(arguments map[string]any) (any, error) {
	input, err := validateSubmitProjectAdoptionArgs(arguments)
	if err != nil {
		return nil, err
	}
	// ProjectAdoptionService.record 的 decision 白名单复检
	// （project_adoptions.py:37-39）：MCP 路径经 Literal 校验后不可达，
	// 移植以钉住服务层语义；ValueError 在 Python 侧冒泡为通用工具失败，
	// 故此处返回普通 error（dispatch 投射 "Tool execution failed."）。
	if !contains(adoptionDecisions, input.decision) {
		return nil, fmt.Errorf("decision 必须是 ['adopted', 'reference_only', 'declined'] 之一。")
	}
	recorded, err := s.recorder.RecordAdoption(AdoptionReceipt{
		ProjectFullName: input.projectFullName,
		Decision:        input.decision,
		Reason:          input.reason,
		Query:           input.query,
		Source:          input.source,
	})
	if err != nil {
		return nil, err
	}

	// 响应投影逐字对齐 tools.py:452-461 的 dict 插入序；stats 内部键序
	// window_days, window, total + 服务层追加的两个 rate（_with_rate）。
	stats := jsonx.Object{
		{Key: "window_days", Value: recorded.Stats.WindowDays},
		{Key: "window", Value: recorded.Stats.Window},
		{Key: "total", Value: recorded.Stats.Total},
		{Key: "window_adoption_rate", Value: jsonx.Float(adoptionRate(recorded.Stats.Window))},
		{Key: "total_adoption_rate", Value: jsonx.Float(adoptionRate(recorded.Stats.Total))},
	}
	return jsonx.Object{
		{Key: "receipt", Value: jsonx.Object{
			{Key: "id", Value: recorded.ID},
			{Key: "project_full_name", Value: recorded.ProjectFullName},
			{Key: "decision", Value: recorded.Decision},
			{Key: "created_at", Value: recorded.CreatedAt},
		}},
		{Key: "stats", Value: stats},
		{Key: "attribution", Value: "Data provided by AIGC Radar · " + s.attributionBase()},
	}, nil
}

// attributionBase 复刻 attribution._base_url：配置为空回退品牌站点。
func (s *AdoptionsService) attributionBase() string {
	if s.publicBaseURL != "" {
		return s.publicBaseURL
	}
	return "https://aigcnews.cn"
}

// adoptionRate 复刻 adoption_rate：复用率 = adopted / 全部回执，无回执为
// 0.0；round(x, 4) 是 Python 银行家舍入（十进制正确舍入的近似见包注释）。
func adoptionRate(counts jsonx.Object) float64 {
	total := 0
	adopted := 0
	for _, pair := range counts {
		count, ok := pair.Value.(int)
		if !ok {
			continue
		}
		total += count
		if pair.Key == "adopted" {
			adopted = count
		}
	}
	if total <= 0 {
		return 0.0
	}
	return math.RoundToEven(float64(adopted)/float64(total)*1e4) / 1e4
}

// ── 入参校验（pydantic v2 文案逐字复刻） ────────────────────────────────

// submitProjectAdoptionInput 是 SubmitProjectAdoptionInput 的验证结果
// （model_dump 后恒为完整形态：reason/query 缺省 ""，source 缺省 "mcp"）。
type submitProjectAdoptionInput struct {
	projectFullName string
	decision        string
	reason          string
	query           string
	source          string
}

// validateSubmitProjectAdoptionArgs 复刻 SubmitProjectAdoptionInput 的
// pydantic v2 校验。错误顺序：字段定义序（project_full_name → decision →
// reason → query → source），extras 殿后（键名排序）。
func validateSubmitProjectAdoptionArgs(args map[string]any) (submitProjectAdoptionInput, error) {
	input := submitProjectAdoptionInput{source: "mcp"}
	var failures []string

	// project_full_name: StrictStr, min_length=3, max_length=200，必填。
	rawName, present := args["project_full_name"]
	switch {
	case !present:
		failures = append(failures, "project_full_name: Field required")
	default:
		name, ok := rawName.(string)
		if !ok {
			failures = append(failures, "project_full_name: Input should be a valid string")
			break
		}
		name = strings.TrimSpace(name)
		switch length := utf8.RuneCountInString(name); {
		case length < 3:
			failures = append(failures, "project_full_name: String should have at least 3 characters")
		case length > 200:
			failures = append(failures, "project_full_name: String should have at most 200 characters")
		default:
			input.projectFullName = name
		}
	}

	// decision: Literal["adopted","reference_only","declined"]，必填；
	// Literal 不经 strip，非枚举值（含非字符串/null）报 Literal 文案。
	if rawDecision, ok := args["decision"]; !ok {
		failures = append(failures, "decision: Field required")
	} else if decision, ok := rawDecision.(string); !ok || !contains(adoptionDecisions, decision) {
		failures = append(failures, "decision: Input should be 'adopted', 'reference_only' or 'declined'")
	} else {
		input.decision = decision
	}

	// reason / query: StrictStr(default="", max_length=N) + strip（复用同包
	// favoritesStrictString）。
	input.reason = favoritesStrictString(args, "reason", 500, &failures)
	input.query = favoritesStrictString(args, "query", 200, &failures)

	// source: Literal["mcp","rest","plugin","hook"]，默认 "mcp"，不经 strip。
	if rawSource, present := args["source"]; present {
		source, ok := rawSource.(string)
		if !ok || !contains(adoptionSources, source) {
			failures = append(failures, "source: Input should be 'mcp', 'rest', 'plugin' or 'hook'")
		} else {
			input.source = source
		}
	}

	// extra="forbid"：未知键逐一报错（Python 按输入序；Go 按键名排序，
	// 与 documents.go 同一近似口径）。
	known := map[string]bool{
		"project_full_name": true, "decision": true, "reason": true,
		"query": true, "source": true,
	}
	var extras []string
	for key := range args {
		if !known[key] {
			extras = append(extras, key)
		}
	}
	sort.Strings(extras)
	for _, key := range extras {
		failures = append(failures, key+": Extra inputs are not permitted")
	}

	if len(failures) > 0 {
		return submitProjectAdoptionInput{}, ToolInputError{Message: strings.Join(failures, "; ")}
	}
	return input, nil
}
