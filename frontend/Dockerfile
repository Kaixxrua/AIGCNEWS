# 阶段一：使用 Node.js 编译 Vue 代码
# 基础镜像按 digest 锁定（更新方式：docker pull <tag> 后
# docker inspect --format '{{index .RepoDigests 0}}' 取新值替换）。
FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS builder
WORKDIR /app
COPY frontend/package*.json ./
# npm ci 严格按 package-lock.json 复现安装
RUN npm ci --registry=https://registry.npmmirror.com
COPY frontend/ ./
# UI catalog 是前端与 Go MCP 的共享发布输入。构建上下文必须是仓库根，
# CI 会先把受控夹具复制到该路径，生产构建则使用完整发布目录。
COPY mcp-go/internal/uicatalog/data /mcp-go/internal/uicatalog/data
RUN npm run build

# 阶段二：使用轻量级 Nginx 提供网页访问服务（含 HTTPS）
FROM nginx:alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752
# 覆盖默认 Nginx 配置（HTTP 重定向 + HTTPS + Vue Router History 模式）
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
# 私有 server 块/主 server 私有指令的空占位文件：default.conf 会 include
# 这两个路径，缺失会导致 nginx 启动失败；私有部署经 compose overlay
# bind-mount 真实文件覆盖（见 docker/docker-compose.yml 头部注释）。
COPY frontend/nginx-private-servers.inc /etc/nginx/conf.d/private-servers.inc
COPY frontend/nginx-private-server-directives.inc /etc/nginx/conf.d/private-server-directives.inc
# 把编译好的 dist 文件夹放进 Nginx
COPY --from=builder /app/dist /usr/share/nginx/html
# SSL 证书目录；证书与私钥不入镜像（ssl/ 已被 gitignore，干净检出中不存在）。
# 运行时通过卷挂载提供：docker/docker-compose.yml 挂载 ../frontend/ssl → /etc/nginx/ssl:ro
RUN mkdir -p /etc/nginx/ssl
EXPOSE 80 443
# 镜像级健康检查：TCP 探测 HTTP/HTTPS 监听（nginx:alpine 自带 busybox nc）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["sh", "-c", "nc -z 127.0.0.1 80 && nc -z 127.0.0.1 443"]
CMD ["nginx", "-g", "daemon off;"]
