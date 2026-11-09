package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
	"sync"
	"unicode"
	"unicode/utf16"
	"unicode/utf8"
)

var errAutoStartUnsupported = errors.New("当前系统不支持 PortShelf 的 Windows 登录启动设置")
var autoStartMu sync.Mutex

type autoStartStore interface {
	read(string) (string, bool, error)
	write(string, string) error
	remove(string) error
}

func autoStartValueName(root string) string {
	digest := sha256.Sum256([]byte(strings.ToLower(strings.ReplaceAll(root, "/", "\\"))))
	return "PortShelf-" + hex.EncodeToString(digest[:12])
}

func autoStartPathValid(value string) bool {
	if !utf8.ValidString(value) || strings.ContainsAny(value, "\"%") || strings.IndexFunc(value, unicode.IsControl) >= 0 {
		return false
	}
	// Absolute local/UNC paths are supported. Device namespaces are not logon
	// commands. Percent signs are rejected to avoid environment expansion.
	if len(value) >= 3 && ((value[0] >= 'A' && value[0] <= 'Z') || (value[0] >= 'a' && value[0] <= 'z')) && value[1] == ':' && value[2] == '\\' {
		return true
	}
	if strings.HasPrefix(value, "\\\\") && !strings.HasPrefix(value, "\\\\?\\") && !strings.HasPrefix(value, "\\\\.\\") {
		parts := strings.Split(value[2:], "\\")
		return len(parts) >= 2 && parts[0] != "" && parts[1] != ""
	}
	return false
}

func quoteAutoStartArgument(value string) string {
	// Valid paths cannot contain quotes. Trailing backslashes still need
	// doubling before the closing quote under Windows argv parsing.
	trailing := len(value) - len(strings.TrimRight(value, "\\"))
	return "\"" + value + strings.Repeat("\\", trailing) + "\""
}

func autoStartCommand(executable, root string) (string, error) {
	if !autoStartPathValid(root) || !autoStartPathValid(executable) || !strings.HasSuffix(strings.ToLower(executable), ".exe") {
		return "", errors.New("登录启动需要有效的 Windows 程序和数据目录绝对路径")
	}
	command := quoteAutoStartArgument(executable) + " -no-browser -data-dir " + quoteAutoStartArgument(root)
	// Reserve the terminating NUL within the documented 260-character limit.
	if len(utf16.Encode([]rune(command)))+1 > 260 {
		return "", errors.New("登录启动命令超过 Windows 的 260 字符限制，请使用较短的程序和数据目录路径")
	}
	return command, nil
}

func ownedAutoStartCommand(command, root string) bool {
	suffix := " -no-browser -data-dir " + quoteAutoStartArgument(root)
	if len(command) <= len(suffix)+2 || !strings.EqualFold(command[len(command)-len(suffix):], suffix) {
		return false
	}
	executable := command[:len(command)-len(suffix)]
	if executable[0] != '"' || executable[len(executable)-1] != '"' {
		return false
	}
	executable = executable[1 : len(executable)-1]
	return autoStartPathValid(executable) && strings.HasSuffix(strings.ToLower(executable), ".exe")
}

func configureAutoStart(store autoStartStore, executable, root string, enabled bool) error {
	if !autoStartPathValid(root) {
		return errors.New("登录启动的数据目录路径无效")
	}
	command := ""
	if enabled {
		var err error
		command, err = autoStartCommand(executable, root)
		if err != nil {
			return err
		}
	}
	name := autoStartValueName(root)
	existing, present, err := store.read(name)
	if err != nil {
		return errors.New("无法核对 Windows 登录启动项")
	}
	if present && !ownedAutoStartCommand(existing, root) {
		return errors.New("同名登录启动项并非 PortShelf 创建，未覆盖或删除该启动项")
	}
	if !enabled {
		if !present {
			return nil
		}
		if err := store.remove(name); err != nil {
			return errors.New("无法移除 PortShelf 登录启动项")
		}
		return nil
	}
	if present && existing == command {
		return nil
	}
	if err := store.write(name, command); err != nil {
		return errors.New("无法保存 PortShelf 登录启动项，请检查当前用户注册表权限")
	}
	return nil
}
