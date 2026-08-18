# AIGC Radar MCP Go 镜像：构建期拉取依赖、产出静态二进制。
# 构建上下文为仓库根（docker compose 的 mcp-api-go 服务即如此声明）。

FROM golang:1.26-alpine AS build
WORKDIR /src
# 先拷清单再拷源码：依赖层缓存命中后源码变更不重拉模块。
COPY mcp-go/go.mod mcp-go/go.sum ./
# 构建机若在无法直连 proxy.golang.org 的网络，经 build-arg 换镜像源：
#   docker build --build-arg GOPROXY=https://goproxy.cn,direct ...
ARG GOPROXY=https://proxy.golang.org,direct
RUN go mod download
COPY mcp-go/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" \
      -o /out/mcp-server ./cmd/mcp-server

FROM alpine:3.20
# Phase 2 的 embedding/rerank/GitHub fallback 都走 HTTPS；运行镜像预装根证书。
RUN apk add --no-cache ca-certificates && adduser -D -u 1000 appuser
COPY --from=build /out/mcp-server /usr/local/bin/mcp-server
USER 1000
EXPOSE 8000
# 就绪探针与 Python mcp-api 同口径（/api/ready，未就绪 503）。
HEALTHCHECK --interval=10s --timeout=7s --retries=18 --start-period=30s \
  CMD wget -q -T 5 -O /dev/null http://127.0.0.1:8000/api/ready || exit 1
ENTRYPOINT ["/usr/local/bin/mcp-server"]
