package main

import (
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
	}
	return false
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
		return
	}
	item.GameNameZh = cleanGameName(item.GameNameZh, true)
	item.GameNameOriginal = cleanGameName(item.GameNameOriginal, false)
	if item.Status != "ready" || (item.PosterKind != "cover" && item.PosterKind != "screenshot") ||
		!validGamePoster(item.Repo, item.PosterURL) || !validPosterSource(item.Repo, item.PosterSourceURL) {
		item.PosterURL, item.PosterSourceURL, item.PosterKind = "", "", ""
	}
}
