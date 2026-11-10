package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode"
)

func newDownloadClient() *http.Client {
	return &http.Client{
		Transport: &http.Transport{Proxy: http.ProxyFromEnvironment, DialContext: (&net.Dialer{Timeout: 15 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
			ForceAttemptHTTP2: true, MaxIdleConns: 4, IdleConnTimeout: 30 * time.Second, TLSHandshakeTimeout: 15 * time.Second, ResponseHeaderTimeout: 30 * time.Second},
		CheckRedirect: func(request *http.Request, via []*http.Request) error {
			if len(via) >= 5 || !(validDownloadTarget(request.URL) || validSourceTarget(request.URL)) {
				return errors.New("GitHub 下载重定向地址不受支持")
			}
			request.Header.Del("Authorization")
			request.Header.Del("Cookie")
			return nil
		},
	}
}

func validDownloadTarget(target *url.URL) bool {
	if target == nil || target.Scheme != "https" || target.User != nil || target.Port() != "" || target.Fragment != "" {
		return false
	}
	switch target.Host {
	case "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com":
		return true
	}
	return false
}

func validDownloadName(name string) bool {
	if name == "" || len(name) > 200 || name == "." || name == ".." || strings.TrimSpace(name) != name ||
		strings.HasSuffix(name, ".") || strings.ContainsAny(name, "\\/:*?\"<>|") {
		return false
	}
	for _, char := range name {
		if unicode.IsControl(char) {
			return false
		}
	}
	stem := strings.ToUpper(strings.SplitN(name, ".", 2)[0])
	switch stem {
	case "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
		"LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9":
		return false
	}
	return true
}

func transferRemoteName(job TransferJob) string {
	if hasSourceBundle(job) {
		return bundleName(job)
	}
	prefix := strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_' || r == '.' {
			return r
		}
		return '_'
	}, job.Repo+"-"+job.Version)
	if len(prefix) > 70 {
		prefix = prefix[:70]
	}
	name := job.Asset.Name
	if len(name) > 110 {
		extension := filepath.Ext(name)
		name = strings.TrimSuffix(name, extension)
		runes := []rune(name)
		for len(string(runes)) > 90 {
			runes = runes[:len(runes)-1]
		}
		name = string(runes) + extension
	}
	return prefix + "-" + name
}

func validCloudShare(provider, raw string) bool {
	target, err := url.Parse(raw)
	if err != nil || target.Scheme != "https" || target.User != nil || target.Port() != "" || target.Fragment != "" {
		return false
	}
	host := "pan.baidu.com"
	if provider == "quark" {
		host = "pan.quark.cn"
	} else if provider != "baidu" {
		return false
	}
	return target.Host == host && strings.HasPrefix(target.Path, "/s/") && len(target.Path) > 3 && !strings.ContainsAny(target.Path[3:], "/\\\x00\r\n")
}

func usableCloudShare(provider string, share CloudShare) bool {
	if !validCloudShare(provider, share.URL) {
		return false
	}
	if share.ExpiresAt == "" {
		return true
	}
	expires, err := time.Parse(time.RFC3339, share.ExpiresAt)
	return err == nil && expires.After(time.Now().Add(time.Minute))
}

type countingDownload struct {
	writer   io.Writer
	progress UploadProgress
	done     int64
	total    int64
	ctx      context.Context
}

func (w *countingDownload) Write(data []byte) (int, error) {
	if err := w.ctx.Err(); err != nil {
		return 0, err
	}
	n, err := w.writer.Write(data)
	w.done += int64(n)
	w.progress(w.done, w.total)
	return n, err
}

func (m *transferManager) verifyLocal(ctx context.Context, job TransferJob) bool {
	if job.Asset == nil || job.SHA256 == "" || !m.ownedDownloadPath(job.DownloadPath) {
		return false
	}
	root, err := os.OpenRoot(m.downloadDir)
	if err != nil {
		return false
	}
	defer root.Close()
	relative, _ := filepath.Rel(m.downloadDir, job.DownloadPath)
	info, err := root.Lstat(relative)
	if err != nil || !info.Mode().IsRegular() || info.Size() != job.Asset.Size {
		return false
	}
	file, err := root.Open(relative)
	if err != nil {
		return false
	}
	defer file.Close()
	hash := sha256.New()
	writer := &countingDownload{writer: hash, ctx: ctx, progress: func(int64, int64) {}}
	_, err = io.Copy(writer, io.LimitReader(file, job.Asset.Size+1))
	return err == nil && hex.EncodeToString(hash.Sum(nil)) == job.SHA256
}

func (m *transferManager) download(ctx context.Context, job TransferJob, progress UploadProgress) (string, string, error) {
	asset := job.Asset
	if asset == nil || !officialReleaseURL(asset.URL, job.Repo, true) || !validDownloadName(asset.Name) || asset.Size <= 0 || asset.Size > maxTransferBytes {
		return "", "", errors.New("下载附件无效或超过单文件 8 GiB 上限")
	}
	if m.verifyLocal(ctx, job) {
		progress(asset.Size, asset.Size)
		return job.DownloadPath, job.SHA256, nil
	}
	if ctx.Err() != nil {
		return "", "", errors.New("下载已停止")
	}
	root, err := os.OpenRoot(m.downloadDir)
	if err != nil {
		return "", "", errors.New("无法访问下载目录")
	}
	defer root.Close()
	if err := root.Mkdir(job.ID, 0700); err != nil && !errors.Is(err, os.ErrExist) {
		return "", "", errors.New("无法创建游戏下载目录")
	}
	info, err := root.Lstat(job.ID)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", "", errors.New("游戏下载目录不安全")
	}
	directory, err := root.OpenRoot(job.ID)
	if err != nil {
		return "", "", errors.New("无法打开游戏下载目录")
	}
	defer directory.Close()
	// Recover a crash between the final rename and the task checkpoint. An
	// upstream digest verifies an orphaned final file; without one, compare it
	// with a fresh download before accepting it. Never replace an existing file.
	targetPath := filepath.Join(m.downloadDir, job.ID, asset.Name)
	existingComplete := false
	if info, err := directory.Lstat(asset.Name); err == nil {
		if !info.Mode().IsRegular() || info.Size() != asset.Size {
			return "", "", errors.New("已有同名文件但校验不匹配，请先取消此任务再新建任务，原文件会保留")
		}
		existingComplete = true
		candidate := job
		candidate.DownloadPath, candidate.SHA256 = targetPath, ""
		if job.DownloadPath == targetPath {
			candidate.SHA256 = job.SHA256
		}
		if candidate.SHA256 == "" && strings.HasPrefix(asset.Digest, "sha256:") {
			candidate.SHA256 = strings.ToLower(asset.Digest[7:])
		}
		if candidate.SHA256 != "" {
			if !m.verifyLocal(ctx, candidate) {
				return "", "", errors.New("已有同名文件但校验不匹配，请先取消此任务再新建任务，原文件会保留")
			}
			progress(asset.Size, asset.Size)
			return targetPath, candidate.SHA256, nil
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", "", errors.New("无法核对已有下载文件")
	}
	partialName := asset.Name + ".part"
	if info, err := directory.Lstat(partialName); err == nil {
		if !info.Mode().IsRegular() {
			return "", "", errors.New("临时下载文件不安全")
		}
		if err := directory.Remove(partialName); err != nil {
			return "", "", errors.New("无法重置未完成的临时下载")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", "", errors.New("无法核对临时下载文件")
	}
	file, err := directory.OpenFile(partialName, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return "", "", errors.New("无法创建下载文件，请检查磁盘空间和权限")
	}
	defer file.Close()
	downloadCtx, cancel := context.WithTimeout(ctx, 2*time.Hour)
	defer cancel()
	request, err := http.NewRequestWithContext(downloadCtx, http.MethodGet, asset.URL, nil)
	if err != nil {
		return "", "", errors.New("下载地址无效")
	}
	request.Header.Set("User-Agent", "PortShelf/"+version)
	request.Header.Set("Accept-Encoding", "identity")
	// Public release downloads never receive the user's GitHub or cloud token.
	response, err := m.client.Do(request)
	if err != nil {
		if ctx.Err() != nil {
			return "", "", errors.New("下载已停止")
		}
		return "", "", errors.New("连接 GitHub 下载服务器失败，请检查网络后重试")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return "", "", fmt.Errorf("GitHub 下载返回 HTTP %d，请稍后重试", response.StatusCode)
	}
	if response.ContentLength >= 0 && response.ContentLength != asset.Size {
		return "", "", errors.New("下载文件大小与 GitHub 发布资料不符，请重新核对发布版本")
	}
	hash := sha256.New()
	writer := &countingDownload{writer: io.MultiWriter(file, hash), progress: progress, total: asset.Size, ctx: downloadCtx}
	written, err := io.Copy(writer, io.LimitReader(response.Body, asset.Size+1))
	if err != nil || written != asset.Size {
		if ctx.Err() != nil {
			return "", "", errors.New("下载已停止，点击继续可重新下载")
		}
		return "", "", errors.New("下载未完整结束，请检查网络和磁盘空间后重试")
	}
	digest := hex.EncodeToString(hash.Sum(nil))
	if asset.Digest != "" && (!strings.HasPrefix(asset.Digest, "sha256:") || !strings.EqualFold(asset.Digest[7:], digest)) {
		_ = file.Close()
		_ = directory.Remove(partialName)
		return "", "", errors.New("下载文件未通过上游 SHA-256 校验，已删除临时文件")
	}
	if err := file.Sync(); err != nil {
		return "", "", errors.New("无法写入完整下载文件，请检查磁盘")
	}
	if err := file.Close(); err != nil {
		return "", "", errors.New("关闭下载文件失败")
	}
	if existingComplete {
		candidate := job
		candidate.DownloadPath, candidate.SHA256 = targetPath, digest
		matches := m.verifyLocal(ctx, candidate)
		_ = directory.Remove(partialName)
		if !matches {
			return "", "", errors.New("已有同名文件与上游不一致，请先取消此任务再新建任务，原文件会保留")
		}
		return targetPath, digest, nil
	}
	if err := directory.Rename(partialName, asset.Name); err != nil {
		return "", "", errors.New("无法保存已完成的下载")
	}
	return targetPath, digest, nil
}
