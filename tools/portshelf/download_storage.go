package main

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"unicode"
)

// Keep every explicitly selected root so existing jobs can resume and clean up
// their verified files. Changing the download folder never moves account data.
type downloadStorage struct {
	Version   int      `json:"version"`
	Directory string   `json:"directory"`
	Roots     []string `json:"roots"`
}

func downloadPath(raw string) (string, error) {
	value := strings.TrimSpace(raw)
	if value == "" || len(value) > 4096 || strings.IndexFunc(value, unicode.IsControl) >= 0 || !filepath.IsAbs(value) {
		return "", errors.New("请填写完整的本地文件夹路径，例如 D:\\PortShelfDownloads")
	}
	value = filepath.Clean(value)
	if filepath.Dir(value) == value {
		return "", errors.New("请使用磁盘中的专用文件夹，例如 D:\\PortShelfDownloads")
	}
	if runtime.GOOS == "windows" {
		volume := filepath.VolumeName(value)
		if len(volume) != 2 || volume[1] != ':' || !strings.ContainsRune("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ", rune(volume[0])) {
			return "", errors.New("请选择本地磁盘中的文件夹")
		}
		for _, part := range strings.Split(strings.TrimPrefix(value[len(volume):], `\`), `\`) {
			if !validDownloadName(part) {
				return "", errors.New("下载目录包含无效的 Windows 文件夹名称")
			}
		}
	}
	return value, nil
}

func regularDownloadRoot(directory string) (os.FileInfo, error) {
	info, err := os.Lstat(directory)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("下载目录不可用，请检查磁盘是否连接、文件夹是否存在及访问权限")
	}
	resolved, err := filepath.EvalSymlinks(directory)
	if err != nil || !sameLocalFile(directory, resolved) {
		return nil, errors.New("下载目录不能使用符号链接或目录联接，请填写真实文件夹路径")
	}
	return info, nil
}

func (m *transferManager) loadDownloadStorage() error {
	f, err := os.Open(filepath.Join(m.app.lib.root, "download-settings.json"))
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	var config downloadStorage
	if err != nil || len(data) > 1<<20 || json.Unmarshal(data, &config) != nil || config.Version != 1 || len(config.Roots) > 64 {
		return errors.New("下载目录设置损坏，请先备份 download-settings.json 再恢复")
	}
	found := sameLocalFile(config.Directory, m.downloadDir)
	for _, directory := range append([]string{config.Directory}, config.Roots...) {
		if clean, err := downloadPath(directory); err != nil || clean != directory {
			return errors.New("下载目录设置包含无效路径")
		}
	}
	for _, directory := range config.Roots {
		found = found || sameLocalFile(directory, config.Directory)
	}
	if !found {
		return errors.New("当前下载目录未登记，请恢复下载目录设置")
	}
	// An unplugged destination must not prevent opening the library/settings,
	// and must never cause downloads to silently fall back to the system disk.
	m.storage.Store(&config)
	return nil
}

func (m *transferManager) downloadDirectory() string {
	if config := m.storage.Load(); config != nil {
		return config.Directory
	}
	return m.downloadDir
}

func (m *transferManager) downloadRoot(target string) string {
	roots := []string{m.downloadDir}
	if config := m.storage.Load(); config != nil {
		roots = append(roots, config.Roots...)
	}
	for _, root := range roots {
		relative, err := filepath.Rel(root, target)
		if err != nil || filepath.IsAbs(relative) {
			continue
		}
		parts := strings.Split(filepath.ToSlash(relative), "/")
		if len(parts) == 2 && sessionTokenPattern.MatchString(parts[0]) && validDownloadName(parts[1]) {
			return root
		}
	}
	return ""
}

func (m *transferManager) setDownloadDirectory(raw string) error {
	directory, err := downloadPath(raw)
	if err != nil {
		return err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	config := downloadStorage{Version: 1, Directory: directory}
	if previous := m.storage.Load(); previous != nil {
		config.Roots = append([]string{}, previous.Roots...)
	}
	known := sameLocalFile(directory, m.downloadDir)
	for _, root := range config.Roots {
		known = known || sameLocalFile(directory, root)
	}
	if !known {
		if len(config.Roots) >= 64 {
			return errors.New("已保存的下载目录过多，请使用已有目录")
		}
		config.Roots = append(config.Roots, directory)
	}
	// Reject links in existing parents before creating a new child folder.
	for parent := directory; ; parent = filepath.Dir(parent) {
		if _, err := os.Lstat(parent); errors.Is(err, os.ErrNotExist) && filepath.Dir(parent) != parent {
			continue
		}
		if _, err := regularDownloadRoot(parent); err != nil {
			return err
		}
		break
	}
	if err := os.MkdirAll(directory, 0700); err != nil {
		return errors.New("无法创建下载目录，请检查磁盘是否连接、文件夹是否可写")
	}
	if _, err := regularDownloadRoot(directory); err != nil {
		return err
	}
	probe, err := os.CreateTemp(directory, ".portshelf-write-*")
	if err != nil {
		return errors.New("下载目录不可写，请选择其他文件夹")
	}
	probeName := probe.Name()
	defer os.Remove(probeName)
	_, writeErr := probe.Write([]byte("PortShelf"))
	syncErr, closeErr := probe.Sync(), probe.Close()
	if writeErr != nil || syncErr != nil || closeErr != nil {
		return errors.New("下载目录写入失败，请检查磁盘空间和访问权限")
	}
	data, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(m.app.lib.root, ".download-settings-*")
	if err != nil {
		return errors.New("无法保存下载目录设置")
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(data); err == nil {
		err = f.Sync()
	}
	if closeErr := f.Close(); err == nil {
		err = closeErr
	}
	if err == nil {
		err = replaceFile(name, filepath.Join(m.app.lib.root, "download-settings.json"))
	}
	if err != nil {
		return errors.New("无法保存下载目录设置，仍使用原目录")
	}
	m.storage.Store(&config)
	return nil
}
