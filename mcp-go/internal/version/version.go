// Package version 解析应用版本，与 backend/app/core/app_version.py 同口径：
// 仓库根 server.json（MCP registry 清单）为唯一真实来源，容器内无该文件时
// 回退到代码内常量。/api/version 与 MCP serverInfo 在任何部署形态下同源。
package version

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
)

// ServerName 与 catalog.py 的 MCP_SERVER_NAME 一致；/api/version 响应体硬编码。
const ServerName = "aigc-radar"

// Fallback 是容器内（无 server.json）的回退版本，必须与
// backend/app/services/mcp/inbound/catalog.py 的 MCP_SERVER_VERSION 逐字同步。
const Fallback = "1.2.0"

// serverJSONPathEnv 允许显式指定 server.json 位置（测试/回放 harness 用）。
const serverJSONPathEnv = "MCP_SERVER_JSON_PATH"

// FromManifest 读取 path 处的 server.json 版本；任何读取/解析/空值问题
// 都回退（ok=false），与 Python 侧 (OSError, ValueError) 宽容语义一致。
func FromManifest(path string) (version string, ok bool) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", false
	}
	var document struct {
		Version string `json:"version"`
	}
	if err := json.Unmarshal(raw, &document); err != nil {
		return "", false
	}
	trimmed := strings.TrimSpace(document.Version)
	if trimmed == "" {
		return "", false
	}
	return trimmed, true
}

// Resolve 等价 resolve_app_version()：先 env 指定的 server.json，
// 再自工作目录向上最多 4 层探测（覆盖 repo 根/mcp-go 子目录运行形态），
// 全部未果时回退代码常量。
func Resolve() string {
	if path, ok := os.LookupEnv(serverJSONPathEnv); ok {
		if v, found := FromManifest(path); found {
			return v
		}
	}
	if cwd, err := os.Getwd(); err == nil {
		dir := cwd
		for range 5 {
			if v, found := FromManifest(filepath.Join(dir, "server.json")); found {
				return v
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}
	return Fallback
}
