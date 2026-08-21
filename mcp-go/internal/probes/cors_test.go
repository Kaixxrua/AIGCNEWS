package probes

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

const testAllowedOrigin = "https://aigcnews.cn"

func corsMux(next http.Handler) http.Handler {
	return NewMuxWithCORS("1.2.0", readyTrue, CORSConfig{
		AllowedOrigins: []string{testAllowedOrigin},
	}, next)
}

func corsRequest(t *testing.T, mux http.Handler, method, path string, headers map[string]string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, path, nil)
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	return rec
}

func TestCORSAllowedPreflight(t *testing.T) {
	called := false
	mux := corsMux(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true }))
	rec := corsRequest(t, mux, http.MethodOptions, "/api/mcp", map[string]string{
		"Origin":                        testAllowedOrigin,
		"Access-Control-Request-Method": "POST",
	})
	if rec.Code != http.StatusOK || rec.Body.String() != "OK" {
		t.Fatalf("exchange = %d %q", rec.Code, rec.Body.String())
	}
	if called {
		t.Fatal("preflight reached downstream handler")
	}
	want := map[string]string{
		"Access-Control-Allow-Methods": corsAllowMethods,
		"Access-Control-Allow-Origin":  testAllowedOrigin,
		"Access-Control-Max-Age":       corsMaxAge,
		"Content-Length":               "2",
		"Content-Type":                 "text/plain; charset=utf-8",
		"Vary":                         "Origin",
	}
	assertHeaders(t, rec, want)
}

func TestCORSDisallowedPreflight(t *testing.T) {
	called := false
	mux := corsMux(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true }))
	rec := corsRequest(t, mux, http.MethodOptions, "/api/mcp", map[string]string{
		"Origin":                        "https://evil.example",
		"Access-Control-Request-Method": "POST",
	})
	if rec.Code != http.StatusBadRequest || rec.Body.String() != "Disallowed CORS origin" {
		t.Fatalf("exchange = %d %q", rec.Code, rec.Body.String())
	}
	if called {
		t.Fatal("disallowed preflight reached downstream handler")
	}
	assertHeaders(t, rec, map[string]string{
		"Access-Control-Allow-Methods": corsAllowMethods,
		"Access-Control-Max-Age":       corsMaxAge,
		"Content-Length":               "22",
		"Content-Type":                 "text/plain; charset=utf-8",
		"Vary":                         "Origin",
	})
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Fatalf("disallowed allow-origin = %q", got)
	}
}

func TestCORSSuccessfulPreflightMirrorsHeaders(t *testing.T) {
	mux := corsMux(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	rec := corsRequest(t, mux, http.MethodOptions, "/api/mcp", map[string]string{
		"Origin":                         testAllowedOrigin,
		"Access-Control-Request-Method":  "POST",
		"Access-Control-Request-Headers": "Authorization, X-Trace",
	})
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if got := rec.Header().Get("Access-Control-Allow-Headers"); got != "Authorization, X-Trace" {
		t.Fatalf("allow-headers = %q", got)
	}
}

func TestCORSPrivateNetworkPreflightRejected(t *testing.T) {
	mux := corsMux(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	rec := corsRequest(t, mux, http.MethodOptions, "/api/mcp", map[string]string{
		"Origin":                                 testAllowedOrigin,
		"Access-Control-Request-Method":          "POST",
		"Access-Control-Request-Private-Network": "true",
	})
	if rec.Code != http.StatusBadRequest || rec.Body.String() != "Disallowed CORS private-network" {
		t.Fatalf("exchange = %d %q", rec.Code, rec.Body.String())
	}
}

func TestCORSAllowedPostPreservesDownstreamResponse(t *testing.T) {
	body := `{"ok":true}`
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Content-Length", "11")
		w.Header().Set("MCP-Protocol-Version", "2025-06-18")
		w.Header().Set("Mcp-Session-Id", "session")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(body))
	})
	rec := corsRequest(t, corsMux(next), http.MethodPost, "/api/mcp", map[string]string{"Origin": testAllowedOrigin})
	if rec.Code != http.StatusOK || rec.Body.String() != body {
		t.Fatalf("exchange = %d %q", rec.Code, rec.Body.String())
	}
	assertHeaders(t, rec, map[string]string{
		"Access-Control-Allow-Origin":   testAllowedOrigin,
		"Access-Control-Expose-Headers": corsExpose,
		"Content-Length":                "11",
		"Content-Type":                  "application/json",
		"MCP-Protocol-Version":          "2025-06-18",
		"Mcp-Session-Id":                "session",
		"Vary":                          "Origin",
	})
}

func TestCORSDisallowedSimpleRequestExposesWithoutAllowing(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) })
	rec := corsRequest(t, corsMux(next), http.MethodPost, "/api/mcp", map[string]string{"Origin": "https://evil.example"})
	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204", rec.Code)
	}
	if got := rec.Header().Get("Access-Control-Expose-Headers"); got != corsExpose {
		t.Fatalf("expose-headers = %q", got)
	}
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Fatalf("allow-origin = %q", got)
	}
	if got := rec.Header().Get("Vary"); got != "" {
		t.Fatalf("vary = %q", got)
	}
}

func TestCORSNonPreflightOptionsDelegates(t *testing.T) {
	rec := corsRequest(t, corsMux(nil), http.MethodOptions, "/api/mcp", map[string]string{"Origin": testAllowedOrigin})
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404 for an unmounted MCP route", rec.Code)
	}
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != testAllowedOrigin {
		t.Fatalf("allow-origin = %q", got)
	}
}

func TestCORSVaryMerges(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Vary", "Accept-Encoding")
		w.WriteHeader(http.StatusOK)
	})
	rec := corsRequest(t, corsMux(next), http.MethodPost, "/api/mcp", map[string]string{"Origin": testAllowedOrigin})
	if got := rec.Header().Get("Vary"); got != "Accept-Encoding, Origin" {
		t.Fatalf("vary = %q", got)
	}
}

func assertHeaders(t *testing.T, rec *httptest.ResponseRecorder, want map[string]string) {
	t.Helper()
	for key, value := range want {
		if got := rec.Header().Get(key); got != value {
			t.Errorf("%s = %q, want %q", key, got, value)
		}
	}
}
