package main

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"testing"
)

func TestBaiduWebDirectoryMetadataRejectsUnverifiedRoot(t *testing.T) {
	for _, tc := range []struct {
		name string
		body string
	}{
		{"empty", `{"errno":0,"info":[]}`},
		{"missing", `{"errno":0}`},
		{"legacy shape", `{"list":[{"path":"/PortShelf","fs_id":1,"isdir":1}]}`},
		{"duplicate", `{"errno":0,"info":[{"path":"/PortShelf","fs_id":1,"isdir":1},{"path":"/PortShelf","fs_id":2,"isdir":1}]}`},
		{"wrong path", `{"errno":0,"info":[{"path":"/other","fs_id":1,"isdir":1}]}`},
		{"file", `{"errno":0,"info":[{"path":"/PortShelf","fs_id":1,"isdir":0}]}`},
		{"missing id", `{"errno":0,"info":[{"path":"/PortShelf","isdir":1}]}`},
		{"invalid id", `{"errno":0,"info":[{"path":"/PortShelf","fs_id":0,"isdir":1}]}`},
		{"expired login", `{"errno":-6,"info":[{"path":"/PortShelf","fs_id":1,"isdir":1}]}`},
		{"invalid JSON", `{"errno":0`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			calls := 0
			drive := baiduTestDrive(func(r *http.Request) (*http.Response, error) {
				calls++
				switch r.URL.Path {
				case "/api/create":
					return apiResponse(400, `{"errno":-8}`), nil
				case "/api/filemetas":
					return apiResponse(200, tc.body), nil
				default:
					t.Fatal("unverified directory must not trigger another request")
					return nil, nil
				}
			})
			if err := drive.ensureDirectory(context.Background(), "csrf"); err == nil || calls != 2 {
				t.Fatalf("unverified directory accepted: calls=%d err=%v", calls, err)
			}
		})
	}
}

func TestBaiduAllDirectoryCollisionCodesUseWebMetadata(t *testing.T) {
	for _, status := range []int{200, 400} {
		for _, code := range []int{-8, -30, 31061} {
			t.Run(fmt.Sprintf("%d/%d", status, code), func(t *testing.T) {
				calls := 0
				drive := baiduTestDrive(func(r *http.Request) (*http.Response, error) {
					calls++
					if r.URL.Path == "/api/create" {
						return apiResponse(status, fmt.Sprintf(`{"error_code":"%d"}`, code)), nil
					}
					if r.URL.Host != "pan.baidu.com" || r.URL.Path != "/api/filemetas" {
						t.Fatal("directory lookup left the web session")
					}
					return apiResponse(200, `{"errno":0,"info":[{"path":"/PortShelf","fs_id":12345678901234567,"isdir":1}]}`), nil
				})
				if err := drive.ensureDirectory(context.Background(), "csrf"); err != nil || calls != 2 {
					t.Fatalf("existing directory rejected: calls=%d err=%v", calls, err)
				}
			})
		}
	}
}

func TestBaiduDirectoryWebFailureCannotFallBackOrExposeCredentials(t *testing.T) {
	for _, status := range []int{302, 400, 403, 429, 500} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			calls := 0
			drive := baiduTestDrive(func(r *http.Request) (*http.Response, error) {
				calls++
				if r.URL.Path == "/api/create" {
					return apiResponse(200, `{"errno":-8}`), nil
				}
				if r.URL.Path != "/api/filemetas" || calls > 2 {
					t.Fatal("failed lookup fell back to a different endpoint")
				}
				response := apiResponse(status, `{"errno":0,"info":[{"path":"/PortShelf","fs_id":1,"isdir":1}],"error_msg":"private-stoken privateCSRF"}`)
				response.Header.Set("Location", "https://pcs.baidu.com/rest/2.0/pcs/file")
				return response, nil
			})
			err := drive.ensureDirectory(context.Background(), "privateCSRF")
			if err == nil || calls != 2 || !strings.Contains(err.Error(), "核对百度上传目录") || strings.Contains(err.Error(), "private") {
				t.Fatalf("unsafe directory failure: calls=%d err=%v", calls, err)
			}
		})
	}
}
