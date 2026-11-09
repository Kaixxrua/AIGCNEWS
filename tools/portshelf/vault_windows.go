package main

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"syscall"
	"unsafe"
)

// Current-user scope is the DPAPI default; LOCAL_MACHINE is deliberately absent.
// https://learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
const cryptProtectUIForbidden = 0x1

var credentialCrypt32 = syscall.NewLazyDLL("crypt32.dll")
var credentialProtect = credentialCrypt32.NewProc("CryptProtectData")
var credentialUnprotect = credentialCrypt32.NewProc("CryptUnprotectData")
var credentialLocalFree = syscall.NewLazyDLL("kernel32.dll").NewProc("LocalFree")

type credentialDataBlob struct {
	Size uint32
	Data *byte
}

func credentialProtectionAvailable() bool {
	return credentialProtect.Find() == nil && credentialUnprotect.Find() == nil && credentialLocalFree.Find() == nil
}

func protectCredentialBytes(plain []byte) ([]byte, error) {
	return transformCredentialBytes(plain, true)
}

func unprotectCredentialBytes(protected []byte) ([]byte, error) {
	return transformCredentialBytes(protected, false)
}

func transformCredentialBytes(input []byte, protect bool) ([]byte, error) {
	if !credentialProtectionAvailable() {
		return nil, errCredentialProtectionUnsupported
	}
	if len(input) == 0 || len(input) > maxCredentialCiphertext {
		return nil, errors.New("Windows 凭据加密数据大小无效")
	}
	entropy := []byte("PortShelf.Credentials.v1")
	in := credentialDataBlob{Size: uint32(len(input)), Data: &input[0]}
	extra := credentialDataBlob{Size: uint32(len(entropy)), Data: &entropy[0]}
	var out credentialDataBlob
	procedure := credentialUnprotect
	if protect {
		procedure = credentialProtect
	}
	ok, _, _ := procedure.Call(
		uintptr(unsafe.Pointer(&in)), 0, uintptr(unsafe.Pointer(&extra)),
		0, 0, cryptProtectUIForbidden, uintptr(unsafe.Pointer(&out)),
	)
	runtime.KeepAlive(input)
	runtime.KeepAlive(entropy)
	if out.Data != nil {
		defer credentialLocalFree.Call(uintptr(unsafe.Pointer(out.Data)))
	}
	if out.Data != nil && out.Size > 0 && out.Size <= maxCredentialCiphertext {
		defer clear(unsafe.Slice(out.Data, int(out.Size)))
	}
	if ok == 0 || out.Data == nil || out.Size == 0 || out.Size > maxCredentialCiphertext {
		return nil, errors.New("Windows 当前用户凭据加密操作失败")
	}
	output := unsafe.Slice(out.Data, int(out.Size))
	result := append([]byte(nil), output...)
	// Deferred cleanup clears the OS-owned plaintext buffer before LocalFree.
	// The caller clears temporary Go byte buffers after use.
	return result, nil
}

const autoStartRegistryKey = `Software\Microsoft\Windows\CurrentVersion\Run`
const autoStartKeyAccess = 0x0001 | 0x0002 // QUERY_VALUE | SET_VALUE, current user only.
const autoStartRegistryString = 1

var autoStartAdvapi = syscall.NewLazyDLL("advapi32.dll")
var autoStartCreateKey = autoStartAdvapi.NewProc("RegCreateKeyExW")
var autoStartSetValue = autoStartAdvapi.NewProc("RegSetValueExW")
var autoStartDeleteValue = autoStartAdvapi.NewProc("RegDeleteValueW")

func autoStartSupported() bool {
	return autoStartCreateKey.Find() == nil && autoStartSetValue.Find() == nil && autoStartDeleteValue.Find() == nil
}

type windowsAutoStartStore struct{ key syscall.Handle }

func (store windowsAutoStartStore) read(name string) (string, bool, error) {
	keyName, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return "", false, errors.New("启动项名称无效")
	}
	var valueType, size uint32
	err = syscall.RegQueryValueEx(store.key, keyName, nil, &valueType, nil, &size)
	if err == syscall.ERROR_FILE_NOT_FOUND {
		return "", false, nil
	}
	if err != nil {
		return "", false, errors.New("无法读取启动项")
	}
	// Do not modify an unrelated value with the same name or accept unterminated
	// registry strings. Never expose another application's command in errors.
	if valueType != autoStartRegistryString || size < 2 || size > 2*260 || size%2 != 0 {
		return "", true, errors.New("已有启动项格式无效")
	}
	value := make([]uint16, size/2)
	err = syscall.RegQueryValueEx(store.key, keyName, nil, &valueType, (*byte)(unsafe.Pointer(&value[0])), &size)
	if err != nil || valueType != autoStartRegistryString || size < 2 || int(size) > len(value)*2 || size%2 != 0 {
		return "", true, errors.New("启动项读取失败或发生变化")
	}
	value = value[:size/2]
	if value[len(value)-1] != 0 {
		return "", true, errors.New("启动项字符串未正确结束")
	}
	for _, char := range value[:len(value)-1] {
		if char == 0 {
			return "", true, errors.New("启动项字符串包含多余数据")
		}
	}
	return syscall.UTF16ToString(value), true, nil
}

func (store windowsAutoStartStore) write(name, command string) error {
	keyName, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return errors.New("启动项名称无效")
	}
	value, err := syscall.UTF16FromString(command)
	if err != nil {
		return errors.New("启动项命令无效")
	}
	code, _, _ := autoStartSetValue.Call(uintptr(store.key), uintptr(unsafe.Pointer(keyName)), 0, autoStartRegistryString,
		uintptr(unsafe.Pointer(&value[0])), uintptr(len(value)*2))
	runtime.KeepAlive(value)
	if code != 0 {
		return errors.New("无法写入启动项")
	}
	return nil
}

func (store windowsAutoStartStore) remove(name string) error {
	keyName, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return errors.New("启动项名称无效")
	}
	code, _, _ := autoStartDeleteValue.Call(uintptr(store.key), uintptr(unsafe.Pointer(keyName)))
	if code != 0 && code != uintptr(syscall.ERROR_FILE_NOT_FOUND) {
		return errors.New("无法删除启动项")
	}
	return nil
}

func setAutoStart(root string, enabled bool) error {
	autoStartMu.Lock()
	defer autoStartMu.Unlock()
	if !autoStartSupported() {
		return errAutoStartUnsupported
	}
	if root == "" {
		return errors.New("登录启动的数据目录无效")
	}
	absolute, err := filepath.Abs(root)
	if err != nil || !autoStartPathValid(absolute) {
		return errors.New("登录启动的数据目录无效")
	}
	executable := ""
	if enabled {
		info, err := os.Stat(absolute)
		if err != nil || !info.IsDir() {
			return errors.New("登录启动的数据目录不存在")
		}
		executable, err = os.Executable()
		if err != nil {
			return errors.New("无法获取当前 PortShelf 程序路径")
		}
		if _, err = autoStartCommand(executable, absolute); err != nil {
			return err
		}
	}
	subkey, _ := syscall.UTF16PtrFromString(autoStartRegistryKey)
	var key syscall.Handle
	if enabled {
		code, _, _ := autoStartCreateKey.Call(uintptr(syscall.HKEY_CURRENT_USER), uintptr(unsafe.Pointer(subkey)),
			0, 0, 0, autoStartKeyAccess, 0, uintptr(unsafe.Pointer(&key)), 0)
		if code != 0 {
			return errors.New("无法打开当前用户的登录启动设置")
		}
	} else {
		err := syscall.RegOpenKeyEx(syscall.HKEY_CURRENT_USER, subkey, 0, autoStartKeyAccess, &key)
		if err == syscall.ERROR_FILE_NOT_FOUND {
			return nil
		}
		if err != nil {
			return errors.New("无法打开当前用户的登录启动设置")
		}
	}
	defer syscall.RegCloseKey(key)
	return configureAutoStart(windowsAutoStartStore{key: key}, executable, absolute, enabled)
}
