package main

import (
	"errors"
	"strings"
	"time"
)

func selectTransferAsset(release Release, arch string) (*Asset, error) {
	for _, asset := range release.Assets {
		if assetScore(asset, arch) > 0 && asset.Size > 0 && validDownloadName(asset.Name) {
			if asset.Size > maxTransferBytes {
				return nil, errors.New("附件超过本工具单文件 8 GiB 上限")
			}
			copy := asset
			return &copy, nil
		}
	}
	return nil, errors.New("上游没有适用于所选 Windows 架构的发布附件，请打开项目发布页确认")
}

func (m *transferManager) enqueueAutomatic(repo string, config AutomationConfig, release Release) ([]string, []string, error) {
	private := config.PrivateShare
	return m.enqueueRelease(TransferRequest{Repos: []string{repo}, Providers: config.Providers, Arch: config.Arch, ShareDays: config.ShareDays,
		ShareCode: config.ShareCode, PrivateShare: &private, Enrich: config.Enrich}, &release, true)
}

func sameReleaseAsset(a, b TransferJob) bool {
	return a.Version == b.Version && a.Asset != nil && b.Asset != nil && a.Asset.ID == b.Asset.ID && a.Asset.URL == b.Asset.URL && a.Asset.Size == b.Asset.Size && a.Asset.Digest == b.Asset.Digest
}

func blocksAutomaticTransfer(previous TransferJob) bool {
	if previous.Status != "done" {
		return true
	}
	for _, provider := range previous.Providers {
		output := previous.Outputs[provider]
		if output.Status != "done" || !usableCloudShare(provider, output.Share) {
			return false
		}
	}
	return true
}

func manualActionRequired(message string) bool {
	for _, fragment := range []string{"验证码", "重新授权", "重新连接", "登录凭证", "授权已失效", "授权已过期", "更新 Cookie", "登录已失效", "请在网页检查", "Token 无效", "Token 已过期", "缺少此操作权限", "没有权限", "安全验证", "空间不足", "容量不足", "额度不足", "已有同名文件", "目录不安全", "文件不安全", "超过本工具", "请填写", "请先填写", "没有适用于", "附件无效", "不属于下载目录", "未通过上游 SHA-256", "请重新核对发布版本"} {
		if strings.Contains(message, fragment) {
			return true
		}
	}
	return false
}

func automaticRetryDelay(attempt int) time.Duration {
	if attempt < 1 {
		attempt = 1
	}
	if attempt > 9 {
		attempt = 9
	}
	duration := time.Minute * time.Duration(1<<attempt)
	if duration > 6*time.Hour {
		return 6 * time.Hour
	}
	return duration
}

func (m *transferManager) beginAutomaticAttempt(id string) error {
	job, ok := m.job(id)
	if !ok {
		return errors.New("任务不存在")
	}
	if !job.Automatic {
		return nil
	}
	return m.modify(id, func(j *TransferJob) {
		if j.Attempts < 1_000_000 {
			j.Attempts++
		}
		j.NextRetryAt = ""
		j.NeedsAttention = false
	}, true)
}

// Persist backoff before scheduling another attempt. A manual cancellation is
// terminal; disabling automation pauses its jobs without touching manual jobs.
func (m *transferManager) planAutomaticRetry(id string) {
	job, ok := m.job(id)
	if !ok || !job.Automatic || job.Status == "cancelled" || job.Status == "paused" {
		return
	}
	needsDescription := job.Enrich && !readyTransferDetails(job)
	if job.Status == "done" && !needsDescription {
		_ = m.modify(id, func(j *TransferJob) { j.NextRetryAt = ""; j.NeedsAttention = false }, true)
		return
	}
	attention, transient := false, false
	if job.Status == "failed" {
		attention = manualActionRequired(job.Error)
		transient = !attention
	}
	for _, provider := range job.Providers {
		// A release/download failure happened before the cloud steps. Their
		// unattempted outputs must not override a terminal upstream error.
		if job.Status == "failed" {
			break
		}
		output := job.Outputs[provider]
		if output.Status == "done" && usableCloudShare(provider, output.Share) {
			continue
		}
		_, configured := m.app.cloud.get(provider)
		if !configured || output.NeedsAttention {
			attention = true
		} else {
			transient = true
		}
	}
	if needsDescription && job.Status != "failed" {
		descriptionBlocked := !m.app.aigc.hasToken()
		for _, warning := range job.Warnings {
			descriptionBlocked = descriptionBlocked || manualActionRequired(warning)
		}
		if descriptionBlocked {
			attention = true
		} else {
			transient = true
		}
	}
	next := ""
	if transient {
		next = time.Now().UTC().Add(automaticRetryDelay(job.Attempts)).Format(time.RFC3339)
	}
	_ = m.modify(id, func(j *TransferJob) {
		j.NextRetryAt, j.NeedsAttention = next, attention
		if j.Status == "done" && needsDescription {
			j.Status = "partial"
			j.Error = "下载与网盘步骤已完成，中文简介仍待补充"
		}
	}, true)
}

func (m *transferManager) maintainAutomatic(config AutomationConfig) {
	m.mu.Lock()
	defer m.mu.Unlock()
	next := append([]TransferJob{}, m.jobs...)
	changed, stop := false, false
	now := time.Now()
	for i, job := range next {
		if !job.Automatic || job.Status == "cancelled" || job.Status == "done" {
			continue
		}
		if !config.Enabled {
			if job.Status == "running" || job.Status == "queued" {
				next[i] = cloneTransfer(job)
				next[i].Status = "paused"
				next[i].NextRetryAt = ""
				next[i].Error = "自动运行已暂停，重新开启后自动继续"
				changed = true
				stop = stop || m.activeID == job.ID
			}
			continue
		}
		if m.storeError != "" || m.activeID == job.ID || job.Status == "running" || job.Status == "queued" {
			continue
		}
		due, err := time.Parse(time.RFC3339, job.NextRetryAt)
		if job.Status == "paused" || (err == nil && !due.After(now)) {
			next[i] = cloneTransfer(job)
			next[i].Status, next[i].Error, next[i].NextRetryAt = "queued", "", ""
			changed = true
		}
	}
	if !changed {
		return
	}
	if err := m.saveLocked(next); err != nil {
		m.storeError = err.Error()
		stop = true
	}
	if stop && m.activeStop != nil {
		m.activeStop()
	}
	m.notify()
}

func (m *transferManager) credentialsAvailable(provider string) {
	m.mu.Lock()
	next := append([]TransferJob{}, m.jobs...)
	changed := false
	for i, job := range next {
		if !job.Automatic || job.Status == "cancelled" || job.Status == "done" || job.Status == "running" || job.Status == "queued" {
			continue
		}
		relevant := provider == "github" && (job.Stage == "release" || job.Stage == "download" || job.Stage == "source") || provider == "aigc" && !readyTransferDetails(job) && job.Enrich
		if output, exists := job.Outputs[provider]; exists && output.Status != "done" {
			relevant = true
		}
		if !relevant {
			continue
		}
		next[i] = cloneTransfer(job)
		if output, exists := next[i].Outputs[provider]; exists {
			output.NeedsAttention = false
			next[i].Outputs[provider] = output
		}
		if job.Status != "paused" {
			next[i].NextRetryAt = time.Now().UTC().Format(time.RFC3339)
		}
		changed = true
	}
	if changed {
		if err := m.saveLocked(next); err != nil {
			m.storeError = err.Error()
		}
	}
	m.mu.Unlock()
	if changed && m.app.automation != nil {
		m.app.automation.notify()
	}
}
