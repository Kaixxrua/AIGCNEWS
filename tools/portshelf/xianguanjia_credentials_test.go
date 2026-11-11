package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

// A fixed pre-Xianguanjia v1 envelope, including its original checksum. Do not
// build this fixture from savedCredentials: doing so would conceal a migration
// that changes the canonical bytes and invalidates every previous vault.
const xgjLegacyVaultEnvelope = `{"version":1,"credentials":{"githubToken":"github-upgrade-fixture","aigcToken":"aigc-upgrade-fixture","clouds":{"baidu":{"credentials":{"cookie":"BDUSS=baidu-fixture; STOKEN=stoken-fixture","accessToken":"","authCode":""},"session":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","account":"百度金样本"},"quark":{"credentials":{"cookie":"","accessToken":"quark-access-fixture","authCode":"","refreshToken":"quark-refresh-fixture","deviceId":"device-fixture","expiresAt":"2026-11-12T10:00:00Z","userId":"user-fixture"},"session":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","account":"夸克金样本"}}},"checksum":"0d4fafea85ad0004bc1bea6f9dcb9e2486064776605ba2537b11bc82802ef0e8"}`

func xgjVaultTestCredentials() XGJCredentials {
	return XGJCredentials{AppKey: "203413189371893", AppSecret: "xgj-supersecret-sentinel"}
}

func xgjWriteEncryptedFixture(t *testing.T, vault *credentialVault, plain []byte) []byte {
	t.Helper()
	protected, err := vault.protect(plain)
	if err != nil {
		t.Fatal(err)
	}
	encoded := append([]byte(credentialVaultMagic), protected...)
	if err := os.WriteFile(filepath.Join(vault.root, credentialVaultFile), encoded, 0600); err != nil {
		t.Fatal(err)
	}
	return encoded
}

func xgjAssertSecretsNotOnDisk(t *testing.T, root string, credentials XGJCredentials) {
	t.Helper()
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		for _, secret := range []string{credentials.AppKey, credentials.AppSecret, `"appKey"`, `"appSecret"`} {
			if secret != "" && bytes.Contains(data, []byte(secret)) {
				t.Fatal("marketplace authorization was written without encryption")
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestXGJCredentialsLegacyVaultChecksumCompatibility(t *testing.T) {
	app := newCredentialTestApp(t)
	app.marketplace = &marketplaceManager{}
	vault := app.credentials.vault
	xgjWriteEncryptedFixture(t, vault, []byte(xgjLegacyVaultEnvelope))
	app.credentials.hasVault = true
	loaded, err := vault.load()
	if err != nil || loaded.Xianguanjia != nil || len(loaded.Clouds) != 2 {
		t.Fatalf("pre-marketplace vault no longer loads: %v", err)
	}
	if loaded.GitHubToken != "github-upgrade-fixture" || loaded.AIGCToken != "aigc-upgrade-fixture" ||
		loaded.Clouds["baidu"].Credentials.Cookie != "BDUSS=baidu-fixture; STOKEN=stoken-fixture" ||
		loaded.Clouds["quark"].Credentials.RefreshToken != "quark-refresh-fixture" {
		t.Fatal("upgrade changed a previously remembered authorization")
	}
	canonical, err := json.Marshal(loaded)
	if err != nil {
		t.Fatal(err)
	}
	checksum := sha256.Sum256(canonical)
	if hex.EncodeToString(checksum[:]) != "0d4fafea85ad0004bc1bea6f9dcb9e2486064776605ba2537b11bc82802ef0e8" || bytes.Contains(canonical, []byte("xianguanjia")) {
		t.Fatal("absent marketplace field changed the legacy canonical encoding")
	}
	restoreUpgradeAccounts(t, app, loaded)
	if app.credentials.loadFailed || app.marketplace.credentialsSnapshot() != (XGJCredentials{}) {
		t.Fatal("legacy account restoration introduced marketplace authorization")
	}
	app.credentials.persist()
	after, err := vault.load()
	if err != nil || !reflect.DeepEqual(after, loaded) {
		t.Fatalf("rewriting a legacy vault lost previous authorization: %v", err)
	}
}

func TestXGJCredentialsEncryptedUpgradeRoundTrip(t *testing.T) {
	config := credentialUpgradeConfig(true)
	first := credentialUpgradeApp(t, config, nil)
	first.marketplace = &marketplaceManager{}
	saved := vaultTestCredentials()
	credentials := xgjVaultTestCredentials()
	saved.Xianguanjia = &credentials
	installUpgradeMemoryAccounts(t, first, saved)
	first.marketplace.restoreCredentials(credentials)
	first.credentials.persist()
	encoded, err := os.ReadFile(filepath.Join(first.lib.root, credentialVaultFile))
	if err != nil || !first.credentials.hasVault {
		t.Fatalf("marketplace authorization was not persisted: %v", err)
	}
	assertVaultCiphertext(t, encoded)
	xgjAssertSecretsNotOnDisk(t, first.lib.root, credentials)
	status, err := json.Marshal(first.credentialStorageStatus())
	if err != nil || bytes.Contains(status, []byte(credentials.AppKey)) || bytes.Contains(status, []byte(credentials.AppSecret)) {
		t.Fatal("public credential status exposed marketplace authorization")
	}
	first.cancel()
	restarted := credentialUpgradeApp(t, config, first)
	restarted.marketplace = &marketplaceManager{}
	restoreUpgradeAccounts(t, restarted, saved)
	if restarted.marketplace.credentialsSnapshot() != credentials || restarted.credentials.enabled {
		t.Fatal("upgrade lost marketplace credentials or enabled automation")
	}
	restarted.credentials.persist()
	disk, err := restarted.credentials.vault.load()
	if err != nil || !reflect.DeepEqual(disk, saved) {
		t.Fatalf("expanded vault did not survive a fresh manager and process state: %v", err)
	}
	xgjAssertSecretsNotOnDisk(t, restarted.lib.root, credentials)
}

func TestXGJCredentialsDisconnectPreservesOtherAccounts(t *testing.T) {
	app := newCredentialTestApp(t)
	app.marketplace = &marketplaceManager{}
	saved := vaultTestCredentials()
	credentials := xgjVaultTestCredentials()
	installUpgradeMemoryAccounts(t, app, saved)
	app.marketplace.restoreCredentials(credentials)
	app.credentials.persist()
	app.marketplace.restoreCredentials(XGJCredentials{})
	app.credentials.persist()
	disk, err := app.credentials.vault.load()
	if err != nil || disk.Xianguanjia != nil || !reflect.DeepEqual(disk, saved) {
		t.Fatalf("disconnect removed another provider or retained marketplace authorization: %v", err)
	}
	restarted := credentialUpgradeApp(t, credentialUpgradeConfig(true), app)
	restarted.marketplace = &marketplaceManager{}
	restoreUpgradeAccounts(t, restarted, saved)
	if restarted.marketplace.credentialsSnapshot() != (XGJCredentials{}) {
		t.Fatal("disconnected marketplace authorization reappeared after restart")
	}
	xgjAssertSecretsNotOnDisk(t, app.lib.root, credentials)
}

func TestXGJCredentialsLoadKeepsAlreadyInstalledAccount(t *testing.T) {
	app := newCredentialTestApp(t)
	app.marketplace = &marketplaceManager{}
	saved := vaultTestCredentials()
	old := xgjVaultTestCredentials()
	saved.Xianguanjia = &old
	installSavedTestCredentials(t, app, saved)
	current := XGJCredentials{AppKey: "203413189371894", AppSecret: "already-installed-secret"}
	app.marketplace.restoreCredentials(current)
	app.credentials.load()
	if app.credentials.loadFailed || app.marketplace.credentialsSnapshot() != current || !reflect.DeepEqual(app.credentials.pending, saved.Clouds) {
		t.Fatal("load replaced a newly installed marketplace account or changed cloud restoration")
	}
}

func TestXGJCredentialsInvalidInputDoesNotReplaceVault(t *testing.T) {
	cases := map[string]XGJCredentials{
		"empty":           {},
		"missing-key":     {AppSecret: "test-secret"},
		"missing-secret":  {AppKey: "203413189371893"},
		"non-numeric-key": {AppKey: "test-app", AppSecret: "test-secret"},
		"zero-key":        {AppKey: "0", AppSecret: "test-secret"},
		"overflow-key":    {AppKey: "9223372036854775808", AppSecret: "test-secret"},
		"spaced-key":      {AppKey: "203413189371893 ", AppSecret: "test-secret"},
		"newline-secret":  {AppKey: "203413189371893", AppSecret: "test\nsecret"},
		"unicode-secret":  {AppKey: "203413189371893", AppSecret: "secret密码"},
		"oversize-secret": {AppKey: "203413189371893", AppSecret: strings.Repeat("s", 257)},
	}
	for name, invalid := range cases {
		t.Run(name, func(t *testing.T) {
			vault := newTestCredentialVault(t)
			original := vaultTestCredentials()
			if err := vault.save(original); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(vault.root, credentialVaultFile)
			before, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			updated := original
			updated.Xianguanjia = &invalid
			if validateSavedCredentials(updated) || vault.save(updated) == nil {
				t.Fatal("invalid marketplace authorization was accepted")
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatalf("invalid marketplace input changed the existing vault: %v", err)
			}
			assertVaultOnlyFinalFile(t, vault)
		})
	}
}

func TestXGJCredentialsInvalidSavedAuthorizationNeverPartiallyRestores(t *testing.T) {
	for _, invalid := range []string{"marketplace", "cloud"} {
		t.Run(invalid, func(t *testing.T) {
			app := newCredentialTestApp(t)
			app.marketplace = &marketplaceManager{}
			saved := vaultTestCredentials()
			credentials := xgjVaultTestCredentials()
			saved.Xianguanjia = &credentials
			if invalid == "marketplace" {
				credentials.AppKey = "invalid-app-key"
			} else {
				cloud := saved.Clouds["quark"]
				cloud.Credentials.AuthCode = "spent-one-use-code"
				saved.Clouds["quark"] = cloud
			}
			canonical, err := json.Marshal(saved)
			if err != nil {
				t.Fatal(err)
			}
			checksum := sha256.Sum256(canonical)
			plain, err := json.Marshal(credentialEnvelope{Version: 1, Credentials: saved, Checksum: hex.EncodeToString(checksum[:])})
			if err != nil {
				t.Fatal(err)
			}
			before := xgjWriteEncryptedFixture(t, app.credentials.vault, plain)
			app.credentials.hasVault = true
			app.credentials.load()
			app.credentials.persist()
			after, err := os.ReadFile(filepath.Join(app.lib.root, credentialVaultFile))
			if err != nil || !bytes.Equal(before, after) || !app.credentials.loadFailed || app.github.hasToken() || app.aigc.hasToken() || len(app.credentials.pending) != 0 || app.marketplace.credentialsSnapshot() != (XGJCredentials{}) {
				t.Fatalf("invalid saved authorization partially restored or replaced its original vault: %v", err)
			}
		})
	}
}

func TestXGJCredentialsUnavailableProtectionNeverWritesPlaintext(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("production protection is supported on Windows")
	}
	vault := newCredentialVault(t.TempDir())
	saved := vaultTestCredentials()
	credentials := xgjVaultTestCredentials()
	saved.Xianguanjia = &credentials
	if err := vault.save(saved); !errors.Is(err, errCredentialProtectionUnsupported) {
		t.Fatalf("unsupported platform did not reject persistence: %v", err)
	}
	files, err := os.ReadDir(vault.root)
	if err != nil || len(files) != 0 {
		t.Fatalf("unsupported platform wrote credentials: %v", err)
	}
}
