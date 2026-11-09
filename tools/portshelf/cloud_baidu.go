package main

// Baidu's official upload protocol is documented at
// https://pan.baidu.com/union/doc/3ksg0s9ye and in baidu-netdisk/baidu-drive-sdk-go.
// Cookie authentication and the web precreate/create/share/pset wire fields were
// independently implemented from the protocol visible in
// https://github.com/qjfoidnh/BaiduPCS-Go/blob/main/baidupcs/prepare.go.
// No code from that GPL client is included. OAuth does not provide this sharing
// interface; the same web session is used throughout to avoid account mismatch.

import (
	"bytes"
	"context"
	"crypto/md5"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"mime/multipart"
	"net"
	"net/http"
	"net/url"
	"os"
	"path"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	baiduDirectory     = "/PortShelf"
	baiduChunkSize     = int64(4 << 20)
	baiduResponseLimit = 1 << 20
)

type baiduDrive struct {
	cookie        string
	credentialErr error
	client        *http.Client
}

func newBaiduDrive(credentials CloudCredentials) CloudDrive {
	cookie, err := baiduCookie(credentials.Cookie)
	return &baiduDrive{
		cookie:        cookie,
		credentialErr: err,
		client: &http.Client{
			Timeout: 10 * time.Minute,
			Transport: &http.Transport{
				Proxy:                 http.ProxyFromEnvironment,
				DialContext:           (&net.Dialer{Timeout: 15 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
				TLSHandshakeTimeout:   15 * time.Second,
				ResponseHeaderTimeout: 45 * time.Second,
				IdleConnTimeout:       90 * time.Second,
			},
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
	}
}

func baiduCookie(raw string) (string, error) {
	invalid := errors.New("请填写百度网盘网页登录 Cookie（包含 BDUSS 和 STOKEN）")
	if len(raw) == 0 || len(raw) > 16<<10 || strings.IndexFunc(raw, unicode.IsControl) >= 0 {
		return "", invalid
	}
	request := &http.Request{Header: http.Header{"Cookie": []string{strings.TrimSpace(raw)}}}
	cookies := request.Cookies()
	seen := make(map[string]bool)
	var clean []string
	for _, cookie := range cookies {
		if seen[cookie.Name] || cookie.Valid() != nil || cookie.Value == "" {
			return "", invalid
		}
		seen[cookie.Name] = true
		clean = append(clean, cookie.String())
	}
	if !seen["BDUSS"] || !seen["STOKEN"] {
		return "", invalid
	}
	return strings.Join(clean, "; "), nil
}

type baiduAPIError struct {
	Code    int
	Sharing bool
}

func (e *baiduAPIError) Error() string {
	switch e.Code {
	case -4, -6, -11, 3, 112, 20016, 20017, 31045:
		return "百度网盘登录已失效，请更新 Cookie"
	case -8, -30, 31061:
		return "百度网盘中已有同名文件或目录"
	case -10:
		if e.Sharing {
			return "百度网盘分享数量已达到上限，请在网页检查已有分享"
		}
		return "百度网盘空间不足"
	case 31190:
		return "百度网盘空间不足"
	case 31034:
		return "百度网盘请求过于频繁，请稍后重试"
	case -3, -9, 31066:
		return "百度网盘中的文件或目录已不存在"
	case -19, -62, 132:
		return "百度网盘要求安全验证，请先在网盘网页完成验证"
	case -1, -16, -17, 110, 115:
		return fmt.Sprintf("百度网盘拒绝本次操作，请在网页检查账号或分享限制（错误码 %d）", e.Code)
	default:
		return fmt.Sprintf("百度网盘操作失败（错误码 %d），请在网页检查账号状态后重试", e.Code)
	}
}

// Only these fixed provider endpoints can receive the user's Cookie. Redirects
// are disabled, including same-host redirects, so credentials never follow one.
func baiduEndpointAllowed(host, endpoint string) bool {
	switch host {
	case "pan.baidu.com":
		switch endpoint {
		case "/api/gettemplatevariable", "/api/precreate", "/api/create", "/share/pset":
			return true
		}
	case "pcs.baidu.com":
		return endpoint == "/rest/2.0/pcs/file"
	case "d.pcs.baidu.com":
		return endpoint == "/rest/2.0/pcs/superfile2"
	}
	return false
}

func (b *baiduDrive) request(ctx context.Context, method, host, endpoint string, query url.Values, body io.Reader, contentType string, contentLength int64, timeout time.Duration, output any) error {
	if b.credentialErr != nil {
		return b.credentialErr
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if !baiduEndpointAllowed(host, endpoint) {
		return errors.New("百度网盘请求地址无效")
	}
	requestCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	u := url.URL{Scheme: "https", Host: host, Path: endpoint, RawQuery: query.Encode()}
	request, err := http.NewRequestWithContext(requestCtx, method, u.String(), body)
	if err != nil {
		return errors.New("无法创建百度网盘请求")
	}
	request.Header.Set("Cookie", b.cookie)
	request.Header.Set("User-Agent", "Mozilla/5.0 PortShelf/1.0")
	request.Header.Set("Referer", "https://pan.baidu.com/disk/main")
	request.Header.Set("Origin", "https://pan.baidu.com")
	request.Header.Set("Accept", "application/json")
	if contentType != "" {
		request.Header.Set("Content-Type", contentType)
	}
	if body != nil {
		request.ContentLength = contentLength
	}
	response, err := b.client.Do(request)
	if err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if requestCtx.Err() != nil {
			return errors.New("百度网盘请求超时，请检查网络或代理配置")
		}
		return errors.New("无法连接百度网盘，请检查网络或代理配置")
	}
	defer response.Body.Close()
	switch {
	case response.StatusCode >= 300 && response.StatusCode < 400:
		return errors.New("百度网盘要求跳转，请更新 Cookie 后重试")
	case response.StatusCode == 401 || response.StatusCode == 403:
		return errors.New("百度网盘拒绝访问，请更新 Cookie 或在网页检查账号状态")
	case response.StatusCode == 429:
		return errors.New("百度网盘请求过于频繁，请稍后重试")
	case response.StatusCode < 200 || response.StatusCode >= 300:
		return fmt.Errorf("百度网盘服务暂不可用（HTTP %d）", response.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, baiduResponseLimit+1))
	if err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return errors.New("读取百度网盘响应失败")
	}
	if len(data) > baiduResponseLimit {
		return errors.New("百度网盘响应过大")
	}
	var status struct {
		Errno     int `json:"errno"`
		ErrorCode int `json:"error_code"`
	}
	if json.Unmarshal(data, &status) != nil {
		return errors.New("百度网盘响应格式无效，请检查 Cookie 是否有效")
	}
	if status.Errno != 0 {
		return &baiduAPIError{Code: status.Errno, Sharing: endpoint == "/share/pset"}
	}
	if status.ErrorCode != 0 {
		return &baiduAPIError{Code: status.ErrorCode, Sharing: endpoint == "/share/pset"}
	}
	if json.Unmarshal(data, output) != nil {
		return errors.New("百度网盘响应格式无效")
	}
	return nil
}

func baiduQuery(token string) url.Values {
	q := url.Values{"app_id": {"250528"}, "web": {"1"}, "clienttype": {"0"}}
	if token != "" {
		q.Set("bdstoken", token)
	}
	return q
}

func (b *baiduDrive) post(ctx context.Context, endpoint, token string, form url.Values, output any) error {
	encoded := form.Encode()
	return b.request(ctx, http.MethodPost, "pan.baidu.com", endpoint, baiduQuery(token), strings.NewReader(encoded), "application/x-www-form-urlencoded", int64(len(encoded)), 45*time.Second, output)
}

func (b *baiduDrive) sessionToken(ctx context.Context) (string, error) {
	q := baiduQuery("")
	q.Set("fields", `["bdstoken"]`)
	var response struct {
		Result struct {
			Token string `json:"bdstoken"`
		} `json:"result"`
	}
	if err := b.request(ctx, http.MethodGet, "pan.baidu.com", "/api/gettemplatevariable", q, nil, "", 0, 30*time.Second, &response); err != nil {
		return "", err
	}
	if !baiduAlphaNumeric(response.Result.Token, 1, 128) {
		return "", errors.New("百度网盘登录已失效，请更新 Cookie")
	}
	return response.Result.Token, nil
}

func (b *baiduDrive) Check(ctx context.Context) (string, error) {
	if _, err := b.sessionToken(ctx); err != nil {
		return "", err
	}
	return "百度网盘", nil
}

type baiduFileInfo struct {
	ID    json.Number `json:"fs_id"`
	Path  string      `json:"path"`
	Name  string      `json:"server_filename"`
	Size  int64       `json:"size"`
	IsDir int         `json:"isdir"`
}

func baiduValidID(id string) bool {
	if id == "" || strings.Trim(id, "0123456789") != "" {
		return false
	}
	n, err := strconv.ParseUint(id, 10, 64)
	return err == nil && n > 0
}

func baiduSafeName(name string) bool {
	if name == "" || len(name) > 200 || !utf8.ValidString(name) || strings.TrimSpace(name) != name || strings.HasPrefix(name, ".") || strings.HasSuffix(name, ".") {
		return false
	}
	return !strings.ContainsAny(name, `/\:*?"<>|`) && strings.IndexFunc(name, unicode.IsControl) < 0
}

func (info baiduFileInfo) uploadedFile(size int64) (CloudFile, error) {
	name := path.Base(info.Path)
	if !baiduValidID(string(info.ID)) || info.IsDir != 0 || info.Size != size || path.Clean(info.Path) != info.Path || path.Dir(info.Path) != baiduDirectory || !baiduSafeName(name) || (info.Name != "" && info.Name != name) {
		return CloudFile{}, errors.New("百度网盘未返回可核实的上传文件信息")
	}
	return CloudFile{ID: string(info.ID), Path: info.Path, Name: name}, nil
}

func (b *baiduDrive) ensureDirectory(ctx context.Context, token string) error {
	var info baiduFileInfo
	err := b.post(ctx, "/api/create", token, url.Values{"path": {baiduDirectory}, "isdir": {"1"}, "size": {"0"}, "block_list": {"[]"}, "rtype": {"0"}}, &info)
	var remote *baiduAPIError
	if errors.As(err, &remote) && (remote.Code == -8 || remote.Code == -30 || remote.Code == 31061) {
		// A same-named file must not be treated as our upload directory.
		var body bytes.Buffer
		writer := multipart.NewWriter(&body)
		_ = writer.WriteField("param", `{"list":[{"path":"/PortShelf"}]}`)
		_ = writer.Close()
		var response struct {
			List []baiduFileInfo `json:"list"`
		}
		q := url.Values{"app_id": {"250528"}, "method": {"meta"}}
		if err = b.request(ctx, http.MethodPost, "pcs.baidu.com", "/rest/2.0/pcs/file", q, &body, writer.FormDataContentType(), int64(body.Len()), 30*time.Second, &response); err != nil {
			return err
		}
		if len(response.List) != 1 {
			return errors.New("无法核实百度网盘 PortShelf 目录")
		}
		info = response.List[0]
	} else if err != nil {
		return err
	}
	if info.Path != baiduDirectory || info.IsDir != 1 || !baiduValidID(string(info.ID)) {
		return errors.New("百度网盘 /PortShelf 已被文件占用或目录信息无效")
	}
	return nil
}

type baiduContextReader struct {
	ctx    context.Context
	reader io.Reader
}

func (r *baiduContextReader) Read(p []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.reader.Read(p)
}

func baiduHashes(ctx context.Context, file *os.File, size, chunkSize int64) ([]string, error) {
	var hashes []string
	for offset := int64(0); offset < size; offset += chunkSize {
		hash := md5.New() // Required by the Baidu upload wire protocol, not authentication.
		count := min(chunkSize, size-offset)
		if _, err := io.CopyN(hash, &baiduContextReader{ctx: ctx, reader: io.NewSectionReader(file, offset, count)}, count); err != nil {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			return nil, errors.New("无法读取待上传文件")
		}
		hashes = append(hashes, hex.EncodeToString(hash.Sum(nil)))
	}
	return hashes, nil
}

type baiduProgressReader struct {
	reader      io.Reader
	done, total int64
	progress    UploadProgress
}

func (r *baiduProgressReader) Read(p []byte) (int, error) {
	n, err := r.reader.Read(p)
	r.done += int64(n)
	if n > 0 && r.progress != nil {
		r.progress(r.done, r.total)
	}
	return n, err
}

func (b *baiduDrive) uploadPart(ctx context.Context, file *os.File, remotePath, uploadID string, index int, chunkSize, size, completed int64, expectedMD5 string, progress UploadProgress) error {
	// Build only the multipart framing in memory. The payload is a SectionReader
	// of the original file, with an exact Content-Length and no writer goroutine.
	var prefix bytes.Buffer
	writer := multipart.NewWriter(&prefix)
	if _, err := writer.CreateFormFile("file", "chunk"); err != nil {
		return errors.New("无法创建百度网盘上传请求")
	}
	header := append([]byte(nil), prefix.Bytes()...)
	prefix.Reset()
	if err := writer.Close(); err != nil {
		return errors.New("无法创建百度网盘上传请求")
	}
	footer := append([]byte(nil), prefix.Bytes()...)
	offset := int64(index) * chunkSize
	count := min(chunkSize, size-offset)
	part := &baiduProgressReader{reader: &baiduContextReader{ctx: ctx, reader: io.NewSectionReader(file, offset, count)}, done: completed, total: size, progress: progress}
	body := io.MultiReader(bytes.NewReader(header), part, bytes.NewReader(footer))
	q := url.Values{"app_id": {"250528"}, "method": {"upload"}, "type": {"tmpfile"}, "path": {remotePath}, "uploadid": {uploadID}, "partseq": {strconv.Itoa(index)}, "partoffset": {strconv.FormatInt(offset, 10)}}
	var response struct {
		MD5 string `json:"md5"`
	}
	if err := b.request(ctx, http.MethodPost, "d.pcs.baidu.com", "/rest/2.0/pcs/superfile2", q, body, writer.FormDataContentType(), int64(len(header)+len(footer))+count, 8*time.Minute, &response); err != nil {
		return err
	}
	if !strings.EqualFold(response.MD5, expectedMD5) {
		return errors.New("百度网盘上传分片校验失败，请重试")
	}
	return nil
}

func (b *baiduDrive) Upload(ctx context.Context, localPath, remoteName string, progress UploadProgress) (CloudFile, error) {
	if !baiduSafeName(remoteName) {
		return CloudFile{}, errors.New("百度网盘文件名无效")
	}
	if b.credentialErr != nil {
		return CloudFile{}, b.credentialErr
	}
	if err := ctx.Err(); err != nil {
		return CloudFile{}, err
	}
	file, err := os.Open(localPath)
	if err != nil {
		return CloudFile{}, errors.New("无法打开待上传文件")
	}
	defer file.Close()
	stat, err := file.Stat()
	if err != nil || !stat.Mode().IsRegular() || stat.Size() <= 0 || stat.Size() > 32<<30 {
		return CloudFile{}, errors.New("待上传文件须为非空普通文件，且不超过 32 GiB")
	}
	size := stat.Size()
	chunkSize := baiduChunkSize
	if size > 8<<30 {
		chunkSize = 16 << 20
	}
	if progress != nil {
		progress(0, size)
	}
	hashes, err := baiduHashes(ctx, file, size, chunkSize)
	if err != nil {
		return CloudFile{}, err
	}
	token, err := b.sessionToken(ctx)
	if err != nil {
		return CloudFile{}, err
	}
	if err = b.ensureDirectory(ctx, token); err != nil {
		return CloudFile{}, err
	}
	remotePath := baiduDirectory + "/" + remoteName
	blockJSON, _ := json.Marshal(hashes)
	form := url.Values{"path": {remotePath}, "target_path": {baiduDirectory}, "size": {strconv.FormatInt(size, 10)}, "isdir": {"0"}, "autoinit": {"1"}, "rtype": {"1"}, "block_list": {string(blockJSON)}}
	var precreate struct {
		UploadID   string        `json:"uploadid"`
		ReturnType int           `json:"return_type"`
		Blocks     *[]int        `json:"block_list"`
		Info       baiduFileInfo `json:"info"`
	}
	if err = b.post(ctx, "/api/precreate", token, form, &precreate); err != nil {
		return CloudFile{}, err
	}
	if precreate.ReturnType == 2 {
		result, err := precreate.Info.uploadedFile(size)
		if err == nil && progress != nil {
			progress(size, size)
		}
		return result, err
	}
	if precreate.ReturnType != 1 || len(precreate.UploadID) == 0 || len(precreate.UploadID) > 512 || strings.IndexFunc(precreate.UploadID, unicode.IsControl) >= 0 {
		return CloudFile{}, errors.New("百度网盘未返回有效的上传会话")
	}
	indices := make([]int, len(hashes))
	for i := range indices {
		indices[i] = i
	}
	if precreate.Blocks != nil {
		indices = *precreate.Blocks
	}
	seen := make(map[int]bool)
	remaining := int64(0)
	for _, index := range indices {
		if index < 0 || index >= len(hashes) || seen[index] {
			return CloudFile{}, errors.New("百度网盘返回了无效的上传分片列表")
		}
		seen[index] = true
		remaining += min(chunkSize, size-int64(index)*chunkSize)
	}
	completed := size - remaining
	if completed > 0 && progress != nil {
		progress(completed, size)
	}
	for _, index := range indices {
		if err = b.uploadPart(ctx, file, remotePath, precreate.UploadID, index, chunkSize, size, completed, hashes[index], progress); err != nil {
			return CloudFile{}, err
		}
		completed += min(chunkSize, size-int64(index)*chunkSize)
	}
	finalStat, err := file.Stat()
	if err != nil || finalStat.Size() != size || !finalStat.ModTime().Equal(stat.ModTime()) {
		return CloudFile{}, errors.New("待上传文件在传输过程中发生变化，请重试")
	}
	form.Del("autoinit")
	form.Set("uploadid", precreate.UploadID)
	var created baiduFileInfo
	if err = b.post(ctx, "/api/create", token, form, &created); err != nil {
		return CloudFile{}, err
	}
	return created.uploadedFile(size)
}

func baiduAlphaNumeric(value string, minimum, maximum int) bool {
	if len(value) < minimum || len(value) > maximum {
		return false
	}
	for _, c := range value {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9') {
			return false
		}
	}
	return true
}

func baiduShareURL(raw, code string) (string, error) {
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Host != "pan.baidu.com" || u.User != nil || u.Fragment != "" || u.RawPath != "" || !strings.HasPrefix(u.Path, "/s/") {
		return "", errors.New("百度网盘返回了无效的分享地址")
	}
	key := strings.TrimPrefix(u.Path, "/s/")
	if len(key) == 0 || len(key) > 128 || strings.Trim(key, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") != "" {
		return "", errors.New("百度网盘返回了无效的分享地址")
	}
	if u.RawQuery != "" || u.ForceQuery {
		q, err := url.ParseQuery(u.RawQuery)
		if err != nil || len(q) != 1 || len(q["pwd"]) != 1 || q.Get("pwd") != code {
			return "", errors.New("百度网盘返回了无效的分享地址")
		}
	}
	return "https://pan.baidu.com" + u.Path, nil
}

func (b *baiduDrive) Share(ctx context.Context, file CloudFile, options ShareOptions) (CloudShare, error) {
	if !options.Private {
		return CloudShare{}, errors.New("当前百度接口仅支持带提取码分享，请选择私密分享")
	}
	if options.Days != 0 && options.Days != 1 && options.Days != 7 && options.Days != 30 {
		return CloudShare{}, errors.New("百度分享有效期仅支持永久、1 天、7 天或 30 天")
	}
	if !baiduValidID(file.ID) || path.Clean(file.Path) != file.Path || path.Dir(file.Path) != baiduDirectory || !baiduSafeName(file.Name) || path.Base(file.Path) != file.Name {
		return CloudShare{}, errors.New("百度网盘待分享文件信息无效")
	}
	code := options.Code
	if code == "" {
		const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
		var generated strings.Builder
		for i := 0; i < 4; i++ {
			n, err := rand.Int(rand.Reader, big.NewInt(int64(len(alphabet))))
			if err != nil {
				return CloudShare{}, errors.New("无法生成百度分享提取码")
			}
			generated.WriteByte(alphabet[n.Int64()])
		}
		code = generated.String()
	}
	if !baiduAlphaNumeric(code, 4, 4) {
		return CloudShare{}, errors.New("百度分享提取码须为 4 位英文字母或数字")
	}
	token, err := b.sessionToken(ctx)
	if err != nil {
		return CloudShare{}, err
	}
	paths, _ := json.Marshal([]string{file.Path})
	form := url.Values{"path_list": {string(paths)}, "schannel": {"4"}, "channel_list": {"[]"}, "period": {strconv.Itoa(options.Days)}, "pwd": {code}, "share_type": {"9"}}
	var response struct {
		Link string `json:"link"`
	}
	if err = b.post(ctx, "/share/pset", token, form, &response); err != nil {
		return CloudShare{}, err
	}
	link, err := baiduShareURL(response.Link, code)
	if err != nil {
		return CloudShare{}, err
	}
	expiresAt := ""
	if options.Days > 0 {
		expiresAt = time.Now().UTC().Add(time.Duration(options.Days) * 24 * time.Hour).Format(time.RFC3339)
	}
	return CloudShare{URL: link, Code: code, ExpiresAt: expiresAt}, nil
}
