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
# 将 SSL 证书复制进镜像
COPY ssl/aigcnews.cn_bundle.crt /etc/nginx/ssl/aigcnews.cn_bundle.crt
COPY ssl/aigcnews.cn.key        /etc/nginx/ssl/aigcnews.cn.key
COPY ssl/sub2api.aigcnews.cn_bundle.crt /etc/nginx/ssl/sub2api.aigcnews.cn_bundle.crt
COPY ssl/sub2api.aigcnews.cn.key        /etc/nginx/ssl/sub2api.aigcnews.cn.key
EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]
