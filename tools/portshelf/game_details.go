package main

import (
	"net"
	"net/url"
	"path"
	"strings"
	"unicode"
	"unicode/utf8"
)

const gameDetailsVersion = 1

func readyGameDetails(item Description) bool {
	return readyDescription(item) && item.DetailsVersion == gameDetailsVersion
}

func needsPosterGeneration(item Description) bool {
	return readyGameDetails(item) && item.GameNameOriginal != "" && item.PosterURL == "" &&
		(item.PosterSearchVersion == 0 || item.PosterRetryAfter <= 0)
}

func cleanGameName(value string, chinese bool) string {
	value = strings.TrimSpace(value)
	if value == "" || utf8.RuneCountInString(value) > 160 {
		return ""
	}
	for _, char := range value {
		if unicode.IsControl(char) {
			return ""
		}
	}
	if chinese && !validChineseDescription(value) {
		return ""
	}
	switch value {
	case "未知", "不确定", "待确认", "暂无", "无", "中文名待确认":
		return ""
	}
	return value
}

func gameImageURL(raw string) *url.URL {
	if len(raw) > 2048 || strings.TrimSpace(raw) != raw || strings.ContainsAny(raw, "\\\r\n\t") {
		return nil
	}
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.User != nil || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" ||
		u.Opaque != "" || u.Host == "" || strings.Contains(u.Host, ":") || path.Clean(u.Path) != u.Path || strings.Contains(u.Path, "\\") {
		return nil
	}
	return u
}

// Images are passive public resources from bounded upstream origins. Neither
// model text nor an imported local cache may introduce arbitrary image hosts.
func validGamePoster(repo, raw string) bool {
	u := gameImageURL(raw)
	if u == nil {
		return false
	}
	extension := strings.ToLower(path.Ext(u.Path))
	image := extension == ".png" || extension == ".jpg" || extension == ".jpeg" || extension == ".webp" || extension == ".gif"
	switch strings.ToLower(u.Host) {
	case "raw.githubusercontent.com":
		prefix := "/" + strings.ToLower(repo) + "/"
		return image && strings.HasPrefix(strings.ToLower(u.Path), prefix) && len(strings.Split(strings.TrimPrefix(strings.ToLower(u.Path), prefix), "/")) >= 2
	case "user-images.githubusercontent.com":
		return image && len(strings.Split(strings.Trim(u.Path, "/"), "/")) >= 2
	case "github.com":
		const prefix = "/user-attachments/assets/"
		id := strings.TrimPrefix(u.Path, prefix)
		if !strings.HasPrefix(u.Path, prefix) || len(id) < 8 || len(id) > 100 {
			return false
		}
		for _, char := range id {
			if !(char >= 'a' && char <= 'z' || char >= 'A' && char <= 'Z' || char >= '0' && char <= '9' || char == '-') {
				return false
			}
		}
		return true
	case "upload.wikimedia.org":
		return validWikimediaPosterPath(u.Path)
	case "aigcnews.cn":
		const prefix = "/api/media/site/game-posters/"
		id := strings.TrimSuffix(strings.TrimPrefix(u.Path, prefix), ".jpg")
		if !strings.HasPrefix(u.Path, prefix) || !strings.HasSuffix(u.Path, ".jpg") || len(id) != 64 || u.RawPath != "" {
			return false
		}
		for _, char := range id {
			if !(char >= 'a' && char <= 'f' || char >= '0' && char <= '9') {
				return false
			}
		}
		return true
	}
	return false
}

func validWikimediaPosterPath(value string) bool {
	parts := strings.Split(strings.TrimPrefix(value, "/"), "/")
	if len(parts) < 5 || parts[0] != "wikipedia" || (parts[1] != "en" && parts[1] != "commons") {
		return false
	}
	start, count := 2, 5
	if parts[2] == "thumb" {
		start, count = 3, 7
	}
	if len(parts) != count || len(parts[start]) != 1 || len(parts[start+1]) != 2 {
		return false
	}
	for _, char := range parts[start] + parts[start+1] {
		if !(char >= '0' && char <= '9' || char >= 'a' && char <= 'f') {
			return false
		}
	}
	for _, name := range parts[start+2:] {
		extension := strings.ToLower(path.Ext(name))
		if strings.Contains(strings.ToLower(name), ".svg") || (extension != ".jpg" && extension != ".jpeg" && extension != ".png" && extension != ".webp") {
			return false
		}
	}
	return true
}

func normalizedGameTitle(value string) string {
	value = strings.NewReplacer("_", " ", "’", "'", "‘", "'", "“", "\"", "”", "\"").Replace(value)
	return strings.ToLower(strings.Join(strings.Fields(value), " "))
}

func validWikipediaPosterSource(original, raw string) bool {
	u := gameImageURL(raw)
	if u == nil || u.Host != "en.wikipedia.org" || !strings.HasPrefix(u.Path, "/wiki/") {
		return false
	}
	title := normalizedGameTitle(strings.TrimPrefix(u.Path, "/wiki/"))
	original = normalizedGameTitle(original)
	return len(original) >= 3 && (title == original || title == original+" (video game)")
}

func validGamePosterSource(item Description) bool {
	u := gameImageURL(item.PosterURL)
	if u == nil {
		return false
	}
	if u.Host == "upload.wikimedia.org" {
		return validWikipediaPosterSource(item.GameNameOriginal, item.PosterSourceURL)
	}
	if u.Host == "aigcnews.cn" {
		return validPublicPosterSource(item.PosterSourceURL)
	}
	return validPosterSource(item.Repo, item.PosterSourceURL)
}

// This is an attribution link, never a URL fetched by the local application.
// Only the backend may fetch search results after its DNS/redirect checks.
func validPublicPosterSource(raw string) bool {
	if len(raw) > 2048 || strings.TrimSpace(raw) != raw {
		return false
	}
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.User != nil || u.Opaque != "" || u.Fragment != "" ||
		strings.Contains(u.Host, ":") || u.ForceQuery {
		return false
	}
	cleanPath := strings.TrimSuffix(u.Path, "/")
	if cleanPath == "" {
		cleanPath = "/"
	}
	if path.Clean(u.Path) != cleanPath || strings.Contains(u.Path, "//") {
		return false
	}
	for _, char := range raw {
		if unicode.IsControl(char) || unicode.IsSpace(char) || char == '\\' {
			return false
		}
	}
	for _, char := range u.Path {
		if unicode.IsControl(char) || char == '\\' {
			return false
		}
	}
	host := strings.ToLower(u.Host)
	if !strings.Contains(host, ".") || net.ParseIP(host) != nil || strings.Trim(host, "0123456789.") == "" ||
		host == "metadata.google.internal" || strings.HasSuffix(host, ".localhost") || strings.HasSuffix(host, ".local") ||
		strings.HasSuffix(host, ".internal") || strings.HasSuffix(host, ".lan") || strings.HasSuffix(host, ".") {
		return false
	}
	for _, char := range host {
		if !(char >= 'a' && char <= 'z' || char >= '0' && char <= '9' || char == '.' || char == '-') {
			return false
		}
	}
	return true
}

func validPosterSource(repo, raw string) bool {
	u, err := url.Parse(raw)
	if err != nil || len(raw) > 2048 || u.Scheme != "https" || u.Host != "github.com" || u.User != nil ||
		u.RawQuery != "" || u.ForceQuery || (u.Fragment != "" && u.Fragment != "readme") ||
		strings.ContainsAny(raw, "\\\r\n\t") || path.Clean(u.Path) != u.Path {
		return false
	}
	base := "/" + strings.ToLower(repo)
	return strings.ToLower(u.Path) == base || strings.HasPrefix(strings.ToLower(u.Path), base+"/blob/")
}

func sanitizeGameDetails(item *Description) {
	if item.DetailsVersion != gameDetailsVersion {
		item.DetailsVersion = 0
		item.GameNameZh, item.GameNameOriginal = "", ""
		item.PosterURL, item.PosterSourceURL, item.PosterKind = "", "", ""
		item.PosterStatus, item.PosterRetryAfter = "", 0
		item.PosterSearchVersion = 0
		return
	}
	item.GameNameZh = cleanGameName(item.GameNameZh, true)
	item.GameNameOriginal = cleanGameName(item.GameNameOriginal, false)
	if item.PosterSearchVersion != 1 {
		item.PosterSearchVersion = 0
	}
	if item.PosterStatus != "ready" && item.PosterStatus != "missing" && item.PosterStatus != "unavailable" {
		item.PosterStatus = ""
	}
	if item.PosterRetryAfter < 0 || item.PosterRetryAfter > 86400 {
		item.PosterRetryAfter = 0
	}
	if (item.Status != "ready" && item.Status != "pending" && item.Status != "failed") || (item.PosterKind != "cover" && item.PosterKind != "screenshot") ||
		!validGamePoster(item.Repo, item.PosterURL) || !validGamePosterSource(*item) {
		item.PosterURL, item.PosterSourceURL, item.PosterKind = "", "", ""
		if item.PosterStatus == "ready" {
			item.PosterStatus, item.PosterRetryAfter = "", 0
		}
	} else if item.PosterStatus == "" {
		item.PosterStatus = "ready"
	}
}
