// Package wire 实现 MCP HTTP JSON-RPC 的解析、校验和响应投影。
// 业务 dispatch 只消费 ValidatedRequest，不重复解释原始 JSON。
package wire

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"

	"aigcnews/mcp-go/internal/jsonx"
)

const (
	ProtocolVersion = "2025-06-18"
	MaxRequestBytes = 64 * 1024

	ParseError     = -32700
	InvalidRequest = -32600
	MethodNotFound = -32601
	InvalidParams  = -32602
	InternalError  = -32603
)

type RequestError struct {
	RequestID any
	Code      int
	Message   string
}

func (e *RequestError) Error() string { return e.Message }

type ValidatedRequest struct {
	RequestID any
	Method    string
	Params    map[string]any
	HasID     bool
}

// ParseRequest 严格复刻 Python parse_mcp_request；请求体上限按字节而非 rune。
func ParseRequest(r *http.Request) (ValidatedRequest, *RequestError) {
	if value := r.Header.Get("Content-Length"); value != "" {
		n, err := strconv.Atoi(value)
		if err != nil {
			return ValidatedRequest{}, &RequestError{Code: InvalidRequest, Message: "Invalid Content-Length"}
		}
		if n > MaxRequestBytes {
			return ValidatedRequest{}, &RequestError{Code: InvalidRequest, Message: "Request body too large"}
		}
	}
	// 生产 net/http 会把 Content-Length 从 Header 摘到 r.ContentLength；
	// 头检查覆盖 httptest 回放路径，字段检查覆盖真实服务器路径。
	if r.ContentLength > MaxRequestBytes {
		return ValidatedRequest{}, &RequestError{Code: InvalidRequest, Message: "Request body too large"}
	}
	body, err := readBounded(r)
	if err != nil {
		return ValidatedRequest{}, &RequestError{Code: InvalidRequest, Message: err.Error()}
	}
	var payload any
	if err := json.Unmarshal(body, &payload); err != nil {
		return ValidatedRequest{}, &RequestError{Code: ParseError, Message: "Parse error"}
	}
	if list, ok := payload.([]any); ok {
		_ = list
		return ValidatedRequest{}, &RequestError{Code: InvalidRequest, Message: "Batch JSON-RPC requests are not supported"}
	}
	object, ok := payload.(map[string]any)
	if !ok {
		return ValidatedRequest{}, &RequestError{Code: InvalidRequest, Message: "Invalid Request"}
	}
	requestID, hasID := object["id"]
	if hasID && requestID != nil {
		if _, ok := requestID.(string); !ok {
			if _, ok := requestID.(float64); !ok {
				// Python isinstance(True, int) is true; preserve this intentional
				// compatibility quirk for the frozen tools-list-id-bool case.
				if _, ok := requestID.(bool); !ok {
					return ValidatedRequest{}, &RequestError{Code: InvalidRequest, Message: "Invalid request id"}
				}
			}
		}
	}
	if object["jsonrpc"] != "2.0" {
		return ValidatedRequest{}, &RequestError{RequestID: requestID, Code: InvalidRequest, Message: "Invalid JSON-RPC version"}
	}
	method, ok := object["method"].(string)
	if !ok || method == "" {
		return ValidatedRequest{}, &RequestError{RequestID: requestID, Code: InvalidRequest, Message: "Missing method"}
	}
	params := map[string]any{}
	if raw, exists := object["params"]; exists {
		var ok bool
		params, ok = raw.(map[string]any)
		if !ok {
			return ValidatedRequest{}, &RequestError{RequestID: requestID, Code: InvalidParams, Message: "params must be an object"}
		}
	}
	return ValidatedRequest{RequestID: requestID, Method: method, Params: params, HasID: hasID}, nil
}

func readBounded(r *http.Request) ([]byte, error) {
	body, err := io.ReadAll(io.LimitReader(r.Body, MaxRequestBytes+1))
	if err != nil {
		return nil, err
	}
	if len(body) > MaxRequestBytes {
		return nil, fmt.Errorf("Request body too large")
	}
	return body, nil
}

type Response struct {
	Status  int
	Body    []byte
	Headers http.Header
}

func (r Response) Write(w http.ResponseWriter) {
	for key, values := range r.Headers {
		for _, value := range values {
			w.Header().Add(key, value)
		}
	}
	if r.Status == http.StatusNoContent {
		// Starlette 204 不带 Content-Length/Content-Type；显式置 0 会在
		// ResponseRecorder 层留下 corpus 中不存在的头。
		w.WriteHeader(r.Status)
		return
	}
	if r.Body == nil {
		w.Header().Set("Content-Length", "0")
	} else {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Content-Length", strconv.Itoa(len(r.Body)))
	}
	w.WriteHeader(r.Status)
	if r.Body != nil {
		_, _ = w.Write(r.Body)
	}
}

func ProtocolHeaders() http.Header {
	headers := make(http.Header)
	headers.Set("MCP-Protocol-Version", ProtocolVersion)
	return headers
}

func Result(id any, result any) Response {
	return envelope(http.StatusOK, jsonx.Object{
		{Key: "jsonrpc", Value: "2.0"},
		{Key: "id", Value: id},
		{Key: "result", Value: result},
	}, nil)
}

func Error(id any, code int, message string) Response {
	return envelope(http.StatusOK, jsonx.Object{
		{Key: "jsonrpc", Value: "2.0"},
		{Key: "id", Value: id},
		{Key: "error", Value: jsonx.Object{
			{Key: "code", Value: code},
			{Key: "message", Value: message},
		}},
	}, nil)
}

func Notification() Response {
	return Response{Status: http.StatusNoContent, Headers: ProtocolHeaders()}
}

func WithSession(response Response, sessionID string) Response {
	response.Headers.Set("Mcp-Session-Id", sessionID)
	return response
}

func envelope(status int, value any, extra http.Header) Response {
	body, err := jsonx.MarshalCompact(value)
	if err != nil {
		return Response{Status: http.StatusInternalServerError, Body: []byte("Internal Server Error"), Headers: http.Header{"Content-Type": []string{"text/plain; charset=utf-8"}}}
	}
	headers := ProtocolHeaders()
	for key, values := range extra {
		headers[key] = append([]string(nil), values...)
	}
	return Response{Status: status, Body: bytes.Clone(body), Headers: headers}
}
