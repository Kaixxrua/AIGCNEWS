package main

import (
	"errors"
	"strings"
	"testing"
	"unicode/utf16"
)

type fakeAutoStartStore struct {
	values    map[string]string
	writes    int
	removals  int
	readErr   error
	writeErr  error
	removeErr error
}

func (store *fakeAutoStartStore) read(name string) (string, bool, error) {
	value, present := store.values[name]
	return value, present, store.readErr
}
func (store *fakeAutoStartStore) write(name, value string) error {
	store.writes++
	if store.writeErr != nil {
		return store.writeErr
	}
	store.values[name] = value
	return nil
}
func (store *fakeAutoStartStore) remove(name string) error {
	store.removals++
	if store.removeErr != nil {
		return store.removeErr
	}
	delete(store.values, name)
	return nil
}

func TestAutoStartOwnsOnlyCurrentDataDirectoryEntry(t *testing.T) {
	root := "C:\\Users\\Player\\PortShelf data"
	executable := "C:\\Games\\Port Shelf\\PortShelf.exe"
	store := &fakeAutoStartStore{values: map[string]string{
		"OtherProgram": "\"C:\\Other\\program.exe\"",
		"PortShelf":    "pre-existing unrelated value",
	}}
	name := autoStartValueName(root)
	if err := configureAutoStart(store, executable, root, true); err != nil {
		t.Fatal(err)
	}
	want := "\"C:\\Games\\Port Shelf\\PortShelf.exe\" -no-browser -data-dir \"C:\\Users\\Player\\PortShelf data\""
	if store.values[name] != want || store.writes != 1 {
		t.Fatalf("unexpected startup command or writes: %q (%d)", store.values[name], store.writes)
	}
	if err := configureAutoStart(store, executable, root, true); err != nil || store.writes != 1 {
		t.Fatalf("duplicate setup was not idempotent: %v", err)
	}
	upgraded := "D:\\New release\\PortShelf.exe"
	if err := configureAutoStart(store, upgraded, root, true); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(store.values[name], "\"D:\\New release\\PortShelf.exe\" ") || store.writes != 2 {
		t.Fatal("upgrade did not replace its own executable")
	}
	secondRoot := "C:\\Users\\Player\\Other library"
	if err := configureAutoStart(store, executable, secondRoot, true); err != nil {
		t.Fatal(err)
	}
	if autoStartValueName(secondRoot) == name || len(store.values) != 4 {
		t.Fatal("different data directories collided")
	}
	if err := configureAutoStart(store, "", root, false); err != nil {
		t.Fatal(err)
	}
	if _, present := store.values[name]; present {
		t.Fatal("own startup entry remained enabled")
	}
	if len(store.values) != 3 || store.values["OtherProgram"] == "" || store.values["PortShelf"] != "pre-existing unrelated value" ||
		store.values[autoStartValueName(secondRoot)] == "" {
		t.Fatal("disable altered another startup item")
	}
	if err := configureAutoStart(store, "", root, false); err != nil || store.removals != 1 {
		t.Fatalf("duplicate removal was not idempotent: %v", err)
	}
	if autoStartValueName(root) != autoStartValueName(strings.ToLower(root)) {
		t.Fatal("Windows path case created a separate startup entry")
	}
}

func TestAutoStartRefusesForeignEntryAndSanitizesErrors(t *testing.T) {
	root := "C:\\PortShelf data"
	executable := "C:\\PortShelf\\PortShelf.exe"
	name := autoStartValueName(root)
	for _, foreign := range []string{
		"foreign-secret-program.exe --password=secret",
		"\"C:\\Other\\other.exe\" -no-browser -data-dir \"C:\\Different data\"",
		"\"C:\\PortShelf\\PortShelf.exe\" -no-browser -data-dir \"C:\\PortShelf data\" & other.exe",
	} {
		for _, enabled := range []bool{true, false} {
			store := &fakeAutoStartStore{values: map[string]string{name: foreign}}
			err := configureAutoStart(store, executable, root, enabled)
			if err == nil || strings.Contains(err.Error(), "secret") || store.writes != 0 || store.removals != 0 || store.values[name] != foreign {
				t.Fatalf("foreign entry overwritten or leaked: %v", err)
			}
		}
	}
	for _, failure := range []string{"read", "write", "remove"} {
		t.Run(failure, func(t *testing.T) {
			command, err := autoStartCommand(executable, root)
			if err != nil {
				t.Fatal(err)
			}
			store := &fakeAutoStartStore{values: map[string]string{}}
			raw := errors.New("raw-registry-secret")
			enabled := true
			switch failure {
			case "read":
				store.readErr = raw
			case "write":
				store.writeErr = raw
			case "remove":
				store.values[name], store.removeErr, enabled = command, raw, false
			}
			err = configureAutoStart(store, executable, root, enabled)
			if err == nil || strings.Contains(err.Error(), "raw-registry-secret") {
				t.Fatalf("registry error not sanitized: %v", err)
			}
		})
	}
}

func TestAutoStartCommandQuotesPathsAndEnforcesWindowsLimit(t *testing.T) {
	for _, test := range []struct{ executable, root, want string }{
		{"C:\\程序 & Games\\PortShelf.exe", "C:\\游戏资料", "\"C:\\程序 & Games\\PortShelf.exe\" -no-browser -data-dir \"C:\\游戏资料\""},
		{"C:\\PortShelf.exe", "C:\\", "\"C:\\PortShelf.exe\" -no-browser -data-dir \"C:\\\\\""},
		{"\\\\host\\share\\PortShelf.exe", "\\\\host\\share\\data", "\"\\\\host\\share\\PortShelf.exe\" -no-browser -data-dir \"\\\\host\\share\\data\""},
	} {
		command, err := autoStartCommand(test.executable, test.root)
		if err != nil || command != test.want || !ownedAutoStartCommand(command, test.root) {
			t.Fatalf("Windows command quoting: %q, %v", command, err)
		}
	}
	for _, invalid := range []string{"relative", "/unix/path", "C:relative", "C:\\bad\"path", "C:\\bad\npath", "C:\\bad\x00path", "C:\\%USERPROFILE%", "\\\\?\\C:\\extended", "\\\\.\\device", "\\\\host", "C:\\\xff"} {
		if _, err := autoStartCommand("C:\\PortShelf.exe", invalid); err == nil {
			t.Fatalf("accepted invalid data path %q", invalid)
		}
		if _, err := autoStartCommand(invalid, "C:\\Data"); err == nil {
			t.Fatalf("accepted invalid executable path %q", invalid)
		}
	}
	if _, err := autoStartCommand("C:\\script.cmd", "C:\\Data"); err == nil {
		t.Fatal("startup accepted non-executable")
	}
	root := "C:\\" + strings.Repeat("a", 210)
	for {
		command := quoteAutoStartArgument("C:\\PortShelf.exe") + " -no-browser -data-dir " + quoteAutoStartArgument(root)
		length := len(utf16.Encode([]rune(command))) + 1
		if length >= 260 {
			_, err := autoStartCommand("C:\\PortShelf.exe", root)
			if length == 260 && err != nil {
				t.Fatal("valid 260-character boundary rejected")
			}
			if _, err := autoStartCommand("C:\\PortShelf.exe", root+"a"); err == nil {
				t.Fatal("oversize Run command accepted")
			}
			break
		}
		root += "a"
	}
	if _, err := autoStartCommand("C:\\PortShelf.exe", "C:\\"+strings.Repeat("🎮", 130)); err == nil {
		t.Fatal("UTF-16 character limit counted supplementary characters as one unit")
	}
}
