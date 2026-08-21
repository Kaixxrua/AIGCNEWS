package probes

import (
	"net/http"
	"strconv"
	"strings"
)

const (
	corsAllowMethods = "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT"
	corsMaxAge       = "600"
	corsExpose       = "Mcp-Session-Id, MCP-Protocol-Version"
)

// CORSConfig is the HTTP CORS policy for the public API.
type CORSConfig struct {
	AllowedOrigins []string
}

// WithCORS wraps a handler with the same explicit-origin, no-credentials
// policy as the Python CORSMiddleware configuration.
func WithCORS(next http.Handler, cfg CORSConfig) http.Handler {
	allowed := make(map[string]struct{}, len(cfg.AllowedOrigins))
	for _, origin := range cfg.AllowedOrigins {
		if origin != "" {
			allowed[origin] = struct{}{}
		}
	}
	return corsHandler{next: next, allowedOrigins: allowed}
}

type corsHandler struct {
	next           http.Handler
	allowedOrigins map[string]struct{}
}

type corsResponseWriter struct {
	http.ResponseWriter
	origin      string
	allowed     bool
	wroteHeader bool
}

func (w *corsResponseWriter) WriteHeader(status int) {
	if w.wroteHeader {
		return
	}
	w.wroteHeader = true
	w.Header().Set("Access-Control-Expose-Headers", corsExpose)
	if w.allowed {
		w.Header().Set("Access-Control-Allow-Origin", w.origin)
		addVaryOrigin(w.Header())
	}
	w.ResponseWriter.WriteHeader(status)
}

func (w *corsResponseWriter) Write(body []byte) (int, error) {
	if !w.wroteHeader {
		w.WriteHeader(http.StatusOK)
	}
	return w.ResponseWriter.Write(body)
}

func (h corsHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	origin := r.Header.Get("Origin")
	if origin == "" {
		h.next.ServeHTTP(w, r)
		return
	}

	if r.Method == http.MethodOptions && r.Header.Get("Access-Control-Request-Method") != "" {
		h.servePreflight(w, r, origin)
		return
	}

	h.next.ServeHTTP(&corsResponseWriter{
		ResponseWriter: w,
		origin:         origin,
		allowed:        h.isAllowed(origin),
	}, r)
}

func (h corsHandler) servePreflight(w http.ResponseWriter, r *http.Request, origin string) {
	w.Header().Set("Access-Control-Allow-Methods", corsAllowMethods)
	w.Header().Set("Access-Control-Max-Age", corsMaxAge)
	addVaryOrigin(w.Header())

	failures := make([]string, 0, 3)
	if !h.isAllowed(origin) {
		failures = append(failures, "origin")
	}
	if !containsMethod(corsAllowMethods, r.Header.Get("Access-Control-Request-Method")) {
		failures = append(failures, "method")
	}
	if requestedHeaders := r.Header.Get("Access-Control-Request-Headers"); requestedHeaders != "" {
		// Python allow_headers=["*"] mirrors the raw requested value.
		w.Header().Set("Access-Control-Allow-Headers", requestedHeaders)
	}
	if r.Header.Get("Access-Control-Request-Private-Network") != "" {
		failures = append(failures, "private-network")
	}

	if len(failures) > 0 {
		writePlainText(w, http.StatusBadRequest, "Disallowed CORS "+strings.Join(failures, ", "))
		return
	}
	w.Header().Set("Access-Control-Allow-Origin", origin)
	writePlainText(w, http.StatusOK, "OK")
}

func (h corsHandler) isAllowed(origin string) bool {
	_, ok := h.allowedOrigins[origin]
	return ok
}

func containsMethod(methods, requested string) bool {
	for _, method := range strings.Split(methods, ", ") {
		if method == requested {
			return true
		}
	}
	return false
}

func addVaryOrigin(header http.Header) {
	values := header.Values("Vary")
	for _, value := range values {
		for _, item := range strings.Split(value, ",") {
			if strings.EqualFold(strings.TrimSpace(item), "Origin") {
				return
			}
		}
	}
	if len(values) == 0 {
		header.Set("Vary", "Origin")
		return
	}
	parts := make([]string, 0, len(values)+1)
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			parts = append(parts, trimmed)
		}
	}
	parts = append(parts, "Origin")
	header.Set("Vary", strings.Join(parts, ", "))
}

func writePlainText(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(status)
	_, _ = w.Write([]byte(body))
}
