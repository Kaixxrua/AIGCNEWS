package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

type automationExportWriter struct {
	file   *os.File
	header http.Header
	err    error
}

func (w *automationExportWriter) Header() http.Header { return w.header }
func (w *automationExportWriter) WriteHeader(int)     {}
func (w *automationExportWriter) Write(data []byte) (int, error) {
	if w.err != nil {
		return 0, w.err
	}
	n, err := w.file.Write(data)
	if err != nil {
		w.err = err
	} else if n != len(data) {
		w.err = io.ErrShortWrite
	}
	return n, w.err
}

var automationExportFormats = []struct{ format, name string }{
	{"json", "最新游戏清单.json"}, {"csv", "最新游戏清单.csv"}, {"markdown", "最新游戏清单.md"},
}

// Files are staged and synced before any destination is replaced. Each target
// is replaced atomically; if a later rename fails, the old digest remains so
// all three files are retried as one snapshot on the next tick.
func writeAutomationExports(directory string, jobs []TransferJob) error {
	if err := os.MkdirAll(directory, 0700); err != nil {
		return err
	}
	info, err := os.Lstat(directory)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("导出目录不是安全的本地文件夹")
	}
	temporaries := []string{}
	defer func() {
		for _, name := range temporaries {
			_ = os.Remove(name)
		}
	}()
	for _, format := range automationExportFormats {
		file, err := os.CreateTemp(directory, ".portshelf-export-*")
		if err != nil {
			return err
		}
		temporaries = append(temporaries, file.Name())
		writer := &automationExportWriter{file: file, header: make(http.Header)}
		err = exportTransfers(writer, format.format, jobs)
		if err == nil {
			err = writer.err
		}
		if err == nil {
			err = file.Sync()
		}
		if closeErr := file.Close(); err == nil {
			err = closeErr
		}
		if err != nil {
			return err
		}
	}
	for index, format := range automationExportFormats {
		if err := replaceFile(temporaries[index], filepath.Join(directory, format.name)); err != nil {
			return err
		}
	}
	return nil
}

func automationExportsExist(directory string) bool {
	info, err := os.Lstat(directory)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return false
	}
	for _, format := range automationExportFormats {
		info, err := os.Lstat(filepath.Join(directory, format.name))
		if err != nil || !info.Mode().IsRegular() || info.Size() == 0 {
			return false
		}
	}
	return true
}

func (m *automationManager) exportLatest() {
	jobs, storeError := m.app.transfers.snapshot()
	if storeError != "" {
		m.recordExport("任务记录未能保存，自动导出等待恢复", "")
		return
	}
	// materials keeps only verified downloaded files. Preserve those rows even
	// when a later upload is paused, cancelled or awaiting a retry.
	encoded, err := json.Marshal(materials(jobs))
	if err != nil {
		m.recordExport("无法整理本地游戏资料，将自动重试", "")
		return
	}
	sum := sha256.Sum256(encoded)
	digest := hex.EncodeToString(sum[:])
	directory := filepath.Join(m.app.lib.root, "exports")
	m.mu.Lock()
	unchanged := m.state.ExportDigest == digest && m.state.ExportError == ""
	m.mu.Unlock()
	if unchanged && automationExportsExist(directory) {
		return
	}
	if err := writeAutomationExports(directory, jobs); err != nil {
		m.recordExport("自动导出失败，请检查 exports 目录的磁盘空间和权限；恢复后会自动重试", "")
		return
	}
	m.recordExport("", digest)
}

func (m *automationManager) recordExport(message, digest string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if message != "" && message == m.state.ExportError {
		return
	}
	next := m.state
	next.ExportError = message
	if digest != "" {
		next.ExportDigest, next.ExportedAt = digest, m.now().UTC().Format(time.RFC3339)
	}
	_ = m.saveLocked(next)
}
