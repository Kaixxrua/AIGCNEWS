package main

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

const testBaiduCookie = "BDUSS=private-bduss; STOKEN=private-stoken; BAIDUID=private-id"

func baiduTestDrive(handler transportFunc) *baiduDrive {
	drive := newBaiduDrive(CloudCredentials{Cookie: testBaiduCookie, AccessToken: "unused-oauth-secret"}).(*baiduDrive)
	drive.client.Transport = handler
	return drive
}

func baiduTestFile(t *testing.T, data []byte) string {
	t.Helper()
	filename := filepath.Join(t.TempDir(), "local-game.zip")
	if err := os.WriteFile(filename, data, 0600); err != nil {
		t.Fatal(err)
	}
	return filename
}

func baiduTestDigest(data []byte) string {
	hash := md5.Sum(data)
	return hex.EncodeToString(hash[:])
}

func baiduTestSessionResponse() *http.Response {
	return apiResponse(200, `{"errno":0,"result":{"bdstoken":"privateCSRF123"}}`)
}

func TestBaiduStreamedUploadRenameAndShare(t *testing.T) {
	data := append(bytes.Repeat([]byte("a"), int(baiduChunkSize)), []byte("second-block")...)
	filename := baiduTestFile(t, data)
	var uploaded []int
	var sharePath string
	var createCount int
	drive := baiduTestDrive(func(request *http.Request) (*http.Response, error) {
		if request.URL.Scheme != "https" || !baiduEndpointAllowed(request.URL.Host, request.URL.Path) || request.Header.Get("Cookie") != testBaiduCookie {
			t.Fatalf("incorrect fixed-host authentication")
		}
		if strings.Contains(request.URL.String(), "unused-oauth-secret") || request.Header.Get("Authorization") != "" {
			t.Fatal("OAuth credential leaked into Cookie workflow")
		}
		switch request.URL.Path {
		case "/api/gettemplatevariable":
			if request.URL.Query().Get("fields") != `["bdstoken"]` {
				t.Fatal("missing session fields")
			}
			return baiduTestSessionResponse(), nil
		case "/api/create":
			if err := request.ParseForm(); err != nil {
				t.Fatal(err)
			}
			if request.Form.Get("isdir") == "1" {
				if request.Form.Get("path") != baiduDirectory || request.Form.Get("rtype") != "0" {
					t.Fatal("directory can be renamed or overwritten")
				}
				return apiResponse(200, `{"errno":0,"path":"/PortShelf","fs_id":101,"isdir":1}`), nil
			}
			createCount++
			if request.Form.Get("path") != "/PortShelf/game.zip" || request.Form.Get("uploadid") != "upload-session" || request.Form.Get("rtype") != "1" || request.Form.Get("size") != strconv.Itoa(len(data)) {
				t.Fatal("incorrect final create form")
			}
			return apiResponse(200, fmt.Sprintf(`{"errno":0,"path":"/PortShelf/game (1).zip","server_filename":"game (1).zip","fs_id":12345678901234567,"size":%d,"isdir":0}`, len(data))), nil
		case "/api/precreate":
			if err := request.ParseForm(); err != nil {
				t.Fatal(err)
			}
			var hashes []string
			if json.Unmarshal([]byte(request.Form.Get("block_list")), &hashes) != nil || len(hashes) != 2 || hashes[0] != baiduTestDigest(data[:baiduChunkSize]) || hashes[1] != baiduTestDigest(data[baiduChunkSize:]) {
				t.Fatal("incorrect precreate hashes")
			}
			if request.Form.Get("rtype") != "1" || request.URL.Query().Get("bdstoken") != "privateCSRF123" {
				t.Fatal("precreate collision/session contract")
			}
			return apiResponse(200, `{"errno":0,"return_type":1,"uploadid":"upload-session","block_list":[0,1]}`), nil
		case "/rest/2.0/pcs/superfile2":
			index, _ := strconv.Atoi(request.URL.Query().Get("partseq"))
			if request.URL.Host != "d.pcs.baidu.com" || request.URL.Query().Get("path") != "/PortShelf/game.zip" || request.URL.Query().Get("uploadid") != "upload-session" || request.URL.Query().Get("partoffset") != strconv.FormatInt(int64(index)*baiduChunkSize, 10) {
				t.Fatal("incorrect slice request")
			}
			if request.ContentLength <= 0 || request.GetBody != nil {
				t.Fatal("payload is not a length-delimited stream")
			}
			reader, err := request.MultipartReader()
			if err != nil {
				t.Fatal(err)
			}
			part, err := reader.NextPart()
			if err != nil || part.FormName() != "file" || part.FileName() != "chunk" {
				t.Fatal("incorrect multipart file framing")
			}
			payload, err := io.ReadAll(part)
			if err != nil {
				t.Fatal(err)
			}
			start := int64(index) * baiduChunkSize
			if !bytes.Equal(payload, data[start:min(start+baiduChunkSize, int64(len(data)))]) {
				t.Fatal("incorrect slice bytes")
			}
			if _, err = reader.NextPart(); err != io.EOF {
				t.Fatal("unexpected extra multipart field")
			}
			uploaded = append(uploaded, index)
			return apiResponse(200, `{"md5":"`+baiduTestDigest(payload)+`"}`), nil
		case "/share/pset":
			if err := request.ParseForm(); err != nil {
				t.Fatal(err)
			}
			var paths []string
			if json.Unmarshal([]byte(request.Form.Get("path_list")), &paths) != nil || len(paths) != 1 {
				t.Fatal("incorrect share path list")
			}
			sharePath = paths[0]
			if request.Form.Get("period") != "30" || request.Form.Get("pwd") != "Ab12" || request.Form.Get("schannel") != "4" || request.Form.Get("share_type") != "9" {
				t.Fatal("incorrect explicit share options")
			}
			return apiResponse(200, `{"errno":0,"link":"https://pan.baidu.com/s/1example?pwd=Ab12"}`), nil
		default:
			t.Fatalf("unexpected request path: %s", request.URL.Path)
		}
		return nil, nil
	})
	var previous int64
	file, err := drive.Upload(context.Background(), filename, "game.zip", func(done, total int64) {
		if total != int64(len(data)) || done < previous || done > total {
			t.Errorf("incorrect payload progress %d / %d after %d", done, total, previous)
		}
		previous = done
	})
	if err != nil {
		t.Fatal(err)
	}
	if file.ID != "12345678901234567" || file.Path != "/PortShelf/game (1).zip" || file.Name != "game (1).zip" || previous != int64(len(data)) || len(uploaded) != 2 || createCount != 1 {
		t.Fatalf("incorrect uploaded file: %+v", file)
	}
	before := time.Now().UTC()
	share, err := drive.Share(context.Background(), file, ShareOptions{Days: 30, Code: "Ab12", Private: true})
	if err != nil {
		t.Fatal(err)
	}
	expires, err := time.Parse(time.RFC3339, share.ExpiresAt)
	if err != nil || expires.Before(before.Add(30*24*time.Hour-time.Second)) || expires.After(time.Now().UTC().Add(30*24*time.Hour+time.Second)) {
		t.Fatalf("incorrect share expiration: %s", share.ExpiresAt)
	}
	if sharePath != file.Path || share.URL != "https://pan.baidu.com/s/1example" || share.Code != "Ab12" {
		t.Fatalf("incorrect share: %+v", share)
	}
}

func TestBaiduExistingRootMustBeDirectory(t *testing.T) {
	for _, isDir := range []int{0, 1} {
		t.Run(strconv.Itoa(isDir), func(t *testing.T) {
			calls := 0
			drive := baiduTestDrive(func(request *http.Request) (*http.Response, error) {
				calls++
				if request.URL.Path == "/api/create" {
					return apiResponse(200, `{"errno":-8}`), nil
				}
				if request.URL.Host != "pcs.baidu.com" || request.URL.Path != "/rest/2.0/pcs/file" || request.URL.Query().Get("method") != "meta" {
					t.Fatal("expected metadata verification")
				}
				reader, err := request.MultipartReader()
				if err != nil {
					t.Fatal(err)
				}
				part, err := reader.NextPart()
				if err != nil || part.FormName() != "param" {
					t.Fatal("missing metadata param")
				}
				param, _ := io.ReadAll(part)
				if string(param) != `{"list":[{"path":"/PortShelf"}]}` {
					t.Fatal("metadata escaped the fixed root")
				}
				return apiResponse(200, fmt.Sprintf(`{"list":[{"path":"/PortShelf","fs_id":101,"isdir":%d}]}`, isDir)), nil
			})
			err := drive.ensureDirectory(context.Background(), "csrf")
			if (err == nil) != (isDir == 1) || calls != 2 {
				t.Fatalf("directory validation = %v, %d calls", err, calls)
			}
		})
	}
}

func TestBaiduCachedAndInvalidPrecreateBlocks(t *testing.T) {
	data := append(bytes.Repeat([]byte("a"), int(baiduChunkSize)), []byte("tail")...)
	filename := baiduTestFile(t, data)
	for _, tc := range []struct {
		name, blocks string
		wantParts    int
		valid        bool
	}{
		{"cached first", "[1]", 1, true}, {"all cached", "[]", 0, true}, {"duplicate", "[1,1]", 0, false}, {"negative", "[-1]", 0, false}, {"outside", "[2]", 0, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			parts, creates := 0, 0
			drive := baiduTestDrive(func(request *http.Request) (*http.Response, error) {
				switch request.URL.Path {
				case "/api/gettemplatevariable":
					return baiduTestSessionResponse(), nil
				case "/api/create":
					_ = request.ParseForm()
					if request.Form.Get("isdir") == "1" {
						return apiResponse(200, `{"path":"/PortShelf","fs_id":1,"isdir":1}`), nil
					}
					creates++
					return apiResponse(200, fmt.Sprintf(`{"path":"/PortShelf/game.zip","fs_id":2,"size":%d}`, len(data))), nil
				case "/api/precreate":
					return apiResponse(200, `{"return_type":1,"uploadid":"session","block_list":`+tc.blocks+`}`), nil
				case "/rest/2.0/pcs/superfile2":
					parts++
					if request.URL.Query().Get("partseq") != "1" {
						t.Fatal("uploaded cached first block")
					}
					_, _ = io.Copy(io.Discard, request.Body)
					return apiResponse(200, `{"md5":"`+baiduTestDigest([]byte("tail"))+`"}`), nil
				default:
					t.Fatal("unexpected request")
				}
				return nil, nil
			})
			last := int64(0)
			_, err := drive.Upload(context.Background(), filename, "game.zip", func(done, total int64) {
				if done < last || done > total {
					t.Error("invalid cached progress")
				}
				last = done
			})
			if (err == nil) != tc.valid || parts != tc.wantParts || (creates > 0) != tc.valid {
				t.Fatalf("upload error=%v parts=%d creates=%d", err, parts, creates)
			}
		})
	}
}

func TestBaiduRapidUploadReturnsServerFileAndNoChunks(t *testing.T) {
	filename := baiduTestFile(t, []byte("game"))
	drive := baiduTestDrive(func(request *http.Request) (*http.Response, error) {
		switch request.URL.Path {
		case "/api/gettemplatevariable":
			return baiduTestSessionResponse(), nil
		case "/api/create":
			_ = request.ParseForm()
			if request.Form.Get("isdir") != "1" {
				t.Fatal("rapid upload must not recreate the file")
			}
			return apiResponse(200, `{"path":"/PortShelf","fs_id":1,"isdir":1}`), nil
		case "/api/precreate":
			return apiResponse(200, `{"return_type":2,"info":{"fs_id":"888","path":"/PortShelf/game (1).zip","size":4}}`), nil
		default:
			t.Fatal("rapid upload unexpectedly sent file data")
		}
		return nil, nil
	})
	file, err := drive.Upload(context.Background(), filename, "game.zip", nil)
	if err != nil || file.ID != "888" || file.Name != "game (1).zip" {
		t.Fatalf("rapid result=%+v error=%v", file, err)
	}
}

func TestBaiduErrorsNeverEchoCredentialsOrProviderBody(t *testing.T) {
	for _, tc := range []struct {
		name           string
		status         int
		body           string
		transportError bool
	}{
		{"expired", 200, `{"errno":-6,"errmsg":"private-bduss privateCSRF123"}`, false},
		{"quota", 200, `{"error_code":31190,"error_msg":"private-stoken"}`, false},
		{"http", 500, "private-bduss", false}, {"unauthorized", 401, "private-stoken", false}, {"rate", 429, "privateCSRF123", false},
		{"html", 200, "<html>private-bduss</html>", false}, {"too large", 200, strings.Repeat(" ", baiduResponseLimit+1), false},
		{"transport", 0, "", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			drive := baiduTestDrive(func(request *http.Request) (*http.Response, error) {
				if tc.transportError {
					return nil, fmt.Errorf("request Cookie=%s URL=%s privateCSRF123", testBaiduCookie, request.URL)
				}
				return apiResponse(tc.status, tc.body), nil
			})
			_, err := drive.Check(context.Background())
			if err == nil {
				t.Fatal("accepted failed response")
			}
			for _, secret := range []string{"private-bduss", "private-stoken", "privateCSRF123", "unused-oauth-secret", "Cookie=", "https://"} {
				if strings.Contains(err.Error(), secret) {
					t.Fatalf("secret in public error: %v", err)
				}
			}
		})
	}
}

func TestBaiduRedirectsCannotReceiveCookie(t *testing.T) {
	for _, target := range []string{"https://evil.example/collect", "https://pan.baidu.com/collect", "http://pan.baidu.com/api/create"} {
		t.Run(target, func(t *testing.T) {
			calls := 0
			drive := baiduTestDrive(func(request *http.Request) (*http.Response, error) {
				calls++
				response := apiResponse(302, "")
				response.Header.Set("Location", target)
				return response, nil
			})
			if _, err := drive.Check(context.Background()); err == nil || calls != 1 {
				t.Fatalf("followed redirect: calls=%d err=%v", calls, err)
			}
		})
	}
}

func TestBaiduInvalidCredentialsAndTargetsMakeNoRequests(t *testing.T) {
	for _, cookie := range []string{"", "BDUSS=one", "STOKEN=two", "BDUSS=one; STOKEN=two\r\nX-Test: secret", "BDUSS=one; STOKEN=two; BDUSS=other", strings.Repeat("x", (16<<10)+1)} {
		drive := newBaiduDrive(CloudCredentials{Cookie: cookie, AccessToken: "secret-token"}).(*baiduDrive)
		drive.client.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
			t.Fatal("invalid credentials reached upstream")
			return nil, nil
		})
		if _, err := drive.Check(context.Background()); err == nil || strings.Contains(err.Error(), "secret-token") {
			t.Fatal("invalid credentials accepted or exposed")
		}
	}
	drive := baiduTestDrive(func(*http.Request) (*http.Response, error) {
		t.Fatal("invalid target reached upstream")
		return nil, nil
	})
	for _, name := range []string{"../game.zip", "..", "/game.zip", "game\\other.zip", " game.zip", "game.zip.", "game\n.zip", "game:other.zip"} {
		if _, err := drive.Upload(context.Background(), "unused", name, nil); err == nil {
			t.Errorf("accepted %q", name)
		}
	}
	var response any
	if err := drive.request(context.Background(), http.MethodGet, "evil.example", "/api/create", nil, nil, "", 0, time.Second, &response); err == nil {
		t.Fatal("accepted arbitrary host")
	}
	if err := drive.request(context.Background(), http.MethodGet, "pan.baidu.com", "/redirect", nil, nil, "", 0, time.Second, &response); err == nil {
		t.Fatal("accepted arbitrary provider path")
	}
}

func TestBaiduShareValidationRandomCodeAndPermanentPeriod(t *testing.T) {
	file := CloudFile{ID: "42", Path: "/PortShelf/game.zip", Name: "game.zip"}
	for _, options := range []ShareOptions{{Private: false}, {Private: true, Days: 2}, {Private: true, Days: -1}, {Private: true, Code: "123"}, {Private: true, Code: "字字"}, {Private: true, Code: "a<>b"}} {
		drive := baiduTestDrive(func(*http.Request) (*http.Response, error) {
			t.Fatal("invalid share options reached upstream")
			return nil, nil
		})
		if _, err := drive.Share(context.Background(), file, options); err == nil {
			t.Fatalf("accepted %+v", options)
		}
	}
	var sentCode string
	drive := baiduTestDrive(func(request *http.Request) (*http.Response, error) {
		if request.URL.Path == "/api/gettemplatevariable" {
			return baiduTestSessionResponse(), nil
		}
		_ = request.ParseForm()
		sentCode = request.Form.Get("pwd")
		if !baiduAlphaNumeric(sentCode, 4, 4) || request.Form.Get("period") != "0" {
			t.Fatal("changed permanent option or missing random code")
		}
		return apiResponse(200, `{"errno":0,"link":"http://pan.baidu.com/s/1safe"}`), nil
	})
	share, err := drive.Share(context.Background(), file, ShareOptions{Private: true})
	if err != nil || share.ExpiresAt != "" || share.Code != sentCode || share.URL != "https://pan.baidu.com/s/1safe" {
		t.Fatalf("share=%+v error=%v", share, err)
	}
	for _, unsafe := range []string{"https://evil.example/s/1abc", "https://pan.baidu.com.evil.example/s/1abc", "https://user@pan.baidu.com/s/1abc", "https://pan.baidu.com:443/s/1abc", "https://pan.baidu.com/s/../evil", "https://pan.baidu.com/s/%2e%2e", "https://pan.baidu.com/s/1abc?token=secret", "https://pan.baidu.com/s/1abc?pwd=other", "https://pan.baidu.com/s/1abc#fragment", "javascript:alert(1)"} {
		if _, err := baiduShareURL(unsafe, "1234"); err == nil {
			t.Errorf("accepted share URL %q", unsafe)
		}
	}
}

func TestBaiduUploadedMetadataMustDescribeTheActualFile(t *testing.T) {
	valid := baiduFileInfo{ID: "42", Path: "/PortShelf/game.zip", Name: "game.zip", Size: 4}
	for _, change := range []func(*baiduFileInfo){
		func(i *baiduFileInfo) { i.ID = "0" }, func(i *baiduFileInfo) { i.ID = "42.1" }, func(i *baiduFileInfo) { i.ID = "secret" },
		func(i *baiduFileInfo) { i.Path = "/other/game.zip" }, func(i *baiduFileInfo) { i.Path = "/PortShelf/nested/game.zip" },
		func(i *baiduFileInfo) { i.Path = "/PortShelf/a/../game.zip" }, func(i *baiduFileInfo) { i.Name = "other.zip" }, func(i *baiduFileInfo) { i.Size = 5 }, func(i *baiduFileInfo) { i.IsDir = 1 },
	} {
		info := valid
		change(&info)
		if _, err := info.uploadedFile(4); err == nil {
			t.Errorf("accepted unexpected metadata %+v", info)
		}
	}
}

func TestBaiduCancellationDuringHashAndUpload(t *testing.T) {
	data := bytes.Repeat([]byte("a"), 64<<10)
	filename := baiduTestFile(t, data)
	ctx, cancel := context.WithCancel(context.Background())
	drive := baiduTestDrive(func(*http.Request) (*http.Response, error) {
		t.Fatal("cancelled hash contacted upstream")
		return nil, nil
	})
	_, err := drive.Upload(ctx, filename, "game.zip", func(int64, int64) { cancel() })
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("hash cancellation=%v", err)
	}
	ctx, cancel = context.WithCancel(context.Background())
	defer cancel()
	drive = baiduTestDrive(func(request *http.Request) (*http.Response, error) {
		switch request.URL.Path {
		case "/api/gettemplatevariable":
			return baiduTestSessionResponse(), nil
		case "/api/create":
			_ = request.ParseForm()
			if request.Form.Get("isdir") != "1" {
				t.Fatal("created file after cancellation")
			}
			return apiResponse(200, `{"path":"/PortShelf","fs_id":1,"isdir":1}`), nil
		case "/api/precreate":
			return apiResponse(200, `{"return_type":1,"uploadid":"session","block_list":[0]}`), nil
		case "/rest/2.0/pcs/superfile2":
			buffer := make([]byte, 1024)
			_, _ = request.Body.Read(buffer)
			cancel()
			_, err := io.Copy(io.Discard, request.Body)
			return nil, err
		}
		t.Fatal("unexpected request")
		return nil, nil
	})
	_, err = drive.Upload(ctx, filename, "game.zip", nil)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("upload cancellation=%v", err)
	}
}

func TestBaiduCheckCanRunConcurrently(t *testing.T) {
	drive := baiduTestDrive(func(*http.Request) (*http.Response, error) { return baiduTestSessionResponse(), nil })
	var group sync.WaitGroup
	for i := 0; i < 12; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			if _, err := drive.Check(context.Background()); err != nil {
				t.Error(err)
			}
		}()
	}
	group.Wait()
}

func TestBaiduRejectsCorruptChunkAndHonorsRequestCancellation(t *testing.T) {
	filename := baiduTestFile(t, []byte("game"))
	file, err := os.Open(filename)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	for _, body := range []string{`{"md5":"00000000000000000000000000000000"}`, `{"errno":0}`} {
		drive := baiduTestDrive(func(request *http.Request) (*http.Response, error) {
			if _, ok := request.Context().Deadline(); !ok {
				t.Fatal("unbounded upload request")
			}
			_, _ = io.Copy(io.Discard, request.Body)
			return apiResponse(200, body), nil
		})
		if err := drive.uploadPart(context.Background(), file, "/PortShelf/game.zip", "session", 0, baiduChunkSize, 4, 0, baiduTestDigest([]byte("game")), nil); err == nil {
			t.Fatal("accepted unverified remote chunk")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	drive := baiduTestDrive(func(request *http.Request) (*http.Response, error) {
		if _, ok := request.Context().Deadline(); !ok {
			t.Fatal("unbounded metadata request")
		}
		cancel()
		<-request.Context().Done()
		return nil, request.Context().Err()
	})
	if _, err := drive.Check(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("request cancellation = %v", err)
	}
}

func TestBaiduProviderErrorsKeepFileAndShareLimitsDistinct(t *testing.T) {
	for _, test := range []struct {
		code    int
		sharing bool
		message string
	}{
		{31061, false, "同名"}, {-10, false, "空间不足"},
		{-10, true, "分享数量"}, {115, true, "分享限制"},
		{112, false, "登录已失效"}, {132, true, "安全验证"},
	} {
		err := &baiduAPIError{Code: test.code, Sharing: test.sharing}
		if !strings.Contains(err.Error(), test.message) {
			t.Fatalf("unexpected provider error: %v", err)
		}
	}
}
