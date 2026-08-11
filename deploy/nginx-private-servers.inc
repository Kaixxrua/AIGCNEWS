# 私有 nginx server 块（不随开源仓库发布）
# 经 compose overlay bind-mount 到 /etc/nginx/conf.d/private-servers.inc，
# 在 http 上下文被 conf.d/default.conf 末尾 include。

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
