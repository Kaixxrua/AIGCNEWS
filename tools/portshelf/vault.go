package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"unicode"
)

type savedCloud struct {
	Credentials CloudCredentials `json:"credentials"`
	Session     string           `json:"session"`
	Account     string           `json:"account"`
}

type savedCredentials struct {
	GitHubToken string                `json:"githubToken"`
	AIGCToken   string                `json:"aigcToken"`
	Clouds      map[string]savedCloud `json:"clouds"`
	// Omit the new field when disconnected so older v1 vaults re-encode to
	// exactly the canonical bytes covered by their existing checksum.
	Xianguanjia *XGJCredentials `json:"xianguanjia,omitempty"`
}

const credentialVaultFile = "credentials.dpapi"
const credentialVaultMagic = "PortShelf-DPAPI-v1\x00"
const maxCredentialPlaintext = 128 << 10
const maxCredentialCiphertext = 256 << 10

var errCredentialProtectionUnsupported = errors.New("此系统不支持 Windows 当前用户加密凭据；不会以明文保存登录信息")

type credentialEnvelope struct {
	Version     int              `json:"version"`
	Credentials savedCredentials `json:"credentials"`
	Checksum    string           `json:"checksum"`
}

type credentialVault struct {
	mu        sync.Mutex
	root      string
	rootError error
	available bool
	protect   func([]byte) ([]byte, error)
	unprotect func([]byte) ([]byte, error)
	// Tests inject an authenticated cipher and commit failures per instance.
	// Production always uses DPAPI; no plaintext fallback is supported.
	replace func(*os.Root, string, string) error
}

func newCredentialVault(root string) *credentialVault {
	var rootError error
	if root == "" || strings.IndexFunc(root, unicode.IsControl) >= 0 {
		rootError = errors.New("凭据目录无效")
	}
	absolute, err := filepath.Abs(root)
	if err != nil {
		rootError = errors.New("凭据目录无效")
	}
	return &credentialVault{
		root: absolute, rootError: rootError, available: credentialProtectionAvailable(),
		protect: protectCredentialBytes, unprotect: unprotectCredentialBytes,
		replace: func(root *os.Root, source, target string) error { return root.Rename(source, target) },
	}
}

func emptySavedCredentials() savedCredentials {
	return savedCredentials{Clouds: map[string]savedCloud{}}
}

func validateSavedCredentials(saved savedCredentials) bool {
	if !validToken(saved.GitHubToken) || !validAIGCToken(saved.AIGCToken) || len(saved.Clouds) > 2 {
		return false
	}
	if c := saved.Xianguanjia; c != nil && (c.AppKey == "" || c.AppSecret == "" || !validXGJCredentials(*c)) {
		return false
	}
	for provider, cloud := range saved.Clouds {
		if !validDrive(provider) || !validCloudCredentials(cloud.Credentials) || !sessionTokenPattern.MatchString(cloud.Session) ||
			len(cloud.Account) > 256 || strings.IndexFunc(cloud.Account, unicode.IsControl) >= 0 {
			return false
		}
	}
	return true
}

func (v *credentialVault) open() (*os.Root, error) {
	if !v.available || v.protect == nil || v.unprotect == nil {
		return nil, errCredentialProtectionUnsupported
	}
	if v.rootError != nil {
		return nil, v.rootError
	}
	root, err := os.OpenRoot(v.root)
	if err != nil {
		return nil, errors.New("无法访问加密凭据目录，请检查磁盘和权限")
	}
	return root, nil
}

func (v *credentialVault) load() (savedCredentials, error) {
	v.mu.Lock()
	defer v.mu.Unlock()
	empty := emptySavedCredentials()
	root, err := v.open()
	if err != nil {
		return empty, err
	}
	defer root.Close()
	info, err := root.Lstat(credentialVaultFile)
	if errors.Is(err, os.ErrNotExist) {
		return empty, nil
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() <= int64(len(credentialVaultMagic)) || info.Size() > maxCredentialCiphertext {
		return empty, errors.New("加密凭据文件无效，请清除已保存凭据后重新连接")
	}
	file, err := root.Open(credentialVaultFile)
	if err != nil {
		return empty, errors.New("无法读取加密凭据文件")
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		return empty, errors.New("加密凭据文件在读取期间发生变化")
	}
	encoded, err := io.ReadAll(io.LimitReader(file, maxCredentialCiphertext+1))
	if err != nil || len(encoded) > maxCredentialCiphertext || !bytes.HasPrefix(encoded, []byte(credentialVaultMagic)) {
		return empty, errors.New("加密凭据文件格式无效，不会尝试读取明文凭据")
	}
	plain, err := v.unprotect(encoded[len(credentialVaultMagic):])
	defer clear(plain)
	if err != nil {
		return empty, errors.New("无法解密已保存凭据，请使用原 Windows 用户，或清除后重新连接")
	}
	if len(plain) == 0 || len(plain) > maxCredentialPlaintext {
		return empty, errors.New("加密凭据内容无效")
	}
	var envelope credentialEnvelope
	decoder := json.NewDecoder(bytes.NewReader(plain))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&envelope) != nil || decoder.Decode(new(any)) != io.EOF || envelope.Version != 1 || !validateSavedCredentials(envelope.Credentials) {
		return empty, errors.New("加密凭据内容损坏或版本不受支持，请重新连接")
	}
	canonical, err := json.Marshal(envelope.Credentials)
	if err != nil {
		return empty, errors.New("加密凭据内容无效")
	}
	defer clear(canonical)
	checksum := sha256.Sum256(canonical)
	if envelope.Checksum != hex.EncodeToString(checksum[:]) {
		return empty, errors.New("加密凭据完整性校验失败，请重新连接")
	}
	if envelope.Credentials.Clouds == nil {
		envelope.Credentials.Clouds = map[string]savedCloud{}
	}
	return envelope.Credentials, nil
}

func (v *credentialVault) save(saved savedCredentials) error {
	v.mu.Lock()
	defer v.mu.Unlock()
	root, err := v.open()
	if err != nil {
		return err
	}
	defer root.Close()
	if !validateSavedCredentials(saved) {
		return errors.New("待保存的凭据或账号信息无效")
	}
	if info, err := root.Lstat(credentialVaultFile); err == nil {
		if !info.Mode().IsRegular() {
			return errors.New("凭据文件位置已被目录或链接占用")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return errors.New("无法检查已有加密凭据文件")
	}
	canonical, err := json.Marshal(saved)
	defer clear(canonical)
	if err != nil || len(canonical) > maxCredentialPlaintext/2 {
		return errors.New("凭据内容过大或无法编码")
	}
	checksum := sha256.Sum256(canonical)
	plain, err := json.Marshal(credentialEnvelope{Version: 1, Credentials: saved, Checksum: hex.EncodeToString(checksum[:])})
	defer clear(plain)
	if err != nil || len(plain) > maxCredentialPlaintext {
		return errors.New("凭据内容过大或无法编码")
	}
	protected, err := v.protect(plain)
	if err != nil || len(protected) == 0 || len(protected)+len(credentialVaultMagic) > maxCredentialCiphertext || bytes.Equal(protected, plain) {
		return errors.New("Windows 凭据加密失败，未保存任何明文登录信息")
	}
	// No file is written before protection succeeds. Temporary files contain
	// only ciphertext and are created exclusively inside the data root.
	var random [16]byte
	if _, err := rand.Read(random[:]); err != nil {
		return errors.New("无法生成加密凭据临时文件名")
	}
	name := ".credentials-" + hex.EncodeToString(random[:]) + ".tmp"
	file, err := root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return errors.New("无法保存加密凭据，请检查磁盘空间和权限")
	}
	defer root.Remove(name)
	_, err = file.Write([]byte(credentialVaultMagic))
	if err == nil {
		_, err = file.Write(protected)
	}
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
		return errors.New("保存加密凭据失败，原有凭据未被替换；请检查磁盘空间和权限")
	}
	return nil
}

func (v *credentialVault) clear() error {
	v.mu.Lock()
	defer v.mu.Unlock()
	root, err := v.open()
	if err != nil {
		return err
	}
	defer root.Close()
	info, err := root.Lstat(credentialVaultFile)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil || !info.Mode().IsRegular() {
		return errors.New("加密凭据文件位置无效，未删除其它文件")
	}
	if err := root.Remove(credentialVaultFile); err != nil && !errors.Is(err, os.ErrNotExist) {
		return errors.New("无法清除已保存的加密凭据，请检查文件权限")
	}
	return nil
}
