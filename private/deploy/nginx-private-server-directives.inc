# 主 server 内私有指令（不随开源仓库发布）
# 经 compose overlay bind-mount 到 /etc/nginx/conf.d/private-server-directives.inc，
# 在 aigcnews.cn 主 server 块内被 include。

# ── 真实客户端 IP 还原 ──────────────────────────────────────────
# 2026-08-14 修正：CF 已于 08-13 彻底退役，回源实为两台 VPS Caddy 经 SSH
# 反向隧道（VPS 127.0.0.1:18443/18080 → 家 443/80）。隧道对端经 docker-proxy
# 到达本容器，peer = 编排网关 172.19.0.1（或 127.0.0.1）；真实客户端 IP 由
# 边缘 Caddy 追加在 X-Forwarded-For 尾跳，recursive off 只取尾跳，公网伪造的
# XFF 首跳不会被采信。旧口径（10.20.0.1 + CF-Connecting-IP）自 CF 退役后
# 不再命中，$remote_addr 恒为网关，全站按 IP 的限流/锁定退化为共享桶。
# 直连（LAN hairpin）流量不携带 XFF、peer 不在白名单，不受影响。
set_real_ip_from 127.0.0.1;
set_real_ip_from 172.19.0.1;
real_ip_header X-Forwarded-For;
real_ip_recursive off;
