// 客户端 IP 信任链，镜像 backend/app/core/client_ip.py：
// X-Forwarded-For 可伪造，仅当直连对端命中可信代理列表（IP/CIDR）时
// 才采信其首跳，否则一律以直连对端为准。
package ratelimit

import (
	"log/slog"
	"net"
	"net/http"
	"net/netip"
	"strings"
)

// parseTrustedProxies 镜像 _parse_trusted_proxy_networks：逗号分隔，
// 逐项解析为单地址前缀（netip.ParseAddr → /32 或 /128）或 CIDR
// （netip.ParsePrefix 后 Masked 归一），非法项告警跳过。
func parseTrustedProxies(raw string) []netip.Prefix {
	var prefixes []netip.Prefix
	for _, item := range strings.Split(raw, ",") {
		entry := strings.TrimSpace(item)
		if entry == "" {
			continue
		}
		if addr, err := netip.ParseAddr(entry); err == nil {
			prefixes = append(prefixes, netip.PrefixFrom(addr, addr.BitLen()))
			continue
		}
		if prefix, err := netip.ParsePrefix(entry); err == nil {
			prefixes = append(prefixes, prefix.Masked())
			continue
		}
		slog.Warn("[ClientIP] 忽略非法的可信代理配置项", "entry", entry)
	}
	return prefixes
}

// ClientIP 镜像 client_ip_from_request：可信代理转发时取 XFF 首跳，
// 否则取直连对端；对端为空回退 "unknown"。
func ClientIP(r *http.Request, trusted []netip.Prefix) string {
	peer := r.RemoteAddr
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		peer = host
	}
	// 不可解析的对端一律不可信（对齐 is_trusted_proxy 的 ValueError 分支）。
	if addr, err := netip.ParseAddr(strings.TrimSpace(peer)); err == nil {
		for _, prefix := range trusted {
			if !prefix.Contains(addr) {
				continue
			}
			if forwardedFor := r.Header.Get("X-Forwarded-For"); forwardedFor != "" {
				if firstHop := strings.TrimSpace(strings.Split(forwardedFor, ",")[0]); firstHop != "" {
					return firstHop
				}
			}
			break
		}
	}
	if peer == "" {
		return "unknown"
	}
	return peer
}
