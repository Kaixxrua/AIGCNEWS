package main

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"sync"
	"time"
)

// Credentials never enter task records, exports or browser storage.
type CloudCredentials struct {
	Cookie       string `json:"cookie"`
	AccessToken  string `json:"accessToken"`
	AuthCode     string `json:"authCode"`
	RefreshToken string `json:"refreshToken,omitempty"`
	DeviceID     string `json:"deviceId,omitempty"`
	ExpiresAt    string `json:"expiresAt,omitempty"`
	UserID       string `json:"userId,omitempty"`
}

type CloudFile struct {
	ID   string `json:"id"`
	Path string `json:"path"`
	Name string `json:"name"`
}

type CloudShare struct {
	URL       string `json:"url"`
	Code      string `json:"code"`
	ExpiresAt string `json:"expiresAt"`
}

type ShareOptions struct {
	Days    int    `json:"days"`
	Code    string `json:"code"`
	Private bool   `json:"private"`
}

type UploadProgress func(done, total int64)

type CloudDrive interface {
	Check(context.Context) (string, error)
	Upload(context.Context, string, string, UploadProgress) (CloudFile, error)
	Share(context.Context, CloudFile, ShareOptions) (CloudShare, error)
}

type cloudStatus struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Configured bool   `json:"configured"`
	Account    string `json:"account"`
	AuthMode   string `json:"authMode"`
}

type cloudAccount struct {
	drive       CloudDrive
	account     string
	credentials CloudCredentials
	// A random session identity prevents retrying an old file ID with a
	// different account. A fresh login rotates it; verified vault restoration
	// preserves it so completed uploads can be reused across restarts.
	session string
}

type cloudRegistry struct {
	mu       sync.RWMutex
	accounts map[string]cloudAccount
	factory  func(string, CloudCredentials) CloudDrive
}

func newCloudRegistry() *cloudRegistry {
	return &cloudRegistry{accounts: map[string]cloudAccount{}, factory: func(id string, c CloudCredentials) CloudDrive {
		switch id {
		case "baidu":
			return newBaiduDrive(c)
		case "quark":
			return newQuarkDrive(c)
		}
		return nil
	}}
}

func validDrive(id string) bool { return id == "baidu" || id == "quark" }

func (c *cloudRegistry) get(id string) (cloudAccount, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	account, ok := c.accounts[id]
	return account, ok
}

func (c *cloudRegistry) statuses() []cloudStatus {
	result := []cloudStatus{{ID: "baidu", Name: "百度网盘", AuthMode: "cookie"}, {ID: "quark", Name: "夸克网盘", AuthMode: "authCode"}}
	for i := range result {
		if account, ok := c.get(result[i].ID); ok {
			result[i].Configured, result[i].Account = true, account.account
		}
	}
	return result
}

func validCloudCredentials(c CloudCredentials) bool {
	for _, value := range []string{c.Cookie, c.AccessToken, c.AuthCode, c.RefreshToken, c.DeviceID, c.ExpiresAt, c.UserID} {
		if len(value) > 12000 {
			return false
		}
		for _, char := range value {
			if char < 32 || char > 126 {
				return false
			}
		}
	}
	return true
}

func (a *App) registerCloudRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/cloud", func(w http.ResponseWriter, r *http.Request) {
		reply(w, http.StatusOK, map[string]any{"providers": a.cloud.statuses(), "downloadDir": a.transfers.downloadDirectory(), "credentialStorage": a.credentialStorageStatus()})
	})
	mux.HandleFunc("POST /api/cloud/quark/authorize", func(w http.ResponseWriter, r *http.Request) {
		var body struct{}
		if err := decode(w, r, &body); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 25*time.Second)
		defer cancel()
		target, err := quarkAuthorizationURL(ctx)
		if err != nil {
			fail(w, http.StatusBadGateway, err)
			return
		}
		reply(w, http.StatusOK, map[string]string{"url": target})
	})
	mux.HandleFunc("POST /api/cloud/{provider}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("provider")
		if !validDrive(id) {
			fail(w, http.StatusNotFound, errors.New("不支持的网盘"))
			return
		}
		var credentials CloudCredentials
		if err := decode(w, r, &credentials); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		credentials.Cookie = strings.TrimSpace(credentials.Cookie)
		credentials.AccessToken = strings.TrimSpace(credentials.AccessToken)
		credentials.AuthCode = strings.TrimSpace(credentials.AuthCode)
		if !validCloudCredentials(credentials) {
			fail(w, http.StatusBadRequest, errors.New("登录信息格式无效或过长，请只粘贴凭据值"))
			return
		}
		if credentials.RefreshToken != "" || credentials.DeviceID != "" || credentials.ExpiresAt != "" || credentials.UserID != "" {
			fail(w, http.StatusBadRequest, errors.New("请使用授权页面登录，续期信息由工具自动管理"))
			return
		}
		if a.transfers.providerBusy(id) {
			fail(w, http.StatusConflict, errors.New("网盘正在处理任务，请先停止任务再更换或清除登录"))
			return
		}
		if credentials == (CloudCredentials{}) {
			if !a.setCloudAccount(id, nil) {
				fail(w, http.StatusConflict, errors.New("网盘正在处理任务，请先停止任务再更换或清除登录"))
				return
			}
			if a.credentials != nil {
				a.credentials.persist()
			}
			a.credentialsChanged()
			reply(w, http.StatusOK, map[string]any{"id": id, "configured": false, "account": "", "credentialStorage": a.credentialStorageStatus()})
			return
		}
		if id == "baidu" && (credentials.Cookie == "" || credentials.AccessToken != "" || credentials.AuthCode != "") ||
			id == "quark" && (credentials.Cookie != "" || (credentials.AccessToken == "") == (credentials.AuthCode == "")) {
			fail(w, http.StatusBadRequest, errors.New("百度请填写网页登录 Cookie；夸克请填写授权码或 Access Token 其中一种"))
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 25*time.Second)
		defer cancel()
		drive := a.cloud.factory(id, credentials)
		a.watchCloudCredentials(drive)
		account, err := drive.Check(ctx)
		if err != nil {
			fail(w, http.StatusBadGateway, err)
			return
		}
		if !a.setCloudAccount(id, &cloudAccount{drive: drive, account: account, credentials: credentials, session: randomID()}) {
			fail(w, http.StatusConflict, errors.New("验证期间网盘任务已开始，请先停止任务再更换登录"))
			return
		}
		// Finish the local encrypted write before acknowledging the connection.
		// A storage error keeps this session usable and is surfaced separately.
		if a.credentials != nil {
			a.credentials.persist()
		}
		a.credentialsChanged()
		a.transfers.credentialsAvailable(id)
		reply(w, http.StatusOK, map[string]any{"id": id, "configured": true, "account": account, "credentialStorage": a.credentialStorageStatus()})
	})
}
