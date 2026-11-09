package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// Tokens are restored only from the current Windows user's encrypted vault.
// Pending accounts remain in the vault if the network is temporarily offline.
type credentialManager struct {
	mu                          sync.Mutex
	restoreMu                   sync.Mutex
	app                         *App
	vault                       *credentialVault
	enabled, remember, hasVault bool
	startOnLogin                bool
	loadFailed                  bool
	pending                     map[string]savedCloud
	lastError                   string
	startupError                string
	startSupported              bool
	setStart                    func(string, bool) error
	wake, ready, done           chan struct{}
}

func newCredentials(a *App, config AutomationConfig) *credentialManager {
	_, err := os.Lstat(filepath.Join(a.lib.root, credentialVaultFile))
	return &credentialManager{app: a, vault: newCredentialVault(a.lib.root), enabled: config.Enabled, remember: config.RememberCredentials,
		hasVault: !errors.Is(err, os.ErrNotExist), startOnLogin: config.StartOnLogin, startSupported: autoStartSupported(), setStart: setAutoStart,
		pending: map[string]savedCloud{}, wake: make(chan struct{}, 1), ready: make(chan struct{}), done: make(chan struct{})}
}

func (a *App) credentialStatus() string {
	if a.credentials == nil {
		return ""
	}
	a.credentials.mu.Lock()
	defer a.credentials.mu.Unlock()
	var messages []string
	for _, message := range []string{a.credentials.lastError, a.credentials.startupError} {
		if message != "" {
			messages = append(messages, message)
		}
	}
	return strings.Join(messages, "；")
}

func (a *App) credentialsChanged() {
	if a.credentials == nil {
		return
	}
	select {
	case a.credentials.wake <- struct{}{}:
	default:
	}
}

func (a *App) watchCloudCredentials(drive CloudDrive) {
	if d, ok := drive.(*quarkDrive); ok {
		d.mu.Lock()
		d.credentialChanged = func() {
			// A rotated refresh token can invalidate its predecessor. Persist it
			// before the next cloud request rather than waiting for the loop.
			if a.credentials != nil {
				a.credentials.persist()
			}
		}
		d.mu.Unlock()
	}
}
func (d *quarkDrive) credentialsChanged() {
	d.mu.Lock()
	callback := d.credentialChanged
	d.mu.Unlock()
	if callback != nil {
		callback()
	}
}
func (d *quarkDrive) credentialsSnapshot() CloudCredentials {
	d.mu.Lock()
	defer d.mu.Unlock()
	expiry := ""
	if !d.expires.IsZero() {
		expiry = d.expires.UTC().Format(time.RFC3339)
	}
	return CloudCredentials{AccessToken: d.token, RefreshToken: d.refresh, DeviceID: d.deviceID, ExpiresAt: expiry, UserID: d.userID}
}
func (d *baiduDrive) credentialsSnapshot() CloudCredentials {
	return CloudCredentials{Cookie: d.cookie}
}

func (m *credentialManager) snapshotLocked() savedCredentials {
	result := savedCredentials{Clouds: map[string]savedCloud{}}
	m.app.github.mu.RLock()
	result.GitHubToken = m.app.github.token
	m.app.github.mu.RUnlock()
	m.app.aigc.mu.RLock()
	result.AIGCToken = m.app.aigc.token
	m.app.aigc.mu.RUnlock()
	for provider, account := range m.pending {
		result.Clouds[provider] = account
	}
	m.app.cloud.mu.RLock()
	defer m.app.cloud.mu.RUnlock()
	for provider, account := range m.app.cloud.accounts {
		credentials := account.credentials
		if d, ok := account.drive.(interface{ credentialsSnapshot() CloudCredentials }); ok {
			credentials = d.credentialsSnapshot()
		}
		// One-use authorization codes are never a usable restart credential.
		credentials.AuthCode = ""
		if credentials.Cookie != "" || credentials.AccessToken != "" {
			result.Clouds[provider] = savedCloud{Credentials: credentials, Session: account.session, Account: account.account}
		}
	}
	return result
}

func (a *App) setCloudAccount(provider string, account *cloudAccount) bool {
	if a.credentials == nil {
		return a.transfers.setCloudAccount(provider, account)
	}
	a.credentials.mu.Lock()
	defer a.credentials.mu.Unlock()
	if !a.transfers.setCloudAccount(provider, account) {
		return false
	}
	delete(a.credentials.pending, provider)
	return true
}

func (m *credentialManager) persist() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.persistLocked()
}

func (m *credentialManager) persistLocked() {
	if m.loadFailed || !m.vault.available || !m.remember || (!m.enabled && !m.hasVault) {
		return
	}
	if err := m.vault.save(m.snapshotLocked()); err != nil {
		m.lastError = "保存登录授权失败：" + err.Error()
		return
	}
	m.hasVault = true
	// A pending login failure still requires attention even if disk writing works.
	if len(m.pending) == 0 {
		m.lastError = ""
	}
}

func (m *credentialManager) load() {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.vault.available || !m.remember || !m.hasVault {
		return
	}
	secrets, err := m.vault.load()
	if err != nil {
		m.loadFailed = true
		m.lastError = "读取保存的登录授权失败：" + err.Error()
		return
	}
	if !validToken(secrets.GitHubToken) || !validAIGCToken(secrets.AIGCToken) {
		m.loadFailed = true
		m.lastError = "保存的登录信息无效，请重新连接"
		return
	}
	for provider, account := range secrets.Clouds {
		c := account.Credentials
		if !validDrive(provider) || !validCloudCredentials(c) || !sessionTokenPattern.MatchString(account.Session) || c.AuthCode != "" {
			m.loadFailed = true
			m.lastError = "保存的网盘授权无效，请重新连接"
			return
		}
	}
	// newApp calls load before publishing the HTTP service. Retain any token
	// already installed by an embedding caller instead of replacing it.
	m.app.github.mu.Lock()
	if m.app.github.token == "" {
		m.app.github.token = secrets.GitHubToken
	}
	m.app.github.mu.Unlock()
	m.app.aigc.mu.Lock()
	if m.app.aigc.token == "" {
		m.app.aigc.token = secrets.AIGCToken
	}
	m.app.aigc.mu.Unlock()
	for provider, account := range secrets.Clouds {
		if _, exists := m.app.cloud.get(provider); exists {
			continue
		}
		m.pending[provider] = account
	}
}

// Rotation may succeed before the subsequent account lookup fails. Save the
// replacement refresh token while this attempt still owns the pending session.
func (m *credentialManager) watchPendingCredentials(id string, saved savedCloud, drive CloudDrive) {
	d, ok := drive.(*quarkDrive)
	if !ok {
		m.app.watchCloudCredentials(drive)
		return
	}
	d.mu.Lock()
	d.credentialChanged = func() {
		m.mu.Lock()
		defer m.mu.Unlock()
		pending, exists := m.pending[id]
		if !exists || pending.Session != saved.Session || !m.remember {
			return
		}
		pending.Credentials = d.credentialsSnapshot()
		m.pending[id] = pending
		m.persistLocked()
	}
	d.mu.Unlock()
}

func (m *credentialManager) restorePending() {
	m.restoreMu.Lock()
	defer m.restoreMu.Unlock()
	m.mu.Lock()
	accounts := map[string]savedCloud{}
	if m.enabled && m.remember {
		for id, account := range m.pending {
			accounts[id] = account
		}
	}
	m.mu.Unlock()
	for id, saved := range accounts {
		if m.app.ctx.Err() != nil {
			return
		}
		if _, ok := m.app.cloud.get(id); ok {
			continue
		}
		ctx, cancel := context.WithTimeout(m.app.ctx, 20*time.Second)
		drive := m.app.cloud.factory(id, saved.Credentials)
		if drive == nil {
			cancel()
			continue
		}
		m.watchPendingCredentials(id, saved, drive)
		name, err := drive.Check(ctx)
		cancel()
		m.mu.Lock()
		pending, stillPending := m.pending[id]
		if !stillPending || pending.Session != saved.Session || !m.enabled || !m.remember {
			m.mu.Unlock()
			continue
		}
		if err != nil {
			m.lastError = "自动恢复网盘连接失败：" + err.Error()
			m.mu.Unlock()
			continue
		}
		installed := false
		if _, exists := m.app.cloud.get(id); !exists && m.app.transfers.setCloudAccount(id, &cloudAccount{drive: drive, account: name, credentials: pending.Credentials, session: saved.Session}) {
			delete(m.pending, id)
			m.app.watchCloudCredentials(drive)
			installed = true
			if len(m.pending) == 0 {
				m.lastError = ""
			}
		}
		m.mu.Unlock()
		if installed {
			m.app.transfers.credentialsAvailable(id)
		}
	}
}

func (m *credentialManager) loop() {
	defer close(m.done)
	m.syncAutoStart()
	m.restorePending()
	m.persist()
	close(m.ready)
	timer := time.NewTicker(5 * time.Minute)
	defer timer.Stop()
	for {
		select {
		case <-m.app.ctx.Done():
			m.persist()
			return
		case <-m.wake:
			m.persist()
			m.restorePending()
			m.persist()
		case <-timer.C:
			m.restorePending()
			m.persist()
		}
	}
}

func (m *credentialManager) syncAutoStart() {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.enabled || !m.startOnLogin {
		return
	}
	if !m.startSupported || m.setStart == nil {
		m.startupError = "当前系统不支持 Windows 登录启动"
	} else if err := m.setStart(m.app.lib.root, true); err != nil {
		m.startupError = "更新登录启动项失败：" + err.Error()
	} else {
		m.startupError = ""
	}
}

func (a *App) applyAutomationSettings(previous, next AutomationConfig) error {
	return a.applyAutomationSettingsTransaction(previous, next, func() error { return nil })
}

// The automation settings lock surrounds this call. Its persist callback takes
// only automation.mu; no caller may hold automation.mu while entering here.
// Manager state is published only after vault, startup and config all succeed.
func (a *App) applyAutomationSettingsTransaction(previous, next AutomationConfig, persist func() error) error {
	m := a.credentials
	if m == nil {
		return errors.New("登录管理器尚未就绪")
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if next.RememberCredentials && !m.vault.available {
		return errors.New("当前系统不支持安全保存登录，请取消记住凭据后运行")
	}
	if next.StartOnLogin && (!m.startSupported || m.setStart == nil) {
		return errors.New("当前系统不支持 Windows 登录启动")
	}
	if next.RememberCredentials && next.Enabled && m.loadFailed {
		return errors.New("已保存的登录授权无法读取，未覆盖原文件；请先关闭记住凭据以清除，再重新连接")
	}
	changeVault := m.vault.available && (!next.RememberCredentials || next.Enabled)
	var before credentialVaultCheckpoint
	var err error
	if changeVault {
		before, err = m.vault.checkpoint()
		if err != nil {
			return err
		}
	}
	startChanged := m.startSupported && m.setStart != nil
	if startChanged {
		if err := m.setStart(a.lib.root, next.Enabled && next.StartOnLogin); err != nil {
			return err
		}
	}
	vaultChanged := false
	rollback := func(cause error) error {
		var rollbackErrors []error
		if vaultChanged {
			if restoreErr := m.vault.restoreCheckpoint(before); restoreErr != nil {
				m.loadFailed = true
				m.lastError = "恢复原有加密凭据失败，请检查磁盘空间和权限；已暂停自动保存"
				rollbackErrors = append(rollbackErrors, errors.New(m.lastError))
			}
		}
		if startChanged {
			if restoreErr := m.setStart(a.lib.root, previous.Enabled && previous.StartOnLogin); restoreErr != nil {
				m.startupError = "恢复原有登录启动设置失败，请重新保存设置"
				rollbackErrors = append(rollbackErrors, errors.New(m.startupError))
			}
		}
		return errors.Join(append([]error{cause}, rollbackErrors...)...)
	}
	if changeVault {
		if !next.RememberCredentials {
			err = m.vault.clear()
		} else {
			err = m.vault.save(m.snapshotLocked())
		}
		if err != nil {
			return rollback(err)
		}
		vaultChanged = true
	}
	if persist == nil {
		return rollback(errors.New("自动运行配置保存器不可用"))
	}
	if err := persist(); err != nil {
		return rollback(err)
	}
	if changeVault {
		m.hasVault = next.RememberCredentials
	}
	m.enabled, m.remember, m.startOnLogin = next.Enabled, next.RememberCredentials, next.StartOnLogin
	m.startupError = ""
	if !next.RememberCredentials {
		m.pending = map[string]savedCloud{}
		m.loadFailed = false
		m.lastError = ""
	}
	a.credentialsChanged()
	return nil
}

// A settings rollback restores the exact previous opaque file. It never
// decrypts credentials to disk, and can preserve a damaged vault after a failed
// explicit "forget" operation without overwriting it with a partial snapshot.
type credentialVaultCheckpoint struct {
	exists  bool
	encoded []byte
}

func (v *credentialVault) checkpoint() (credentialVaultCheckpoint, error) {
	v.mu.Lock()
	defer v.mu.Unlock()
	var result credentialVaultCheckpoint
	root, err := v.open()
	if err != nil {
		return result, err
	}
	defer root.Close()
	info, err := root.Lstat(credentialVaultFile)
	if errors.Is(err, os.ErrNotExist) {
		return result, nil
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() > maxCredentialCiphertext {
		return result, errors.New("无法安全备份原有凭据文件，未修改登录设置")
	}
	file, err := root.Open(credentialVaultFile)
	if err != nil {
		return result, errors.New("无法读取原有凭据文件，未修改登录设置")
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return result, errors.New("原有凭据文件发生变化，未修改登录设置")
	}
	encoded, err := io.ReadAll(io.LimitReader(file, maxCredentialCiphertext+1))
	if err != nil || len(encoded) > maxCredentialCiphertext {
		return result, errors.New("无法备份原有凭据文件，未修改登录设置")
	}
	return credentialVaultCheckpoint{exists: true, encoded: encoded}, nil
}

func (v *credentialVault) restoreCheckpoint(checkpoint credentialVaultCheckpoint) error {
	if !checkpoint.exists {
		return v.clear()
	}
	v.mu.Lock()
	defer v.mu.Unlock()
	root, err := v.open()
	if err != nil {
		return err
	}
	defer root.Close()
	if info, statErr := root.Lstat(credentialVaultFile); statErr == nil {
		if !info.Mode().IsRegular() {
			return errors.New("凭据文件位置已改变，无法恢复")
		}
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return errors.New("无法核对凭据文件位置")
	}
	var random [16]byte
	if _, err := rand.Read(random[:]); err != nil {
		return errors.New("无法生成恢复文件名")
	}
	name := ".credentials-rollback-" + hex.EncodeToString(random[:]) + ".tmp"
	file, err := root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return errors.New("无法写入凭据恢复文件")
	}
	defer root.Remove(name)
	_, err = file.Write(checkpoint.encoded)
	if err == nil {
		err = file.Sync()
	}
	if closeErr := file.Close(); err == nil {
		err = closeErr
	}
	if err == nil {
		err = v.replace(root, name, credentialVaultFile)
	}
	if err != nil {
		return errors.New("无法恢复原有凭据文件")
	}
	return nil
}
