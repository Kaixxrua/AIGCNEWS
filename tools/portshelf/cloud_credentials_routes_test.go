package main

import (
	"fmt"
	"strings"
	"testing"
)

func TestCloudRoutesRejectCallerSuppliedRestoreIdentity(t *testing.T) {
	a := testApp(t)
	a.cloud.factory = func(string, CloudCredentials) CloudDrive {
		t.Fatal("internal restore fields reached upstream auth")
		return nil
	}
	for _, provider := range []string{"baidu", "quark"} {
		for _, field := range []string{"refreshToken", "deviceId", "expiresAt", "userId"} {
			response := call(a, "POST", "/api/cloud/"+provider, fmt.Sprintf(`{"%s":"private-test-value"}`, field))
			if response.Code != 400 || strings.Contains(response.Body.String(), "private-test-value") {
				t.Fatalf("caller-controlled %s was accepted or exposed: %d", field, response.Code)
			}
		}
	}
}
