package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"testing/iotest"
	"time"
)

func TestBaiduHTTP400ExistingDirectoryContinuesUpload(t *testing.T) {
	data := []byte("existing directory must not prevent the next upload")
	filename := baiduTestFile(t, data)
	var steps []string
	var mu sync.Mutex
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		steps = append(steps, r.URL.Path)
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/gettemplatevariable":
			fmt.Fprint(w, `{"errno":0,"result":{"bdstoken":"testCSRF"}}`)
		case "/api/create":
			if err := r.ParseForm(); err != nil {
				t.Error(err)
			}
			if r.Form.Get("isdir") == "1" {
				w.WriteHeader(http.StatusBadRequest)
				fmt.Fprint(w, `{"error_code":31061,"error_msg":"file already exists"}`)
				return
			}
			fmt.Fprintf(w, `{"errno":0,"fs_id":42,"path":"/PortShelf/game.zip","size":%d,"isdir":0}`, len(data))
		case "/api/filemetas":
			if r.Method != http.MethodGet || r.URL.Query().Get("target") != `["/PortShelf"]` || r.URL.Query().Get("bdstoken") != "testCSRF" {
				t.Error("metadata must use the authenticated web API")
			}
			fmt.Fprint(w, `{"errno":0,"info":[{"path":"/PortShelf","fs_id":1,"isdir":1}]}`)
		case "/rest/2.0/pcs/file":
			w.WriteHeader(http.StatusBadRequest)
			fmt.Fprint(w, `{"error_code":31030,"error_msg":"pcs token not exist"}`)
		case "/api/precreate":
			fmt.Fprint(w, `{"errno":0,"return_type":1,"uploadid":"test-upload","block_list":[0]}`)
		case "/rest/2.0/pcs/superfile2":
			reader, err := r.MultipartReader()
			if err != nil {
				t.Error(err)
				return
			}
			part, err := reader.NextPart()
			if err != nil {
				t.Error(err)
				return
			}
			payload, err := io.ReadAll(part)
			if err != nil || !bytes.Equal(payload, data) {
				t.Errorf("upload bytes changed: %v", err)
			}
			fmt.Fprintf(w, `{"md5":%q}`, baiduTestDigest(payload))
		default:
			t.Errorf("unexpected path: %s", r.URL.Path)
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	local, _ := url.Parse(server.URL)
	drive := baiduTestDrive(func(r *http.Request) (*http.Response, error) {
		// Exercise actual HTTP 400/body handling, using only synthetic credentials.
		clone := r.Clone(r.Context())
		clone.URL.Scheme, clone.URL.Host, clone.Host = local.Scheme, local.Host, local.Host
		return server.Client().Transport.RoundTrip(clone)
	})
	file, err := drive.Upload(context.Background(), filename, "game.zip", nil)
	mu.Lock()
	defer mu.Unlock()
	if err != nil || file.ID != "42" || file.Path != "/PortShelf/game.zip" || len(steps) != 6 {
		t.Fatalf("HTTP 400 directory-exists interrupted upload: file=%+v steps=%v err=%v", file, steps, err)
	}
}

func TestBaiduHTTPErrorCodesAndStepsAreSafeAndActionable(t *testing.T) {
	for _, tc := range []struct {
		name, endpoint, body, stage, message string
		status, code                         int
		attention                            bool
	}{
		{"login", "/api/gettemplatevariable", `{"errno":-6}`, "验证百度登录", "更新 Cookie", 400, -6, true},
		{"space", "/api/precreate", `{"error_code":"31190"}`, "准备百度上传", "空间不足", 400, 31190, true},
		{"params", "/rest/2.0/pcs/superfile2", `{"error_code":2}`, "上传百度文件分片", "请求参数", 400, 2, false},
		{"unknown", "/rest/2.0/pcs/superfile2", `{"error_code":31299}`, "上传百度文件分片", "操作失败", 400, 31299, true},
		{"rate", "/api/filemetas", `{"errno":31034}`, "核对百度上传目录", "请求过于频繁", 429, 31034, false},
		{"share limit", "/share/pset", `{"errno":-10}`, "创建百度分享链接", "分享数量", 400, -10, true},
		{"same directory", "/api/create", `{"errno":-8}`, "创建百度文件或目录", "同名", 400, -8, true},
		{"http ok api failed", "/api/precreate", `{"errno":2}`, "准备百度上传", "请求参数", 200, 2, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body := strings.TrimSuffix(tc.body, "}") + `,"error_msg":"private-bduss private-stoken privateCSRF123 Cookie=secret","request_id":"secret-id"}`
			drive := baiduTestDrive(func(*http.Request) (*http.Response, error) { return apiResponse(tc.status, body), nil })
			host := "pan.baidu.com"
			if tc.endpoint == "/rest/2.0/pcs/superfile2" {
				host = "d.pcs.baidu.com"
			}
			var output any
			err := drive.request(context.Background(), http.MethodPost, host, tc.endpoint, url.Values{"bdstoken": {"privateCSRF123"}}, nil, "", 0, time.Second, &output)
			var remote *baiduAPIError
			if !errors.As(err, &remote) || remote.Code != tc.code || remote.Sharing != (tc.endpoint == "/share/pset") {
				t.Fatalf("business error lost: %v", err)
			}
			for _, want := range []string{tc.stage, tc.message, fmt.Sprintf("错误码 %d", tc.code)} {
				if !strings.Contains(err.Error(), want) {
					t.Errorf("missing %q in %v", want, err)
				}
			}
			if tc.status >= 400 && !strings.Contains(err.Error(), fmt.Sprintf("HTTP %d", tc.status)) {
				t.Errorf("HTTP status lost: %v", err)
			}
			if manualActionRequired(err.Error()) != tc.attention {
				t.Errorf("incorrect automatic retry classification: %v", err)
			}
			for _, secret := range []string{"private-bduss", "private-stoken", "privateCSRF123", "Cookie=", "secret-id", "https://"} {
				if strings.Contains(err.Error(), secret) {
					t.Errorf("credential/body escaped: %v", err)
				}
			}
		})
	}
}

func TestBaiduHTTP400FallbackNeverBecomesSuccessOrExposesBody(t *testing.T) {
	for _, body := range []string{"", "<html>private-stoken</html>", `{"errno":0}`, `{"error_code":0,"result":{"bdstoken":"privateCSRF123"}}`, `{"error_code":"private-bduss"}`, `{"error_code":99999999999999999999999}`, strings.Repeat("x", baiduResponseLimit+1)} {
		drive := baiduTestDrive(func(*http.Request) (*http.Response, error) { return apiResponse(400, body), nil })
		_, err := drive.Check(context.Background())
		if err == nil || !strings.Contains(err.Error(), "HTTP 400") || strings.Contains(err.Error(), "暂不可用") || strings.Contains(err.Error(), "private-") || strings.Contains(err.Error(), "privateCSRF") {
			t.Fatalf("bad HTTP fallback: %v", err)
		}
	}
	drive := baiduTestDrive(func(*http.Request) (*http.Response, error) {
		response := apiResponse(400, "")
		response.Body = io.NopCloser(iotest.ErrReader(errors.New("private-body-read-error")))
		return response, nil
	})
	if _, err := drive.Check(context.Background()); err == nil || !strings.Contains(err.Error(), "HTTP 400") || strings.Contains(err.Error(), "private-") {
		t.Fatalf("unreadable HTTP error body lost status: %v", err)
	}
}

func TestBaiduMalformedBusinessCodeCannotBeAcceptedAsHTTP200Success(t *testing.T) {
	for _, code := range []string{`"private-secret"`, `"1.5"`, `99999999999999999999999`, `1000001`} {
		drive := baiduTestDrive(func(*http.Request) (*http.Response, error) {
			return apiResponse(200, `{"errno":`+code+`,"result":{"bdstoken":"validLookingToken"}}`), nil
		})
		if _, err := drive.Check(context.Background()); err == nil || strings.Contains(err.Error(), "private-") {
			t.Fatalf("invalid business status accepted or exposed: %v", err)
		}
	}
}
