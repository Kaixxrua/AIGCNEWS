# 阶段一：使用 Node.js 编译 Vue 代码
FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install --registry=https://registry.npmmirror.com
COPY . .
# 注意：确保你的前端 .env.production 里 VITE_API_BASE_URL=http://118.89.101.11:8000
RUN npm run build

# 阶段二：使用轻量级 Nginx 提供网页访问服务
FROM nginx:alpine
# 把编译好的 dist 文件夹放进 Nginx
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
