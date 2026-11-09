package main

import (
	"crypto/sha256"
	"fmt"
	"strings"
	"syscall"
	"unsafe"
)

func notifyUser(title, message string) {
	caption, _ := syscall.UTF16PtrFromString(title)
	text, _ := syscall.UTF16PtrFromString(strings.ReplaceAll(message, "\x00", ""))
	_, _, _ = syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(text)), uintptr(unsafe.Pointer(caption)), 0x10)
}

func openURL(target string) error {
	dll := syscall.NewLazyDLL("shell32.dll")
	proc := dll.NewProc("ShellExecuteW")
	verb, _ := syscall.UTF16PtrFromString("open")
	path, err := syscall.UTF16PtrFromString(target)
	if err != nil {
		return err
	}
	result, _, _ := proc.Call(0, uintptr(unsafe.Pointer(verb)), uintptr(unsafe.Pointer(path)), 0, 0, 1)
	if result <= 32 {
		return fmt.Errorf("Windows 无法打开浏览器（错误 %d）", result)
	}
	return nil
}

func lockLibrary(root string) (func(), error) {
	name, _ := syscall.UTF16PtrFromString(fmt.Sprintf("Local\\PortShelf-%x", sha256.Sum256([]byte(strings.ToLower(root)))))
	kernel := syscall.NewLazyDLL("kernel32.dll")
	handle, _, err := kernel.NewProc("CreateMutexW").Call(0, 0, uintptr(unsafe.Pointer(name)))
	if handle == 0 {
		return nil, err
	}
	close := func() { _, _, _ = kernel.NewProc("CloseHandle").Call(handle) }
	if err == syscall.ERROR_ALREADY_EXISTS {
		close()
		return nil, errRunning
	}
	return close, nil
}

// os.Rename does not promise replacement on Windows. Replace the existing cache
// with MoveFileExW and flush the move before publishing its in-memory version.
func replaceFile(source, target string) error {
	from, err := syscall.UTF16PtrFromString(source)
	if err != nil {
		return err
	}
	to, err := syscall.UTF16PtrFromString(target)
	if err != nil {
		return err
	}
	const moveFileReplaceExisting = 0x1
	const moveFileWriteThrough = 0x8
	ok, _, callErr := syscall.NewLazyDLL("kernel32.dll").NewProc("MoveFileExW").Call(uintptr(unsafe.Pointer(from)), uintptr(unsafe.Pointer(to)), moveFileReplaceExisting|moveFileWriteThrough)
	if ok == 0 {
		return callErr
	}
	return nil
}
