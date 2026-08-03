# 阶段一：使用 Node.js 编译 Vue 代码
FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install --registry=https://registry.npmmirror.com
COPY . .
RUN npm run build

# 阶段二：使用轻量级 Nginx 提供网页访问服务（含 HTTPS）
FROM nginx:alpine
# 覆盖默认 Nginx 配置（HTTP 重定向 + HTTPS + Vue Router History 模式）
COPY nginx.conf /etc/nginx/conf.d/default.conf
# 把编译好的 dist 文件夹放进 Nginx
COPY --from=builder /app/dist /usr/share/nginx/html
# SSL 证书目录；证书与私钥不入镜像（ssl/ 已被 gitignore，干净检出中不存在）。
# 运行时通过卷挂载提供：docker/docker-compose.yml 挂载 ../frontend/ssl → /etc/nginx/ssl:ro
RUN mkdir -p /etc/nginx/ssl
EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]
