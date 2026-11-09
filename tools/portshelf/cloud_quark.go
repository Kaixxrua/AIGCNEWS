package main

// Independent implementation of the public Quark Drive Agent protocol, checked
// against the official quarkclouddrive 1.0.20 distribution linked from:
// https://www.quark.cn/documents/help/quark-drive-skill
// No SDK code, telemetry, executable or user credentials are bundled. The
// third_party_agent parameters below are the SDK's public WILD_DEFAULT_CLIENT_INFO
// (its secretKey is empty), not an application private key or account credential.

import (
	"bytes"
	"context"
	"crypto/md5"
	"crypto/rand"
	"crypto/sha1"
	"crypto/sha256"
	"encoding"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	quarkAPIOrigin = "https://open-api-drive.quark.cn"
	quarkClientID  = "third_party_agent"
	quarkSignKey   = "cf134812e2de4032bd1cb7c3727e84b3"
	quarkDeviceID  = "wild_claw"
	quarkAgentID   = "portshelf"
	quarkMaxReply  = 4 << 20
	quarkMaxParts  = 10000
)

var quarkDeviceIdentity = sync.OnceValues(func() (string, error) {
	value := make([]byte, 16)
	if _, err := rand.Read(value); err != nil {
		return "", errors.New("无法生成夸克授权设备标识")
	}
	return "portshelf-" + hex.EncodeToString(value), nil
})

type quarkDrive struct {
	client            *http.Client
	authGate          chan struct{}
	mu                sync.Mutex
	token             string
	authCode          string
	refresh           string
	deviceID          string
	expires           time.Time
	userID            string
	name              string
	badAuth           bool
	credentialChanged func()
}

func newQuarkDrive(credentials CloudCredentials) CloudDrive {
	return &quarkDrive{
		client: newQuarkHTTPClient(), authGate: make(chan struct{}, 1),
		token: strings.TrimSpace(credentials.AccessToken), authCode: strings.TrimSpace(credentials.AuthCode),
		refresh: credentials.RefreshToken, deviceID: credentials.DeviceID, userID: credentials.UserID,
		expires: quarkExpiry(json.RawMessage(strconv.Quote(credentials.ExpiresAt))),
		badAuth: credentials.Cookie != "" || !quarkCredential(credentials.AccessToken, true) || !quarkCredential(credentials.AuthCode, true),
	}
}

func quarkCredential(value string, emptyOK bool) bool {
	if (!emptyOK && value == "") || len(value) > 12000 {
		return false
	}
	for _, c := range value {
		if c < 33 || c > 126 {
			return false
		}
	}
	return true
}

func newQuarkHTTPClient() *http.Client {
	transport := &http.Transport{
		DialContext: quarkPublicDial, ForceAttemptHTTP2: true,
		TLSHandshakeTimeout: 10 * time.Second, ResponseHeaderTimeout: 45 * time.Second,
		IdleConnTimeout: 60 * time.Second, MaxIdleConns: 8, MaxIdleConnsPerHost: 4,
		MaxResponseHeaderBytes: 32 << 10,
	}
	return &http.Client{Transport: transport, Timeout: 10 * time.Minute,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

// Resolve, reject all non-public answers, and dial the checked IP directly. This
// also prevents DNS rebinding between validation and connection establishment.
func quarkPublicDial(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil || port != "443" {
		return nil, errors.New("夸克连接地址无效")
	}
	answers, err := net.DefaultResolver.LookupNetIP(ctx, "ip", host)
	if err != nil || len(answers) == 0 {
		return nil, errors.New("无法解析夸克服务地址")
	}
	for _, ip := range answers {
		if !quarkPublicIP(ip) {
			return nil, errors.New("夸克服务地址不是公网地址")
		}
	}
	dialer := net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}
	for _, ip := range answers {
		conn, dialErr := dialer.DialContext(ctx, network, net.JoinHostPort(ip.String(), port))
		if dialErr == nil {
			return conn, nil
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
	}
	return nil, errors.New("无法连接夸克服务")
}

func quarkPublicIP(ip netip.Addr) bool {
	ip = ip.Unmap()
	if !ip.IsValid() || !ip.IsGlobalUnicast() || ip.IsPrivate() || ip.IsLoopback() || ip.IsLinkLocalUnicast() {
		return false
	}
	for _, prefix := range []string{"0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "192.0.2.0/24", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "240.0.0.0/4", "::/96", "64:ff9b::/96", "64:ff9b:1::/48", "2001::/23", "2001:db8::/32", "2002::/16", "fec0::/10"} {
		if netip.MustParsePrefix(prefix).Contains(ip) {
			return false
		}
	}
	return true
}

func quarkHeaders(method, path string) http.Header {
	timestamp := strconv.FormatInt(time.Now().UnixMilli(), 10)
	signature := sha256.Sum256([]byte(strings.ToUpper(method) + "&" + path + "&" + timestamp + "&" + quarkSignKey))
	header := make(http.Header)
	header.Set("Accept", "application/json")
	header.Set("Content-Type", "application/json")
	header.Set("X-Pan-Client-Id", quarkClientID)
	header.Set("X-Pan-Tm", timestamp)
	header.Set("X-Pan-Token", hex.EncodeToString(signature[:]))
	header.Set("X-Agent-Id", quarkAgentID)
	return header
}

type quarkAPIError struct{ httpStatus, status, errno int }

func (e *quarkAPIError) Error() string {
	if e.httpStatus == 401 || e.httpStatus == 403 {
		return "夸克授权已失效或缺少此操作权限，请重新授权"
	}
	if e.httpStatus == 429 {
		return "夸克请求过于频繁，请稍后重试"
	}
	return fmt.Sprintf("夸克请求失败（HTTP %d，状态 %d，错误码 %d）", e.httpStatus, e.status, e.errno)
}

// Never expose URL errors or upstream messages: both may contain the access
// token, authorization code, storage signatures or account information.
func quarkRequestError(ctx context.Context) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	return errors.New("夸克网络请求失败或超时，请稍后重试")
}

func (d *quarkDrive) api(ctx context.Context, method, path string, query url.Values, body any, headers http.Header, authenticated bool, result any) error {
	if !strings.HasPrefix(path, "/open/v1/") && !strings.HasPrefix(path, "/agent/v1/") || strings.ContainsAny(path, "?#") {
		return errors.New("夸克接口地址无效")
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	if query == nil {
		query = make(url.Values)
	}
	id := make([]byte, 16)
	if _, err := rand.Read(id); err != nil {
		return errors.New("无法生成夸克请求标识")
	}
	query.Set("req_id", hex.EncodeToString(id))
	if headers == nil {
		headers = quarkHeaders(method, path)
	} else {
		headers = headers.Clone()
	}
	var token string
	if authenticated {
		if err := d.ensureToken(ctx); err != nil {
			return err
		}
		d.mu.Lock()
		token = d.token
		d.mu.Unlock()
		query.Set("access_token", token)
		query.Set("device_id", quarkDeviceID)
		headers.Set("Authorization", "Bearer "+token)
	}
	var data []byte
	if body != nil {
		var err error
		data, err = json.Marshal(body)
		if err != nil || len(data) > quarkMaxReply {
			return errors.New("夸克请求数据无效或过大")
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, quarkAPIOrigin+path+"?"+query.Encode(), bytes.NewReader(data))
	if err != nil {
		return errors.New("无法创建夸克请求")
	}
	req.Header = headers
	response, err := d.client.Do(req)
	if err != nil {
		return quarkRequestError(ctx)
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return &quarkAPIError{httpStatus: response.StatusCode}
	}
	payload, err := io.ReadAll(io.LimitReader(response.Body, quarkMaxReply+1))
	if err != nil {
		return quarkRequestError(ctx)
	}
	if len(payload) > quarkMaxReply {
		return errors.New("夸克响应过大")
	}
	var envelope struct {
		Status *int            `json:"status"`
		Errno  int             `json:"errno"`
		Data   json.RawMessage `json:"data"`
	}
	if json.Unmarshal(payload, &envelope) != nil || envelope.Status == nil {
		return errors.New("夸克返回了无效响应")
	}
	if *envelope.Status != 0 || envelope.Errno != 0 {
		return &quarkAPIError{httpStatus: response.StatusCode, status: *envelope.Status, errno: envelope.Errno}
	}
	if len(envelope.Data) == 0 || bytes.Equal(envelope.Data, []byte("null")) || json.Unmarshal(envelope.Data, result) != nil {
		return errors.New("夸克响应缺少有效数据")
	}
	if next := response.Header.Get("X-New-Access-Token"); authenticated && next != "" && quarkCredential(next, false) {
		d.mu.Lock()
		if d.token == token {
			d.token = next
		}
		d.mu.Unlock()
		d.credentialsChanged()
	}
	return nil
}

func quarkAuthorizationURL(ctx context.Context) (string, error) {
	d := newQuarkDrive(CloudCredentials{}).(*quarkDrive)
	return d.authorizationURL(ctx)
}

func (d *quarkDrive) authorizationURL(ctx context.Context) (string, error) {
	device, err := quarkDeviceIdentity()
	if err != nil {
		return "", err
	}
	var response struct {
		URL string `json:"authorize_page_url"`
	}
	err = d.api(ctx, http.MethodPost, "/agent/v1/get_authorize_page_url", nil, map[string]string{
		"client_device_id": device, "device_name": "PortShelf", "agent_id": quarkAgentID,
		"client_id": quarkClientID, "work_dir": "", "is_cloud_agent": "false", "is_unsure_agent": "true",
	}, nil, false, &response)
	if err != nil {
		return "", err
	}
	u, err := url.Parse(response.URL)
	if err != nil || len(response.URL) > 8192 || !quarkWebURL(u) || u.Path != "/open/v1/oauth/agent" || u.RawPath != "" || (u.Fragment != "" && u.Fragment != "/agent-oauth") || u.RawFragment != "" || u.Query().Get("page_code") == "" {
		return "", errors.New("夸克返回了无效的授权页面地址")
	}
	for key, values := range u.Query() {
		if (key != "page_code" && key != "device_id" && key != "device_name" && key != "agent_id") || len(values) != 1 {
			return "", errors.New("夸克授权页面包含无效参数")
		}
	}
	return u.String(), nil
}

func (d *quarkDrive) ensureToken(ctx context.Context) error {
	select {
	case d.authGate <- struct{}{}:
		defer func() { <-d.authGate }()
	case <-ctx.Done():
		return ctx.Err()
	}
	d.mu.Lock()
	token, code, refresh, device, expires, bad := d.token, d.authCode, d.refresh, d.deviceID, d.expires, d.badAuth
	d.mu.Unlock()
	if bad || (!quarkCredential(token, false) && !quarkCredential(code, false)) {
		return errors.New("请使用夸克官方授权码或 Access Token 授权，网页登录 Cookie 不适用于此接口")
	}
	if code != "" {
		identity, err := quarkDeviceIdentity()
		if err != nil {
			return err
		}
		var response struct {
			Status       string          `json:"status"`
			Token        string          `json:"access_token"`
			Refresh      string          `json:"refresh_token"`
			Device       string          `json:"device_id"`
			User         string          `json:"user_id"`
			TokenExpires json.RawMessage `json:"access_token_expires_at"`
		}
		err = d.api(ctx, http.MethodGet, "/agent/v1/oauth/agent_auth_code", url.Values{
			"agent_auth_code": {code}, "client_device_id": {identity}, "device_name": {"PortShelf"},
			"agent_id": {quarkAgentID}, "work_dir": {""},
		}, nil, nil, false, &response)
		if err != nil {
			return err
		}
		if response.Status == "second_confirmed" {
			return errors.New("此授权码对应已有授权，请在夸克取消该设备原有授权后重新授权并复制新授权码")
		}
		if response.Status == "expired" || !quarkCredential(response.Token, false) || !quarkIdentifier(response.User) || !quarkCredential(response.Refresh, true) || !quarkCredential(response.Device, true) {
			return errors.New("夸克授权码已过期、尚未确认或未返回有效登录信息，请重新授权")
		}
		d.mu.Lock()
		d.token, d.authCode, d.refresh, d.deviceID = response.Token, "", response.Refresh, response.Device
		d.expires = quarkExpiry(response.TokenExpires)
		d.mu.Unlock()
		d.credentialsChanged()
		return nil
	}
	if expires.IsZero() || time.Until(expires) > time.Minute {
		return nil
	}
	if !quarkCredential(refresh, false) || !quarkCredential(device, false) {
		return errors.New("夸克授权已过期，请重新授权")
	}
	var response struct {
		Token   string `json:"access_token"`
		Refresh string `json:"refresh_token"`
		Expires int64  `json:"expires_in"`
	}
	if err := d.api(ctx, http.MethodPost, "/agent/v1/oauth/access_token/rotate", nil, map[string]string{"refresh_token": refresh, "device_id": device}, nil, false, &response); err != nil {
		return err
	}
	if !quarkCredential(response.Token, false) || !quarkCredential(response.Refresh, false) || response.Expires <= 0 || response.Expires > 366*24*3600 {
		return errors.New("夸克刷新授权返回了无效信息，请重新授权")
	}
	d.mu.Lock()
	d.token, d.refresh, d.expires = response.Token, response.Refresh, time.Now().Add(time.Duration(response.Expires)*time.Second)
	d.mu.Unlock()
	d.credentialsChanged()
	return nil
}

func quarkExpiry(raw json.RawMessage) time.Time {
	value := strings.Trim(string(raw), "\"")
	if n, err := strconv.ParseInt(value, 10, 64); err == nil && n > 0 {
		if n > 100000000000 {
			return time.UnixMilli(n)
		}
		return time.Unix(n, 0)
	}
	parsed, _ := time.Parse(time.RFC3339, value)
	return parsed
}

func (d *quarkDrive) Check(ctx context.Context) (string, error) {
	var response struct {
		User string `json:"user_id"`
		Name string `json:"nickname"`
	}
	if err := d.api(ctx, http.MethodGet, "/open/v1/user/info", nil, nil, nil, true, &response); err != nil {
		return "", err
	}
	if !quarkIdentifier(response.User) {
		return "", errors.New("夸克未返回有效账号信息")
	}
	name := strings.TrimSpace(response.Name)
	if name == "" || len(name) > 256 || strings.IndexFunc(name, unicode.IsControl) >= 0 {
		name = "夸克账号已授权"
	}
	d.mu.Lock()
	if d.userID != "" && d.userID != response.User {
		d.mu.Unlock()
		return "", errors.New("夸克登录账号与保存的授权不一致，请重新连接")
	}
	d.userID, d.name = response.User, name
	d.mu.Unlock()
	return name, nil
}

func quarkIdentifier(value string) bool {
	if len(value) == 0 || len(value) > 256 {
		return false
	}
	for _, c := range value {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return false
		}
	}
	return true
}

func quarkSafeName(name string) bool {
	return name != "" && name != "." && name != ".." && len(name) <= 255 && utf8.ValidString(name) &&
		name == strings.TrimSpace(name) && !strings.ContainsAny(name, "/\\:*?\"<>|") && !strings.HasSuffix(name, ".") && strings.IndexFunc(name, unicode.IsControl) < 0
}

type quarkSHA1Context struct {
	Offset int64     `json:"part_offset"`
	H      [5]uint32 `json:"h"`
}

type quarkPart struct {
	Number int               `json:"part_number"`
	Size   int64             `json:"part_size"`
	SHA1   *quarkSHA1Context `json:"parallel_sha1_ctx,omitempty"`
}

type quarkUploadedPart struct {
	Number int    `json:"part_number"`
	ETag   string `json:"etag"`
}

type quarkUploadResult struct {
	Task    string            `json:"task_id"`
	Size    int64             `json:"part_size"`
	Finish  bool              `json:"finish"`
	FID     string            `json:"fid"`
	Headers map[string]string `json:"common_headers"`
}

type quarkUploadURL struct {
	Number    int    `json:"part_number"`
	URL       string `json:"upload_url"`
	Signature struct {
		Value string `json:"signature"`
	} `json:"signature_info"`
}

func (d *quarkDrive) Upload(ctx context.Context, localPath, remoteName string, progress UploadProgress) (CloudFile, error) {
	if !quarkSafeName(remoteName) {
		return CloudFile{}, errors.New("夸克远端文件名无效")
	}
	file, err := os.Open(localPath)
	if err != nil {
		return CloudFile{}, errors.New("无法读取待上传文件")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() <= 0 {
		return CloudFile{}, errors.New("夸克只支持上传非空普通文件")
	}
	if _, err := d.Check(ctx); err != nil {
		return CloudFile{}, err
	}
	var directory struct {
		FID string `json:"fid"`
	}
	// Official createDir is idempotent for an existing same-name directory.
	if err := d.api(ctx, http.MethodPost, "/open/v1/dir", nil, map[string]string{"dir_path": "PortShelf", "pdir_fid": "0"}, nil, true, &directory); err != nil {
		return CloudFile{}, err
	}
	if !quarkIdentifier(directory.FID) {
		return CloudFile{}, errors.New("夸克未返回有效目标文件夹")
	}
	headers := quarkHeaders(http.MethodPost, "/open/v1/file/upload_pre")
	d.mu.Lock()
	userID := d.userID
	d.mu.Unlock()
	proof, err := quarkProof(file, info.Size(), userID, headers.Get("X-Pan-Token"))
	if err != nil {
		return CloudFile{}, err
	}
	format := mime.TypeByExtension(filepath.Ext(remoteName))
	if format == "" {
		format = "application/octet-stream"
	}
	body := map[string]any{"file_name": remoteName, "size": info.Size(), "sha1": "", "pdir_fid": directory.FID,
		"format_type": format, "l_created_at": info.ModTime().UnixMilli(), "l_updated_at": info.ModTime().UnixMilli(),
		"parallel_upload": true, "hash_update": true, "device_id": quarkDeviceID, "device_name": "PortShelf", "agent_id": quarkAgentID}
	for key, value := range proof {
		body[key] = value
	}
	var prepared quarkUploadResult
	if err := d.api(ctx, http.MethodPost, "/open/v1/file/upload_pre", nil, body, headers, true, &prepared); err != nil {
		return CloudFile{}, err
	}
	completed := func(fid string) (CloudFile, error) {
		if !quarkIdentifier(fid) {
			return CloudFile{}, errors.New("夸克上传完成响应缺少文件标识")
		}
		if progress != nil {
			progress(info.Size(), info.Size())
		}
		return CloudFile{ID: fid, Path: "/PortShelf/" + remoteName, Name: remoteName}, nil
	}
	if prepared.Finish {
		return completed(prepared.FID)
	}
	if !quarkIdentifier(prepared.Task) || prepared.Size <= 0 || prepared.Size > 1<<30 || (prepared.Size < info.Size() && prepared.Size%64 != 0) || (info.Size()-1)/prepared.Size >= quarkMaxParts {
		return CloudFile{}, errors.New("夸克返回了无效的分片参数或文件过大")
	}
	parts, sha, md, err := quarkHashParts(ctx, file, info.Size(), prepared.Size)
	if err != nil {
		return CloudFile{}, err
	}
	var hashed quarkUploadResult
	if err := d.api(ctx, http.MethodPost, "/open/v1/file/update/hash", nil, map[string]string{"task_id": prepared.Task, "sha1": sha, "md5": md}, nil, true, &hashed); err != nil {
		return CloudFile{}, err
	}
	if hashed.Finish {
		return completed(hashed.FID)
	}
	uploaded := make([]quarkUploadedPart, 0, len(parts))
	var done int64
	if progress != nil {
		progress(0, info.Size())
	}
	for first := 0; first < len(parts); first += 100 {
		last := min(first+100, len(parts))
		var batch struct {
			URLs    []quarkUploadURL  `json:"upload_urls"`
			Headers map[string]string `json:"common_headers"`
		}
		if err := d.api(ctx, http.MethodPost, "/open/v1/file/get_upload_urls", nil, map[string]any{"task_id": prepared.Task, "part_info_list": parts[first:last]}, nil, true, &batch); err != nil {
			return CloudFile{}, err
		}
		if len(batch.URLs) != last-first {
			return CloudFile{}, errors.New("夸克返回的上传分片不完整")
		}
		urls := make(map[int]quarkUploadURL, len(batch.URLs))
		for _, entry := range batch.URLs {
			if entry.Number <= first || entry.Number > last || urls[entry.Number].Number != 0 {
				return CloudFile{}, errors.New("夸克返回了重复或无效的上传分片")
			}
			urls[entry.Number] = entry
		}
		common := batch.Headers
		if common == nil {
			common = prepared.Headers
		}
		for _, part := range parts[first:last] {
			entry := urls[part.Number]
			reader := &quarkProgressReader{ctx: ctx, reader: io.NewSectionReader(file, done, part.Size), offset: done, total: info.Size(), progress: progress}
			etag, err := d.putPart(ctx, entry, common, reader, part.Size)
			if err != nil {
				return CloudFile{}, err
			}
			done += part.Size
			uploaded = append(uploaded, quarkUploadedPart{Number: part.Number, ETag: etag})
		}
	}
	current, err := file.Stat()
	if err != nil || current.Size() != info.Size() || !current.ModTime().Equal(info.ModTime()) {
		return CloudFile{}, errors.New("上传期间本地文件发生变化，请重新上传")
	}
	var finished quarkUploadResult
	if err := d.api(ctx, http.MethodPost, "/open/v1/file/upload_finish", nil, map[string]any{"task_id": prepared.Task, "part_info_list": uploaded}, nil, true, &finished); err != nil {
		return CloudFile{}, err
	}
	if !finished.Finish {
		return CloudFile{}, errors.New("夸克尚未确认上传完成")
	}
	return completed(finished.FID)
}

func quarkProof(file *os.File, size int64, userID, token string) (map[string]string, error) {
	md := func(value string) string { sum := md5.Sum([]byte(value)); return hex.EncodeToString(sum[:]) }
	result := map[string]string{"proof_version": "v1", "proof_seed1": md(md(userID + token)), "proof_seed2": md(md(strconv.FormatInt(size, 10)))}
	for _, index := range []string{"1", "2"} {
		value, err := strconv.ParseUint(result["proof_seed"+index][:16], 16, 64)
		if err != nil || size <= 0 {
			return nil, errors.New("无法生成夸克文件校验信息")
		}
		offset := int64(value % uint64(size))
		buffer := make([]byte, min(8, size-offset))
		if _, err := file.ReadAt(buffer, offset); err != nil {
			return nil, errors.New("无法读取夸克文件校验片段")
		}
		result["proof_code"+index] = base64.StdEncoding.EncodeToString(buffer)
	}
	return result, nil
}

func quarkHashParts(ctx context.Context, file *os.File, size, partSize int64) ([]quarkPart, string, string, error) {
	sha, md := sha1.New(), md5.New()
	parts := make([]quarkPart, 0, (size-1)/partSize+1)
	buffer := make([]byte, 64<<10)
	for offset := int64(0); offset < size; {
		part := quarkPart{Number: len(parts) + 1, Size: min(partSize, size-offset)}
		if offset > 0 {
			// crypto/sha1's documented BinaryMarshaler contains its five chaining
			// words after the version tag. Verify the format instead of assuming
			// its layout silently; no unsafe access or third-party SHA1 is needed.
			state, err := sha.(encoding.BinaryMarshaler).MarshalBinary()
			if err != nil || len(state) != 96 || string(state[:4]) != "sha\x01" {
				return nil, "", "", errors.New("当前运行环境不支持夸克分片校验")
			}
			part.SHA1 = &quarkSHA1Context{Offset: offset}
			for n := range part.SHA1.H {
				part.SHA1.H[n] = binary.BigEndian.Uint32(state[4+n*4 : 8+n*4])
			}
		}
		remaining := part.Size
		for remaining > 0 {
			if err := ctx.Err(); err != nil {
				return nil, "", "", err
			}
			chunk := buffer[:min(int64(len(buffer)), remaining)]
			if _, err := file.ReadAt(chunk, offset); err != nil {
				return nil, "", "", errors.New("无法读取待上传文件的校验内容")
			}
			_, _ = sha.Write(chunk)
			_, _ = md.Write(chunk)
			offset += int64(len(chunk))
			remaining -= int64(len(chunk))
		}
		parts = append(parts, part)
	}
	return parts, hex.EncodeToString(sha.Sum(nil)), hex.EncodeToString(md.Sum(nil)), nil
}

type quarkProgressReader struct {
	ctx          context.Context
	reader       io.Reader
	offset, done int64
	total        int64
	progress     UploadProgress
}

func (r *quarkProgressReader) Read(buffer []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	n, err := r.reader.Read(buffer)
	r.done += int64(n)
	if n > 0 && r.progress != nil {
		r.progress(r.offset+r.done, r.total)
	}
	return n, err
}

func quarkStorageURL(raw string) (*url.URL, error) {
	u, err := url.Parse(raw)
	if err != nil || len(raw) > 16000 || u.Scheme != "https" || u.User != nil || u.Host != u.Hostname() || u.Fragment != "" || u.Opaque != "" {
		return nil, errors.New("夸克返回了不安全的上传地址")
	}
	host := strings.ToLower(u.Hostname())
	// Official upload URLs are signed Alibaba OSS URLs. Restrict both the
	// provider and the OSS endpoint shape; an arbitrary server URL is unsafe.
	labels := strings.Split(host, ".")
	if len(labels) != 4 || labels[2] != "aliyuncs" || labels[3] != "com" || !strings.HasPrefix(labels[1], "oss-") || !quarkDNSLabel(labels[0]) || !quarkDNSLabel(labels[1]) {
		return nil, errors.New("夸克返回了不支持的上传服务地址")
	}
	return u, nil
}

func quarkDNSLabel(label string) bool {
	if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
		return false
	}
	for _, c := range label {
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '-') {
			return false
		}
	}
	return true
}

func (d *quarkDrive) putPart(ctx context.Context, entry quarkUploadURL, common map[string]string, body io.Reader, size int64) (string, error) {
	u, err := quarkStorageURL(entry.URL)
	if err != nil {
		return "", err
	}
	if !quarkHeaderValue(entry.Signature.Value) || entry.Signature.Value == "" || len(common) > 32 {
		return "", errors.New("夸克上传签名无效")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, u.String(), body)
	if err != nil {
		return "", errors.New("无法创建夸克分片上传请求")
	}
	for key, value := range common {
		lower := strings.ToLower(key)
		if !(lower == "content-type" || lower == "content-md5" || lower == "date" || strings.HasPrefix(lower, "x-oss-")) || !quarkHeaderValue(value) || len(key) > 128 || strings.IndexFunc(key, func(c rune) bool {
			return !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '-')
		}) >= 0 {
			return "", errors.New("夸克返回了不安全的上传请求头")
		}
		req.Header.Set(key, value)
	}
	req.Header.Set("Authorization", entry.Signature.Value)
	req.ContentLength = size
	response, err := d.client.Do(req)
	if err != nil {
		return "", quarkRequestError(ctx)
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return "", fmt.Errorf("夸克分片上传失败（HTTP %d）", response.StatusCode)
	}
	etag := response.Header.Get("ETag")
	if etag == "" || len(etag) > 256 || !quarkHeaderValue(etag) {
		return "", errors.New("夸克上传响应缺少有效 ETag")
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 64<<10))
	return etag, nil
}

func quarkHeaderValue(value string) bool {
	if len(value) > 16000 {
		return false
	}
	for _, c := range value {
		if c < 32 || c > 126 {
			return false
		}
	}
	return true
}

func quarkWebURL(u *url.URL) bool {
	return u != nil && u.Scheme == "https" && u.Host == "pan.quark.cn" && u.User == nil && u.Opaque == ""
}

func (d *quarkDrive) Share(ctx context.Context, file CloudFile, options ShareOptions) (CloudShare, error) {
	expiry := map[int]int{0: 1, 1: 2, 7: 3, 30: 4, 60: 5, 100: 6, 180: 7}
	expiredType, ok := expiry[options.Days]
	if !ok {
		return CloudShare{}, errors.New("夸克分享有效期只支持永久或 1、7、30、60、100、180 天")
	}
	if options.Code != "" {
		return CloudShare{}, errors.New("夸克提取码由服务端自动生成，不支持自定义提取码")
	}
	if !quarkIdentifier(file.ID) || !quarkSafeName(file.Name) {
		return CloudShare{}, errors.New("夸克分享文件信息无效")
	}
	urlType := 1
	if options.Private {
		urlType = 2
	}
	var response struct {
		URL  string `json:"share_url"`
		Code string `json:"passcode"`
	}
	if err := d.api(ctx, http.MethodPost, "/agent/v1/share/create", nil, map[string]any{"fid_list": []string{file.ID}, "title": file.Name, "url_type": urlType, "expired_type": expiredType}, nil, true, &response); err != nil {
		return CloudShare{}, err
	}
	u, err := url.Parse(response.URL)
	if err != nil || len(response.URL) > 8192 || !quarkWebURL(u) || u.Fragment != "" || !strings.HasPrefix(u.Path, "/s/") || !quarkIdentifier(strings.TrimPrefix(u.Path, "/s/")) || u.RawPath != "" || len(response.Code) > 32 || !quarkCredential(response.Code, !options.Private) {
		return CloudShare{}, errors.New("夸克返回了无效分享链接或提取码")
	}
	share := CloudShare{URL: u.String(), Code: response.Code}
	if options.Days > 0 {
		share.ExpiresAt = time.Now().UTC().Add(time.Duration(options.Days) * 24 * time.Hour).Format(time.RFC3339)
	}
	return share, nil
}
