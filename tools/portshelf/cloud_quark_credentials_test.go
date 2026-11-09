package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

func savedQuarkForCredentialsTest() savedCloud {
	return savedCloud{
		Credentials: CloudCredentials{
			AccessToken: "old-access", RefreshToken: "old-refresh", DeviceID: "account-device",
			ExpiresAt: time.Now().Add(-time.Hour).UTC().Format(time.RFC3339), UserID: "user1",
		},
		Session: strings.Repeat("b", 48), Account: "已保存账号",
	}
}

func TestQuarkPendingRotationSavedBeforeAccountLookupFailure(t *testing.T) {
	app := newCredentialTestApp(t)
	m := app.credentials
	saved := savedQuarkForCredentialsTest()
	installSavedTestCredentials(t, app, savedCredentials{Clouds: map[string]savedCloud{"quark": saved}})
	m.load()
	rotations := 0
	failInfo := true
	app.cloud.factory = func(id string, credentials CloudCredentials) CloudDrive {
		if id != "quark" {
			t.Fatal("unexpected provider")
		}
		drive := newQuarkDrive(credentials).(*quarkDrive)
		drive.client.Transport = quarkTestTransport(func(r *http.Request) (*http.Response, error) {
			if r.URL.Host != "open-api-drive.quark.cn" {
				t.Fatal("unexpected upstream target")
			}
			switch r.URL.Path {
			case "/agent/v1/oauth/access_token/rotate":
				rotations++
				var body map[string]string
				if json.NewDecoder(r.Body).Decode(&body) != nil || body["refresh_token"] != "old-refresh" || body["device_id"] != "account-device" {
					t.Fatal("restore did not use saved refresh grant")
				}
				return quarkTestResponse(map[string]any{"access_token": "rotated-access", "refresh_token": "rotated-refresh", "expires_in": 7200}), nil
			case "/open/v1/user/info":
				if r.Header.Get("Authorization") != "Bearer rotated-access" {
					t.Fatal("account lookup did not use rotated access token")
				}
				// Rotation must already be durable before another request can fail.
				disk, err := m.vault.load()
				cached := disk.Clouds["quark"]
				if err != nil || cached.Credentials.RefreshToken != "rotated-refresh" || cached.Credentials.DeviceID != "account-device" || cached.Credentials.UserID != "user1" || cached.Session != saved.Session {
					t.Fatalf("new grant not saved before account lookup: %v", err)
				}
				if failInfo {
					return &http.Response{StatusCode: 503, Header: make(http.Header), Body: io.NopCloser(strings.NewReader("private-upstream-body"))}, nil
				}
				return quarkTestResponse(map[string]string{"user_id": "user1", "nickname": "已恢复账号"}), nil
			default:
				return nil, errors.New("unexpected test request")
			}
		})
		return drive
	}
	m.restorePending()
	if _, exists := app.cloud.get("quark"); exists || len(m.pending) != 1 || rotations != 1 || strings.Contains(app.credentialStatus(), "private-upstream-body") {
		t.Fatal("failed account check activated account or exposed upstream response")
	}
	m.persist()
	disk, err := m.vault.load()
	if err != nil || disk.Clouds["quark"].Credentials.RefreshToken != "rotated-refresh" {
		t.Fatalf("failed account lookup lost rotated credentials: %v", err)
	}
	failInfo = false
	m.restorePending()
	account, exists := app.cloud.get("quark")
	if !exists || account.session != saved.Session || len(m.pending) != 0 || rotations != 1 {
		t.Fatal("retry did not restore saved session with fresh credentials")
	}
	m.persist()
	disk, err = m.vault.load()
	if err != nil || disk.Clouds["quark"].Credentials.RefreshToken != "rotated-refresh" || disk.Clouds["quark"].Account != "已恢复账号" {
		t.Fatalf("successful restore lost refreshed credentials: %v", err)
	}
}

func TestQuarkPendingRefreshCannotOverwriteNewAccount(t *testing.T) {
	app := newCredentialTestApp(t)
	m := app.credentials
	old := savedQuarkForCredentialsTest()
	m.pending["quark"] = old
	started, release, finished := make(chan struct{}), make(chan struct{}), make(chan struct{})
	app.cloud.factory = func(_ string, credentials CloudCredentials) CloudDrive {
		drive := newQuarkDrive(credentials).(*quarkDrive)
		drive.client.Transport = quarkTestTransport(func(r *http.Request) (*http.Response, error) {
			switch r.URL.Path {
			case "/agent/v1/oauth/access_token/rotate":
				close(started)
				select {
				case <-release:
				case <-r.Context().Done():
					return nil, r.Context().Err()
				}
				return quarkTestResponse(map[string]any{"access_token": "old-account-rotated", "refresh_token": "old-account-refresh", "expires_in": 7200}), nil
			case "/open/v1/user/info":
				return quarkTestResponse(map[string]string{"user_id": "user1", "nickname": "旧账号"}), nil
			}
			return nil, errors.New("unexpected test request")
		})
		return drive
	}
	go func() { m.restorePending(); close(finished) }()
	<-started
	newCredentials := CloudCredentials{AccessToken: "new-account-access", RefreshToken: "new-account-refresh", DeviceID: "new-device", UserID: "user2"}
	newDrive := newQuarkDrive(newCredentials)
	newSession := strings.Repeat("c", 48)
	if !app.setCloudAccount("quark", &cloudAccount{drive: newDrive, credentials: newCredentials, session: newSession, account: "新账号"}) {
		t.Fatal("could not replace idle account")
	}
	close(release)
	<-finished
	m.persist()
	disk, err := m.vault.load()
	account, exists := app.cloud.get("quark")
	if err != nil || !exists || account.session != newSession || disk.Clouds["quark"].Credentials != newCredentials || disk.Clouds["quark"].Session != newSession || len(m.pending) != 0 {
		t.Fatalf("late refresh replaced the new account: %v", err)
	}
}

func TestQuarkRestoredIdentityMismatchNeverReusesSession(t *testing.T) {
	app := newCredentialTestApp(t)
	m := app.credentials
	saved := savedQuarkForCredentialsTest()
	saved.Credentials.ExpiresAt = time.Now().Add(time.Hour).UTC().Format(time.RFC3339)
	m.pending["quark"] = saved
	app.cloud.factory = func(_ string, credentials CloudCredentials) CloudDrive {
		drive := newQuarkDrive(credentials).(*quarkDrive)
		drive.client.Transport = quarkTestTransport(func(r *http.Request) (*http.Response, error) {
			if r.URL.Path != "/open/v1/user/info" {
				t.Fatal("unexpected refresh")
			}
			return quarkTestResponse(map[string]string{"user_id": "different_user", "nickname": "另一个账号"}), nil
		})
		return drive
	}
	m.restorePending()
	if _, exists := app.cloud.get("quark"); exists || m.pending["quark"].Session != saved.Session || app.credentialStatus() == "" {
		t.Fatal("restored authorization for another account inherited the saved session")
	}
}

func TestQuarkActiveRotationPersistsGrantAndHeaderToken(t *testing.T) {
	app := newCredentialTestApp(t)
	m := app.credentials
	saved := savedQuarkForCredentialsTest()
	drive := newQuarkDrive(saved.Credentials).(*quarkDrive)
	app.watchCloudCredentials(drive)
	if !app.setCloudAccount("quark", &cloudAccount{drive: drive, account: saved.Account, session: saved.Session, credentials: saved.Credentials}) {
		t.Fatal("could not install active account")
	}
	m.persist()
	drive.client.Transport = quarkTestTransport(func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case "/agent/v1/oauth/access_token/rotate":
			return quarkTestResponse(map[string]any{"access_token": "active-rotated", "refresh_token": "active-refresh", "expires_in": 7200}), nil
		case "/open/v1/user/info":
			disk, err := m.vault.load()
			if err != nil || disk.Clouds["quark"].Credentials.AccessToken != "active-rotated" || disk.Clouds["quark"].Credentials.RefreshToken != "active-refresh" {
				t.Fatalf("live grant rotation was not durable before next request: %v", err)
			}
			response := quarkTestResponse(map[string]string{"user_id": "user1", "nickname": "账号"})
			response.Header.Set("X-New-Access-Token", "header-rotated")
			return response, nil
		default:
			return nil, errors.New("unexpected test request")
		}
	})
	if _, err := drive.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	disk, err := m.vault.load()
	cloud := disk.Clouds["quark"]
	if err != nil || cloud.Credentials.AccessToken != "header-rotated" || cloud.Credentials.RefreshToken != "active-refresh" ||
		cloud.Credentials.DeviceID != "account-device" || cloud.Credentials.UserID != "user1" || cloud.Session != saved.Session {
		t.Fatalf("response token update lost session or refresh grant: %v", err)
	}
}
