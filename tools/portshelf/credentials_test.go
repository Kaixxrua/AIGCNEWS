package main

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

type credentialTestDrive struct {
	check       func(context.Context) (string, error)
	credentials CloudCredentials
}

func (d *credentialTestDrive) Check(ctx context.Context) (string, error) {
	return d.check(ctx)
}
func (d *credentialTestDrive) Upload(context.Context, string, string, UploadProgress) (CloudFile, error) {
	return CloudFile{}, errors.New("unexpected test upload")
}
func (d *credentialTestDrive) Share(context.Context, CloudFile, ShareOptions) (CloudShare, error) {
	return CloudShare{}, errors.New("unexpected test share")
}
func (d *credentialTestDrive) credentialsSnapshot() CloudCredentials { return d.credentials }

// Build an isolated app without background workers or real DPAPI/registry calls.
func newCredentialTestApp(t *testing.T) *App {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	app := &App{lib: testLibrary(t), github: newGitHub(""), aigc: newAIGC(), cloud: newCloudRegistry(), ctx: ctx, cancel: cancel}
	var err error
	app.transfers, err = newTransferManager(app)
	if err != nil {
		t.Fatal(err)
	}
	app.credentials = newCredentials(app, credentialTestConfig())
	app.credentials.vault = newTestCredentialVault(t)
	app.credentials.vault.root = app.lib.root
	app.credentials.startSupported = true
	app.credentials.setStart = func(string, bool) error { return nil }
	return app
}

func credentialTestConfig() AutomationConfig {
	return AutomationConfig{Enabled: true, RememberCredentials: true, StartOnLogin: true}
}

func installSavedTestCredentials(t *testing.T, app *App, saved savedCredentials) []byte {
	t.Helper()
	if err := app.credentials.vault.save(saved); err != nil {
		t.Fatal(err)
	}
	app.credentials.hasVault = true
	encoded, err := os.ReadFile(filepath.Join(app.lib.root, credentialVaultFile))
	if err != nil {
		t.Fatal(err)
	}
	return encoded
}

func TestCredentialsDamagedVaultRequiresExplicitForget(t *testing.T) {
	app := newCredentialTestApp(t)
	m := app.credentials
	path := filepath.Join(app.lib.root, credentialVaultFile)
	damaged := []byte(credentialVaultMagic + "damaged-encrypted-data")
	if err := os.WriteFile(path, damaged, 0600); err != nil {
		t.Fatal(err)
	}
	m.hasVault = true
	m.load()
	if !m.loadFailed || app.credentialStatus() == "" {
		t.Fatal("damaged vault did not block writes")
	}
	app.github.setToken("new-memory-token")
	m.persist()
	startCalls := 0
	m.setStart = func(string, bool) error { startCalls++; return nil }
	if err := app.applyAutomationSettings(credentialTestConfig(), credentialTestConfig()); err == nil {
		t.Fatal("settings overwrote unreadable vault")
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(after, damaged) || startCalls != 0 {
		t.Fatalf("blocked save changed disk or startup: %v", err)
	}
	forget := credentialTestConfig()
	forget.RememberCredentials = false
	if err := app.applyAutomationSettingsTransaction(credentialTestConfig(), forget, func() error { return errors.New("config unavailable") }); err == nil {
		t.Fatal("configuration failure ignored")
	}
	after, err = os.ReadFile(path)
	if err != nil || !bytes.Equal(after, damaged) || !m.loadFailed || !m.remember {
		t.Fatalf("failed forget did not restore original damaged vault: %v", err)
	}
	if err := app.applyAutomationSettings(credentialTestConfig(), forget); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) || m.loadFailed || m.hasVault || m.remember {
		t.Fatalf("explicit forget failed: %v", err)
	}
}

func TestCredentialsLoadAndRestoreKeepSessionAndOfflineAccounts(t *testing.T) {
	app := newCredentialTestApp(t)
	m := app.credentials
	saved := vaultTestCredentials()
	delete(saved.Clouds, "quark")
	installSavedTestCredentials(t, app, saved)
	app.github.setToken("already-installed-token")
	m.load()
	if !app.aigc.hasToken() || app.github.token != "already-installed-token" || !reflect.DeepEqual(m.pending, saved.Clouds) {
		t.Fatal("startup load replaced a token or lost pending accounts")
	}
	online := false
	app.cloud.factory = func(_ string, credentials CloudCredentials) CloudDrive {
		return &credentialTestDrive{credentials: credentials, check: func(context.Context) (string, error) {
			if !online {
				return "", errors.New("测试离线")
			}
			return "restored account", nil
		}}
	}
	m.restorePending()
	m.persist()
	disk, err := m.vault.load()
	if err != nil || !reflect.DeepEqual(disk.Clouds, saved.Clouds) || len(m.pending) != 1 {
		t.Fatalf("offline restore lost saved credentials: %v", err)
	}
	online = true
	m.restorePending()
	account, ok := app.cloud.get("baidu")
	if !ok || account.session != saved.Clouds["baidu"].Session || len(m.pending) != 0 {
		t.Fatal("same account restore changed session or remained pending")
	}
	m.persist()
	disk, err = m.vault.load()
	if err != nil || disk.Clouds["baidu"].Session != account.session || disk.Clouds["baidu"].Credentials != saved.Clouds["baidu"].Credentials {
		t.Fatalf("restored account not saved with stable session: %v", err)
	}
}

func TestCredentialsInvalidSavedAuthorizationIsNotPartiallyApplied(t *testing.T) {
	app := newCredentialTestApp(t)
	saved := vaultTestCredentials()
	quark := saved.Clouds["quark"]
	quark.Credentials.AuthCode = "one-use-code"
	saved.Clouds["quark"] = quark
	before := installSavedTestCredentials(t, app, saved)
	app.credentials.load()
	app.credentials.persist()
	after, err := os.ReadFile(filepath.Join(app.lib.root, credentialVaultFile))
	if err != nil || !bytes.Equal(before, after) || !app.credentials.loadFailed || app.github.hasToken() || app.aigc.hasToken() {
		t.Fatalf("invalid saved authorization partially loaded or rewritten: %v", err)
	}
}

func TestCredentialsPendingRestoreCannotOverwriteNewAccountOrDisconnect(t *testing.T) {
	for _, disconnect := range []bool{false, true} {
		t.Run(map[bool]string{false: "new-account", true: "disconnect"}[disconnect], func(t *testing.T) {
			app := newCredentialTestApp(t)
			m := app.credentials
			m.pending["baidu"] = vaultTestCredentials().Clouds["baidu"]
			started, release, finished := make(chan struct{}), make(chan struct{}), make(chan struct{})
			app.cloud.factory = func(_ string, credentials CloudCredentials) CloudDrive {
				return &credentialTestDrive{credentials: credentials, check: func(ctx context.Context) (string, error) {
					close(started)
					select {
					case <-release:
						return "old account", nil
					case <-ctx.Done():
						return "", ctx.Err()
					}
				}}
			}
			go func() { m.restorePending(); close(finished) }()
			<-started
			newAccount := &cloudAccount{drive: &credentialTestDrive{}, account: "new account", session: strings.Repeat("c", 48), credentials: CloudCredentials{Cookie: "new-cookie"}}
			if disconnect {
				newAccount = nil
			}
			if !app.setCloudAccount("baidu", newAccount) {
				t.Fatal("idle account change refused")
			}
			close(release)
			<-finished
			active, exists := app.cloud.get("baidu")
			if disconnect && exists || !disconnect && (!exists || active.account != "new account" || active.session != newAccount.session) || len(m.pending) != 0 {
				t.Fatal("late pending restoration resurrected or replaced an account")
			}
		})
	}
}

func TestCredentialsSettingsTransactionRestoresExactState(t *testing.T) {
	for _, hadVault := range []bool{false, true} {
		t.Run(map[bool]string{false: "new-vault", true: "existing-vault"}[hadVault], func(t *testing.T) {
			app := newCredentialTestApp(t)
			m := app.credentials
			saved := vaultTestCredentials()
			var before []byte
			if hadVault {
				before = installSavedTestCredentials(t, app, saved)
			}
			m.pending["baidu"] = saved.Clouds["baidu"]
			app.github.setToken("changed-token")
			var startup []bool
			m.setStart = func(_ string, enabled bool) error { startup = append(startup, enabled); return nil }
			next := credentialTestConfig()
			next.StartOnLogin = false
			if hadVault {
				next.RememberCredentials = false
			}
			err := app.applyAutomationSettingsTransaction(credentialTestConfig(), next, func() error {
				if !m.remember || !m.enabled || len(m.pending) != 1 {
					t.Fatal("manager state published before config commit")
				}
				return errors.New("config commit failed")
			})
			if err == nil || !reflect.DeepEqual(startup, []bool{false, true}) || m.hasVault != hadVault || !m.remember || !m.startOnLogin || len(m.pending) != 1 {
				t.Fatalf("transaction failed to restore settings: %v", err)
			}
			after, readErr := os.ReadFile(filepath.Join(app.lib.root, credentialVaultFile))
			if hadVault && (readErr != nil || !bytes.Equal(before, after)) || !hadVault && !errors.Is(readErr, os.ErrNotExist) {
				t.Fatalf("transaction did not restore exact prior file: %v", readErr)
			}
		})
	}
}

func TestCredentialsSettingsStartupOrVaultFailureDoesNotPublish(t *testing.T) {
	for _, failure := range []string{"startup", "vault"} {
		t.Run(failure, func(t *testing.T) {
			app := newCredentialTestApp(t)
			m := app.credentials
			before := installSavedTestCredentials(t, app, vaultTestCredentials())
			calls, commits := 0, 0
			m.setStart = func(string, bool) error {
				calls++
				if failure == "startup" {
					return errors.New("startup unavailable")
				}
				return nil
			}
			if failure == "vault" {
				m.vault.protect = func([]byte) ([]byte, error) { return nil, errors.New("raw-secret-encryption-error") }
			}
			next := credentialTestConfig()
			next.StartOnLogin = false
			err := app.applyAutomationSettingsTransaction(credentialTestConfig(), next, func() error { commits++; return nil })
			after, readErr := os.ReadFile(filepath.Join(app.lib.root, credentialVaultFile))
			if err == nil || strings.Contains(err.Error(), "raw-secret") || readErr != nil || !bytes.Equal(before, after) || commits != 0 || !m.startOnLogin || !m.hasVault {
				t.Fatalf("failed side effect published config or lost original vault: %v", err)
			}
			if failure == "vault" && calls != 2 || failure == "startup" && calls != 1 {
				t.Fatalf("startup rollback calls = %d", calls)
			}
		})
	}
}

func TestCredentialsRefreshDuringSettingsCommitIsNotLost(t *testing.T) {
	for _, commitFails := range []bool{false, true} {
		t.Run(map[bool]string{false: "forget-commits", true: "forget-rolls-back"}[commitFails], func(t *testing.T) {
			app := newCredentialTestApp(t)
			m := app.credentials
			drive := newQuarkDrive(CloudCredentials{AccessToken: "old-access", RefreshToken: "old-refresh", DeviceID: "device", UserID: "user1"}).(*quarkDrive)
			app.watchCloudCredentials(drive)
			if !app.setCloudAccount("quark", &cloudAccount{drive: drive, account: "account", session: strings.Repeat("b", 48)}) {
				t.Fatal("could not install account")
			}
			m.persist()
			entered, finish := make(chan struct{}), make(chan struct{})
			result := make(chan error, 1)
			next := credentialTestConfig()
			next.RememberCredentials = false
			go func() {
				result <- app.applyAutomationSettingsTransaction(credentialTestConfig(), next, func() error {
					close(entered)
					<-finish
					if commitFails {
						return errors.New("config failure")
					}
					return nil
				})
			}()
			<-entered
			drive.mu.Lock()
			drive.token, drive.refresh = "new-access", "new-refresh"
			drive.mu.Unlock()
			refreshed := make(chan struct{})
			go func() { drive.credentialsChanged(); close(refreshed) }()
			persisted := make(chan struct{})
			go func() { m.persist(); close(persisted) }()
			select {
			case <-persisted:
				t.Fatal("credential save bypassed settings transaction")
			default:
			}
			close(finish)
			if err := <-result; (err != nil) != commitFails {
				t.Fatalf("unexpected transaction result: %v", err)
			}
			<-refreshed
			<-persisted
			if commitFails {
				saved, err := m.vault.load()
				if err != nil || saved.Clouds["quark"].Credentials.AccessToken != "new-access" || saved.Clouds["quark"].Credentials.RefreshToken != "new-refresh" {
					t.Fatalf("refresh lost after settings rollback: %v", err)
				}
			} else if _, err := os.Stat(filepath.Join(app.lib.root, credentialVaultFile)); !errors.Is(err, os.ErrNotExist) {
				t.Fatalf("concurrent save resurrected forgotten vault: %v", err)
			}
		})
	}
}

func TestCredentialsRollbackFailureStopsFutureVaultWrites(t *testing.T) {
	app := newCredentialTestApp(t)
	m := app.credentials
	installSavedTestCredentials(t, app, vaultTestCredentials())
	replace := m.vault.replace
	calls := 0
	m.vault.replace = func(root *os.Root, source, target string) error {
		calls++
		if calls > 1 {
			return errors.New("rollback disk failure")
		}
		return replace(root, source, target)
	}
	err := app.applyAutomationSettingsTransaction(credentialTestConfig(), credentialTestConfig(), func() error { return errors.New("config failure") })
	if err == nil || !m.loadFailed || app.credentialStatus() == "" {
		t.Fatal("rollback error silently ignored")
	}
	m.persist()
	if calls != 2 {
		t.Fatal("failed rollback did not block subsequent writes")
	}
}

func TestCredentialsStartupRefreshAndErrorSurviveVaultSave(t *testing.T) {
	app := newCredentialTestApp(t)
	m := app.credentials
	calls := 0
	m.setStart = func(root string, enabled bool) error {
		calls++
		if root != app.lib.root || !enabled {
			t.Error("startup refresh changed unrelated entry")
		}
		return errors.New("startup registration unavailable")
	}
	m.syncAutoStart()
	m.persist()
	if calls != 1 || !strings.Contains(app.credentialStatus(), "登录启动") {
		t.Fatal("startup update failure disappeared after vault save")
	}
	m.enabled = false
	m.syncAutoStart()
	if calls != 1 {
		t.Fatal("disabled automation wrote a startup entry")
	}
}

func TestCredentialsConcurrentNotificationsAndSnapshots(t *testing.T) {
	app := newCredentialTestApp(t)
	m := app.credentials
	drive := newQuarkDrive(CloudCredentials{AccessToken: "initial", RefreshToken: "refresh", DeviceID: "device", UserID: "user1"}).(*quarkDrive)
	app.watchCloudCredentials(drive)
	if !app.setCloudAccount("quark", &cloudAccount{drive: drive, session: strings.Repeat("a", 48)}) {
		t.Fatal("could not install account")
	}
	var group sync.WaitGroup
	for worker := 0; worker < 4; worker++ {
		group.Add(1)
		go func() {
			defer group.Done()
			for i := 0; i < 10; i++ {
				drive.mu.Lock()
				drive.expires = time.Now().Add(time.Hour)
				drive.mu.Unlock()
				drive.credentialsChanged()
				m.persist()
				_ = app.credentialStatus()
			}
		}()
	}
	group.Wait()
	saved, err := m.vault.load()
	if err != nil || saved.Clouds["quark"].Credentials.RefreshToken != "refresh" {
		t.Fatalf("concurrent saves produced invalid state: %v", err)
	}
}
