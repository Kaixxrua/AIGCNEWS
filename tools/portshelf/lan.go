package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"io"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
)

func validateListenAddress(address string, lan bool) error {
	host, port, err := net.SplitHostPort(address)
	n, portErr := strconv.Atoi(port)
	if err != nil || portErr != nil || n < 0 || n > 65535 {
		return errors.New("监听地址需包含 IP 和有效端口")
	}
	if !lan {
		if host != "127.0.0.1" {
			return errors.New("默认仅监听 127.0.0.1；内网访问请显式启用 -lan")
		}
		return nil
	}
	ip, err := netip.ParseAddr(host)
	if err != nil || ip.Zone() != "" || !(ip.IsPrivate() || ip.IsLoopback()) || n == 0 {
		return errors.New("内网服务需指定私有 IP 和固定端口，不允许公网 IP、域名或所有网卡")
	}
	return nil
}

// Called only while the data-directory lock is held. Never rotate an existing
// secret implicitly: both access URLs and saved credentials survive updates.
func privateSecret(directory, name string, size int, mustExist bool) ([]byte, error) {
	root, err := os.OpenRoot(directory)
	if err != nil {
		return nil, errors.New("无法访问服务器密钥目录")
	}
	defer root.Close()
	info, err := root.Lstat(name)
	if errors.Is(err, os.ErrNotExist) && !mustExist {
		secret := make([]byte, size)
		if _, err := rand.Read(secret); err != nil {
			return nil, err
		}
		file, err := root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return nil, errors.New("无法创建服务器密钥")
		}
		_, err = file.Write(secret)
		if err == nil {
			err = file.Sync()
		}
		if closeErr := file.Close(); err == nil {
			err = closeErr
		}
		if err != nil {
			_ = root.Remove(name)
			clear(secret)
			return nil, errors.New("无法保存服务器密钥")
		}
		return secret, nil
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() != int64(size) || runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("服务器密钥缺失、格式错误或权限过宽；请恢复原密钥并限制为当前用户读写")
	}
	file, err := root.Open(name)
	if err != nil {
		return nil, errors.New("无法读取服务器密钥")
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return nil, errors.New("服务器密钥在读取期间发生变化")
	}
	secret, err := io.ReadAll(io.LimitReader(file, int64(size)+1))
	if err != nil || len(secret) != size {
		clear(secret)
		return nil, errors.New("无法完整读取服务器密钥")
	}
	return secret, nil
}

func loadLANAccessToken(root string) (string, error) {
	secret, err := privateSecret(root, "lan-access.key", 24, false)
	defer clear(secret)
	return hex.EncodeToString(secret), err
}

func newServerCredentialVault(root string) (*credentialVault, error) {
	vault := newCredentialVault(root)
	if runtime.GOOS == "windows" {
		return vault, nil
	}
	vault.fileName, vault.magic = "credentials.encrypted", "PortShelf-AESGCM-v1\x00"
	_, statErr := os.Lstat(filepath.Join(root, vault.fileName))
	// Lost encryption keys must never be silently replaced while a vault exists.
	key, err := privateSecret(root, "credentials.key", 32, !errors.Is(statErr, os.ErrNotExist))
	if err != nil {
		return nil, err
	}
	defer clear(key)
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCMWithRandomNonce(block)
	if err != nil {
		return nil, err
	}
	vault.available = true
	vault.protect = func(plain []byte) ([]byte, error) {
		return aead.Seal(nil, nil, plain, []byte(vault.magic)), nil
	}
	vault.unprotect = func(encoded []byte) ([]byte, error) {
		return aead.Open(nil, nil, encoded, []byte(vault.magic))
	}
	return vault, nil
}
