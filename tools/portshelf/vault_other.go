//go:build !windows

package main

func credentialProtectionAvailable() bool { return false }

func protectCredentialBytes([]byte) ([]byte, error) {
	return nil, errCredentialProtectionUnsupported
}

func unprotectCredentialBytes([]byte) ([]byte, error) {
	return nil, errCredentialProtectionUnsupported
}

func autoStartSupported() bool { return false }

func setAutoStart(string, bool) error { return errAutoStartUnsupported }
