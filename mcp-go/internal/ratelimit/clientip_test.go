package ratelimit

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestParseTrustedProxies(t *testing.T) {
	prefixes := parseTrustedProxies("127.0.0.1, ::1 ,172.16.0.0/12,bogus,")
	if len(prefixes) != 3 {
		t.Fatalf("parsed %d prefixes, want 3 (bogus/空项跳过)", len(prefixes))
	}
	// 单地址 → 全位前缀。
	if prefixes[0].String() != "127.0.0.1/32" {
		t.Fatalf("prefixes[0] = %s, want 127.0.0.1/32", prefixes[0])
	}
	if prefixes[1].String() != "::1/128" {
		t.Fatalf("prefixes[1] = %s, want ::1/128", prefixes[1])
	}
	// CIDR Masked 归一。
	if prefixes[2].String() != "172.16.0.0/12" {
		t.Fatalf("prefixes[2] = %s, want 172.16.0.0/12", prefixes[2])
	}
}

func TestClientIP(t *testing.T) {
	trusted := parseTrustedProxies("127.0.0.1,::1,172.16.0.0/12")
	cases := []struct {
		name       string
		remoteAddr string
		xff        string
		want       string
	}{
		{"可信回环取XFF首跳", "127.0.0.1:9000", "203.0.113.9, 10.0.0.1", "203.0.113.9"},
		{"可信CIDR取XFF首跳", "172.16.3.4:9000", "198.51.100.2", "198.51.100.2"},
		{"可信IPv6回环取XFF首跳", "[::1]:9000", "203.0.113.10", "203.0.113.10"},
		{"可信但XFF首跳空白用对端", "127.0.0.1:9000", "  ", "127.0.0.1"},
		{"不可信对端忽略XFF", "203.0.113.7:9000", "1.2.3.4", "203.0.113.7"},
		{"无XFF用对端", "203.0.113.7:9000", "", "203.0.113.7"},
		{"不可解析对端一律不可信", "not-an-ip", "1.2.3.4", "not-an-ip"},
		{"无端口对端原样使用", "203.0.113.7", "", "203.0.113.7"},
		{"空对端回退unknown", "", "", "unknown"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest(http.MethodPost, "/api/mcp", nil)
			r.RemoteAddr = tc.remoteAddr
			if tc.xff != "" {
				r.Header.Set("X-Forwarded-For", tc.xff)
			}
			if got := ClientIP(r, trusted); got != tc.want {
				t.Fatalf("ClientIP(%q, xff=%q) = %q, want %q", tc.remoteAddr, tc.xff, got, tc.want)
			}
		})
	}
}
