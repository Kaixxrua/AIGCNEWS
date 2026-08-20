package mcpapp

// project_search_contract.go 是 search_github_projects（PR 2.7）与
// search_github_ai_projects + aigc-news://projects/library 资源（PR 2.8）
// 共享的跨包契约：校验后输入形态、引擎接口、以及 handler 后处理（Python
// tools.py:_search_project_library 的 items 投影链 + lang/attribution
// 追加）的唯一实现。
//
// 跨包依赖方向（无环）：projectsem ← mcpapp ← projectsearch。
// projectsearch.Engine 实现本文件的 ProjectSearchEngine；internal/postgres
// 的仓储适配器由引擎侧（projectsearch）消费，与本包无直接关系。
//
// Python 锚点（逐字语义）：
//   - backend/app/services/mcp/inbound/tools.py:266-321
//     _search_project_library（generic/ai 双模式共用的后处理薄壳）
//   - backend/app/services/mcp/inbound/attribution.py:12-31
//     mcp_attribution / _base_url（_BRAND_BASE_URL 兜底）
//
// 字节级纪律：
//   - result["items"] = [...] 是「键在则原位覆盖、键无则末尾追加」；
//     lang/attribution 恒末尾追加（fixture 与生产 base 都不含这两键）。
//   - items 元素先经 dict(item) 浅拷贝再过投影链，严禁共享底层数组
//     （enrich/tag 的 append 在容量富余时会原位写）。
//   - 数字字面量原样透传（回放 fixture 经 jsonx.DecodeOrdered 得
//     json.Number；生产引擎自建 jsonx.Object），本函数不做任何数值重排。

import (
	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/projectsem"
)

// ProjectSearchInput 是校验层（pydantic 镜像）产物的引擎侧输入。
// 字段对应 project_discovery.py:search_projects 的形参（经
// _normalize_search_request 之前的原始形态；归一化在引擎内完成）。
//
// 缺省语义（对齐 model_dump 后的恒完整形态）：
//   - Sort 为 "" 即 Python None（未传与显式 null 在 Python 同义，无需区分）；
//     否则恒为六枚举之一（relevance/hot/stars/updated/recent/name）。
//   - Page/Limit 已钳制（page>=1，1<=limit<=20），引擎的 max/min 是防御。
//   - Mode 恒为 "generic" 或 "ai"；generic 时 Category/Subcategory/Scope
//     已被 handler 强制为 ""/""/"all"、ClientIntent 恒 nil（对齐
//     tools.py:271-276 的 generic 短路）。
//   - ClientIntent 非 nil 时对应 Python build_client_project_search_intent
//     的 model_dump（exclude schema_version）九槽位。
type ProjectSearchInput struct {
	Query       string
	Mode        string // "generic" | "ai"
	Language    string
	Category    string
	Subcategory string
	Scope       string
	Sort        string // "" = None
	Page        int
	Limit       int

	ClientIntent *projectsem.ClientIntentFields
}

// ProjectSearchEngine 是 search_projects 服务函数的 Go 边界
// （backend/app/services/project_discovery.py:811-902 的决策树）。
// 生产实现为 projectsearch.Engine；回放实现直接返回 fixtures.json 的
// 保序解码段（jsonx.DecodeOrdered 产物）。
//
// 返回 jsonx.Object：键序即响应字节序（生产 = _assemble_base_response 的
// 20 键基座及其扩展；回放 = fixture 盘上顺序），引擎负责在跨响应边界前
// 落成有序 Object。error 一律为普通 error——校验错误不出本层；引擎内部
// DB/HTTP 失败在 Python 冒泡为通用工具失败（dispatch 折叠
// "Tool execution failed."）。
type ProjectSearchEngine interface {
	SearchProjects(input ProjectSearchInput) (jsonx.Object, error)
}

// finalizeProjectSearchResult 复刻 tools.py:_search_project_library 的
// 返回前处理（304-319 行）：
//
//	result["items"] = [tag(enrich(localize(dict(item), lang), request))
//	                   for item in result.get("items") or []
//	                   if isinstance(item, dict)]
//	result["lang"] = lang
//	result["attribution"] = mcp_attribution(request)
//
// 键序：items 键存在 → 原位覆盖；不存在 → 追加在原 pairs 之后、lang 之前
// （Python dict 赋值语义）。lang/attribution 依次殿后。
//
// 已记录近似（两路径均不可达）：items 值为真值非标量（如 int 5）时 Python
// 抛 TypeError 使整次调用失败；Go 按空列表折叠。字符串真值在 Python 逐
// 字符迭代且字符非 dict 被丢弃 → 与 Go 空列表同字节结果。
func finalizeProjectSearchResult(result jsonx.Object, lang, base string) jsonx.Object {
	items := make([]any, 0)
	if raw := objectValue(result, "items"); pythonTruthy(raw) {
		if list, ok := raw.([]any); ok {
			for _, item := range list {
				object, ok := item.(jsonx.Object)
				if !ok {
					continue // isinstance(item, dict) 过滤：静默丢弃
				}
				// dict(item) 浅拷贝：固定容量防 append 别名。
				copied := append(jsonx.Object{}, object...)
				projected := localizeProjectItem(copied, lang)
				projected = enrichProjectDetailURL(projected, projectSearchAttributionBase(base))
				projected = tagProjectDataSource(projected)
				items = append(items, projected)
			}
		}
	}

	out := make(jsonx.Object, 0, len(result)+3)
	found := false
	for _, pair := range result {
		if pair.Key == "items" {
			pair.Value = items
			found = true
		}
		out = append(out, pair)
	}
	if !found {
		out = append(out, jsonx.Pair{Key: "items", Value: items})
	}
	out = append(out,
		jsonx.Pair{Key: "lang", Value: lang},
		jsonx.Pair{Key: "attribution", Value: "Data provided by AIGC Radar · " + projectSearchAttributionBase(base)},
	)
	return out
}

// projectSearchAttributionBase 复刻 attribution._base_url：
// public_base_url(request)（配置 PUBLIC_BASE_URL rstrip("/")，忽略请求
// 本身）为空时回退品牌站点 _BRAND_BASE_URL。
func projectSearchAttributionBase(base string) string {
	if base != "" {
		return base
	}
	return "https://aigcnews.cn"
}
