package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

func bothCloudCopiesReady(job TransferJob) bool {
	if len(job.Providers) != 2 || !(job.Providers[0] == "baidu" && job.Providers[1] == "quark" || job.Providers[0] == "quark" && job.Providers[1] == "baidu") {
		return false
	}
	for _, id := range []string{"baidu", "quark"} {
		output := job.Outputs[id]
		if output.Status != "done" || output.File.ID == "" || output.Session == "" || output.Error != "" || output.NeedsAttention || !usableCloudShare(id, output.Share) {
			return false
		}
	}
	return true
}

func cleanupEligible(job TransferJob) bool {
	return job.LocalDeletedAt == "" && (job.Status == "done" || job.Status == "partial") && bothCloudCopiesReady(job) &&
		job.Asset != nil && job.Asset.Size > 0 && job.Asset.Size <= maxTransferBytes && len(job.SHA256) == 64 && job.DownloadPath != ""
}

func sameLocalFile(a, b string) bool {
	if runtime.GOOS == "windows" {
		return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
	}
	return filepath.Clean(a) == filepath.Clean(b)
}

// An intentionally removed download is only needed again for a new upload.
// Existing file IDs can renew shares, and description retries need no binary.
func (m *transferManager) needsLocalDownload(job TransferJob) bool {
	if job.LocalDeletedAt == "" || job.Asset == nil || job.SHA256 == "" || len(job.Providers) == 0 {
		return true
	}
	for _, provider := range job.Providers {
		account, configured := m.app.cloud.get(provider)
		output := job.Outputs[provider]
		if configured && (output.File.ID == "" || output.Session != account.session || output.Status == "failed") {
			return true
		}
	}
	return false
}

// Runs only on the transfer worker while no job is active. API mutations are
// rechecked under mu after hashing, before any file is removed.
func (m *transferManager) cleanupLocalFiles() {
	jobs, storeError := m.snapshot()
	if storeError != "" {
		return
	}
	seen := map[string]bool{}
	for _, job := range jobs {
		if m.app.ctx.Err() != nil {
			return
		}
		if (!cleanupEligible(job) && !job.LocalCleanupPending) || job.LocalDeletedAt != "" || seen[job.DownloadPath] {
			continue
		}
		seen[job.DownloadPath] = true
		m.cleanupFile(job)
	}
}

func (m *transferManager) cleanupFile(job TransferJob) {
	m.mu.Lock()
	blocked := m.activeID != "" || m.storeError != ""
	shared := len(m.cleanupReferencesLocked(job)) == 0
	m.mu.Unlock()
	if blocked {
		return
	}
	if shared && !job.LocalCleanupPending {
		m.cleanupError(job, "同一本地文件仍被其他任务使用，暂时保留")
		return
	}
	if !m.ownedDownloadPath(job.DownloadPath) || job.Asset == nil || filepath.Base(job.DownloadPath) != job.Asset.Name {
		m.cleanupError(job, "下载路径无法核实，已保留本地文件")
		return
	}
	rootInfo, err := os.Lstat(m.downloadDir)
	if err != nil || !rootInfo.IsDir() || rootInfo.Mode()&os.ModeSymlink != 0 {
		m.cleanupError(job, "下载目录无法安全访问，已保留本地文件")
		return
	}
	root, err := os.OpenRoot(m.downloadDir)
	if err != nil {
		m.cleanupError(job, "下载目录无法安全访问，已保留本地文件")
		return
	}
	defer root.Close()
	openedRoot, err := root.Stat(".")
	if err != nil || !os.SameFile(rootInfo, openedRoot) {
		m.cleanupError(job, "下载目录已变化，已保留本地文件")
		return
	}
	relative, _ := filepath.Rel(m.downloadDir, job.DownloadPath)
	parent, name := filepath.Dir(relative), filepath.Base(relative)
	parentInfo, err := root.Lstat(parent)
	if errors.Is(err, os.ErrNotExist) && job.LocalCleanupPending {
		m.finishMissingCleanup(job)
		return
	}
	if err != nil || !parentInfo.IsDir() || parentInfo.Mode()&os.ModeSymlink != 0 {
		m.cleanupError(job, "游戏目录无法安全核实，已保留本地文件")
		return
	}
	directory, err := root.OpenRoot(parent)
	if err != nil {
		m.cleanupError(job, "无法打开游戏目录，稍后自动重试清理")
		return
	}
	defer directory.Close()
	openedParent, err := directory.Stat(".")
	if err != nil || !os.SameFile(parentInfo, openedParent) {
		m.cleanupError(job, "游戏目录已变化，已保留本地文件")
		return
	}
	info, err := directory.Lstat(name)
	if errors.Is(err, os.ErrNotExist) && job.LocalCleanupPending {
		m.finishMissingCleanup(job)
		return
	}
	if !cleanupEligible(job) {
		return
	}
	if shared {
		m.cleanupError(job, "同一本地文件仍被其他任务使用，暂时保留")
		return
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() != job.Asset.Size {
		m.cleanupError(job, "本地文件与下载记录不一致，已保留文件")
		return
	}
	file, err := directory.Open(name)
	if err != nil {
		m.cleanupError(job, "本地文件暂时无法读取，稍后自动重试清理")
		return
	}
	opened, statErr := file.Stat()
	hash := sha256.New()
	if statErr == nil && os.SameFile(info, opened) {
		_, err = io.Copy(&countingDownload{writer: hash, ctx: m.app.ctx, progress: func(int64, int64) {}}, io.LimitReader(file, job.Asset.Size+1))
	} else {
		err = errors.New("file changed")
	}
	closeErr := file.Close()
	if m.app.ctx.Err() != nil {
		return
	}
	if err != nil || closeErr != nil || hex.EncodeToString(hash.Sum(nil)) != job.SHA256 {
		m.cleanupError(job, "本地文件校验不匹配，已保留文件")
		return
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.activeID != "" || m.storeError != "" || m.app.ctx.Err() != nil {
		return
	}
	indices := m.cleanupReferencesLocked(job)
	if len(indices) == 0 {
		return
	}
	current, err := directory.Lstat(name)
	currentParent, parentErr := root.Lstat(parent)
	currentRoot, rootErr := os.Lstat(m.downloadDir)
	if err != nil || !current.Mode().IsRegular() || !os.SameFile(info, current) || current.Size() != info.Size() || !current.ModTime().Equal(info.ModTime()) ||
		parentErr != nil || currentParent.Mode()&os.ModeSymlink != 0 || !os.SameFile(parentInfo, currentParent) ||
		rootErr != nil || currentRoot.Mode()&os.ModeSymlink != 0 || !os.SameFile(rootInfo, currentRoot) {
		m.recordCleanupLocked(indices, "本地文件已变化，已保留文件", false)
		return
	}
	// Commit the removal intent first. A crash after Remove can then finish the
	// receipt without redownloading or erasing the cloud/share checkpoints.
	if !m.recordCleanupLocked(indices, "", false) {
		return
	}
	if err = directory.Remove(name); err != nil && !errors.Is(err, os.ErrNotExist) {
		m.recordCleanupLocked(indices, "本地文件暂时无法删除，稍后自动重试清理", false)
		return
	}
	m.recordCleanupLocked(indices, "", true)
}

// Every live reference must have its own completed two-drive copy. Never
// remove a shared local file still needed by a queued, failed or local-only job.
func (m *transferManager) cleanupReferencesLocked(candidate TransferJob) []int {
	indices := []int{}
	for i, job := range m.jobs {
		if job.DownloadPath == "" || !sameLocalFile(job.DownloadPath, candidate.DownloadPath) || job.LocalDeletedAt != "" {
			continue
		}
		if !cleanupEligible(job) || !sameReleaseAsset(candidate, job) || job.SHA256 != candidate.SHA256 {
			return nil
		}
		indices = append(indices, i)
	}
	return indices
}

func (m *transferManager) recordCleanupLocked(indices []int, message string, deleted bool) bool {
	next := append([]TransferJob{}, m.jobs...)
	changed := false
	for _, i := range indices {
		if !deleted && next[i].LocalCleanupPending && next[i].LocalCleanupError == message {
			continue
		}
		next[i] = cloneTransfer(next[i])
		next[i].LocalCleanupPending, next[i].LocalCleanupError = !deleted, message
		next[i].UpdatedAt = time.Now().UTC().Format(time.RFC3339)
		if deleted {
			next[i].LocalDeletedAt = next[i].UpdatedAt
		}
		changed = true
	}
	if changed {
		if err := m.saveLocked(next); err != nil {
			m.storeError = err.Error()
			return false
		}
		if m.app.automation != nil {
			m.app.automation.notify()
		}
	}
	return true
}

func (m *transferManager) cleanupError(job TransferJob, message string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for i, current := range m.jobs {
		if current.ID == job.ID && current.LocalDeletedAt == "" && sameLocalFile(current.DownloadPath, job.DownloadPath) && current.SHA256 == job.SHA256 {
			m.recordCleanupLocked([]int{i}, message, false)
			return
		}
	}
}

func (m *transferManager) finishMissingCleanup(job TransferJob) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.activeID != "" || m.storeError != "" {
		return
	}
	indices := []int{}
	for i, current := range m.jobs {
		if current.LocalCleanupPending && current.LocalDeletedAt == "" && sameLocalFile(current.DownloadPath, job.DownloadPath) && current.SHA256 == job.SHA256 {
			indices = append(indices, i)
		}
	}
	m.recordCleanupLocked(indices, "", true)
}
