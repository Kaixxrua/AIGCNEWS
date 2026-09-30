package postgres

// documents_test.go 的期望值全部由 Python 权威实现现场生成
// （backend.app.repositories.postgres_document_repository._document_search_candidates
// / domain.search_semantics 的 TECHNICAL_TOKEN_RE / normalize_search_query /
// escape_like_literal），逐条对齐，禁止"看着像"手写期望。

import (
	"reflect"
	"testing"
	"time"
)

func TestNormalizeSearchQuery(t *testing.T) {
	cases := map[string]string{
		"agent":                 "agent",
		"  AGENT   Framework  ": "AGENT Framework",
		"什么是 MCP 协议？":           "什么是 MCP 协议?", // NFKC：全角问号 → ASCII
		"":                      "",
		"   ":                   "",
		"ｓｃａｌｉｎｇ":               "scaling", // 全角 ASCII → 半角
	}
	for in, want := range cases {
		if got := normalizeSearchQuery(in); got != want {
			t.Errorf("normalizeSearchQuery(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestEscapeLikeLiteral(t *testing.T) {
	cases := map[string]string{
		"=_%":   "===_=%",
		"a=b":   "a==b",
		"100%":  "100=%",
		"a_b":   "a=_b",
		"==":    "====",
		"%_=":   "=%=_==",
		"plain": "plain",
	}
	for in, want := range cases {
		if got := escapeLikeLiteral.Replace(in); got != want {
			t.Errorf("escapeLikeLiteral(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestTechnicalTokens(t *testing.T) {
	cases := map[string][]string{
		"agent":               {"agent"},
		"scaling law":         {"scaling", "law"},
		"C++":                 {"C++"},
		".NET core":           {".NET", "core"},
		"gpt-4o mini":         {"gpt-4o", "mini"},
		"v0.1.2":              {"v0.1.2"},
		"Qwen3-Next-80B-A3B":  {"Qwen3-Next-80B-A3B"},
		"node.js 与 deno.land": {"node.js", "与", "deno.land"},
		"什么是 MCP 协议?":         {"什么是", "MCP", "协议"},
		"帮我找一些 agent 学习资料":    {"帮我找一些", "agent", "学习资料"},
		"AGENT Framework":     {"AGENT", "Framework"},
		"a":                   {"a"},
		"":                    nil,
	}
	for in, want := range cases {
		if got := technicalTokens(in); !reflect.DeepEqual(got, want) {
			t.Errorf("technicalTokens(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestDocumentSearchCandidates(t *testing.T) {
	cases := map[string][]string{
		// 无意图短语且 ≤48 字符：整串直通。
		"agent":                  {"agent"},
		"scaling law":            {"scaling law"},
		"多模态模型":                  {"多模态模型"},
		"a":                      {"a"},
		"AI":                     {"AI"},
		"ai agent":               {"ai agent"},
		"C++":                    {"C++"},
		".NET core":              {".NET core"},
		"gpt-4o mini":            {"gpt-4o mini"},
		"RAG 教程":                 {"RAG 教程"},
		"学习 python":              {"学习 python"},
		"   AGENT   Framework  ": {"AGENT Framework"},
		"v0.1.2":                 {"v0.1.2"},
		"Qwen3-Next-80B-A3B":     {"Qwen3-Next-80B-A3B"},
		"node.js 与 deno.land":    {"node.js 与 deno.land"},
		"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx": {"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
		// 空查询 → 无候选（仓储短路返回空页）。
		"":    nil,
		"   ": nil,
		// 意图剥离 + 残词停用 + 技术词抽取。
		"帮我找一些 agent 学习资料":   {"帮我找一些 agent 学习资料", "agent"},
		"帮我找 rag":            {"帮我找 rag", "rag"},
		"transformer 架构相关内容": {"transformer 架构相关内容", "transformer 架构", "transformer", "架构"},
		"I want to find me some LLM learning resources": {
			"I want to find me some LLM learning resources", "some LLM", "some", "LLM",
		},
	}
	// 提问式查询（含提问词/时间词）的拆句见 document_intent_test.go 共享向量。
	today := time.Date(2026, 9, 30, 0, 0, 0, 0, time.UTC)
	for in, want := range cases {
		if got := documentSearchCandidates(in, 5, today); !reflect.DeepEqual(got, want) {
			t.Errorf("documentSearchCandidates(%q) = %q, want %q", in, got, want)
		}
	}
}

// 前缀剥离正则的 (?=[A-Za-z0-9]) 前瞻是手工扫描实现，专项钉住：
// 学习/帮我 后随空白或中文时不得剥离。
func TestStripLearningHelpPrefixes(t *testing.T) {
	cases := map[string]string{
		"帮我python":  "python",
		"学习 rag":    "学习 rag", // 前瞻是空白 → 不剥离（Python re 实测）
		" 帮我python": " python",
		"，学习x":      "，x",
		"，，学习x":     "，，x",
		"帮我 python": "帮我 python", // 前瞻是空白 → 不剥离
		"帮我学习":      "帮我学习",      // 前瞻非 ASCII 字母数字 → 不剥离
		"他帮我python": "他帮我python", // 前缀非分隔符 → 不剥离
		"学 习python": "学 习python", // 词不连续 → 不剥离
	}
	for in, want := range cases {
		if got := stripLearningHelpPrefixes(in); got != want {
			t.Errorf("stripLearningHelpPrefixes(%q) = %q, want %q", in, got, want)
		}
	}
}
