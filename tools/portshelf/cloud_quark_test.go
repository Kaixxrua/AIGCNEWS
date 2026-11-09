package main

import (
	"bytes"
	"context"
	"crypto/md5"
	"crypto/sha1"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type quarkTestTransport func(*http.Request) (*http.Response, error)

func (f quarkTestTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func quarkTestResponse(data any) *http.Response {
	body, _ := json.Marshal(map[string]any{"status": 0, "errno": 0, "data": data})
	return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(bytes.NewReader(body))}
}

func quarkTestDrive(t *testing.T, handler quarkTestTransport) *quarkDrive {
	t.Helper()
	d := newQuarkDrive(CloudCredentials{AccessToken: "private-account-token"}).(*quarkDrive)
	d.client.Transport = quarkTestTransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host == "open-api-drive.quark.cn" {
			if r.Header.Get("Cookie") != "" {
				t.Error("cookie sent to official token API")
			}
			tm := r.Header.Get("X-Pan-Tm")
			expect := sha256.Sum256([]byte(r.Method + "&" + r.URL.Path + "&" + tm + "&" + quarkSignKey))
			if r.Header.Get("X-Pan-Token") != hex.EncodeToString(expect[:]) || r.Header.Get("X-Pan-Client-Id") != quarkClientID {
				t.Error("invalid official signature")
			}
			if _, err := strconv.ParseInt(tm, 10, 64); err != nil || r.URL.Query().Get("req_id") == "" {
				t.Error("missing timestamp/request ID")
			}
		}
		return handler(r)
	})
	return d
}

func quarkTestFile(t *testing.T, contents []byte) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "game.zip")
	if err := os.WriteFile(path, contents, 0600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestQuarkAuthorizationCodeAndMemoryRefresh(t *testing.T) {
	var exchanges, rotations int
	d := quarkTestDrive(t, func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case "/agent/v1/get_authorize_page_url":
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			identity, _ := quarkDeviceIdentity()
			if body["client_device_id"] != identity || body["client_id"] != quarkClientID || body["agent_id"] != "portshelf" || body["work_dir"] != "" {
				t.Fatalf("bad authorize metadata: %v", body)
			}
			return quarkTestResponse(map[string]string{"authorize_page_url": "https://pan.quark.cn/open/v1/oauth/agent?page_code=public-page#/agent-oauth"}), nil
		case "/agent/v1/oauth/agent_auth_code":
			exchanges++
			if r.URL.Query().Get("agent_auth_code") != "user-auth-code" || r.Header.Get("Authorization") != "" || r.URL.Query().Has("access_token") {
				t.Fatal("code exchange did not use code-only authorization")
			}
			return quarkTestResponse(map[string]any{"status": "install_confirmed", "access_token": "first-token", "refresh_token": "first-refresh", "device_id": "account-device", "user_id": "user1", "access_token_expires_at": time.Now().Add(2 * time.Hour).UnixMilli()}), nil
		case "/agent/v1/oauth/access_token/rotate":
			rotations++
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["refresh_token"] != "first-refresh" || body["device_id"] != "account-device" || r.Header.Get("Authorization") != "" {
				t.Fatal("wrong refresh grant")
			}
			return quarkTestResponse(map[string]any{"access_token": "rotated-token", "refresh_token": "rotated-refresh", "expires_in": 7200}), nil
		case "/open/v1/user/info":
			expect := "first-token"
			if rotations > 0 {
				expect = "rotated-token"
			}
			if r.URL.Query().Get("access_token") != expect || r.Header.Get("Authorization") != "Bearer "+expect || r.URL.Query().Get("device_id") != "wild_claw" {
				t.Fatal("wrong account authorization")
			}
			return quarkTestResponse(map[string]string{"user_id": "user1", "nickname": "测试账号"}), nil
		default:
			t.Fatalf("unexpected API path: %s", r.URL.Path)
			return nil, nil
		}
	})
	d.token, d.authCode = "", "user-auth-code"
	if target, err := d.authorizationURL(context.Background()); err != nil || target != "https://pan.quark.cn/open/v1/oauth/agent?page_code=public-page#/agent-oauth" {
		t.Fatalf("authorize URL %q: %v", target, err)
	}
	if account, err := d.Check(context.Background()); err != nil || account != "测试账号" || d.authCode != "" {
		t.Fatalf("code login account=%q error=%v codeCleared=%v", account, err, d.authCode == "")
	}
	d.expires = time.Now().Add(-time.Minute)
	if _, err := d.Check(context.Background()); err != nil || exchanges != 1 || rotations != 1 || d.refresh != "rotated-refresh" {
		t.Fatalf("refresh failed: %v, exchanges=%d rotations=%d", err, exchanges, rotations)
	}
}

func TestQuarkMultipartUploadAndPrivateShare(t *testing.T) {
	contents := bytes.Repeat([]byte("a"), 150)
	local := quarkTestFile(t, contents)
	var calls []string
	var received []byte
	var previous int64
	var progressCalls int
	d := quarkTestDrive(t, func(r *http.Request) (*http.Response, error) {
		calls = append(calls, r.URL.Path)
		if r.URL.Host == "portshelf.oss-cn-shanghai.aliyuncs.com" {
			if r.Method != "PUT" || r.Header.Get("Authorization") != "OSS temporary-part-signature" || r.Header.Get("X-Pan-Token") != "" || r.Header.Get("Cookie") != "" || r.URL.Query().Has("access_token") {
				t.Fatal("account credentials leaked to storage or wrong upload method")
			}
			body, err := io.ReadAll(r.Body)
			if err != nil || int64(len(body)) != r.ContentLength {
				t.Fatalf("stream mismatch: %v, length=%d expected=%d", err, len(body), r.ContentLength)
			}
			received = append(received, body...)
			return &http.Response{StatusCode: 200, Header: http.Header{"Etag": []string{"part-etag"}}, Body: io.NopCloser(strings.NewReader(""))}, nil
		}
		switch r.URL.Path {
		case "/open/v1/user/info":
			return quarkTestResponse(map[string]string{"user_id": "user1", "nickname": "玩家"}), nil
		case "/open/v1/dir":
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["dir_path"] != "PortShelf" || body["pdir_fid"] != "0" {
				t.Fatal("wrong upload directory")
			}
			return quarkTestResponse(map[string]string{"fid": "folder1"}), nil
		case "/open/v1/file/upload_pre":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["pdir_fid"] != "folder1" || body["file_name"] != "游戏.zip" || body["size"] != float64(len(contents)) || body["parallel_upload"] != true || body["hash_update"] != true || body["sha1"] != "" {
				t.Fatalf("incorrect preupload request: %v", body)
			}
			md := func(s string) string { sum := md5.Sum([]byte(s)); return hex.EncodeToString(sum[:]) }
			seeds := []string{md(md("user1" + r.Header.Get("X-Pan-Token"))), md(md("150"))}
			for n, seed := range seeds {
				number := strconv.Itoa(n + 1)
				offset, _ := strconv.ParseUint(seed[:16], 16, 64)
				start := int(offset % uint64(len(contents)))
				expect := base64.StdEncoding.EncodeToString(contents[start:min(start+8, len(contents))])
				if body["proof_seed"+number] != seed || body["proof_code"+number] != expect {
					t.Fatal("upload proof does not match signed request")
				}
			}
			return quarkTestResponse(map[string]any{"task_id": "task1", "part_size": 64, "finish": false, "common_headers": map[string]string{"Content-Type": "application/octet-stream", "x-oss-date": "20261109T000000Z"}}), nil
		case "/open/v1/file/update/hash":
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			sha, md := sha1.Sum(contents), md5.Sum(contents)
			if body["task_id"] != "task1" || body["sha1"] != hex.EncodeToString(sha[:]) || body["md5"] != hex.EncodeToString(md[:]) {
				t.Fatal("wrong content digests")
			}
			return quarkTestResponse(map[string]bool{"finish": false}), nil
		case "/open/v1/file/get_upload_urls":
			var body struct {
				Task  string      `json:"task_id"`
				Parts []quarkPart `json:"part_info_list"`
			}
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body.Task != "task1" || len(body.Parts) != 3 || body.Parts[0].SHA1 != nil || body.Parts[2].Size != 22 {
				t.Fatalf("invalid multipart request: %+v", body)
			}
			// SHA-1's compression state after one block of 64 ASCII 'a' bytes,
			// independently calculated from the FIPS 180-4 compression rounds.
			golden := [5]uint32{0xda4968eb, 0x2e377c1f, 0x884e8f52, 0x83524beb, 0xe74ebdbd}
			if body.Parts[1].SHA1 == nil || body.Parts[1].SHA1.Offset != 64 || body.Parts[1].SHA1.H != golden {
				t.Fatalf("wrong SHA1 chaining state: %+v", body.Parts[1].SHA1)
			}
			var urls []map[string]any
			for _, part := range body.Parts {
				urls = append(urls, map[string]any{"part_number": part.Number, "upload_url": fmt.Sprintf("https://portshelf.oss-cn-shanghai.aliyuncs.com/part%d?uploadId=temporary", part.Number), "signature_info": map[string]string{"signature": "OSS temporary-part-signature"}})
			}
			return quarkTestResponse(map[string]any{"upload_urls": urls}), nil
		case "/open/v1/file/upload_finish":
			var body struct {
				Task  string              `json:"task_id"`
				Parts []quarkUploadedPart `json:"part_info_list"`
			}
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body.Task != "task1" || len(body.Parts) != 3 || body.Parts[2].Number != 3 || body.Parts[2].ETag != "part-etag" || !bytes.Equal(received, contents) {
				t.Fatal("finish before complete content/etags")
			}
			return quarkTestResponse(map[string]any{"finish": true, "fid": "uploaded1"}), nil
		case "/agent/v1/share/create":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["url_type"] != float64(2) || body["expired_type"] != float64(3) || body["passcode"] != nil || body["title"] != "游戏.zip" {
				t.Fatal("incorrect private sharing settings")
			}
			return quarkTestResponse(map[string]string{"share_url": "https://pan.quark.cn/s/share123", "passcode": "ABCD"}), nil
		default:
			t.Fatalf("unexpected API path: %s", r.URL.Path)
			return nil, nil
		}
	})
	file, err := d.Upload(context.Background(), local, "游戏.zip", func(done, total int64) {
		progressCalls++
		if done < previous || done > total || total != int64(len(contents)) {
			t.Fatalf("invalid progress %d/%d after %d", done, total, previous)
		}
		previous = done
	})
	if err != nil || file.ID != "uploaded1" || file.Path != "/PortShelf/游戏.zip" || previous != int64(len(contents)) || progressCalls < 4 {
		t.Fatalf("upload result %+v, error=%v, progress=%d/%d", file, err, previous, progressCalls)
	}
	share, err := d.Share(context.Background(), file, ShareOptions{Days: 7, Private: true})
	if err != nil || share.URL != "https://pan.quark.cn/s/share123" || share.Code != "ABCD" || share.ExpiresAt == "" {
		t.Fatalf("share result %+v, error=%v", share, err)
	}
	if calls[len(calls)-2] != "/open/v1/file/upload_finish" {
		t.Fatal("sharing did not follow finish")
	}
}

func TestQuarkRapidUploadAndCancelBeforeFinish(t *testing.T) {
	for _, mode := range []string{"pre-rapid", "hash-rapid", "cancel", "invalid-parts", "storage-failure"} {
		t.Run(mode, func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			var finished, put bool
			d := quarkTestDrive(t, func(r *http.Request) (*http.Response, error) {
				switch r.URL.Path {
				case "/open/v1/user/info":
					return quarkTestResponse(map[string]string{"user_id": "user1"}), nil
				case "/open/v1/dir":
					return quarkTestResponse(map[string]string{"fid": "folder1"}), nil
				case "/open/v1/file/upload_pre":
					if mode == "pre-rapid" {
						return quarkTestResponse(map[string]any{"finish": true, "fid": "rapid1"}), nil
					}
					partSize := 64
					if mode == "invalid-parts" {
						partSize = 0
					}
					return quarkTestResponse(map[string]any{"task_id": "task1", "part_size": partSize}), nil
				case "/open/v1/file/update/hash":
					return quarkTestResponse(map[string]any{"finish": mode == "hash-rapid", "fid": "rapid1"}), nil
				case "/open/v1/file/get_upload_urls":
					return quarkTestResponse(map[string]any{"upload_urls": []any{map[string]any{"part_number": 1, "upload_url": "https://bucket.oss-cn-shanghai.aliyuncs.com/part1", "signature_info": map[string]string{"signature": "OSS signature"}}}}), nil
				case "/part1":
					put = true
					if mode == "storage-failure" {
						return &http.Response{StatusCode: 500, Header: make(http.Header), Body: io.NopCloser(strings.NewReader("secret-token"))}, nil
					}
					buffer := make([]byte, 2)
					_, _ = r.Body.Read(buffer)
					cancel()
					_, err := r.Body.Read(buffer)
					if !errors.Is(err, context.Canceled) {
						t.Fatalf("reader did not stop on cancellation: %v", err)
					}
					return nil, context.Canceled
				case "/open/v1/file/upload_finish":
					finished = true
					t.Fatal("must not finalize failed/cancelled/rapid upload")
				}
				return nil, errors.New("unexpected call")
			})
			file, err := d.Upload(ctx, quarkTestFile(t, []byte("test-file-content")), "game.zip", nil)
			if mode == "pre-rapid" || mode == "hash-rapid" {
				if err != nil || file.ID != "rapid1" || put || finished {
					t.Fatalf("rapid upload result %+v: %v", file, err)
				}
			} else if err == nil || file.ID != "" || finished || (mode == "cancel" && !errors.Is(err, context.Canceled)) {
				t.Fatalf("failed upload result %+v: %v", file, err)
			}
		})
	}
}

func TestQuarkBoundariesAndCredentialErrors(t *testing.T) {
	for _, raw := range []string{
		"http://bucket.oss-cn-shanghai.aliyuncs.com/p", "https://127.0.0.1/p", "https://[::1]/p", "https://evil.example/p", "https://bucket.oss-cn-shanghai.aliyuncs.com.evil.example/p", "https://user:pass@bucket.oss-cn-shanghai.aliyuncs.com/p", "https://bucket.oss-cn-shanghai.aliyuncs.com:443/p", "https://bucket.oss-cn-shanghai.aliyuncs.com:/p", "https://bucket.oss-cn-shanghai.aliyuncs.com/p#fragment", "https://bucket.oss-cn-shanghai.aliyuncs.com./p", "https://bucket.not-oss.aliyuncs.com/p",
	} {
		if _, err := quarkStorageURL(raw); err == nil {
			t.Errorf("accepted untrusted storage URL: %s", raw)
		}
	}
	for _, raw := range []string{"127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "198.18.0.1", "192.0.2.1", "::1", "::ffff:127.0.0.1", "fc00::1", "fe80::1", "fec0::1", "2001:db8::1", "2001::1", "64:ff9b::7f00:1", "64:ff9b:1::7f00:1"} {
		if quarkPublicIP(netip.MustParseAddr(raw)) {
			t.Errorf("accepted non-public destination: %s", raw)
		}
	}
	if !quarkPublicIP(netip.MustParseAddr("8.8.8.8")) || !quarkPublicIP(netip.MustParseAddr("2606:4700:4700::1111")) {
		t.Fatal("rejected public IP")
	}
	for _, credential := range []CloudCredentials{{Cookie: "own-cookie"}, {AccessToken: "has\r\nheader"}, {AccessToken: strings.Repeat("a", 12001)}, {}} {
		d := newQuarkDrive(credential).(*quarkDrive)
		d.client.Transport = quarkTestTransport(func(*http.Request) (*http.Response, error) {
			t.Fatal("invalid credential reached HTTP")
			return nil, nil
		})
		if _, err := d.Check(context.Background()); err == nil {
			t.Fatal("accepted invalid credentials")
		}
	}
	for _, failure := range []string{"network", "status", "missing-status", "null-data", "oversize", "redirect"} {
		t.Run(failure, func(t *testing.T) {
			calls := 0
			d := quarkTestDrive(t, func(r *http.Request) (*http.Response, error) {
				calls++
				if failure == "network" {
					return nil, &url.Error{Op: "Get", URL: r.URL.String(), Err: errors.New("private-account-token")}
				}
				body := `{"status":1,"errno":42,"error_info":"private-account-token","data":{}}`
				switch failure {
				case "missing-status":
					body = `{"data":{"user_id":"forged"}}`
				case "null-data":
					body = `{"status":0,"data":null}`
				case "oversize":
					body = strings.Repeat("a", quarkMaxReply+1)
				case "redirect":
					return &http.Response{StatusCode: 302, Header: http.Header{"Location": []string{"https://evil.example/leak"}}, Body: io.NopCloser(strings.NewReader(""))}, nil
				}
				return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}, nil
			})
			_, err := d.Check(context.Background())
			if err == nil || strings.Contains(err.Error(), "private-account-token") || strings.Contains(err.Error(), "access_token") || calls != 1 {
				t.Fatalf("unsafe/incorrect error: %v calls=%d", err, calls)
			}
		})
	}
}

func TestQuarkStorageHeaderAndRedirectProtection(t *testing.T) {
	d := quarkTestDrive(t, func(r *http.Request) (*http.Response, error) {
		if r.URL.Host != "bucket.oss-cn-shanghai.aliyuncs.com" {
			t.Fatal("followed external redirect")
		}
		return &http.Response{StatusCode: 307, Header: http.Header{"Location": []string{"https://evil.example/leak"}}, Body: io.NopCloser(strings.NewReader(""))}, nil
	})
	entry := quarkUploadURL{URL: "https://bucket.oss-cn-shanghai.aliyuncs.com/p"}
	entry.Signature.Value = "OSS signed-part"
	for _, header := range []map[string]string{{"Cookie": "private"}, {"Host": "evil.example"}, {"Authorization": "Bearer private"}, {"X-Pan-Token": "private"}, {"X-Oss-Foo": "ok\r\nCookie: private"}, {"X Oss Foo": "invalid"}} {
		if _, err := d.putPart(context.Background(), entry, header, strings.NewReader("file"), 4); err == nil {
			t.Fatalf("accepted unsafe upload headers: %v", header)
		}
	}
	if _, err := d.putPart(context.Background(), entry, nil, strings.NewReader("file"), 4); err == nil || !strings.Contains(err.Error(), "307") {
		t.Fatalf("storage redirect error=%v", err)
	}
}

func TestQuarkShareValidationAndAuthorizationURL(t *testing.T) {
	file := CloudFile{ID: "file1", Name: "game.zip"}
	d := quarkTestDrive(t, func(*http.Request) (*http.Response, error) {
		t.Fatal("invalid share input reached HTTP")
		return nil, nil
	})
	for _, options := range []ShareOptions{{Days: 2}, {Days: -1}, {Code: "custom"}} {
		if _, err := d.Share(context.Background(), file, options); err == nil {
			t.Fatalf("accepted invalid options: %+v", options)
		}
	}
	for _, name := range []string{"", "../game.zip", "..", "bad\\game.zip", "nul\x00.zip", "game\n.zip", strings.Repeat("a", 256)} {
		if _, err := d.Upload(context.Background(), "unused", name, nil); err == nil {
			t.Errorf("accepted bad remote name %q", name)
		}
	}
	for _, endpoint := range []string{"authorization", "share"} {
		for _, raw := range []string{"https://evil.example/s/fid", "https://pan.quark.cn.evil.example/s/fid", "https://user@pan.quark.cn/s/fid", "http://pan.quark.cn/s/fid", "https://pan.quark.cn:443/s/fid", "https://pan.quark.cn/s/fid#fragment"} {
			d.client.Transport = quarkTestTransport(func(*http.Request) (*http.Response, error) {
				return quarkTestResponse(map[string]string{"authorize_page_url": raw, "share_url": raw, "passcode": "ABCD"}), nil
			})
			var err error
			if endpoint == "authorization" {
				_, err = d.authorizationURL(context.Background())
			} else {
				_, err = d.Share(context.Background(), file, ShareOptions{Private: true})
			}
			if err == nil {
				t.Fatalf("accepted unsafe %s URL: %s", endpoint, raw)
			}
		}
	}
	var gotTypes []int
	for _, days := range []int{0, 1, 7, 30, 60, 100, 180} {
		d.client.Transport = quarkTestTransport(func(r *http.Request) (*http.Response, error) {
			var body struct {
				Expiry  int `json:"expired_type"`
				URLType int `json:"url_type"`
			}
			_ = json.NewDecoder(r.Body).Decode(&body)
			gotTypes = append(gotTypes, body.Expiry)
			if body.URLType != 1 {
				t.Fatal("default share should be public")
			}
			return quarkTestResponse(map[string]string{"share_url": "https://pan.quark.cn/s/fid"}), nil
		})
		share, err := d.Share(context.Background(), file, ShareOptions{Days: days})
		if err != nil || (days == 0) != (share.ExpiresAt == "") {
			t.Fatalf("expiry mapping days=%d result=%+v error=%v", days, share, err)
		}
	}
	if !reflect.DeepEqual(gotTypes, []int{1, 2, 3, 4, 5, 6, 7}) {
		t.Fatalf("wrong expiry enum %v", gotTypes)
	}
}

func TestQuarkConcurrentAuthorizationAndCancelledWait(t *testing.T) {
	var exchanges atomic.Int32
	started := make(chan struct{})
	release := make(chan struct{})
	d := quarkTestDrive(t, func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == "/agent/v1/oauth/agent_auth_code" {
			exchanges.Add(1)
			close(started)
			<-release
			return quarkTestResponse(map[string]string{"status": "confirmed", "access_token": "new-token", "user_id": "user1"}), nil
		}
		return quarkTestResponse(map[string]string{"user_id": "user1"}), nil
	})
	d.token, d.authCode = "", "code"
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		if _, err := d.Check(context.Background()); err != nil {
			t.Error(err)
		}
	}()
	<-started
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := d.Check(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("blocked authorization did not cancel: %v", err)
	}
	close(release)
	wg.Wait()
	if _, err := d.Check(context.Background()); err != nil || exchanges.Load() != 1 {
		t.Fatalf("exchanged one-time auth code more than once: %v count=%d", err, exchanges.Load())
	}
}
