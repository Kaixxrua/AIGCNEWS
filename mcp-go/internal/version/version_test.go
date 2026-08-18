package version

import (
	"os"
	"path/filepath"
	"testing"
)

func writeManifest(t *testing.T, dir, body string) string {
	t.Helper()
	path := filepath.Join(dir, "server.json")
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestFromManifest(t *testing.T) {
	dir := t.TempDir()
	path := writeManifest(t, dir, `{"name": "aigc-radar", "version": "1.4.0"}`)
	v, ok := FromManifest(path)
	if !ok || v != "1.4.0" {
		t.Fatalf("FromManifest = %q, %v; want 1.4.0, true", v, ok)
	}
}

func TestFromManifestTolerant(t *testing.T) {
	cases := map[string]string{
		"bad json":       `{oops`,
		"empty version":  `{"version": "  "}`,
		"non-string":     `{"version": 42}`,
		"version absent": `{"name": "x"}`,
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			path := writeManifest(t, t.TempDir(), body)
			if v, ok := FromManifest(path); ok || v != "" {
				t.Errorf("FromManifest = %q, %v; want \"\", false", v, ok)
			}
		})
	}
	if v, ok := FromManifest(filepath.Join(t.TempDir(), "nope.json")); ok || v != "" {
		t.Errorf("missing file: FromManifest = %q, %v; want \"\", false", v, ok)
	}
}

func TestResolvePrefersEnvPath(t *testing.T) {
	dir := t.TempDir()
	path := writeManifest(t, dir, `{"version": "9.9.9"}`)
	t.Setenv("MCP_SERVER_JSON_PATH", path)
	if got := Resolve(); got != "9.9.9" {
		t.Fatalf("Resolve = %q, want 9.9.9", got)
	}
}

// 无 env、工作目录树内无 server.json 时回退常量——容器内形态。
// t.Chdir 换到临时空目录，且该目录向上 4 层仍在 /tmp 系内（无 server.json）。
func TestResolveFallback(t *testing.T) {
	t.Chdir(t.TempDir())
	os.Unsetenv("MCP_SERVER_JSON_PATH") // t.Setenv 之外防御宿主环境
	if got := Resolve(); got != Fallback {
		t.Fatalf("Resolve = %q, want fallback %q", got, Fallback)
	}
}

// Fallback 常量与 server.json / catalog.py 同源漂移会打破语料钉住的
// /api/version 字节——语料对齐测试（probes 包）会先行翻红。
func TestFallbackMatchesServerManifest(t *testing.T) {
	raw, err := os.ReadFile("../../../server.json")
	if err != nil {
		t.Skip("仓库根 server.json 不可读（裁剪构建上下文），跳过")
	}
	v, ok := FromManifest("../../../server.json")
	if !ok {
		t.Fatalf("仓库根 server.json 解析失败: %s", raw)
	}
	if v != Fallback {
		t.Fatalf("Fallback = %q 与 server.json version = %q 漂移", Fallback, v)
	}
}
