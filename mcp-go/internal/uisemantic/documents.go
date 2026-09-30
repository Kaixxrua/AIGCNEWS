// Package uisemantic 是 search_ui_templates / search_ui_icons 的语义召回通道：
// 嵌入式目录的每个模板与图标各一条向量，存在 Milvus 集合
// aigc_ui_catalog_vectors_v1。目录随镜像发布，因此由 mcp-go 自己在启动时
// 增量补齐向量（只 embed 新增或文本变化的条目），检索时按当前目录的指纹
// 复核命中，再与关键词结果做 RRF 融合；任何失败都回落纯关键词结果。
package uisemantic

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"

	"aigcnews/mcp-go/internal/uicatalog"
)

const (
	KindTemplate = "template"
	KindIcon     = "icon"

	// TextVersion 参与指纹：改动下面的拼文本规则时递增，已有向量随之失效重算。
	TextVersion = "ui-semantic-v1"
)

// Document 是一条待索引条目：Text 喂给 embedding，Fingerprint 标识文本版本。
type Document struct {
	ID          string
	Kind        string
	Text        string
	Fingerprint string
}

// VectorID 是 Milvus 主键：同一条目的不同文本版本各占一行，
// 新旧镜像并存或回滚时互不覆盖；检索侧只认当前指纹。
func (d Document) VectorID() string {
	return VectorID(d.ID, d.Fingerprint)
}

func Fingerprint(text string) string {
	sum := sha256.Sum256([]byte(TextVersion + "\n" + text))
	return hex.EncodeToString(sum[:])
}

func VectorID(itemID, fingerprint string) string {
	sum := sha256.Sum256([]byte(itemID + "\x00" + fingerprint))
	return hex.EncodeToString(sum[:])
}

// TemplateDocuments 用双语名称、描述、分类、风格与别名拼出模板的语义文本。
func TemplateDocuments(items []uicatalog.Template) []Document {
	documents := make([]Document, 0, len(items))
	for _, item := range items {
		lines := []string{joinUnique(" / ", item.Name["en"], item.Name["zh"])}
		lines = appendNonEmpty(lines, item.Description["en"], item.Description["zh"])
		tags := []string{item.Category, item.Subcategory, item.Kind}
		tags = append(tags, item.Styles...)
		lines = appendNonEmpty(lines, joinUnique(", ", tags...), joinUnique(", ", item.Aliases...))
		documents = append(documents, newDocument(item.ID, KindTemplate, strings.Join(lines, "\n")))
	}
	return documents
}

// IconDocuments 用图标名（连字符转空格）、别名与分类拼出语义文本；
// 图标元数据只有英文，中文查询靠多语 embedding 跨语言对齐。
func IconDocuments(icons []uicatalog.Icon) []Document {
	documents := make([]Document, 0, len(icons))
	for _, icon := range icons {
		name := strings.ReplaceAll(icon.Display["en"], "-", " ")
		lines := []string{name + " icon"}
		lines = appendNonEmpty(lines, joinUnique(", ", icon.Aliases...), icon.Category)
		documents = append(documents, newDocument(icon.ID, KindIcon, strings.Join(lines, "\n")))
	}
	return documents
}

func newDocument(id, kind, text string) Document {
	return Document{ID: id, Kind: kind, Text: text, Fingerprint: Fingerprint(kind + "\n" + text)}
}

func appendNonEmpty(lines []string, values ...string) []string {
	for _, value := range values {
		if value = strings.TrimSpace(value); value != "" {
			lines = append(lines, value)
		}
	}
	return lines
}

// joinUnique 去空、按不区分大小写去重后保序拼接。
func joinUnique(separator string, values ...string) string {
	seen := map[string]bool{}
	out := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		key := strings.ToLower(value)
		if value == "" || seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, value)
	}
	return strings.Join(out, separator)
}
