package mcpapp

import (
	"encoding/json"
	"strings"
	"testing"
	"unicode/utf16"

	"aigcnews/mcp-go/internal/jsonx"
)

// claudeCodeTextBudget 低于 Claude Code 的 2048 截断线（按 JS 字符串长度，即
// UTF-16 码元计），留出余量给以后的小改动。
const claudeCodeTextBudget = 2000

func utf16Len(s string) int { return len(utf16.Encode([]rune(s))) }

// TestInstructionsPutProjectDiscoveryFirstWithinBudget 钉住说明的顺序与长度：
// 项目发现必须在最前，整段要完整落在客户端保留的范围内。
func TestInstructionsPutProjectDiscoveryFirstWithinBudget(t *testing.T) {
	withUI := uiRPC(t, uiApp(t), "initialize", map[string]any{})["instructions"].(string)
	if withUI != hostInstructions+" "+uiHostInstructions {
		t.Fatal("instructions must be project discovery first, then the UI route")
	}
	if !strings.HasPrefix(withUI, "Project discovery:") || !strings.Contains(withUI, " Frontend UI: ") {
		t.Fatal("instructions lost their section labels")
	}
	if n := utf16Len(withUI); n > claudeCodeTextBudget {
		t.Fatalf("instructions are %d UTF-16 units, budget %d", n, claudeCodeTextBudget)
	}
	if got := New("aigc-radar", "test", nil).instructions(); got != hostInstructions {
		t.Fatal("without the UI library only project discovery instructions are sent")
	}
	for _, text := range []string{hostInstructions, uiHostInstructions} {
		if text != strings.TrimSpace(text) {
			t.Fatal("instruction fragments must not carry edge whitespace")
		}
	}
}

// TestToolDescriptionsFitClaudeCodeBudget 覆盖认证会话 + UI 库的全量工具表。
func TestToolDescriptionsFitClaudeCodeBudget(t *testing.T) {
	var listed struct {
		Tools []struct {
			Name        string `json:"name"`
			Description string `json:"description"`
		} `json:"tools"`
	}
	if err := json.Unmarshal(jsonx.MustMarshalCompact(uiApp(t).toolsList(true)), &listed); err != nil {
		t.Fatal(err)
	}
	if len(listed.Tools) != 15 {
		t.Fatalf("expected 15 tools, got %d", len(listed.Tools))
	}
	for _, tool := range listed.Tools {
		if n := utf16Len(tool.Description); n == 0 || n > claudeCodeTextBudget {
			t.Errorf("%s description is %d UTF-16 units, budget %d", tool.Name, n, claudeCodeTextBudget)
		}
	}
}
