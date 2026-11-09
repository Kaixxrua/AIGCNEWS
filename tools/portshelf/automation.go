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
	"reflect"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"
)

const automationMaxBytes = 4 << 20
const automationReleaseBudget = 10

type AutomationConfig struct {
	Enabled             bool     `json:"enabled"`
	IntervalHours       int      `json:"intervalHours"`
	MinStars            int      `json:"minStars"`
	MaxStars            *int     `json:"maxStars"`
	Arch                string   `json:"arch"`
	Providers           []string `json:"providers"`
	DailyLimit          int      `json:"dailyLimit"`
	ShareDays           int      `json:"shareDays"`
	ShareCode           string   `json:"shareCode"`
	PrivateShare        bool     `json:"privateShare"`
	Enrich              bool     `json:"enrich"`
	RememberCredentials bool     `json:"rememberCredentials"`
	StartOnLogin        bool     `json:"startOnLogin"`
}

type automationState struct {
	Version      int              `json:"version"`
	Config       AutomationConfig `json:"config"`
	NextRun      string           `json:"nextRun"`
	LastRun      string           `json:"lastRun"`
	LastError    string           `json:"lastError"`
	ExportError  string           `json:"exportError"`
	ExportedAt   string           `json:"exportedAt"`
	ExportDigest string           `json:"exportDigest"`
	Discovered   int              `json:"discovered"`
	Queued       int              `json:"queued"`
	Unsupported  int              `json:"unsupported"`
	Day          string           `json:"day"`
	DayCount     int              `json:"dayCount"`
	Page         int              `json:"page"`
	Following    int              `json:"following"`
	Candidates   []Game           `json:"candidates"`
	Cursor       int              `json:"cursor"`
}

type automationStatus struct {
	Config                     AutomationConfig `json:"config"`
	Running                    bool             `json:"running"`
	NextRun                    string           `json:"nextRun"`
	LastRun                    string           `json:"lastRun"`
	LastError                  string           `json:"lastError"`
	ExportDir                  string           `json:"exportDir"`
	ExportedAt                 string           `json:"exportedAt"`
	Discovered                 int              `json:"discovered"`
	Queued                     int              `json:"queued"`
	Unsupported                int              `json:"unsupported"`
	CredentialStorageSupported bool             `json:"credentialStorageSupported"`
	StartOnLoginSupported      bool             `json:"startOnLoginSupported"`
	CredentialError            string           `json:"credentialError"`
}

type automationManager struct {
	mu         sync.Mutex
	settingsMu sync.Mutex
	app        *App
	state      automationState
	running    bool
	requested  bool
	revision   uint64
	stopRun    context.CancelFunc
	storeError string
	wake       chan struct{}
	done       chan struct{}
	now        func() time.Time
	discover   func(context.Context, starBounds, int) (DiscoveryPage, error)
	latest     func(context.Context, string, string) (Release, error)
	enqueue    func(string, AutomationConfig, Release) ([]string, []string, error)
	maintain   func(AutomationConfig)
	// apply is an optional test override. Production uses the credentials
	// transaction so a failed config write restores the exact prior vault.
	apply            func(AutomationConfig, AutomationConfig) error
	applyTransaction func(AutomationConfig, AutomationConfig, func() error) error
}

func defaultAutomationConfig() AutomationConfig {
	arch := runtime.GOARCH
	if arch != "arm64" {
		arch = "amd64"
	}
	return AutomationConfig{IntervalHours: 6, MinStars: 10, Arch: arch, Providers: []string{"baidu", "quark"}, DailyLimit: 10,
		PrivateShare: true, Enrich: true, RememberCredentials: credentialProtectionAvailable(), StartOnLogin: autoStartSupported()}
}

func cloneAutomationConfig(config AutomationConfig) AutomationConfig {
	config.Providers = append([]string{}, config.Providers...)
	if config.MaxStars != nil {
		value := *config.MaxStars
		config.MaxStars = &value
	}
	return config
}

func validateAutomationConfig(config AutomationConfig) (AutomationConfig, error) {
	config = cloneAutomationConfig(config)
	if config.IntervalHours < 1 || config.IntervalHours > 168 || config.DailyLimit < 1 || config.DailyLimit > 100 {
		return config, errors.New("自动检查间隔须为 1–168 小时，每日新增任务上限须为 1–100")
	}
	if config.MinStars < 0 || config.MinStars > 1000000000 || config.MaxStars != nil && (*config.MaxStars < config.MinStars || *config.MaxStars > 1000000000) {
		return config, errors.New("Stars 范围无效，下限不能超过上限，数值须为 0–1000000000")
	}
	if config.Arch != "amd64" && config.Arch != "arm64" {
		return config, errors.New("请选择 Windows x64 或 ARM64")
	}
	if len(config.Providers) < 1 || len(config.Providers) > 2 {
		return config, errors.New("自动模式至少需要选择一个网盘")
	}
	sort.Strings(config.Providers)
	for i, provider := range config.Providers {
		if !validDrive(provider) || i > 0 && provider == config.Providers[i-1] || provider == "baidu" && !config.PrivateShare {
			return config, errors.New("请选择百度或夸克；百度分享需要提取码")
		}
	}
	if config.ShareDays != 0 && config.ShareDays != 1 && config.ShareDays != 7 && config.ShareDays != 30 {
		return config, errors.New("分享有效期须为永久、1、7 或 30 天")
	}
	if config.ShareCode != "" && len(config.ShareCode) != 4 {
		return config, errors.New("百度提取码须为 4 位英文字母或数字，留空自动生成")
	}
	for _, c := range config.ShareCode {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9') {
			return config, errors.New("百度提取码须为 4 位英文字母或数字")
		}
	}
	if config.RememberCredentials && !credentialProtectionAvailable() || config.StartOnLogin && !autoStartSupported() {
		return config, errors.New("当前平台不支持所选的安全记住登录或开机启动设置")
	}
	return config, nil
}

func newAutomation(a *App) (*automationManager, error) {
	m := &automationManager{app: a, state: automationState{Version: 1, Config: defaultAutomationConfig(), Page: 1, Following: 1, Candidates: []Game{}},
		wake: make(chan struct{}, 1), done: make(chan struct{}), now: time.Now,
		discover: a.github.discover, latest: a.github.latest, enqueue: a.transfers.enqueueAutomatic, maintain: a.transfers.maintainAutomatic, applyTransaction: a.applyAutomationSettingsTransaction}
	file, err := os.Open(filepath.Join(a.lib.root, "automation.json"))
	if errors.Is(err, os.ErrNotExist) {
		return m, nil
	}
	if err != nil {
		return nil, errors.New("无法读取自动运行配置")
	}
	defer file.Close()
	encoded, err := io.ReadAll(io.LimitReader(file, automationMaxBytes+1))
	var restored automationState
	if err != nil || len(encoded) > automationMaxBytes || json.Unmarshal(encoded, &restored) != nil || restored.Version != 1 {
		return nil, errors.New("自动运行记录损坏，请先备份 automation.json 再恢复")
	}
	m.state = restored
	config, err := validateAutomationConfig(m.state.Config)
	if err != nil {
		return nil, fmt.Errorf("自动运行配置无效：%w", err)
	}
	m.state.Config = config
	if m.state.Page < 1 || m.state.Page > 10 || m.state.Following < 1 || m.state.Following > 10 || len(m.state.Candidates) > 100 || m.state.Cursor < 0 || m.state.Cursor > len(m.state.Candidates) || m.state.DayCount < 0 || m.state.DayCount > 100 {
		return nil, errors.New("自动运行的分页或每日配额记录无效")
	}
	for _, value := range []string{m.state.LastRun, m.state.NextRun, m.state.ExportedAt} {
		if value != "" {
			if _, err := time.Parse(time.RFC3339, value); err != nil {
				return nil, errors.New("自动运行时间记录无效")
			}
		}
	}
	if m.state.Day != "" {
		if _, err := time.Parse("2006-01-02", m.state.Day); err != nil {
			return nil, errors.New("自动运行每日配额日期无效")
		}
	}
	for i := range m.state.Candidates {
		if err := validateGame(&m.state.Candidates[i]); err != nil || m.state.Candidates[i].Stars == nil || *m.state.Candidates[i].Stars < 0 {
			return nil, errors.New("自动发现候选记录无效")
		}
	}
	return m, nil
}

// mu must be held; memory only advances after the atomic file replacement.
func (m *automationManager) saveLocked(next automationState) error {
	encoded, err := json.MarshalIndent(next, "", "  ")
	if err != nil || len(encoded) > automationMaxBytes {
		return errors.New("自动运行记录过大或无效")
	}
	if err := automationWriteFile(m.app.lib.root, "automation.json", encoded); err != nil {
		m.storeError = "无法保存自动运行记录，请检查本地磁盘空间和权限"
		return errors.New(m.storeError)
	}
	m.state, m.storeError = next, ""
	return nil
}

func automationWriteFile(directory, name string, data []byte) error {
	file, err := os.CreateTemp(directory, ".portshelf-auto-*")
	if err != nil {
		return err
	}
	temporary := file.Name()
	defer os.Remove(temporary)
	if _, err = file.Write(data); err == nil {
		err = file.Sync()
	}
	if closeErr := file.Close(); err == nil {
		err = closeErr
	}
	if err == nil {
		err = replaceFile(temporary, filepath.Join(directory, name))
	}
	return err
}

func (m *automationManager) configSnapshot() AutomationConfig {
	m.mu.Lock()
	defer m.mu.Unlock()
	return cloneAutomationConfig(m.state.Config)
}

func (m *automationManager) status() automationStatus {
	m.mu.Lock()
	s := m.state
	result := automationStatus{Config: cloneAutomationConfig(s.Config), Running: m.running, NextRun: s.NextRun, LastRun: s.LastRun,
		ExportDir: filepath.Join(m.app.lib.root, "exports"), ExportedAt: s.ExportedAt, Discovered: s.Discovered, Queued: s.Queued, Unsupported: s.Unsupported,
		CredentialStorageSupported: credentialProtectionAvailable(), StartOnLoginSupported: autoStartSupported()}
	var messages []string
	for _, message := range []string{s.LastError, s.ExportError, m.storeError} {
		if message != "" {
			messages = append(messages, message)
		}
	}
	result.LastError = strings.Join(messages, "；")
	m.mu.Unlock()
	result.CredentialError = m.app.credentialStatus()
	return result
}

func automationSameSelection(a, b AutomationConfig) bool {
	a.Enabled, b.Enabled = false, false
	a.IntervalHours, b.IntervalHours = 0, 0
	a.DailyLimit, b.DailyLimit = 0, 0
	a.RememberCredentials, b.RememberCredentials = false, false
	a.StartOnLogin, b.StartOnLogin = false, false
	return reflect.DeepEqual(a, b)
}

func (m *automationManager) configure(config AutomationConfig) error {
	validated, err := validateAutomationConfig(config)
	if err != nil {
		return err
	}
	m.settingsMu.Lock()
	defer m.settingsMu.Unlock()
	previous := m.configSnapshot()
	persist := func() error {
		m.mu.Lock()
		defer m.mu.Unlock()
		next := m.state
		next.Config = validated
		reset := !automationSameSelection(previous, validated)
		if reset {
			next.Page, next.Following, next.Cursor, next.Candidates = 1, 1, 0, []Game{}
		}
		if !validated.Enabled {
			next.NextRun = ""
		} else if !previous.Enabled || reset || next.NextRun == "" {
			next.NextRun = m.now().UTC().Format(time.RFC3339)
		} else if previous.IntervalHours != validated.IntervalHours {
			next.NextRun = m.now().Add(time.Duration(validated.IntervalHours) * time.Hour).UTC().Format(time.RFC3339)
		}
		if err := m.saveLocked(next); err != nil {
			return err
		}
		m.revision++
		m.requested = false
		if m.stopRun != nil {
			m.stopRun()
		}
		return nil
	}
	if m.apply != nil {
		if err = m.apply(previous, validated); err != nil {
			return err
		}
		if err = persist(); err != nil {
			if rollbackErr := m.apply(validated, previous); rollbackErr != nil {
				return fmt.Errorf("%v；恢复系统设置失败：%v", err, rollbackErr)
			}
		}
	} else {
		err = m.applyTransaction(previous, validated, persist)
	}
	if err != nil {
		return err
	}
	if !validated.Enabled {
		m.maintain(validated)
	}
	m.notify()
	return nil
}

func (m *automationManager) notify() {
	select {
	case m.wake <- struct{}{}:
	default:
	}
}

func (m *automationManager) requestRun() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.state.Config.Enabled {
		return errors.New("请先启用自动模式，再立即检查")
	}
	if m.running || m.requested {
		return errors.New("自动检查已在运行或等待启动")
	}
	m.requested = true
	m.notify()
	return nil
}

func (m *automationManager) loop() {
	defer close(m.done)
	select {
	case <-m.app.ctx.Done():
		return
	case <-m.app.credentialsReady:
	}
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		m.tick()
		select {
		case <-m.app.ctx.Done():
			return
		case <-m.wake:
		case <-ticker.C:
		}
	}
}

func (m *automationManager) tick() {
	if m.app.ctx.Err() != nil {
		return
	}
	m.settingsMu.Lock()
	config := m.configSnapshot()
	m.maintain(config)
	m.settingsMu.Unlock()
	m.mu.Lock()
	due, _ := time.Parse(time.RFC3339, m.state.NextRun)
	shouldRun := config.Enabled && !m.running && (m.requested || due.IsZero() || !m.now().Before(due))
	m.mu.Unlock()
	if shouldRun {
		m.runOnce()
	}
	if m.app.ctx.Err() == nil {
		m.exportLatest()
	}
}

var errAutomationChanged = errors.New("自动运行设置已改变")

func (m *automationManager) checkpoint(revision uint64, update func(*automationState)) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if revision != m.revision || !m.state.Config.Enabled {
		return errAutomationChanged
	}
	next := m.state
	update(&next)
	return m.saveLocked(next)
}

func (m *automationManager) runOnce() {
	m.mu.Lock()
	if m.running || !m.state.Config.Enabled || m.app.ctx.Err() != nil {
		m.mu.Unlock()
		return
	}
	config, revision := cloneAutomationConfig(m.state.Config), m.revision
	ctx, cancel := context.WithTimeout(m.app.ctx, 6*time.Minute)
	m.running, m.requested, m.stopRun = true, false, cancel
	m.mu.Unlock()
	start := m.now()
	err := m.checkpoint(revision, func(state *automationState) {
		state.LastRun, state.LastError = start.UTC().Format(time.RFC3339), ""
		state.Discovered, state.Queued, state.Unsupported = 0, 0, 0
		if state.Day != start.Format("2006-01-02") {
			state.Day, state.DayCount = start.Format("2006-01-02"), 0
		}
		state.NextRun = start.Add(time.Duration(config.IntervalHours) * time.Hour).UTC().Format(time.RFC3339)
	})
	if err == nil {
		err = m.scan(ctx, revision, config)
	}
	cancel()
	m.mu.Lock()
	m.running, m.stopRun = false, nil
	if revision == m.revision && err != nil && !errors.Is(err, errAutomationChanged) && m.app.ctx.Err() == nil {
		next := m.state
		next.LastError = err.Error()
		delay := 15 * time.Minute
		var upstream *githubError
		if errors.As(err, &upstream) && (upstream.Status == http.StatusForbidden || upstream.Status == http.StatusTooManyRequests) {
			delay = time.Hour
		}
		next.NextRun = m.now().Add(delay).UTC().Format(time.RFC3339)
		_ = m.saveLocked(next)
	}
	m.mu.Unlock()
}

func (m *automationManager) scan(ctx context.Context, revision uint64, config AutomationConfig) error {
	m.mu.Lock()
	state := m.state
	m.mu.Unlock()
	if state.DayCount >= config.DailyLimit {
		return nil
	}
	if state.Cursor >= len(state.Candidates) {
		page, err := m.discover(ctx, starBounds{min: &config.MinStars, max: config.MaxStars}, state.Page)
		if err != nil {
			return err
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		if len(page.Items) > 100 {
			return errors.New("自动发现返回的项目数量超过单页上限")
		}
		games := make([]Game, 0, len(page.Items))
		seen := map[string]bool{}
		bounds := starBounds{min: &config.MinStars, max: config.MaxStars}
		for _, game := range page.Items {
			if err := validateGame(&game); err != nil || game.Stars == nil || !bounds.includes(*game.Stars) || seen[strings.ToLower(game.Repo)] {
				continue
			}
			seen[strings.ToLower(game.Repo)] = true
			games = append(games, cloneGame(game))
		}
		m.app.cacheDiscovery(games, m.now().UTC().Format(time.RFC3339))
		repos := make([]string, len(games))
		for i := range games {
			repos[i] = games[i].Repo
		}
		if result := m.app.addDiscovered(repos); len(result.Failed) != 0 {
			return errors.New("自动发现项目无法保存到目录，请检查本地磁盘空间和权限")
		}
		following := 1
		if page.HasMore && state.Page < 10 {
			following = state.Page + 1
		}
		if err := m.checkpoint(revision, func(next *automationState) {
			next.Candidates, next.Cursor, next.Following, next.Discovered = games, 0, following, len(games)
			if len(games) == 0 {
				next.Page = following
			}
		}); err != nil {
			return err
		}
	}
	requests := 0
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		m.mu.Lock()
		state = m.state
		m.mu.Unlock()
		if state.Cursor >= len(state.Candidates) || state.DayCount >= config.DailyLimit || requests >= automationReleaseBudget {
			return nil
		}
		game := state.Candidates[state.Cursor]
		release, unsupported, fetched, err := m.release(ctx, game, config.Arch)
		if fetched {
			requests++
		}
		if err != nil {
			return err
		}
		if unsupported || !m.needsTransfer(game.Repo, config, release) {
			if err := m.advance(revision, unsupported, 0); err != nil {
				return err
			}
			continue
		}
		// Reserve the daily slot before committing a task in transfers.json.
		// A crash between these two files may under-use one slot, never exceed
		// the daily cap. Transfer history makes a repeated cursor idempotent.
		day := m.now().Format("2006-01-02")
		if err := m.checkpoint(revision, func(next *automationState) {
			if next.Day != day {
				next.Day, next.DayCount = day, 0
			}
			next.DayCount++
		}); err != nil {
			return err
		}
		if err := ctx.Err(); err != nil {
			m.refund(day)
			return err
		}
		added, _, err := m.enqueue(game.Repo, config, release)
		if len(added) == 0 {
			if refundErr := m.refund(day); refundErr != nil {
				return refundErr
			}
		}
		if err != nil {
			return err
		}
		if err := m.advance(revision, false, len(added)); err != nil {
			return err
		}
	}
}

func (m *automationManager) refund(day string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	next := m.state
	if next.Day == day && next.DayCount > 0 {
		next.DayCount--
	}
	return m.saveLocked(next)
}

func (m *automationManager) advance(revision uint64, unsupported bool, queued int) error {
	return m.checkpoint(revision, func(state *automationState) {
		state.Cursor++
		state.Queued += queued
		if unsupported {
			state.Unsupported++
		}
		if state.Cursor >= len(state.Candidates) {
			state.Page, state.Cursor, state.Candidates = state.Following, 0, []Game{}
		}
	})
}

func (m *automationManager) release(ctx context.Context, game Game, arch string) (Release, bool, bool, error) {
	snapshot := m.app.lib.snapshot().Snapshots[strings.ToLower(game.Repo)]
	checked, err := time.Parse(time.RFC3339, snapshot.ReleaseCheckedAt)
	fresh := err == nil && !checked.After(m.now()) && m.now().Sub(checked) < 6*time.Hour && snapshot.Error == ""
	var release Release
	fetched := false
	if fresh {
		if snapshot.Release == nil {
			return Release{}, true, false, nil
		}
		release, err = prepareRelease(game.Repo, *snapshot.Release, arch)
	} else {
		fetched = true
		release, err = m.latest(ctx, game.Repo, arch)
		var upstream *githubError
		if err != nil && (!errors.As(err, &upstream) || upstream.Status != http.StatusNotFound) {
			return Release{}, false, fetched, err
		}
		snapshot.Release, snapshot.Error, snapshot.ReleaseCheckedAt = nil, "", m.now().UTC().Format(time.RFC3339)
		if err == nil {
			snapshot.Release = &release
		}
		if game.Stars != nil {
			snapshot.Stars, snapshot.StarsCheckedAt = *game.Stars, m.now().UTC().Format(time.RFC3339)
		}
		if err := m.app.lib.updateSnapshot(game.Repo, snapshot); err != nil {
			return Release{}, false, fetched, errors.New("无法保存正式发布信息，请检查本地磁盘空间和权限")
		}
		if snapshot.Release == nil {
			return Release{}, true, fetched, nil
		}
	}
	if err != nil {
		return Release{}, false, fetched, err
	}
	return release, automationAsset(release, arch) == nil, fetched, nil
}

func automationAsset(release Release, arch string) *Asset {
	selected, _ := selectTransferAsset(release, arch)
	return selected
}

func (m *automationManager) needsTransfer(repo string, config AutomationConfig, release Release) bool {
	asset := automationAsset(release, config.Arch)
	if asset == nil {
		return false
	}
	candidate := TransferJob{Repo: repo, Arch: config.Arch, Providers: config.Providers, Enrich: config.Enrich,
		ShareOptions: ShareOptions{Days: config.ShareDays, Code: config.ShareCode, Private: config.PrivateShare}}
	jobs, _ := m.app.transfers.snapshot()
	for i := len(jobs) - 1; i >= 0; i-- {
		job := jobs[i]
		if !sameTransfer(candidate, job) || job.Version != release.Tag || job.Asset == nil || job.Asset.ID != asset.ID || job.Asset.URL != asset.URL || job.Asset.Size != asset.Size || job.Asset.Digest != asset.Digest {
			continue
		}
		// User cancellation and exhausted/failed tasks are durable suppressions.
		// Retry policy belongs to maintainAutomatic; discovery never creates an
		// unbounded replacement stream for the same release and profile.
		if job.Status != "done" {
			return false
		}
		valid := true
		for _, provider := range config.Providers {
			output := job.Outputs[provider]
			valid = valid && output.Status == "done" && usableCloudShare(provider, output.Share)
		}
		if valid {
			return false
		}
	}
	return true
}
