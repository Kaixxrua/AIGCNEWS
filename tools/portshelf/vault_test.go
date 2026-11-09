package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"sync"
	"testing"
)

// Only tests inject AES-GCM. Production has no non-DPAPI persistence path.
func newTestCredentialVault(t *testing.T) *credentialVault {
	t.Helper()
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		t.Fatal(err)
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		t.Fatal(err)
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		t.Fatal(err)
	}
	vault := newCredentialVault(t.TempDir())
	vault.available = true
	vault.protect = func(plain []byte) ([]byte, error) {
		nonce := make([]byte, aead.NonceSize())
		if _, err := rand.Read(nonce); err != nil {
			return nil, err
		}
		return aead.Seal(nonce, nonce, plain, nil), nil
	}
	vault.unprotect = func(protected []byte) ([]byte, error) {
		if len(protected) < aead.NonceSize() {
			return nil, errors.New("invalid ciphertext")
		}
		return aead.Open(nil, protected[:aead.NonceSize()], protected[aead.NonceSize():], nil)
	}
	return vault
}

func vaultTestCredentials() savedCredentials {
	return savedCredentials{
		GitHubToken: "github-supersecret-sentinel",
		AIGCToken:   "aigc-supersecret-sentinel",
		Clouds: map[string]savedCloud{
			"baidu": {
				Credentials: CloudCredentials{Cookie: "BDUSS=cookie-supersecret-sentinel; STOKEN=second-secret"},
				Session:     strings.Repeat("a", 48),
				Account:     "测试百度账号",
			},
			"quark": {
				Credentials: CloudCredentials{
					AccessToken: "access-supersecret-sentinel", RefreshToken: "refresh-supersecret-sentinel",
					DeviceID: "device-sentinel", UserID: "user-sentinel", ExpiresAt: "2026-11-12T10:00:00Z",
				},
				Session: strings.Repeat("b", 48), Account: "测试夸克账号",
			},
		},
	}
}

func assertVaultCiphertext(t *testing.T, encoded []byte) {
	t.Helper()
	if !bytes.HasPrefix(encoded, []byte(credentialVaultMagic)) {
		t.Fatal("missing vault header")
	}
	for _, secret := range []string{"supersecret-sentinel", "second-secret", "device-sentinel", "user-sentinel", "githubToken", "refreshToken", "测试百度账号"} {
		if bytes.Contains(encoded, []byte(secret)) {
			t.Fatalf("credential data written without encryption: %q", secret)
		}
	}
}

func assertVaultOnlyFinalFile(t *testing.T, vault *credentialVault) {
	t.Helper()
	files, err := os.ReadDir(vault.root)
	if err != nil {
		t.Fatal(err)
	}
	if len(files) != 1 || files[0].Name() != credentialVaultFile {
		t.Fatalf("unexpected files or leaked temporary files: %v", files)
	}
}

func TestCredentialVaultEncryptedRoundTripAndReplace(t *testing.T) {
	vault := newTestCredentialVault(t)
	empty, err := vault.load()
	if err != nil || empty.Clouds == nil || len(empty.Clouds) != 0 {
		t.Fatalf("absent vault: %+v, %v", empty, err)
	}
	saved := vaultTestCredentials()
	if err := vault.save(saved); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(vault.root, credentialVaultFile)
	first, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	assertVaultCiphertext(t, first)
	loaded, err := vault.load()
	if err != nil || !reflect.DeepEqual(loaded, saved) {
		t.Fatalf("round trip did not preserve all credential fields: %v", err)
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(path)
		if err != nil || info.Mode().Perm() != 0600 {
			t.Fatalf("vault permissions: %v, %v", info, err)
		}
	}
	saved.GitHubToken = "replacement-supersecret-sentinel"
	if err := vault.save(saved); err != nil {
		t.Fatal(err)
	}
	second, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	assertVaultCiphertext(t, second)
	if bytes.Equal(first, second) {
		t.Fatal("replacement did not update ciphertext")
	}
	loaded, err = vault.load()
	if err != nil || !reflect.DeepEqual(loaded, saved) {
		t.Fatalf("replacement failed to round trip: %v", err)
	}
	assertVaultOnlyFinalFile(t, vault)
}

func TestCredentialVaultProtectionAndCommitFailureRetainPrevious(t *testing.T) {
	for _, failure := range []string{"protect", "identity", "empty", "oversize", "replace"} {
		t.Run(failure, func(t *testing.T) {
			vault := newTestCredentialVault(t)
			if err := vault.save(vaultTestCredentials()); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(vault.root, credentialVaultFile)
			before, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			switch failure {
			case "protect":
				vault.protect = func([]byte) ([]byte, error) { return nil, errors.New("raw-secret-provider-error") }
			case "identity":
				vault.protect = func(data []byte) ([]byte, error) { return data, nil }
			case "empty":
				vault.protect = func([]byte) ([]byte, error) { return nil, nil }
			case "oversize":
				vault.protect = func([]byte) ([]byte, error) { return make([]byte, maxCredentialCiphertext), nil }
			case "replace":
				vault.replace = func(root *os.Root, source, target string) error {
					if target != credentialVaultFile {
						t.Fatalf("unexpected commit destination %q", target)
					}
					pending, err := root.ReadFile(source)
					if err != nil {
						t.Fatal(err)
					}
					assertVaultCiphertext(t, pending)
					return errors.New("raw-secret-provider-error")
				}
			}
			updated := vaultTestCredentials()
			updated.GitHubToken = "updated-supersecret-sentinel"
			err = vault.save(updated)
			if err == nil || strings.Contains(err.Error(), "raw-secret") || strings.Contains(err.Error(), updated.GitHubToken) {
				t.Fatalf("failure not sanitized: %v", err)
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatalf("failed save replaced previous vault: %v", err)
			}
			assertVaultOnlyFinalFile(t, vault)
		})
	}
}

func TestCredentialVaultRejectsUntrustedFiles(t *testing.T) {
	for _, kind := range []string{"plaintext", "wrong-header", "tampered", "wrong-key", "oversize", "wrong-version", "bad-checksum", "unknown-field", "trailing-json", "invalid-credentials"} {
		t.Run(kind, func(t *testing.T) {
			vault := newTestCredentialVault(t)
			saved := vaultTestCredentials()
			if err := vault.save(saved); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(vault.root, credentialVaultFile)
			encoded, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "plaintext":
				encoded, _ = json.Marshal(saved)
			case "wrong-header":
				encoded[0] ^= 1
			case "tampered":
				encoded[len(encoded)-1] ^= 1
			case "wrong-key":
				other := newTestCredentialVault(t)
				vault.unprotect = other.unprotect
			case "oversize":
				encoded = make([]byte, maxCredentialCiphertext+1)
			default:
				canonical, _ := json.Marshal(saved)
				checksum := sha256.Sum256(canonical)
				envelope := credentialEnvelope{Version: 1, Credentials: saved, Checksum: hex.EncodeToString(checksum[:])}
				if kind == "wrong-version" {
					envelope.Version = 2
				}
				if kind == "bad-checksum" {
					envelope.Checksum = strings.Repeat("0", 64)
				}
				if kind == "invalid-credentials" {
					envelope.Credentials.GitHubToken = "token\nsecret"
				}
				plain, _ := json.Marshal(envelope)
				if kind == "unknown-field" {
					plain = append([]byte("{\"unexpected\":1,"), plain[1:]...)
				}
				if kind == "trailing-json" {
					plain = append(plain, []byte(" {}")...)
				}
				protected, err := vault.protect(plain)
				if err != nil {
					t.Fatal(err)
				}
				encoded = append([]byte(credentialVaultMagic), protected...)
			}
			if err := os.WriteFile(path, encoded, 0600); err != nil {
				t.Fatal(err)
			}
			loaded, err := vault.load()
			if err == nil || loaded.GitHubToken != "" || len(loaded.Clouds) != 0 {
				t.Fatalf("accepted %s vault or leaked partial credentials: %v", kind, err)
			}
			if err := vault.clear(); err != nil {
				t.Fatalf("could not clear corrupt vault: %v", err)
			}
		})
	}
}

func TestCredentialVaultRejectsLinksAndDirectories(t *testing.T) {
	for _, kind := range []string{"symlink", "directory"} {
		t.Run(kind, func(t *testing.T) {
			vault := newTestCredentialVault(t)
			target := filepath.Join(vault.root, credentialVaultFile)
			outside := filepath.Join(t.TempDir(), "outside.txt")
			if err := os.WriteFile(outside, []byte("outside marker"), 0600); err != nil {
				t.Fatal(err)
			}
			if kind == "symlink" {
				if err := os.Symlink(outside, target); err != nil {
					t.Skipf("symlinks unavailable: %v", err)
				}
			} else if err := os.Mkdir(target, 0700); err != nil {
				t.Fatal(err)
			}
			if _, err := vault.load(); err == nil {
				t.Fatal("unsafe file accepted by load")
			}
			if err := vault.save(vaultTestCredentials()); err == nil {
				t.Fatal("unsafe file accepted by save")
			}
			if err := vault.clear(); err == nil {
				t.Fatal("unsafe file removed by clear")
			}
			if _, err := os.Lstat(target); err != nil {
				t.Fatalf("unsafe target changed: %v", err)
			}
			data, err := os.ReadFile(outside)
			if err != nil || string(data) != "outside marker" {
				t.Fatalf("outside file changed: %v", err)
			}
		})
	}
}

func TestCredentialVaultClearAndUnsupported(t *testing.T) {
	vault := newTestCredentialVault(t)
	marker := filepath.Join(vault.root, "library.json")
	if err := os.WriteFile(marker, []byte("keep library"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := vault.save(vaultTestCredentials()); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		if err := vault.clear(); err != nil {
			t.Fatal(err)
		}
	}
	data, err := os.ReadFile(marker)
	if err != nil || string(data) != "keep library" {
		t.Fatalf("clear modified unrelated file: %v", err)
	}
	if _, err := os.Stat(filepath.Join(vault.root, credentialVaultFile)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("vault was not removed: %v", err)
	}
	if runtime.GOOS == "windows" {
		return
	}
	unsupported := newCredentialVault(t.TempDir())
	if credentialProtectionAvailable() || autoStartSupported() {
		t.Fatal("unsupported platform advertised Windows persistence")
	}
	if _, err := unsupported.load(); !errors.Is(err, errCredentialProtectionUnsupported) {
		t.Fatalf("load: %v", err)
	}
	if err := unsupported.save(vaultTestCredentials()); !errors.Is(err, errCredentialProtectionUnsupported) {
		t.Fatalf("save: %v", err)
	}
	if err := unsupported.clear(); !errors.Is(err, errCredentialProtectionUnsupported) {
		t.Fatalf("clear: %v", err)
	}
	if err := setAutoStart(unsupported.root, true); !errors.Is(err, errAutoStartUnsupported) {
		t.Fatalf("startup: %v", err)
	}
	files, err := os.ReadDir(unsupported.root)
	if err != nil || len(files) != 0 {
		t.Fatalf("unsupported platform wrote files: %v", err)
	}
}

func TestCredentialVaultInvalidInputDoesNotWrite(t *testing.T) {
	for _, kind := range []string{"token", "cookie", "provider", "session", "account"} {
		t.Run(kind, func(t *testing.T) {
			vault := newTestCredentialVault(t)
			saved := vaultTestCredentials()
			switch kind {
			case "token":
				saved.GitHubToken = strings.Repeat("a", 257)
			case "provider":
				saved.Clouds["untrusted"] = saved.Clouds["baidu"]
			default:
				cloud := saved.Clouds["baidu"]
				switch kind {
				case "cookie":
					cloud.Credentials.Cookie = "cookie\r\nsecret"
				case "session":
					cloud.Session = "../untrusted"
				case "account":
					cloud.Account = "account\nsecret"
				}
				saved.Clouds["baidu"] = cloud
			}
			if err := vault.save(saved); err == nil {
				t.Fatal("invalid credentials saved")
			}
			files, err := os.ReadDir(vault.root)
			if err != nil || len(files) != 0 {
				t.Fatalf("invalid input wrote files: %v", err)
			}
		})
	}
}

func TestCredentialVaultEmptyCredentialsAndDecryptFailure(t *testing.T) {
	vault := newTestCredentialVault(t)
	if err := vault.save(savedCredentials{}); err != nil {
		t.Fatal(err)
	}
	loaded, err := vault.load()
	if err != nil || loaded.Clouds == nil || loaded.GitHubToken != "" {
		t.Fatalf("empty credentials did not round trip: %v", err)
	}
	raw := []byte("sensitive-buffer")
	vault.unprotect = func([]byte) ([]byte, error) {
		return raw, errors.New("raw-secret-decryption-error")
	}
	if _, err := vault.load(); err == nil || strings.Contains(err.Error(), "raw-secret") {
		t.Fatalf("decrypt error not sanitized: %v", err)
	}
	if !bytes.Equal(raw, make([]byte, len(raw))) {
		t.Fatal("decryption error left plaintext bytes in temporary buffer")
	}
}

func TestCredentialVaultMissingOrInvalidDirectory(t *testing.T) {
	for _, root := range []string{"", "bad\x00root", filepath.Join(t.TempDir(), "absent")} {
		vault := newTestCredentialVault(t)
		invalid := newCredentialVault(root)
		invalid.available, invalid.protect, invalid.unprotect = true, vault.protect, vault.unprotect
		if _, err := invalid.load(); err == nil {
			t.Fatal("load accepted invalid directory")
		}
		if err := invalid.save(savedCredentials{}); err == nil {
			t.Fatal("save accepted invalid directory")
		}
		if err := invalid.clear(); err == nil {
			t.Fatal("clear accepted invalid directory")
		}
	}
}

func TestCredentialVaultConcurrentSaveLoadClear(t *testing.T) {
	vault := newTestCredentialVault(t)
	var group sync.WaitGroup
	for worker := 0; worker < 8; worker++ {
		group.Add(1)
		go func(worker int) {
			defer group.Done()
			for index := 0; index < 15; index++ {
				saved := vaultTestCredentials()
				saved.GitHubToken = fmt.Sprintf("worker-%d-write-%d", worker, index)
				if err := vault.save(saved); err != nil {
					t.Errorf("concurrent save: %v", err)
					return
				}
				loaded, err := vault.load()
				if err != nil || !validateSavedCredentials(loaded) {
					t.Errorf("concurrent load returned partial state: %v", err)
					return
				}
				if worker%3 == 0 {
					if err := vault.clear(); err != nil {
						t.Errorf("concurrent clear: %v", err)
						return
					}
				}
			}
		}(worker)
	}
	group.Wait()
	if err := vault.save(vaultTestCredentials()); err != nil {
		t.Fatal(err)
	}
	assertVaultOnlyFinalFile(t, vault)
}
