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
		if job.BundleVersion != 0 && (!hasSourceBundle(job) || output.PayloadSHA256 != job.BundleSHA256) {
			return false
		}
	}
	return true
}

func cleanupEligible(job TransferJob) bool {
	return job.LocalDeletedAt == "" && (job.Status == "done" || job.Status == "partial") && bothCloudCopiesReady(job) &&
		job.Asset != nil && job.Asset.Size > 0 && job.Asset.Size <= maxTransferBytes && sha256Pattern.MatchString(job.SHA256) && job.DownloadPath != ""
}

func sameLocalFile(a, b string) bool {
	if runtime.GOOS == "windows" {
		return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
	}
	return filepath.Clean(a) == filepath.Clean(b)
}

func localFilesWereCleaned(job TransferJob) bool {
	return job.LocalDeletedAt != "" || len(job.LocalRemovedFiles) > 0
}

// Existing remote bundles can renew shares or receive updated metadata without
// recreating intentionally deleted source files. New accounts need a new copy.
func (m *transferManager) needsLocalDownload(job TransferJob) bool {
	if len(job.Providers) != 0 && !hasSourceBundle(job) {
		return true
	}
	if !localFilesWereCleaned(job) || job.Asset == nil || job.SHA256 == "" || len(job.Providers) == 0 {
		return true
	}
	for _, provider := range job.Providers {
		account, configured := m.app.cloud.get(provider)
		output := job.Outputs[provider]
		if configured && (output.File.ID == "" || output.Session != account.session || output.Status == "failed" || output.PayloadSHA256 != job.BundleSHA256) {
			return true
		}
	}
	return false
}

type localArtifact struct {
	key, path, name, digest string
	size                    int64
}

func transferArtifacts(job TransferJob) []localArtifact {
	if job.Asset == nil {
		return nil
	}
	files := []localArtifact{{"binary", job.DownloadPath, job.Asset.Name, job.SHA256, job.Asset.Size}}
	if job.BundleVersion != 0 {
		files = append(files, localArtifact{"source", job.SourcePath, sourceArchiveName(job), job.SourceSHA256, job.SourceSize},
			localArtifact{"bundle", job.BundlePath, bundleName(job), job.BundleSHA256, job.BundleSize})
	}
	return files
}
func artifactAtPath(job TransferJob, target string) (localArtifact, bool) {
	for _, file := range transferArtifacts(job) {
		if file.path != "" && sameLocalFile(file.path, target) {
			return file, true
		}
	}
	return localArtifact{}, false
}
func artifactRemovalIntent(job TransferJob, file localArtifact) bool {
	return job.LocalCleanupIntents[file.key] == file.digest || job.BundleVersion == 0 && job.LocalCleanupPending
}

// The transfer worker runs cleanup only while idle. Each file gets its own
// durable intent and receipt so a crash halfway through a bundle is recoverable.
func (m *transferManager) cleanupLocalFiles() {
	jobs, storeError := m.snapshot()
	if storeError != "" {
		return
	}
	for _, job := range jobs {
		if m.app.ctx.Err() != nil {
			return
		}
		if (!cleanupEligible(job) && !job.LocalCleanupPending) || job.LocalDeletedAt != "" {
			continue
		}
		m.cleanupFile(job)
	}
}

func (m *transferManager) cleanupFile(job TransferJob) {
	for _, file := range transferArtifacts(job) {
		current, ok := m.job(job.ID)
		if !ok || current.LocalDeletedAt != "" || current.LocalRemovedFiles[file.key] != "" {
			continue
		}
		m.cleanupArtifact(current, file)
	}
}

func (m *transferManager) cleanupArtifact(job TransferJob, artifact localArtifact) {
	m.mu.Lock()
	blocked := m.activeID != "" || m.storeError != ""
	shared := len(m.cleanupArtifactReferencesLocked(artifact)) == 0
	m.mu.Unlock()
	if blocked {
		return
	}
	if shared && !artifactRemovalIntent(job, artifact) {
		m.cleanupError(job, "同一本地文件仍被其他任务使用，暂时保留")
		return
	}
	if !m.ownedDownloadPath(artifact.path) || filepath.Base(artifact.path) != artifact.name || !sha256Pattern.MatchString(artifact.digest) || artifact.size <= 0 || artifact.size > maxBundleBytes {
		m.cleanupError(job, "下载路径无法核实，已保留本地文件")
		return
	}
	base := m.downloadRoot(artifact.path)
	rootInfo, err := regularDownloadRoot(base)
	if err != nil {
		m.cleanupError(job, "下载目录无法安全访问，已保留本地文件")
		return
	}
	root, err := os.OpenRoot(base)
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
	relative, _ := filepath.Rel(base, artifact.path)
	parent, name := filepath.Dir(relative), filepath.Base(relative)
	parentInfo, err := root.Lstat(parent)
	if errors.Is(err, os.ErrNotExist) && artifactRemovalIntent(job, artifact) {
		m.finishMissingArtifact(artifact)
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
	if errors.Is(err, os.ErrNotExist) && artifactRemovalIntent(job, artifact) {
		m.finishMissingArtifact(artifact)
		return
	}
	if !cleanupEligible(job) {
		return
	}
	if shared {
		m.cleanupError(job, "同一本地文件仍被其他任务使用，暂时保留")
		return
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() != artifact.size {
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
		_, err = io.Copy(&countingDownload{writer: hash, ctx: m.app.ctx, progress: func(int64, int64) {}}, io.LimitReader(file, artifact.size+1))
	} else {
		err = errors.New("file changed")
	}
	closeErr := file.Close()
	if m.app.ctx.Err() != nil {
		return
	}
	if err != nil || closeErr != nil || hex.EncodeToString(hash.Sum(nil)) != artifact.digest {
		m.cleanupError(job, "本地文件校验不匹配，已保留文件")
		return
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.activeID != "" || m.storeError != "" || m.app.ctx.Err() != nil {
		return
	}
	indices := m.cleanupArtifactReferencesLocked(artifact)
	if len(indices) == 0 {
		return
	}
	current, err := directory.Lstat(name)
	currentParent, parentErr := root.Lstat(parent)
	currentRoot, rootErr := regularDownloadRoot(base)
	if err != nil || !current.Mode().IsRegular() || !os.SameFile(info, current) || current.Size() != info.Size() || !current.ModTime().Equal(info.ModTime()) ||
		parentErr != nil || currentParent.Mode()&os.ModeSymlink != 0 || !os.SameFile(parentInfo, currentParent) ||
		rootErr != nil || currentRoot.Mode()&os.ModeSymlink != 0 || !os.SameFile(rootInfo, currentRoot) {
		m.recordCleanupErrorLocked(indices, "本地文件已变化，已保留文件")
		return
	}
	if !m.recordArtifactCleanupLocked(indices, artifact, false) {
		return
	}
	if err = directory.Remove(name); err != nil && !errors.Is(err, os.ErrNotExist) {
		m.recordCleanupErrorLocked(indices, "本地文件暂时无法删除，稍后自动重试清理")
		return
	}
	m.recordArtifactCleanupLocked(indices, artifact, true)
}

// Every reference must have both cloud copies of its actual payload. A queued,
// failed, local-only or single-drive job keeps its shared files available.
func (m *transferManager) cleanupArtifactReferencesLocked(candidate localArtifact) []int {
	indices := []int{}
	for i, job := range m.jobs {
		file, found := artifactAtPath(job, candidate.path)
		if !found || job.LocalDeletedAt != "" || job.LocalRemovedFiles[file.key] != "" {
			continue
		}
		if !cleanupEligible(job) || file.digest != candidate.digest || file.size != candidate.size || file.name != candidate.name {
			return nil
		}
		indices = append(indices, i)
	}
	return indices
}

func (m *transferManager) saveCleanupLocked(next []TransferJob) bool {
	if err := m.saveLocked(next); err != nil {
		m.storeError = err.Error()
		return false
	}
	if m.app.automation != nil {
		m.app.automation.notify()
	}
	return true
}

func (m *transferManager) recordArtifactCleanupLocked(indices []int, artifact localArtifact, deleted bool) bool {
	next := append([]TransferJob{}, m.jobs...)
	changed := false
	for _, i := range indices {
		file, ok := artifactAtPath(next[i], artifact.path)
		if !ok {
			continue
		}
		if !deleted && next[i].LocalCleanupIntents[file.key] == artifact.digest {
			continue
		}
		next[i] = cloneTransfer(next[i])
		changed = true
		job := &next[i]
		if job.LocalCleanupIntents == nil {
			job.LocalCleanupIntents = map[string]string{}
		}
		if job.LocalRemovedFiles == nil {
			job.LocalRemovedFiles = map[string]string{}
		}
		job.LocalCleanupPending = true
		job.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
		job.LocalCleanupIntents[file.key] = artifact.digest
		if deleted {
			job.LocalRemovedFiles[file.key] = job.UpdatedAt
			delete(job.LocalCleanupIntents, file.key)
			complete := true
			for _, required := range transferArtifacts(*job) {
				complete = complete && job.LocalRemovedFiles[required.key] != ""
			}
			if complete {
				job.LocalDeletedAt, job.LocalCleanupPending, job.LocalCleanupError = job.UpdatedAt, false, ""
			}
		}
	}
	return !changed || m.saveCleanupLocked(next)
}

func (m *transferManager) recordCleanupErrorLocked(indices []int, message string) bool {
	next := append([]TransferJob{}, m.jobs...)
	changed := false
	for _, i := range indices {
		if next[i].LocalCleanupPending && next[i].LocalCleanupError == message {
			continue
		}
		next[i] = cloneTransfer(next[i])
		changed = true
		next[i].LocalCleanupPending, next[i].LocalCleanupError = true, message
		next[i].UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	}
	return !changed || m.saveCleanupLocked(next)
}

func (m *transferManager) cleanupError(job TransferJob, message string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for i, current := range m.jobs {
		if current.ID == job.ID && current.LocalDeletedAt == "" {
			m.recordCleanupErrorLocked([]int{i}, message)
			return
		}
	}
}

func (m *transferManager) finishMissingArtifact(artifact localArtifact) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.activeID != "" || m.storeError != "" {
		return
	}
	indices := []int{}
	for i, current := range m.jobs {
		file, ok := artifactAtPath(current, artifact.path)
		if ok && current.LocalDeletedAt == "" && file.digest == artifact.digest && current.LocalRemovedFiles[file.key] == "" && artifactRemovalIntent(current, file) {
			indices = append(indices, i)
		}
	}
	m.recordArtifactCleanupLocked(indices, artifact, true)
}
