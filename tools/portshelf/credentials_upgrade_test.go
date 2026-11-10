package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func credentialUpgradeConfig(remember bool) AutomationConfig {
	config := credentialTestConfig()
	config.Enabled, config.StartOnLogin, config.RememberCredentials = false, false, remember
	return config
}

// Each instance has fresh in-memory managers. Reusing only the data directory
// and test encryption key models the same Windows user launching a new build.
func credentialUpgradeApp(t *testing.T, config AutomationConfig, previous *App) *App {
	t.Helper()
	app := newCredentialTestApp(t)
	vault := app.credentials.vault
	if previous != nil {
		var err error
		app.lib, err = newLibrary(previous.lib.root)
		if err != nil {
			t.Fatal(err)
		}
		app.transfers, err = newTransferManager(app)
		if err != nil {
			t.Fatal(err)
		}
		vault.protect, vault.unprotect = previous.credentials.vault.protect, previous.credentials.vault.unprotect
	}
	app.credentials = newCredentials(app, config)
	vault.root = app.lib.root
	app.credentials.vault = vault
	app.credentials.startSupported = true
	app.credentials.setStart = func(string, bool) error { return nil }
	app.host, app.token = "127.0.0.1:12345", randomID()
	return app
}

func installUpgradeMemoryAccounts(t *testing.T, app *App, saved savedCredentials) {
	t.Helper()
	app.github.setToken(saved.GitHubToken)
	app.aigc.setToken(saved.AIGCToken)
	for id, cloud := range saved.Clouds {
		drive := &credentialTestDrive{credentials: cloud.Credentials, check: func(context.Context) (string, error) { return "local test account", nil }}
		if !app.setCloudAccount(id, &cloudAccount{drive: drive, account: cloud.Account, credentials: cloud.Credentials, session: cloud.Session}) {
			t.Fatal("could not install idle test account")
		}
	}
}

func restoreUpgradeAccounts(t *testing.T, app *App, saved savedCredentials) {
	t.Helper()
	checks := map[string]int{}
	app.cloud.factory = func(id string, credentials CloudCredentials) CloudDrive {
		expected, ok := saved.Clouds[id]
		if !ok || credentials != expected.Credentials {
			t.Fatal("restore did not use the saved provider authorization")
		}
		return &credentialTestDrive{credentials: credentials, check: func(context.Context) (string, error) {
			checks[id]++
			return expected.Account, nil
		}}
	}
	app.credentials.load()
	app.credentials.restorePending()
	for id, expected := range saved.Clouds {
		actual, ok := app.cloud.get(id)
		if !ok || checks[id] != 1 || actual.session != expected.Session || actual.credentials != expected.Credentials {
			t.Fatalf("%s account/session was not restored across upgrade", id)
		}
	}
	if app.github.token != saved.GitHubToken || app.aigc.token != saved.AIGCToken || len(app.credentials.pending) != 0 {
		t.Fatal("upgrade lost a token or left successfully restored accounts pending")
	}
}

func TestCredentialsUpgradeDisabledAutomationPersistsAndRestoresBothAccounts(t *testing.T) {
	config := credentialUpgradeConfig(true)
	first := credentialUpgradeApp(t, config, nil)
	saved := vaultTestCredentials()
	installUpgradeMemoryAccounts(t, first, saved)
	first.credentials.persist()
	encoded, err := os.ReadFile(filepath.Join(first.lib.root, credentialVaultFile))
	if err != nil || !first.credentials.hasVault || first.credentials.enabled {
		t.Fatalf("first login with automation off was not saved: %v", err)
	}
	assertVaultCiphertext(t, encoded)
	first.cancel()
	restarted := credentialUpgradeApp(t, config, first)
	restoreUpgradeAccounts(t, restarted, saved)
	restarted.credentials.persist()
	disk, err := restarted.credentials.vault.load()
	if err != nil || !reflect.DeepEqual(disk, saved) || restarted.credentials.enabled {
		t.Fatalf("restart changed remembered credentials or enabled scanning: %v", err)
	}
}

func TestCredentialsUpgradeRememberCanBeSavedBeforeEnablingAutomation(t *testing.T) {
	for _, failCommit := range []bool{false, true} {
		t.Run(map[bool]string{false: "commit", true: "rollback"}[failCommit], func(t *testing.T) {
			previous := credentialUpgradeConfig(false)
			app := credentialUpgradeApp(t, previous, nil)
			saved := vaultTestCredentials()
			installUpgradeMemoryAccounts(t, app, saved)
			next := credentialUpgradeConfig(true)
			commits := 0
			err := app.applyAutomationSettingsTransaction(previous, next, func() error {
				commits++
				if failCommit {
					return errors.New("test configuration write failure")
				}
				return nil
			})
			if (err != nil) != failCommit || commits != 1 || app.credentials.enabled {
				t.Fatal("disabled remember setting did not follow its config transaction")
			}
			if failCommit {
				if _, statErr := os.Stat(filepath.Join(app.lib.root, credentialVaultFile)); !errors.Is(statErr, os.ErrNotExist) || app.credentials.remember || app.credentials.hasVault {
					t.Fatal("failed remember transaction left a vault or changed preference")
				}
				return
			}
			disk, err := app.credentials.vault.load()
			if err != nil || !reflect.DeepEqual(disk, saved) || !app.credentials.remember || !app.credentials.hasVault {
				t.Fatalf("remember setting saved without the connected accounts: %v", err)
			}
		})
	}
}

func TestCredentialsUpgradePausedAutomationStillRestoresRememberedAccounts(t *testing.T) {
	previous := credentialTestConfig()
	first := credentialUpgradeApp(t, previous, nil)
	saved := vaultTestCredentials()
	installUpgradeMemoryAccounts(t, first, saved)
	first.credentials.persist()
	next := previous
	next.Enabled = false
	if err := first.applyAutomationSettings(previous, next); err != nil {
		t.Fatal(err)
	}
	first.cancel()
	restarted := credentialUpgradeApp(t, next, first)
	starts := 0
	restarted.credentials.setStart = func(string, bool) error { starts++; return nil }
	restarted.credentials.syncAutoStart()
	restoreUpgradeAccounts(t, restarted, saved)
	if starts != 0 || restarted.credentials.enabled || !restarted.credentials.remember {
		t.Fatal("restoring login restarted paused automation or changed remember preference")
	}
}

func TestCredentialsUpgradeExplicitForgetNeverSavesOrRestores(t *testing.T) {
	t.Run("first-login-not-remembered", func(t *testing.T) {
		config := credentialUpgradeConfig(false)
		first := credentialUpgradeApp(t, config, nil)
		installUpgradeMemoryAccounts(t, first, vaultTestCredentials())
		first.credentials.persist()
		if _, err := os.Stat(filepath.Join(first.lib.root, credentialVaultFile)); !errors.Is(err, os.ErrNotExist) {
			t.Fatal("explicitly unremembered login created a vault")
		}
		restarted := credentialUpgradeApp(t, config, first)
		restarted.credentials.load()
		restarted.credentials.restorePending()
		if restarted.github.hasToken() || restarted.aigc.hasToken() || len(restarted.cloud.accounts) != 0 {
			t.Fatal("unremembered credentials survived restart")
		}
	})
	t.Run("stale-vault-ignored-and-explicitly-cleared", func(t *testing.T) {
		config := credentialUpgradeConfig(false)
		app := credentialUpgradeApp(t, config, nil)
		before := installSavedTestCredentials(t, app, vaultTestCredentials())
		app.credentials.load()
		app.credentials.restorePending()
		app.credentials.persist()
		after, err := os.ReadFile(filepath.Join(app.lib.root, credentialVaultFile))
		if err != nil || !bytes.Equal(before, after) || app.github.hasToken() || app.aigc.hasToken() || len(app.cloud.accounts) != 0 {
			t.Fatal("disabled remember preference read or rewrote a stale vault")
		}
		if err := app.applyAutomationSettings(config, config); err != nil {
			t.Fatal(err)
		}
		if _, err := os.Stat(filepath.Join(app.lib.root, credentialVaultFile)); !errors.Is(err, os.ErrNotExist) || app.credentials.hasVault {
			t.Fatal("explicit forget did not remove the stale vault")
		}
	})
}

func TestCredentialsUpgradeDisabledSettingsCannotOverwriteDamagedVault(t *testing.T) {
	config := credentialUpgradeConfig(true)
	app := credentialUpgradeApp(t, config, nil)
	path := filepath.Join(app.lib.root, credentialVaultFile)
	damaged := []byte(credentialVaultMagic + "damaged-test-encrypted-data")
	if err := os.WriteFile(path, damaged, 0600); err != nil {
		t.Fatal(err)
	}
	app.credentials.hasVault = true
	app.credentials.load()
	installUpgradeMemoryAccounts(t, app, vaultTestCredentials())
	app.credentials.persist()
	commits, starts := 0, 0
	app.credentials.setStart = func(string, bool) error { starts++; return nil }
	err := app.applyAutomationSettingsTransaction(config, config, func() error { commits++; return nil })
	after, readErr := os.ReadFile(path)
	if err == nil || readErr != nil || !bytes.Equal(after, damaged) || !app.credentials.loadFailed || commits != 0 || starts != 0 {
		t.Fatal("saving disabled automation replaced unreadable credentials or published settings")
	}
}

func TestCredentialsUpgradeDisabledAutomationPersistsRotatedQuarkGrant(t *testing.T) {
	app := credentialUpgradeApp(t, credentialUpgradeConfig(true), nil)
	saved := savedQuarkForCredentialsTest()
	drive := newQuarkDrive(saved.Credentials).(*quarkDrive)
	app.watchCloudCredentials(drive)
	if !app.setCloudAccount("quark", &cloudAccount{drive: drive, account: saved.Account, credentials: saved.Credentials, session: saved.Session}) {
		t.Fatal("could not install test Quark account")
	}
	rotations, checks := 0, 0
	drive.client.Transport = quarkTestTransport(func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case "/agent/v1/oauth/access_token/rotate":
			rotations++
			return quarkTestResponse(map[string]any{"access_token": "upgrade-rotated-access", "refresh_token": "upgrade-rotated-refresh", "expires_in": 7200}), nil
		case "/open/v1/user/info":
			checks++
			disk, err := app.credentials.vault.load()
			cloud := disk.Clouds["quark"]
			if err != nil || cloud.Credentials.RefreshToken != "upgrade-rotated-refresh" || cloud.Credentials.AccessToken != "upgrade-rotated-access" || cloud.Session != saved.Session {
				t.Fatal("disabled automation lost the first refresh grant before account lookup")
			}
			return quarkTestResponse(map[string]string{"user_id": "user1", "nickname": saved.Account}), nil
		default:
			return nil, errors.New("unexpected test cloud request")
		}
	})
	if _, err := drive.Check(context.Background()); err != nil || rotations != 1 || checks != 1 || app.credentials.enabled {
		t.Fatalf("credential refresh depended on enabling automation: %v", err)
	}
}

func TestCredentialsUpgradeCloudResponseReportsDurableLoginOrSaveFailure(t *testing.T) {
	for _, test := range []struct {
		name     string
		hadVault bool
		failSave bool
	}{
		{name: "saved-before-response"},
		{name: "new-vault-save-failure", failSave: true},
		{name: "existing-vault-save-failure", hadVault: true, failSave: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			app := credentialUpgradeApp(t, credentialUpgradeConfig(true), nil)
			var before []byte
			if test.hadVault {
				before = installSavedTestCredentials(t, app, vaultTestCredentials())
			}
			if test.failSave {
				app.credentials.vault.protect = func([]byte) ([]byte, error) {
					return nil, errors.New("private-test-encryption-error")
				}
			}
			app.cloud.factory = func(_ string, credentials CloudCredentials) CloudDrive {
				return &credentialTestDrive{credentials: credentials, check: func(context.Context) (string, error) { return "connected test account", nil }}
			}
			response := call(app, "POST", "/api/cloud/baidu", `{"cookie":"BDUSS=upgrade-test-cookie; STOKEN=upgrade-test-stoken"}`)
			var result struct {
				Configured bool                    `json:"configured"`
				Storage    credentialStorageStatus `json:"credentialStorage"`
			}
			if response.Code != http.StatusOK || json.Unmarshal(response.Body.Bytes(), &result) != nil || !result.Configured {
				t.Fatal("local save failure should not reject an otherwise verified live login")
			}
			if !result.Storage.Supported || !result.Storage.Remember || result.Storage.Saved == test.failSave || (result.Storage.Error != "") != test.failSave {
				t.Fatal("cloud response falsely reported that the current login was saved")
			}
			account, ok := app.cloud.get("baidu")
			if !ok {
				t.Fatal("successful login was not available in this session")
			}
			for _, value := range []string{"upgrade-test-cookie", "upgrade-test-stoken", "private-test-encryption-error", account.session, "refreshToken"} {
				if strings.Contains(response.Body.String(), value) {
					t.Fatal("cloud response exposed credential or internal encryption material")
				}
			}
			if !test.failSave {
				disk, err := app.credentials.vault.load()
				if err != nil || disk.Clouds["baidu"].Credentials != account.credentials || disk.Clouds["baidu"].Session != account.session {
					t.Fatal("cloud endpoint acknowledged before saving the current login")
				}
			} else if test.hadVault {
				after, err := os.ReadFile(filepath.Join(app.lib.root, credentialVaultFile))
				if err != nil || !bytes.Equal(before, after) {
					t.Fatal("failed new login save changed the existing encrypted file")
				}
			}
		})
	}
}
