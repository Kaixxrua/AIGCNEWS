package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
)

func baiduRequestStage(endpoint string) string {
	switch endpoint {
	case "/api/gettemplatevariable":
		return "验证百度登录"
	case "/api/create":
		return "创建百度文件或目录"
	case "/api/filemetas":
		return "核对百度上传目录"
	case "/api/precreate":
		return "准备百度上传"
	case "/rest/2.0/pcs/superfile2":
		return "上传百度文件分片"
	case "/share/pset":
		return "创建百度分享链接"
	default:
		return "百度网盘请求"
	}
}

func baiduHTTPError(status int) error {
	var message string
	switch {
	case status >= 300 && status < 400:
		message = "百度网盘要求跳转，请更新 Cookie 后重试"
	case status == 401 || status == 403:
		message = "百度网盘拒绝访问，请更新 Cookie 或在网页检查账号状态"
	case status == 429:
		message = "百度网盘请求过于频繁，请稍后重试"
	case status >= 400 && status < 500:
		message = "百度网盘拒绝本次请求，未返回可识别的错误码"
	default:
		message = "百度网盘服务暂不可用"
	}
	return fmt.Errorf("%s（HTTP %d）", message, status)
}

func baiduResponse(ctx context.Context, response *http.Response, sharing bool, output any) error {
	status := response.StatusCode
	if status >= 300 && status < 400 {
		return baiduHTTPError(status)
	}
	httpFailed := status < 200 || status >= 300
	data, err := io.ReadAll(io.LimitReader(response.Body, baiduResponseLimit+1))
	if ctx.Err() != nil {
		return ctx.Err()
	}
	// HTTP 4xx can carry a useful business error (including "directory exists").
	// Keep only numeric error codes; bodies can echo Cookies, tokens or paths.
	var codes struct {
		Errno     json.Number `json:"errno"`
		ErrorCode json.Number `json:"error_code"`
	}
	validBody := err == nil && len(data) <= baiduResponseLimit
	var decodeErr error
	if validBody {
		decodeErr = json.Unmarshal(data, &codes)
	}
	if validBody && decodeErr == nil {
		for _, value := range []json.Number{codes.Errno, codes.ErrorCode} {
			if value == "" {
				continue
			}
			code, parseErr := value.Int64()
			if parseErr != nil || code < -1_000_000 || code > 1_000_000 {
				decodeErr = errors.New("invalid error code")
				break
			}
			if code != 0 {
				remote := &baiduAPIError{Code: int(code), Sharing: sharing}
				if httpFailed {
					return fmt.Errorf("%w（HTTP %d）", remote, status)
				}
				return remote
			}
		}
	}
	if httpFailed {
		return baiduHTTPError(status)
	}
	if err != nil {
		return errors.New("读取百度网盘响应失败")
	}
	if len(data) > baiduResponseLimit {
		return errors.New("百度网盘响应过大")
	}
	if decodeErr != nil || json.Unmarshal(data, output) != nil {
		return errors.New("百度网盘响应格式无效")
	}
	return nil
}
