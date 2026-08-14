# 私有 nginx server 块（不随开源仓库发布）
# 经 compose overlay bind-mount 到 /etc/nginx/conf.d/private-servers.inc，
# 在 http 上下文被 conf.d/default.conf 末尾 include。

# AIGC Radar MCP 独立域名（aigcradar.online）：MCP 网关专用 vhost。
# 公网链路：Cloudflare（橙云，边缘终止 TLS）→ 本机 cloudflared 隧道 →
# 本 server（:80）→ 独立 MCP 容器 aigc-mcp:8000（与主站后端进程解耦，
# 主站迭代不中断 MCP 会话）。只暴露 /api/mcp 与探活/版本，其余一律 404。
# 旧域名 aigcnews.cn/api/mcp 不受影响（仍由主后端服务，双跑灰度）。
server {
    listen 80;
    server_name aigcradar.online;

    # 与主 server 同口径：cloudflared 回源对端是宿主机 WireGuard 地址，
    # 边缘注入的 XFF 只含 CF 节点 IP，真实客户端 IP 仅在 CF-Connecting-IP
    set_real_ip_from 10.20.0.1;
    real_ip_header CF-Connecting-IP;

    # JSON-RPC 请求体很小，收紧上传上限
    client_max_body_size 1m;
    limit_req_status 429;

    # 变量化上游：配合 http 级 resolver 动态解析 aigc-mcp 容器 IP
    # （容器重建换 IP 后字面 proxy_pass 会 502，2026-08-08 教训）
    set $mcp_upstream http://aigc-mcp:8000;

    location = /api/mcp {
        limit_req zone=api_general burst=50 nodelay;

        proxy_pass $mcp_upstream$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # 边缘 XFF 链不含真实客户端，以还原后的地址为准（MCP 限流按首跳取值）
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        # MCP 会话长响应：禁用缓冲，保持连接语义
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        chunked_transfer_encoding on;
    }

    # 探活与版本（公网可观测面；ready 失败时对外仅 not_ready，明细在日志）
    location ~ ^/api/(live|ready|version)$ {
        proxy_pass $mcp_upstream$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }

    # 其余一律 404：MCP 网关不承载站点页面与其他 API
    location / {
        return 404;
    }
}

# sub2api HTTP → HTTPS 重定向
server {
    listen 80;
    server_name sub2api.aigcnews.cn;
    return 301 https://$host$request_uri;
}

# PriceAI 由腾讯 VPS Caddy 终止公网 TLS，再通过 WireGuard 回源。
server {
    listen 80;
    server_name price.gptsakura.com;

    location / {
        # 变量化上游：配合 http 级 resolver 动态解析 priceai 容器 IP
        set $priceai_upstream http://priceai:3000;
        proxy_pass $priceai_upstream$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}

# sub2api HTTPS 反向代理（供本机调用，避免经 Cloudflare Tunnel 公网回环）
server {
    listen 443 ssl;
    server_name sub2api.aigcnews.cn;

    ssl_certificate     /etc/nginx/ssl/sub2api.aigcnews.cn_bundle.crt;
    ssl_certificate_key /etc/nginx/ssl/sub2api.aigcnews.cn.key;

    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    client_max_body_size 0;
    client_body_timeout 600s;

    location / {
        proxy_pass http://10.20.0.2:18080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        chunked_transfer_encoding on;
    }
}
