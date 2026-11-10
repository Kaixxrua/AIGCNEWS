package main

import (
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type transferMaterial struct {
	SupportedSystems []string                  `json:"supportedSystems"`
	Name             string                    `json:"name"`
	GameNameZh       string                    `json:"gameNameZh,omitempty"`
	GameNameOriginal string                    `json:"gameNameOriginal,omitempty"`
	PosterURL        string                    `json:"posterUrl,omitempty"`
	PosterSourceURL  string                    `json:"posterSourceUrl,omitempty"`
	PosterKind       string                    `json:"posterKind,omitempty"`
	DetailsVersion   int                       `json:"detailsVersion,omitempty"`
	Title            string                    `json:"title"`
	Repo             string                    `json:"repo"`
	Version          string                    `json:"version"`
	Arch             string                    `json:"arch"`
	Stars            *int                      `json:"stars,omitempty"`
	Description      string                    `json:"descriptionZh"`
	DataNote         string                    `json:"requirements"`
	Upstream         string                    `json:"upstream"`
	Guide            string                    `json:"guide"`
	Filename         string                    `json:"filename"`
	SHA256           string                    `json:"sha256"`
	SourceCommit     string                    `json:"sourceCommit,omitempty"`
	SourceURL        string                    `json:"sourceUrl,omitempty"`
	SourceSHA256     string                    `json:"sourceSha256,omitempty"`
	BundleVersion    int                       `json:"bundleVersion,omitempty"`
	BundleFilename   string                    `json:"bundleFilename,omitempty"`
	BundleSHA256     string                    `json:"bundleSha256,omitempty"`
	BundleSize       int64                     `json:"bundleSize,omitempty"`
	LegacyOutputs    map[string]TransferOutput `json:"legacyOutputs,omitempty"`
	DownloadPath     string                    `json:"downloadPath"`
	LocalDeletedAt   string                    `json:"localDeletedAt,omitempty"`
	Status           string                    `json:"status"`
	Baidu            CloudShare                `json:"baidu"`
	Quark            CloudShare                `json:"quark"`
}

func materials(jobs []TransferJob) []transferMaterial {
	result := []transferMaterial{}
	for _, job := range jobs {
		if job.DownloadPath == "" || job.SHA256 == "" || job.Asset == nil {
			continue
		}
		displayName := job.GameNameZh
		if displayName == "" {
			displayName = job.Name
		}
		title := fmt.Sprintf("%s · Windows %s · %s", displayName, job.Arch, job.Version)
		localPath, _ := transferPayload(job)
		bundleFilename := ""
		if hasSourceBundle(job) {
			bundleFilename = bundleName(job)
		}
		if job.LocalDeletedAt != "" {
			localPath = ""
		}
		result = append(result, transferMaterial{SupportedSystems: append([]string{}, job.SupportedSystems...), Name: job.Name, GameNameZh: job.GameNameZh, GameNameOriginal: job.GameNameOriginal, PosterURL: job.PosterURL, PosterSourceURL: job.PosterSourceURL, PosterKind: job.PosterKind, DetailsVersion: job.DetailsVersion, Title: title, Repo: job.Repo, Version: job.Version, Arch: job.Arch,
			Stars: job.Stars, Description: job.Description, DataNote: job.DataNote, Upstream: "https://github.com/" + job.Repo,
			Guide: job.Guide, Filename: job.Asset.Name, SHA256: job.SHA256, SourceCommit: job.SourceCommit, SourceURL: job.SourceURL, SourceSHA256: job.SourceSHA256, BundleVersion: job.BundleVersion, BundleFilename: bundleFilename, BundleSHA256: job.BundleSHA256, BundleSize: job.BundleSize, LegacyOutputs: job.LegacyOutputs, DownloadPath: localPath, LocalDeletedAt: job.LocalDeletedAt, Status: job.Status,
			Baidu: job.Outputs["baidu"].Share, Quark: job.Outputs["quark"].Share})
	}
	return result
}

func csvCell(value string) string {
	trimmed := strings.TrimLeft(value, " \t\r\n")
	if strings.HasPrefix(trimmed, "=") || strings.HasPrefix(trimmed, "+") || strings.HasPrefix(trimmed, "-") || strings.HasPrefix(trimmed, "@") ||
		strings.HasPrefix(value, "\t") || strings.HasPrefix(value, "\r") || strings.HasPrefix(value, "\n") {
		return "'" + value
	}
	return value
}

func exportTransfers(w http.ResponseWriter, format string, jobs []TransferJob) error {
	rows := materials(jobs)
	extension, contentType := "json", "application/json; charset=utf-8"
	switch format {
	case "json":
	case "csv":
		extension, contentType = "csv", "text/csv; charset=utf-8"
	case "markdown":
		extension, contentType = "md", "text/markdown; charset=utf-8"
	default:
		return errors.New("请选择 JSON、CSV 或 Markdown 导出格式")
	}
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="PortShelf-materials-%s.%s"`, time.Now().Format("20060102"), extension))
	if format == "json" {
		encoder := json.NewEncoder(w)
		encoder.SetIndent("", "  ")
		return encoder.Encode(rows)
	}
	if format == "csv" {
		_, _ = w.Write([]byte{0xef, 0xbb, 0xbf})
		writer := csv.NewWriter(w)
		writer.UseCRLF = true
		_ = writer.Write([]string{"游戏名称", "标题", "GitHub仓库", "版本", "Windows架构", "支持系统（据发布附件）", "Stars", "中文简介", "运行要求",
			"上游项目", "运行指南", "附件", "SHA256", "本地文件", "本地文件清理时间", "任务状态", "百度链接", "百度提取码", "百度有效期", "夸克链接", "夸克提取码", "夸克有效期", "中文游戏名称", "游戏原名", "海报图片", "图片来源", "源码提交", "源码来源", "源码SHA256", "含源码分享包", "分享包SHA256"})
		for _, row := range rows {
			stars := ""
			if row.Stars != nil {
				stars = fmt.Sprint(*row.Stars)
			}
			cells := []string{row.Name, row.Title, row.Repo, row.Version, row.Arch, systemDescription(row.SupportedSystems), stars, row.Description, row.DataNote, row.Upstream, row.Guide,
				row.Filename, row.SHA256, row.DownloadPath, row.LocalDeletedAt, row.Status, row.Baidu.URL, row.Baidu.Code, row.Baidu.ExpiresAt, row.Quark.URL, row.Quark.Code, row.Quark.ExpiresAt, row.GameNameZh, row.GameNameOriginal, row.PosterURL, row.PosterSourceURL, row.SourceCommit, row.SourceURL, row.SourceSHA256, row.BundleFilename, row.BundleSHA256}
			for i := range cells {
				cells[i] = csvCell(cells[i])
			}
			if err := writer.Write(cells); err != nil {
				return err
			}
		}
		writer.Flush()
		return writer.Error()
	}
	escape := strings.NewReplacer("\\", "\\\\", "`", "\\`", "*", "\\*", "_", "\\_", "[", "\\[", "]", "\\]", "<", "&lt;", ">", "&gt;", "#", "\\#", "\r", "", "\n", " ")
	_, _ = fmt.Fprintln(w, "# PortShelf 游戏资料\n\n以下为上游公开发布附件及整理资料，分发时请保留上游要求的许可与来源说明。")
	for _, row := range rows {
		description := row.Description
		if description == "" {
			description = "中文简介待补充"
		}
		_, _ = fmt.Fprintf(w, "\n## %s\n\n%s\n\n- 仓库：%s\n- 版本：%s / Windows %s\n- 上游：%s\n- 运行要求：%s\n- SHA-256：%s\n",
			escape.Replace(row.Name), escape.Replace(description), escape.Replace(row.Repo), escape.Replace(row.Version), escape.Replace(row.Arch),
			row.Upstream, escape.Replace(row.DataNote), row.SHA256)
		if row.GameNameZh != "" {
			_, _ = fmt.Fprintf(w, "- 中文游戏名：%s\n- 游戏原名：%s\n", escape.Replace(row.GameNameZh), escape.Replace(row.GameNameOriginal))
		}
		if row.PosterURL != "" {
			_, _ = fmt.Fprintf(w, "- 游戏图片：%s\n- 图片来源：%s\n", escape.Replace(row.PosterURL), escape.Replace(row.PosterSourceURL))
		}
		if row.BundleVersion == sourceBundleVersion {
			_, _ = fmt.Fprintf(w, "- 分享包（含对应版本源码）：%s\n- 分享包 SHA-256：%s\n- 源码提交：%s\n- 源码来源：%s\n- 源码 SHA-256：%s\n", escape.Replace(row.BundleFilename), row.BundleSHA256, row.SourceCommit, row.SourceURL, row.SourceSHA256)
		}
		_, _ = fmt.Fprintf(w, "- 支持系统（据发布附件）：%s\n", escape.Replace(systemDescription(row.SupportedSystems)))
		if row.LocalDeletedAt != "" {
			_, _ = fmt.Fprintf(w, "- 本地文件：双盘完成后已清理（%s）\n", escape.Replace(row.LocalDeletedAt))
		}
		for _, item := range []struct {
			name  string
			share CloudShare
		}{{"百度网盘", row.Baidu}, {"夸克网盘", row.Quark}} {
			if item.share.URL != "" {
				_, _ = fmt.Fprintf(w, "- %s：%s 提取码：%s 有效期：%s\n", item.name, escape.Replace(item.share.URL),
					escape.Replace(item.share.Code), escape.Replace(item.share.ExpiresAt))
			}
		}
	}
	return nil
}

func (a *App) registerTransferRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/transfers", func(w http.ResponseWriter, r *http.Request) {
		jobs, storeError := a.transfers.snapshot()
		reply(w, http.StatusOK, map[string]any{"jobs": jobs, "downloadDir": a.transfers.downloadDir, "storeError": storeError})
	})
	mux.HandleFunc("POST /api/transfers", func(w http.ResponseWriter, r *http.Request) {
		var body TransferRequest
		if err := decode(w, r, &body); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		added, skipped, err := a.transfers.enqueue(body)
		if err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		reply(w, http.StatusAccepted, map[string]any{"added": added, "skipped": skipped})
	})
	for _, action := range []string{"retry", "cancel"} {
		mux.HandleFunc("POST /api/transfers/{id}/"+action, func(w http.ResponseWriter, r *http.Request) {
			var body struct{}
			if err := decode(w, r, &body); err != nil {
				fail(w, http.StatusBadRequest, err)
				return
			}
			if err := a.transfers.action(r.PathValue("id"), action); err != nil {
				fail(w, http.StatusConflict, err)
				return
			}
			reply(w, http.StatusAccepted, map[string]bool{"ok": true})
		})
	}
	mux.HandleFunc("POST /api/transfers/clear", func(w http.ResponseWriter, r *http.Request) {
		var body struct{}
		if err := decode(w, r, &body); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		m := a.transfers
		m.mu.Lock()
		defer m.mu.Unlock()
		next := []TransferJob{}
		for _, job := range m.jobs {
			if job.ID == m.activeID || job.Status != "done" && job.Status != "cancelled" {
				next = append(next, job)
			}
		}
		removed := len(m.jobs) - len(next)
		if err := m.saveLocked(next); err != nil {
			fail(w, http.StatusInternalServerError, err)
			return
		}
		m.storeError = ""
		reply(w, http.StatusOK, map[string]int{"removed": removed})
	})
	mux.HandleFunc("GET /api/transfers/export", func(w http.ResponseWriter, r *http.Request) {
		jobs, _ := a.transfers.snapshot()
		if err := exportTransfers(w, r.URL.Query().Get("format"), jobs); err != nil {
			fail(w, http.StatusBadRequest, err)
		}
	})
	mux.HandleFunc("POST /api/transfers/open", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			ID string `json:"id"`
		}
		if err := decode(w, r, &body); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		target := a.transfers.downloadDir
		if body.ID != "" {
			job, found := a.transfers.job(body.ID)
			if found && job.LocalDeletedAt != "" {
				fail(w, http.StatusGone, errors.New("本地文件已自动清理，可通过网盘分享链接下载"))
				return
			}
			if !found || job.DownloadPath == "" || !a.transfers.ownedDownloadPath(job.DownloadPath) {
				fail(w, http.StatusNotFound, errors.New("下载文件尚未准备好"))
				return
			}
			target = filepath.Dir(job.DownloadPath)
		}
		if info, err := os.Lstat(target); err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			fail(w, http.StatusNotFound, errors.New("下载目录不存在或不安全"))
			return
		}
		if err := openURL(target); err != nil {
			fail(w, http.StatusInternalServerError, errors.New("无法打开目录，请复制下载路径后在文件管理器中打开"))
			return
		}
		reply(w, http.StatusOK, map[string]bool{"ok": true})
	})
}
