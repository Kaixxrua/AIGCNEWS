package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const maxTransferJobs = 2000
const maxTransferBytes = 8 << 30

type TransferRequest struct {
	Repos        []string `json:"repos"`
	Providers    []string `json:"providers"`
	Arch         string   `json:"arch"`
	ShareDays    int      `json:"shareDays"`
	ShareCode    string   `json:"shareCode"`
	PrivateShare *bool    `json:"privateShare"`
	Enrich       bool     `json:"enrich"`
}

type TransferOutput struct {
	Status         string     `json:"status"`
	PayloadSHA256  string     `json:"payloadSha256,omitempty"`
	NeedsAttention bool       `json:"needsAttention,omitempty"`
	File           CloudFile  `json:"file"`
	Share          CloudShare `json:"share"`
	Error          string     `json:"error,omitempty"`
	Session        string     `json:"session,omitempty"`
}

type TransferJob struct {
	Automatic           bool                      `json:"automatic,omitempty"`
	Attempts            int                       `json:"attempts,omitempty"`
	NextRetryAt         string                    `json:"nextRetryAt,omitempty"`
	NeedsAttention      bool                      `json:"needsAttention,omitempty"`
	ResolvedAt          string                    `json:"resolvedAt,omitempty"`
	SupportedSystems    []string                  `json:"supportedSystems,omitempty"`
	ID                  string                    `json:"id"`
	Repo                string                    `json:"repo"`
	Name                string                    `json:"name"`
	GameNameZh          string                    `json:"gameNameZh,omitempty"`
	GameNameOriginal    string                    `json:"gameNameOriginal,omitempty"`
	PosterURL           string                    `json:"posterUrl,omitempty"`
	PosterSourceURL     string                    `json:"posterSourceUrl,omitempty"`
	PosterKind          string                    `json:"posterKind,omitempty"`
	DetailsVersion      int                       `json:"detailsVersion,omitempty"`
	Version             string                    `json:"version"`
	Arch                string                    `json:"arch"`
	Providers           []string                  `json:"providers"`
	ShareOptions        ShareOptions              `json:"shareOptions"`
	Enrich              bool                      `json:"enrich"`
	Status              string                    `json:"status"`
	Stage               string                    `json:"stage"`
	Provider            string                    `json:"provider"`
	CompletedBytes      int64                     `json:"completedBytes"`
	TotalBytes          int64                     `json:"totalBytes"`
	DownloadPath        string                    `json:"downloadPath"`
	LocalDeletedAt      string                    `json:"localDeletedAt,omitempty"`
	LocalCleanupPending bool                      `json:"localCleanupPending,omitempty"`
	LocalCleanupError   string                    `json:"localCleanupError,omitempty"`
	SHA256              string                    `json:"sha256"`
	SourceCommit        string                    `json:"sourceCommit,omitempty"`
	SourceURL           string                    `json:"sourceUrl,omitempty"`
	SourcePath          string                    `json:"sourcePath,omitempty"`
	SourceSHA256        string                    `json:"sourceSha256,omitempty"`
	SourceSize          int64                     `json:"sourceSize,omitempty"`
	BundleVersion       int                       `json:"bundleVersion,omitempty"`
	BundlePath          string                    `json:"bundlePath,omitempty"`
	BundleSHA256        string                    `json:"bundleSha256,omitempty"`
	BundleSize          int64                     `json:"bundleSize,omitempty"`
	LocalCleanupIntents map[string]string         `json:"localCleanupIntents,omitempty"`
	LocalRemovedFiles   map[string]string         `json:"localRemovedFiles,omitempty"`
	LegacyOutputs       map[string]TransferOutput `json:"legacyOutputs,omitempty"`
	Description         string                    `json:"description"`
	DataNote            string                    `json:"dataNote"`
	Guide               string                    `json:"guide"`
	Stars               *int                      `json:"stars,omitempty"`
	Error               string                    `json:"error,omitempty"`
	Warnings            []string                  `json:"warnings"`
	Outputs             map[string]TransferOutput `json:"outputs"`
	CreatedAt           string                    `json:"createdAt"`
	UpdatedAt           string                    `json:"updatedAt"`
	Asset               *Asset                    `json:"asset,omitempty"`
}

type transferManager struct {
	mu          sync.Mutex
	app         *App
	jobs        []TransferJob
	downloadDir string
	storage     atomic.Pointer[downloadStorage]
	storeError  string
	wake        chan struct{}
	done        chan struct{}
	activeID    string
	activeStop  context.CancelFunc
	client      *http.Client
}

func cloneTransfer(job TransferJob) TransferJob {
	encoded, _ := json.Marshal(job)
	var result TransferJob
	_ = json.Unmarshal(encoded, &result)
	return result
}

func newTransferManager(a *App) (*transferManager, error) {
	m := &transferManager{app: a, jobs: []TransferJob{}, downloadDir: filepath.Join(a.lib.root, "downloads"), wake: make(chan struct{}, 1), done: make(chan struct{}), client: newDownloadClient()}
	if err := os.MkdirAll(m.downloadDir, 0700); err != nil {
		return nil, fmt.Errorf("无法创建下载目录：%w", err)
	}
	if err := m.loadDownloadStorage(); err != nil {
		return nil, err
	}
	f, err := os.Open(filepath.Join(a.lib.root, "transfers.json"))
	if err == nil {
		defer f.Close()
		encoded, readErr := io.ReadAll(io.LimitReader(f, (32<<20)+1))
		if readErr != nil || len(encoded) > 32<<20 || json.Unmarshal(encoded, &m.jobs) != nil || len(m.jobs) > maxTransferJobs {
			return nil, errors.New("下载任务记录损坏，请先备份 transfers.json 再恢复")
		}
		ids := map[string]bool{}
		for i := range m.jobs {
			job := &m.jobs[i]
			if !sessionTokenPattern.MatchString(job.ID) || ids[job.ID] {
				return nil, errors.New("下载任务记录包含无效或重复的任务编号")
			}
			ids[job.ID] = true
			if _, err := parseRepo(job.Repo); err != nil || (job.Arch != "amd64" && job.Arch != "arm64") {
				return nil, errors.New("下载任务中的项目或架构无效")
			}
			if job.Asset != nil && (!officialReleaseURL(job.Asset.URL, job.Repo, true) || !validDownloadName(job.Asset.Name)) {
				return nil, errors.New("下载任务中的附件地址无效")
			}
			if len(job.SupportedSystems) == 0 && job.Asset != nil {
				job.SupportedSystems = supportedSystems([]Asset{*job.Asset})
			}
			if job.DownloadPath != "" && !m.ownedDownloadPath(job.DownloadPath) {
				return nil, errors.New("下载任务中的文件路径不属于下载目录")
			}
			for _, localPath := range []string{job.SourcePath, job.BundlePath} {
				if localPath != "" && !m.ownedDownloadPath(localPath) {
					return nil, errors.New("源码或分享包路径不属于下载目录")
				}
			}
			if job.SourceCommit != "" && !commitPattern.MatchString(job.SourceCommit) {
				return nil, errors.New("下载任务中的源码提交无效")
			}
			if job.SourceURL != "" && job.SourceURL != sourceArchiveURL(job.Repo, job.SourceCommit) {
				return nil, errors.New("下载任务中的源码来源无效")
			}
			if job.BundleVersion < 0 || job.BundleVersion > sourceBundleVersion {
				return nil, errors.New("此分享包版本暂不支持，请升级工具")
			}
			for _, outputs := range []map[string]TransferOutput{job.Outputs, job.LegacyOutputs} {
				for id, output := range outputs {
					if !validDrive(id) || (output.Share.URL != "" && !validCloudShare(id, output.Share.URL)) {
						return nil, errors.New("下载任务中的网盘分享地址无效")
					}
				}
			}
			if job.Outputs == nil {
				job.Outputs = map[string]TransferOutput{}
			}
			if job.Status == "queued" || job.Status == "running" || job.Status == "waiting_auth" {
				job.Status, job.Error = "paused", "上次任务已暂停，重新连接网盘后点击继续"
			}
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	return m, nil
}

func (m *transferManager) ownedDownloadPath(target string) bool {
	return m.downloadRoot(target) != ""
}

func (m *transferManager) saveLocked(next []TransferJob) error {
	encoded, err := json.MarshalIndent(next, "", "  ")
	if err != nil || len(encoded) > 32<<20 {
		return errors.New("任务记录过大，请先导出并清理已完成任务")
	}
	f, err := os.CreateTemp(m.app.lib.root, ".transfers-*")
	if err != nil {
		return errors.New("无法保存任务进度，请检查本地磁盘空间和权限")
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(encoded); err == nil {
		err = f.Sync()
	}
	if closeErr := f.Close(); err == nil {
		err = closeErr
	}
	if err == nil {
		err = replaceFile(name, filepath.Join(m.app.lib.root, "transfers.json"))
	}
	if err != nil {
		return errors.New("无法保存任务进度，请检查本地磁盘空间和权限")
	}
	m.jobs = next
	return nil
}

func (m *transferManager) snapshot() ([]TransferJob, string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	jobs := make([]TransferJob, len(m.jobs))
	for i, job := range m.jobs {
		jobs[i] = cloneTransfer(job)
	}
	return jobs, m.storeError
}

func (m *transferManager) job(id string) (TransferJob, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, job := range m.jobs {
		if job.ID == id {
			return cloneTransfer(job), true
		}
	}
	return TransferJob{}, false
}

func (m *transferManager) modify(id string, change func(*TransferJob), persist bool) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	next := append([]TransferJob{}, m.jobs...)
	for i, job := range next {
		if job.ID != id {
			continue
		}
		next[i] = cloneTransfer(job)
		change(&next[i])
		next[i].UpdatedAt = time.Now().UTC().Format(time.RFC3339)
		if persist {
			if err := m.saveLocked(next); err != nil {
				m.storeError = err.Error()
				if m.activeStop != nil {
					m.activeStop()
				}
				return err
			}
		} else {
			m.jobs = next
		}
		return nil
	}
	return errors.New("任务不存在")
}

func (m *transferManager) notify() {
	select {
	case m.wake <- struct{}{}:
	default:
	}
}

func (m *transferManager) providerBusy(provider string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.providerBusyLocked(provider)
}

func (m *transferManager) providerBusyLocked(provider string) bool {
	for _, job := range m.jobs {
		if job.ID == m.activeID {
			for _, id := range job.Providers {
				if id == provider {
					return true
				}
			}
		}
	}
	return false
}

// Use the worker's start lock so an account cannot change between its busy
// check and publication. Network authentication happens before taking it.
func (m *transferManager) setCloudAccount(provider string, account *cloudAccount) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.providerBusyLocked(provider) {
		return false
	}
	m.app.cloud.mu.Lock()
	defer m.app.cloud.mu.Unlock()
	if account == nil {
		delete(m.app.cloud.accounts, provider)
	} else {
		m.app.cloud.accounts[provider] = *account
	}
	return true
}

func sameTransfer(a, b TransferJob) bool {
	return strings.EqualFold(a.Repo, b.Repo) && a.Arch == b.Arch && strings.Join(a.Providers, ",") == strings.Join(b.Providers, ",") && a.ShareOptions == b.ShareOptions && a.Enrich == b.Enrich
}

func (m *transferManager) enqueue(request TransferRequest) ([]string, []string, error) {
	return m.enqueueRelease(request, nil, false)
}
func (m *transferManager) enqueueRelease(request TransferRequest, pinned *Release, automatic bool) ([]string, []string, error) {
	if len(request.Repos) == 0 || len(request.Repos) > 100 || (request.Arch != "amd64" && request.Arch != "arm64") ||
		(request.ShareDays != 0 && request.ShareDays != 1 && request.ShareDays != 7 && request.ShareDays != 30) {
		return nil, nil, errors.New("每批请选择 1–100 个游戏、Windows x64/ARM64 和有效分享期限")
	}
	if len(request.Providers) > 2 || len(request.ShareCode) > 4 {
		return nil, nil, errors.New("网盘或提取码设置无效")
	}
	for _, char := range request.ShareCode {
		if !(char >= 'a' && char <= 'z' || char >= 'A' && char <= 'Z' || char >= '0' && char <= '9') {
			return nil, nil, errors.New("百度提取码只能使用 4 位英文字母或数字，留空自动生成")
		}
	}
	if request.ShareCode != "" && len(request.ShareCode) != 4 {
		return nil, nil, errors.New("百度提取码必须为 4 位，留空自动生成")
	}
	private := request.PrivateShare == nil || *request.PrivateShare
	providers := append([]string{}, request.Providers...)
	sort.Strings(providers)
	for i, id := range providers {
		if !validDrive(id) || i > 0 && id == providers[i-1] || id == "baidu" && !private {
			return nil, nil, errors.New("请选择百度或夸克；百度网盘需要使用提取码分享")
		}
	}
	candidates := []TransferJob{}
	state := m.app.lib.snapshot()
	for _, raw := range request.Repos {
		repo, err := parseRepo(raw)
		if err != nil {
			return nil, nil, err
		}
		game, ok := m.app.game(repo)
		if !ok {
			return nil, nil, errors.New("请先把所选项目添加到我的目录")
		}
		stars := game.Stars
		if snapshot, ok := state.Snapshots[strings.ToLower(repo)]; ok && snapshot.StarsCheckedAt != "" {
			value := snapshot.Stars
			stars = &value
		}
		description := ""
		if item, ok := state.Descriptions[strings.ToLower(repo)]; ok && readyDescription(item) {
			description = item.DescriptionZh
		} else if validChineseDescription(game.Description) {
			description = game.Description
		}
		now := time.Now().UTC().Format(time.RFC3339)
		candidate := TransferJob{Automatic: automatic, ID: randomID(), Repo: game.Repo, Name: game.Name, Arch: request.Arch,
			Providers: providers, ShareOptions: ShareOptions{Days: request.ShareDays, Code: request.ShareCode, Private: private},
			Enrich: request.Enrich, Status: "queued", Stage: "release", Description: description, DataNote: game.DataNote, Guide: game.Guide,
			Stars: stars, Warnings: []string{}, Outputs: map[string]TransferOutput{}, CreatedAt: now, UpdatedAt: now}
		if item, ok := state.Descriptions[strings.ToLower(repo)]; ok && readyDescription(item) {
			applyTransferDetails(&candidate, item)
		}
		if pinned != nil {
			release, err := prepareRelease(game.Repo, *pinned, request.Arch)
			if err != nil {
				return nil, nil, err
			}
			selected, err := selectTransferAsset(release, request.Arch)
			if err != nil {
				return nil, nil, err
			}
			candidate.Asset, candidate.Version, candidate.ResolvedAt = selected, release.Tag, now
			candidate.SupportedSystems = append([]string{}, release.SupportedSystems...)
		}
		candidates = append(candidates, candidate)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.storeError != "" {
		return nil, nil, errors.New(m.storeError)
	}
	next := append([]TransferJob{}, m.jobs...)
	added, skipped := []string{}, []string{}
	for _, candidate := range candidates {
		duplicate := false
		for _, previous := range next {
			blocks := previous.Status != "done" && previous.Status != "cancelled"
			if automatic && pinned != nil {
				blocks = sameReleaseAsset(candidate, previous) && blocksAutomaticTransfer(previous)
			}
			if sameTransfer(candidate, previous) && blocks {
				duplicate = true
				break
			}
		}
		if duplicate {
			skipped = append(skipped, candidate.Repo)
		} else {
			next = append(next, candidate)
			added = append(added, candidate.ID)
		}
	}
	if len(next) > maxTransferJobs {
		return nil, nil, errors.New("任务历史已达 2,000 条，请先导出并清理已完成任务")
	}
	if err := m.saveLocked(next); err != nil {
		return nil, nil, err
	}
	m.notify()
	return added, skipped, nil
}

func (m *transferManager) action(id, action string) error {
	automaticEnabled := m.app.automation != nil && m.app.automation.configSnapshot().Enabled
	m.mu.Lock()
	defer m.mu.Unlock()
	next := append([]TransferJob{}, m.jobs...)
	for i, job := range next {
		if job.ID != id {
			continue
		}
		if action == "retry" {
			if job.Automatic && !automaticEnabled {
				return errors.New("请先开启自动运行，再继续自动任务")
			}
			if job.Status == "running" || job.Status == "queued" || m.activeID == id {
				return errors.New("任务正在运行，请稍候")
			}
			next[i] = cloneTransfer(job)
			next[i].Status, next[i].Error = "queued", ""
			next[i].Attempts, next[i].NextRetryAt, next[i].NeedsAttention = 0, "", false
			for provider, output := range next[i].Outputs {
				output.NeedsAttention = false
				next[i].Outputs[provider] = output
			}
		} else {
			next[i] = cloneTransfer(job)
			next[i].Status, next[i].Error = "cancelled", "任务已停止，已完成的下载和网盘文件会保留"
			next[i].NextRetryAt, next[i].NeedsAttention = "", false
		}
		next[i].UpdatedAt = time.Now().UTC().Format(time.RFC3339)
		if err := m.saveLocked(next); err != nil {
			return err
		}
		m.storeError = ""
		if action == "cancel" && m.activeID == id && m.activeStop != nil {
			m.activeStop()
		}
		m.notify()
		return nil
	}
	return errors.New("任务不存在")
}

func (m *transferManager) loop() {
	defer close(m.done)
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	m.notify()
	for {
		select {
		case <-m.app.ctx.Done():
			return
		case <-m.wake:
		case <-ticker.C:
		}
		m.cleanupLocalFiles()
		for {
			enabled := m.app.automation != nil && m.app.automation.configSnapshot().Enabled
			m.mu.Lock()
			id := ""
			if m.storeError == "" && m.app.ctx.Err() == nil {
				for _, job := range m.jobs {
					if job.Status == "queued" && (!job.Automatic || enabled) {
						id = job.ID
						break
					}
				}
			}
			if id == "" {
				m.mu.Unlock()
				break
			}
			ctx, cancel := context.WithTimeout(m.app.ctx, 8*time.Hour)
			m.activeID, m.activeStop = id, cancel
			m.mu.Unlock()
			err := m.beginAutomaticAttempt(id)
			if err == nil {
				err = m.run(ctx, id)
			}
			cancel()
			if err != nil {
				_ = m.modify(id, func(job *TransferJob) {
					if job.Status != "cancelled" && job.Status != "paused" {
						job.Status, job.Error = "failed", err.Error()
						if ctx.Err() != nil && m.app.ctx.Err() != nil {
							job.Status, job.Error = "paused", "工具已退出，点击继续可恢复任务"
						}
					}
				}, true)
			}
			m.planAutomaticRetry(id)
			m.mu.Lock()
			m.activeID, m.activeStop = "", nil
			m.mu.Unlock()
			m.cleanupLocalFiles()
			if m.app.automation != nil {
				m.app.automation.notify()
			}
			if m.app.marketplace != nil {
				m.app.marketplace.notify()
			}
		}
	}
}

func (m *transferManager) stage(id, stage, provider string) error {
	return m.modify(id, func(job *TransferJob) {
		if job.Status != "cancelled" && job.Status != "paused" {
			job.Status, job.Stage, job.Provider, job.Error = "running", stage, provider, ""
			job.CompletedBytes, job.TotalBytes = 0, 0
		}
	}, true)
}

func (m *transferManager) progress(id string) UploadProgress {
	last := time.Time{}
	var mu sync.Mutex
	return func(done, total int64) {
		mu.Lock()
		defer mu.Unlock()
		if time.Since(last) < 250*time.Millisecond && done != total {
			return
		}
		last = time.Now()
		_ = m.modify(id, func(job *TransferJob) {
			job.CompletedBytes, job.TotalBytes = done, total
		}, false)
	}
}

func (m *transferManager) run(ctx context.Context, id string) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if err := m.stage(id, "release", ""); err != nil {
		return err
	}
	job, _ := m.job(id)
	if job.Asset == nil {
		release, err := m.app.github.latest(ctx, job.Repo, job.Arch)
		if err != nil {
			return err
		}
		selected, err := selectTransferAsset(release, job.Arch)
		if err != nil {
			return err
		}
		if err := m.modify(id, func(j *TransferJob) {
			j.Asset, j.Version = selected, release.Tag
			j.ResolvedAt = time.Now().UTC().Format(time.RFC3339)
			j.SupportedSystems = append([]string{}, release.SupportedSystems...)
		}, true); err != nil {
			return err
		}
		job, _ = m.job(id)
	}
	if job.DownloadPath == "" {
		if err := m.reuseCompleted(&job); err != nil {
			return err
		}
	}
	if err := ctx.Err(); err != nil {
		return errors.New("任务已停止")
	}
	path := job.DownloadPath
	if m.needsLocalDownload(job) {
		if err := m.stage(id, "download", ""); err != nil {
			return err
		}
		var digest string
		var err error
		path, digest, err = m.download(ctx, job, m.progress(id))
		if err != nil {
			return err
		}
		if err := m.modify(id, func(j *TransferJob) {
			if job.SHA256 != "" && job.SHA256 != digest {
				j.Outputs = map[string]TransferOutput{}
			}
			j.DownloadPath, j.SHA256 = path, digest
			j.LocalDeletedAt, j.LocalCleanupError, j.LocalCleanupPending = "", "", false
			j.LocalCleanupIntents, j.LocalRemovedFiles = nil, nil
		}, true); err != nil {
			return err
		}
	}
	job, _ = m.job(id)
	if job.Enrich && (!readyTransferDetails(job) || job.PosterURL == "") {
		if err := m.enrich(ctx, job); err != nil {
			return err
		}
	}
	if err := m.prepareSourceBundle(ctx, id); err != nil {
		return err
	}
	job, _ = m.job(id)
	path, payloadDigest := transferPayload(job)
	waiting, failed := false, false
	for _, provider := range job.Providers {
		if ctx.Err() != nil {
			return errors.New("任务已停止")
		}
		job, _ = m.job(id)
		output := job.Outputs[provider]
		if output.PayloadSHA256 != payloadDigest {
			output = TransferOutput{}
		}
		account, configured := m.app.cloud.get(provider)
		if job.Automatic && output.NeedsAttention && (!configured || output.Session == account.session) {
			failed = true
			continue
		}
		if (configured && output.Session == account.session || !configured && localFilesWereCleaned(job)) && output.Status == "done" && usableCloudShare(provider, output.Share) {
			continue
		}
		if configured && output.Session != account.session {
			output = TransferOutput{}
		} else if output.Status == "done" {
			output.Share = CloudShare{}
		}
		if !configured {
			waiting = true
			output.Status, output.Error, output.NeedsAttention = "waiting_auth", "请在连接设置中登录此网盘，再点击继续", true
		} else {
			if err := m.stage(id, "upload", provider); err != nil {
				return err
			}
			if output.File.ID == "" || output.Session != account.session {
				output.Session, output.PayloadSHA256 = account.session, payloadDigest
				output.NeedsAttention = false
				remoteName := transferRemoteName(job)
				file, uploadErr := account.drive.Upload(ctx, path, remoteName, m.progress(id))
				if uploadErr == nil && !m.verifyManaged(ctx, path, payloadDigest, job.BundleSize) {
					uploadErr = errors.New("上传期间分享包发生变化，请重新核对；本地文件会保留")
				}
				if uploadErr != nil {
					output.Status, output.Error, output.NeedsAttention = "failed", uploadErr.Error(), manualActionRequired(uploadErr.Error())
				} else {
					output.File, output.Session, output.Status, output.Error = file, account.session, "uploaded", ""
					if err := m.modify(id, func(j *TransferJob) { j.Outputs[provider] = output }, true); err != nil {
						return err
					}
				}
			}
			if output.File.ID != "" && output.Session == account.session && output.Status != "failed" {
				if err := m.stage(id, "share", provider); err != nil {
					return err
				}
				options := job.ShareOptions
				if provider == "quark" {
					options.Code = ""
				}
				share, shareErr := account.drive.Share(ctx, output.File, options)
				if shareErr != nil {
					output.Status, output.Error, output.NeedsAttention = "share_failed", shareErr.Error(), manualActionRequired(shareErr.Error())
				} else if !validCloudShare(provider, share.URL) {
					output.Status, output.Error = "share_failed", "网盘返回的分享地址无效"
				} else {
					output.Status, output.Share, output.Error, output.NeedsAttention = "done", share, "", false
				}
			}
			failed = failed || output.Status != "done"
		}
		if err := m.modify(id, func(j *TransferJob) { j.Outputs[provider] = output }, true); err != nil {
			return err
		}
	}
	if ctx.Err() != nil {
		return errors.New("任务已停止")
	}
	return m.modify(id, func(j *TransferJob) {
		if j.Status == "cancelled" || j.Status == "paused" {
			return
		}
		j.Status, j.Stage, j.Provider, j.Error = "done", "done", "", ""
		if waiting {
			j.Status, j.Error = "waiting_auth", "下载已完成，请连接网盘后点击继续"
		} else if failed {
			j.Status, j.Error = "partial", "下载已完成，部分网盘步骤失败，可单独重试"
		}
		if cleanupEligible(*j) {
			j.LocalCleanupPending = true
		}
	}, true)
}

func (m *transferManager) reuseCompleted(job *TransferJob) error {
	// Download once for an immutable release asset; never match by filename alone.
	jobs, _ := m.snapshot()
	for i := len(jobs) - 1; i >= 0; i-- {
		previous := jobs[i]
		if previous.ID == job.ID || previous.Asset == nil || job.Asset == nil || previous.SHA256 == "" ||
			!strings.EqualFold(previous.Repo, job.Repo) || previous.Arch != job.Arch || previous.Version != job.Version ||
			previous.Asset.ID != job.Asset.ID || previous.Asset.URL != job.Asset.URL || previous.Asset.Size != job.Asset.Size ||
			previous.Asset.Digest != job.Asset.Digest || !m.ownedDownloadPath(previous.DownloadPath) {
			continue
		}
		job.DownloadPath, job.SHA256 = previous.DownloadPath, previous.SHA256
		job.LocalDeletedAt = previous.LocalDeletedAt
		if len(job.Providers) > 0 && hasSourceBundle(previous) {
			job.SourceCommit, job.SourceURL, job.SourcePath, job.SourceSHA256, job.SourceSize = previous.SourceCommit, sourceArchiveURL(job.Repo, previous.SourceCommit), previous.SourcePath, previous.SourceSHA256, previous.SourceSize
			job.LocalRemovedFiles = previous.LocalRemovedFiles
			job.BundleVersion, job.BundlePath, job.BundleSHA256, job.BundleSize = previous.BundleVersion, previous.BundlePath, previous.BundleSHA256, previous.BundleSize
		}
		for _, provider := range job.Providers {
			output := previous.Outputs[provider]
			account, configured := m.app.cloud.get(provider)
			if !hasSourceBundle(previous) || output.PayloadSHA256 != previous.BundleSHA256 || !configured || output.Session != account.session {
				continue
			}
			if previous.ShareOptions == job.ShareOptions && output.Status == "done" && usableCloudShare(provider, output.Share) {
				job.Outputs[provider] = output
			} else if previous.LocalDeletedAt != "" && output.File.ID != "" && !output.NeedsAttention &&
				(output.Status == "done" || output.Status == "uploaded" || output.Status == "share_failed") {
				// An expired link or changed share options need a new share, not
				// another download/upload of an intentionally cleaned release.
				output.Status, output.Share, output.Error = "uploaded", CloudShare{}, ""
				job.Outputs[provider] = output
			}
		}
		return m.modify(job.ID, func(j *TransferJob) {
			j.DownloadPath, j.SHA256, j.Outputs = job.DownloadPath, job.SHA256, job.Outputs
			j.LocalDeletedAt = job.LocalDeletedAt
			j.LocalRemovedFiles = job.LocalRemovedFiles
			j.SourceCommit, j.SourceURL, j.SourcePath, j.SourceSHA256, j.SourceSize = job.SourceCommit, job.SourceURL, job.SourcePath, job.SourceSHA256, job.SourceSize
			j.BundleVersion, j.BundlePath, j.BundleSHA256, j.BundleSize = job.BundleVersion, job.BundlePath, job.BundleSHA256, job.BundleSize
		}, true)
	}
	return nil
}

func (m *transferManager) enrich(ctx context.Context, job TransferJob) error {
	if err := m.stage(job.ID, "description", ""); err != nil {
		return err
	}
	// Background metadata work can take four minutes; allow time to read its result.
	descriptionCtx, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()
	result, err := m.app.aigc.get(descriptionCtx, []string{job.Repo})
	var previous Description
	if err == nil && len(result.Items) > 0 && readyGameDetails(result.Items[0]) {
		previous = result.Items[0]
	}
	// Resume a queued job by reading its status instead of submitting it again.
	if err == nil && (len(result.Items) == 0 || result.Items[0].Status != "pending" && (!readyGameDetails(result.Items[0]) || needsPosterGeneration(result.Items[0]))) && m.app.aigc.hasToken() {
		result, _, err = m.app.aigc.generate(descriptionCtx, job.Repo)
	}
	for err == nil && len(result.Items) > 0 && result.Items[0].Status == "pending" {
		delay := result.PollAfter
		if delay < 2 {
			delay = 3
		}
		if delay > 15 {
			delay = 15
		}
		select {
		case <-descriptionCtx.Done():
			err = errors.New("中文简介生成尚未完成，可在目录中补全后重试")
		case <-time.After(time.Duration(delay) * time.Second):
			result, err = m.app.aigc.get(descriptionCtx, []string{job.Repo})
		}
	}
	posterUnavailable := readyGameDetails(previous) && (err != nil || len(result.Items) == 0 || !readyGameDetails(result.Items[0]))
	if posterUnavailable {
		// A poster-only request cannot discard text already verified by GET or
		// turn a completed download into endless Chinese-description retries.
		result, err = DescriptionsResponse{Items: []Description{previous}}, nil
	}
	if err == nil && len(result.Items) > 0 && readyDescription(result.Items[0]) {
		item := result.Items[0]
		_ = m.app.lib.saveDescriptions([]Description{item})
		if cached, ok := m.app.lib.snapshot().Descriptions[strings.ToLower(job.Repo)]; ok && readyGameDetails(cached) {
			item = cached
		}
		return m.modify(job.ID, func(j *TransferJob) {
			applyTransferDetails(j, item)
			j.Warnings = []string{}
			if !readyTransferDetails(*j) {
				j.Warnings = []string{"中文简介已保留，中文游戏名与海报资料待补充"}
			} else if posterUnavailable || j.PosterURL == "" {
				j.Warnings = []string{"中文游戏资料已保留，海报联网查找尚未完成"}
			}
		}, true)
	}
	message := "中文简介待补充，请设置 AIGCNEWS Token 后重试；文件传输会继续"
	if readyTransferDetails(job) {
		message = "中文游戏资料已保留，海报联网查找尚未完成"
	} else if err != nil {
		message = "中文简介未完成：" + err.Error()
	}
	return m.modify(job.ID, func(j *TransferJob) {
		j.Warnings = append([]string{}, message)
	}, true)
}

func applyTransferDetails(job *TransferJob, item Description) {
	sanitizeGameDetails(&item)
	job.Description = item.DescriptionZh
	if item.DetailsVersion != gameDetailsVersion && job.DetailsVersion == gameDetailsVersion {
		return
	}
	job.GameNameZh, job.GameNameOriginal = item.GameNameZh, item.GameNameOriginal
	job.PosterURL, job.PosterSourceURL, job.PosterKind = item.PosterURL, item.PosterSourceURL, item.PosterKind
	job.DetailsVersion = item.DetailsVersion
}

func readyTransferDetails(job TransferJob) bool {
	return job.Description != "" && job.DetailsVersion == gameDetailsVersion
}
