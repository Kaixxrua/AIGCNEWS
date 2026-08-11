# 主 server 内私有指令（不随开源仓库发布）
# 经 compose overlay bind-mount 到 /etc/nginx/conf.d/private-server-directives.inc，
# 在 aigcnews.cn 主 server 块内被 include。

# ── 真实客户端 IP 还原 ──────────────────────────────────────────
# 公网流量经 Cloudflare Tunnel 回源：cloudflared 以宿主机 WireGuard 地址
# （10.20.0.1）直连本服务，边缘注入的 X-Forwarded-For 只含 CF 边缘节点 IP，
# 真实客户端 IP 仅在 CF-Connecting-IP 中可信。直连（LAN）流量不受影响。
set_real_ip_from 10.20.0.1;
real_ip_header CF-Connecting-IP;
