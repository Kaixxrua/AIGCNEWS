package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

func TestLANListenRequiresExplicitPrivateBinding(t *testing.T) {
	for _, tc := range []struct {
		address string
		lan, ok bool
	}{
		{"127.0.0.1:0", false, true}, {"192.168.0.100:8769", false, false},
		{"192.168.0.100:8769", true, true}, {"10.0.0.1:8000", true, true},
		{"[fd00::1]:8769", true, true}, {"127.0.0.1:8769", true, true},
		{"0.0.0.0:8769", true, false}, {"[::]:8769", true, false},
		{"8.8.8.8:8769", true, false}, {"example.com:8769", true, false},
		{"192.168.0.100:0", true, false}, {"192.168.0.100:65536", true, false},
		{"[fe80::1%eth0]:8769", true, false}, {"localhost:8769", false, false},
	} {
		if got := validateListenAddress(tc.address, tc.lan); (got == nil) != tc.ok {
			t.Errorf("address=%q lan=%v: %v", tc.address, tc.lan, got)
		}
	}
}

func TestLANRestartKeepsAccessCredentialsAndSettings(t *testing.T) {
	lib := testLibrary(t)
	app, err := newAppWithMode(lib, true)
	if err != nil {
		t.Fatal(err)
	}
	defer app.cancel()
	app.host = "192.168.0.100:8769"
	token := app.token
	if !sessionTokenPattern.MatchString(token) {
		t.Fatal("invalid LAN token")
	}
	status := app.automation.status()
	if !status.ServerMode || !status.CredentialStorageSupported || !status.Config.RememberCredentials || status.StartOnLoginSupported || status.Config.Enabled {
		t.Fatalf("incorrect LAN defaults: %+v", status)
	}
	config := app.automation.configSnapshot()
	config.MinStars = 500
	body, _ := json.Marshal(config)
	if w := call(app, "POST", "/api/automation", string(body)); w.Code != 200 {
		t.Fatalf("LAN config rejected: %d %s", w.Code, w.Body.String())
	}
	app.github.setToken("lan-credential-test-sentinel")
	app.credentials.persist()
	if state := app.credentialStorageStatus(); !state.Saved || state.Error != "" {
		t.Fatalf("credential save failed: %+v", state)
	}
	app.cancel()
	reloaded, err := newLibrary(lib.root)
	if err != nil {
		t.Fatal(err)
	}
	restarted, err := newAppWithMode(reloaded, true)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.cancel()
	if restarted.token != token || !restarted.github.hasToken() || restarted.automation.configSnapshot().MinStars != 500 {
		t.Fatal("restart lost the access code, credentials or config")
	}
	restored, err := restarted.credentials.vault.load()
	if err != nil || restored.GitHubToken != "lan-credential-test-sentinel" {
		t.Fatal("encrypted token did not survive restart", err)
	}
}

func TestLANHTTPAuthIsolationAndHeadlessActions(t *testing.T) {
	app, err := newAppWithMode(testLibrary(t), true)
	if err != nil {
		t.Fatal(err)
	}
	defer app.cancel()
	app.host = "192.168.0.100:8769"
	for _, tc := range []struct {
		name   string
		mutate func(*http.Request)
		status int
	}{
		{"authorized", func(r *http.Request) {}, 200},
		{"unauthorized", func(r *http.Request) { r.Header.Del("Authorization") }, 401},
		{"wrong code", func(r *http.Request) { r.Header.Set("Authorization", "Bearer invalid") }, 401},
		{"foreign origin", func(r *http.Request) { r.Header.Set("Origin", "https://foreign.example") }, 403},
		{"rebound host", func(r *http.Request) { r.Host = "foreign.example:8769" }, 403},
		{"cross site", func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "cross-site") }, 401},
		{"same origin", func(r *http.Request) { r.Header.Set("Origin", "http://"+app.host) }, 200},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := request(app, "GET", "/api/library", "")
			tc.mutate(r)
			w := httptest.NewRecorder()
			app.handler().ServeHTTP(w, r)
			if w.Code != tc.status || w.Header().Get("Cache-Control") != "no-store" {
				t.Fatalf("unexpected status or cache policy: %d", w.Code)
			}
		})
	}
	r := request(app, "GET", "/runtime.json", "")
	r.Header.Del("Authorization")
	w := httptest.NewRecorder()
	app.handler().ServeHTTP(w, r)
	if w.Code != 200 || strings.TrimSpace(w.Body.String()) != `{"serverMode":true}` {
		t.Fatalf("public bootstrap must expose only mode: %s", w.Body.String())
	}
	for _, path := range []string{"/api/quit", "/api/transfers/open", "/api/automation/open"} {
		if w := call(app, "POST", path, `{}`); w.Code != http.StatusConflict {
			t.Fatalf("headless action %s returned %d", path, w.Code)
		}
	}
	select {
	case <-app.quit:
		t.Fatal("browser exit shut down the server")
	default:
	}
}

func TestServerVaultEncryptionIntegrityAndKeyLoss(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows LAN mode uses the existing DPAPI vault")
	}
	root := t.TempDir()
	vault, err := newServerCredentialVault(root)
	if err != nil {
		t.Fatal(err)
	}
	saved := vaultTestCredentials()
	if err := vault.save(saved); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(root, vault.fileName)
	encoded, err := os.ReadFile(file)
	if err != nil || bytes.Contains(encoded, []byte("supersecret-sentinel")) || bytes.Contains(encoded, []byte("refreshToken")) {
		t.Fatal("credential file is missing or contains plaintext", err)
	}
	reopened, err := newServerCredentialVault(root)
	if err != nil {
		t.Fatal(err)
	}
	restored, err := reopened.load()
	if err != nil || !reflect.DeepEqual(restored, saved) {
		t.Fatal("server vault did not round trip", err)
	}
	checkpoint, err := vault.checkpoint()
	if err != nil {
		t.Fatal(err)
	}
	encoded[len(encoded)-1] ^= 1
	if err := os.WriteFile(file, encoded, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := reopened.load(); err == nil {
		t.Fatal("tampered ciphertext accepted")
	}
	if err := vault.restoreCheckpoint(checkpoint); err != nil {
		t.Fatal(err)
	}
	if restored, err := reopened.load(); err != nil || !reflect.DeepEqual(restored, saved) {
		t.Fatal("failed to restore exact encrypted checkpoint", err)
	}
	keyPath := filepath.Join(root, "credentials.key")
	if err := os.Remove(keyPath); err != nil {
		t.Fatal(err)
	}
	if _, err := newServerCredentialVault(root); err == nil {
		t.Fatal("silently regenerated a missing encryption key")
	}
	if _, err := os.Stat(keyPath); !os.IsNotExist(err) {
		t.Fatal("missing key was replaced")
	}
}

func TestLANSecretsRejectSymlinksCorruptionAndBroadPermissions(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix file modes")
	}
	for _, kind := range []string{"symlink", "short", "permissions"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			if _, err := loadLANAccessToken(root); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(root, "lan-access.key")
			switch kind {
			case "symlink":
				if err := os.Rename(path, filepath.Join(root, "original")); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink("original", path); err != nil {
					t.Fatal(err)
				}
			case "short":
				if err := os.WriteFile(path, []byte("short"), 0600); err != nil {
					t.Fatal(err)
				}
			case "permissions":
				if err := os.Chmod(path, 0644); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := loadLANAccessToken(root); err == nil {
				t.Fatal("unsafe access-key file accepted")
			}
		})
	}
}
