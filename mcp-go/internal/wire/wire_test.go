package wire

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"testing"

	"aigcnews/mcp-go/internal/jsonx"
)

func request(t *testing.T, body string) *http.Request {
	t.Helper()
	r := httptest.NewRequest(http.MethodPost, "http://example.test/api/mcp", bytes.NewBufferString(body))
	r.Header.Set("Content-Type", "application/json")
	return r
}

func TestParseRequestValidAndDefaults(t *testing.T) {
	got, err := ParseRequest(request(t, `{"jsonrpc":"2.0","id":1,"method":"initialize"}`))
	if err != nil {
		t.Fatalf("ParseRequest error: %+v", err)
	}
	if got.RequestID != float64(1) || got.Method != "initialize" || !got.HasID || len(got.Params) != 0 {
		t.Fatalf("unexpected request: %+v", got)
	}
}

func TestParseRequestErrors(t *testing.T) {
	cases := []struct {
		name string
		body string
		code int
		msg  string
	}{
		{"empty", "", ParseError, "Parse error"},
		{"invalid-json", "{", ParseError, "Parse error"},
		{"batch", "[]", InvalidRequest, "Batch JSON-RPC requests are not supported"},
		{"scalar", "1", InvalidRequest, "Invalid Request"},
		{"missing-version", `{"id":1,"method":"x"}`, InvalidRequest, "Invalid JSON-RPC version"},
		{"missing-method", `{"jsonrpc":"2.0","id":1}`, InvalidRequest, "Missing method"},
		{"method-number", `{"jsonrpc":"2.0","id":1,"method":1}`, InvalidRequest, "Missing method"},
		{"object-id", `{"jsonrpc":"2.0","id":{},"method":"x"}`, InvalidRequest, "Invalid request id"},
		{"params-list", `{"jsonrpc":"2.0","id":1,"method":"x","params":[]}`, InvalidParams, "params must be an object"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := ParseRequest(request(t, tc.body))
			if err == nil || err.Code != tc.code || err.Message != tc.msg {
				t.Fatalf("error = %+v, want code=%d message=%q", err, tc.code, tc.msg)
			}
		})
	}
}

func TestParseRequestContentLengthAndBodyLimit(t *testing.T) {
	r := request(t, `{"jsonrpc":"2.0","id":1,"method":"x"}`)
	r.Header.Set("Content-Length", "not-a-number")
	_, err := ParseRequest(r)
	if err == nil || err.Code != InvalidRequest || err.Message != "Invalid Content-Length" {
		t.Fatalf("invalid content length error = %+v", err)
	}

	r = request(t, `{"jsonrpc":"2.0","id":1,"method":"x"}`)
	r.Header.Set("Content-Length", "65537")
	_, err = ParseRequest(r)
	if err == nil || err.Code != InvalidRequest || err.Message != "Request body too large" {
		t.Fatalf("oversize content length error = %+v", err)
	}

	r = request(t, string(bytes.Repeat([]byte{'x'}, MaxRequestBytes+1)))
	_, err = ParseRequest(r)
	if err == nil || err.Code != InvalidRequest || err.Message != "Request body too large" {
		t.Fatalf("oversize body error = %+v", err)
	}
}

func TestParseRequestPythonBoolIDCompatibility(t *testing.T) {
	got, err := ParseRequest(request(t, `{"jsonrpc":"2.0","id":true,"method":"x"}`))
	if err != nil || got.RequestID != true {
		t.Fatalf("bool id = %+v, error=%v", got, err)
	}
}

func TestResponseProjections(t *testing.T) {
	result := Result("x", map[string]any{"ok": true})
	if result.Status != http.StatusOK || result.Headers.Get("MCP-Protocol-Version") != ProtocolVersion {
		t.Fatalf("result projection = %+v", result)
	}
	if string(result.Body) != `{"jsonrpc":"2.0","id":"x","result":{"ok":true}}` {
		t.Fatalf("result body = %s", result.Body)
	}

	notification := Notification()
	if notification.Status != http.StatusNoContent || notification.Body != nil {
		t.Fatalf("notification = %+v", notification)
	}

	errResponse := Error(nil, MethodNotFound, "Method not found")
	if string(errResponse.Body) != `{"jsonrpc":"2.0","id":null,"error":{"code":-32601,"message":"Method not found"}}` {
		t.Fatalf("error body = %s", errResponse.Body)
	}
}

func TestErrorResponseWithDataAndHeaders(t *testing.T) {
	extra := http.Header{}
	extra.Set("Retry-After", "42")
	response := ErrorResponse(http.StatusTooManyRequests, float64(7), -32000, "limited", jsonx.Object{
		{Key: "scope", Value: "daily"},
		{Key: "retry_after", Value: int64(42)},
	}, extra)
	if response.Status != http.StatusTooManyRequests {
		t.Fatalf("status = %d, want 429", response.Status)
	}
	if got := response.Headers.Get("Retry-After"); got != "42" {
		t.Fatalf("Retry-After = %q, want 42", got)
	}
	if got := response.Headers.Get("MCP-Protocol-Version"); got != ProtocolVersion {
		t.Fatalf("protocol version = %q, want %q", got, ProtocolVersion)
	}
	want := `{"jsonrpc":"2.0","id":7,"error":{"code":-32000,"message":"limited","data":{"scope":"daily","retry_after":42}}}`
	if string(response.Body) != want {
		t.Fatalf("body = %s, want %s", response.Body, want)
	}
}

func TestResponseWriteSetsExactBodyLength(t *testing.T) {
	response := Result(float64(1), map[string]any{"ok": true})
	rr := httptest.NewRecorder()
	response.Write(rr)
	if rr.Code != http.StatusOK || rr.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("response = status=%d headers=%v", rr.Code, rr.Header())
	}
	if rr.Header().Get("Content-Length") != "45" {
		t.Fatalf("content length = %q", rr.Header().Get("Content-Length"))
	}
}
