package main

import (
	"regexp"
	"strings"
)

var auxiliaryAsset = regexp.MustCompile(`(^|[._-])(symbols|debug|source|src|server|mods|addons|sdk|dev)([._-]|$)`)
var systemMarkers = []struct {
	name    string
	pattern *regexp.Regexp
}{
	{"macOS", regexp.MustCompile(`(^|[._-])(macos|mac|osx|darwin)([._-]|$)|\.dmg$`)},
	{"Linux", regexp.MustCompile(`(^|[._-])(linux|ubuntu|debian|fedora)([._-]|$)|\.(appimage|deb|rpm)$`)},
	{"Android", regexp.MustCompile(`(^|[._-])android([._-]|$)|\.(apk|aab)$`)},
	{"iOS", regexp.MustCompile(`(^|[._-])ios([._-]|$)|\.ipa$`)},
	{"FreeBSD", regexp.MustCompile(`(^|[._-])freebsd([._-]|$)`)},
}

// Report evidence from distributable release attachments, never model guesses.
// This describes the packages published by upstream, not every OS the source
// code might theoretically compile on. Empty means that support is unverified.
func supportedSystems(assets []Asset) []string {
	seen := map[string]bool{}
	for _, asset := range assets {
		name := strings.ToLower(asset.Name)
		if asset.Size <= 0 || !validDownloadName(asset.Name) || auxiliaryAsset.MatchString(name) || strings.Contains(name, "checksum") || strings.Contains(name, ".sha") || strings.Contains(name, "mingw-dev") {
			continue
		}
		packageFile := false
		for _, suffix := range []string{".zip", ".7z", ".rar", ".exe", ".msi", ".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".dmg", ".appimage", ".deb", ".rpm", ".apk", ".aab", ".ipa", ".pkg"} {
			if strings.HasSuffix(name, suffix) {
				packageFile = true
				break
			}
		}
		if !packageFile {
			continue
		}
		classifyAsset(&asset)
		systems := []string{}
		if asset.Windows {
			systems = append(systems, "Windows")
		}
		for _, marker := range systemMarkers {
			if marker.pattern.MatchString(name) {
				systems = append(systems, marker.name)
			}
		}
		for _, system := range systems {
			suffix := ""
			switch asset.Arch {
			case "amd64":
				suffix = " x64"
			case "arm64":
				suffix = " ARM64"
			case "386":
				suffix = " x86"
			}
			if system == "macOS" && strings.Contains(name, "universal") {
				suffix = " Universal"
			}
			seen[system+suffix] = true
		}
	}
	result := []string{}
	for _, system := range []string{"Windows", "macOS", "Linux", "Android", "iOS", "FreeBSD"} {
		for _, suffix := range []string{"", " x64", " ARM64", " x86", " Universal"} {
			if seen[system+suffix] {
				result = append(result, system+suffix)
			}
		}
	}
	return result
}

func systemDescription(systems []string) string {
	if len(systems) == 0 {
		return "支持系统待核实"
	}
	return strings.Join(systems, "、")
}
