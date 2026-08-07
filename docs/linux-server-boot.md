# Linux 服务器开机启动

主项目由 Docker Compose project `docker` 管理。Docker restart policy 负责容器进程恢复，systemd unit 在服务器启动时执行一次全栈协调并等待健康检查通过。

## 手工恢复 Milvus

不得使用 `docker compose down -v`，也不得删除 `docker/volumes/{etcd,minio,milvus}`。依赖异常时按顺序恢复：

```bash
docker start milvus-etcd
# 等待 docker inspect 显示 healthy
docker start milvus-minio
# 等待 docker inspect 显示 healthy
docker start milvus-standalone
docker exec milvus-standalone curl -f http://127.0.0.1:9091/healthz
```

验证后端实际连接：

```bash
docker exec aigc-backend python -c \
  "from backend.app.monitoring.health import _check_milvus; print(_check_milvus())"
```

结果应为 `status: ok`，并包含 collection 数量。

## 验证并启动全栈

PriceAI 的现有环境文件 `/home/kaixxrua/.priceai-node.env` 必须提供：

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

不要在日志或终端输出变量值。

管理脚本会按 dotenv 语义读取项目 `.env` 和 `/home/kaixxrua/.priceai-node.env`，无需用 shell `source`（配置中可能包含空格或 cron 表达式）。

```bash
scripts/manage_main_stack.sh config
scripts/manage_main_stack.sh up
scripts/manage_main_stack.sh status
```

`up` 不构建镜像、不拉取镜像，并最多等待 300 秒。发布新镜像或重建应用应走独立部署流程。

## 安装 systemd unit

```bash
sudo install -m 0644 \
  deploy/systemd/aigcnews-compose@.service \
  /etc/systemd/system/aigcnews-compose@.service
sudo systemctl daemon-reload
sudo systemctl enable --now aigcnews-compose@kaixxrua.service
```

查看状态和日志：

```bash
systemctl status aigcnews-compose@kaixxrua.service
journalctl -u aigcnews-compose@kaixxrua.service
scripts/manage_main_stack.sh status
```

unit 以实例用户运行 Compose，不使用 root 创建容器或持久化文件。unit 没有 `ExecStop`：服务器关机时不拆除 Compose project，下一次开机由 Docker restart policy 和 systemd 共同恢复。

## 容器最小权限边界

- `backend-api` 以镜像内非 root 用户 `app`（uid/gid 1000，与实例用户一致）运行，并启用 `no-new-privileges` 与 `cap_drop: ALL`；HuggingFace 缓存挂载点为镜像声明的 `HF_HOME=/hf-cache`（宿主目录仍是 `storage/hf_cache/huggingface`）。
- 首次以非 root 镜像重建后端前，若宿主存储目录留有 root 属主文件（历史容器以 root 写入，如 `storage/papers`、`storage/hf_cache`），先执行一次性属主修复：`sudo chown -R 1000:1000 storage/papers storage/hf_cache`，否则应用无法覆写旧文件。
- `frontend-web` 的 nginx master 保留 root 启动（绑定 80/443、读取宿主证书），但只授予 root-master nginx 的最小 capability 集：`NET_BIND_SERVICE`（绑定端口）、`SETUID`/`SETGID`（派生 nginx worker）、`CHOWN`（把 tmpfs 上的临时目录 chown 给 worker）；容器根文件系统只读，可写路径仅 `/var/cache/nginx`、`/var/run` 两个 tmpfs，CHOWN 的作用域因此仅限于这两个 tmpfs。
- 后端与前端镜像均内置 `HEALTHCHECK`；Compose 中的 healthcheck 定义与镜像行为一致并优先生效。

## 健康验证

```bash
docker exec milvus-standalone curl -f http://127.0.0.1:9091/healthz
curl --fail http://127.0.0.1:8000/api/live
curl --fail http://127.0.0.1:8000/api/ready
docker compose --project-name docker --file docker/docker-compose.yml ps
```

`/api/ready` 验证后端项目目录依赖；Milvus 必须同时使用 `/healthz` 和后端内 collection 探测验证。

## 端口与证书边界

- Milvus、MinIO、Attu、Neo4j、Redis 只在编排网络内 `expose`，不向宿主机发布端口；`priceai` 同样仅 `expose`，由前端 nginx 反代。宿主机只发布 `127.0.0.1:8000`（后端，仅回环）、`80/443`（前端 nginx）。
- 后端经编排网络按服务名访问依赖（`MILVUS_HOST=milvus`、`NEO4J_URI=bolt://neo4j:7687`、`REDIS_HOST=redis` 等，见 `.env`）。宿主机侧临时调试用 `docker exec <container> ...` 或 `docker compose ... port-forward` 式临时映射，不把管理端口长期发布到宿主机。
- 前端镜像不包含 SSL 证书；`frontend-web` 以只读卷挂载 `frontend/ssl` 到 `/etc/nginx/ssl`。重建前端容器前确认该目录存在且包含 nginx.conf 引用的四个证书/私钥文件（该目录被 gitignore，不进仓库、不进镜像）。
- **私钥属主约定**：`frontend/ssl/*.key` 必须为 `root:root`（权限 600）。加固后的 `frontend-web` `cap_drop: ALL`，容器内 nginx master 以 uid 0 运行但没有 `CAP_DAC_OVERRIDE`，读不动 `kaixxrua:kaixxrua 600` 的私钥（2026-08-03 曾因此 crash loop）。证书续期/替换后务必 `chown root:root *.key`。
- **TLS 分层**：公网边缘证书由 Cloudflare 托管并自动续期，与本目录无关；源站（本 nginx 443）使用 Cloudflare Origin Certificate——一张通配证书覆盖 `aigcnews.cn` 与 `*.aigcnews.cn`（含 sub2api vhost），2026-08-07 签发、**2041-08-03 到期**，期间无需续期。注意 Origin CA 只被 Cloudflare 信任、不是公开 CA：任何非 Cloudflare 的回源客户端直连 443 都必须跳过校验——VPS Caddy 的 `aigcnews.cn` @api transport 已配 `tls_insecure_skip_verify`（2026-08-07 从 TrustAsia 公开证书切到 Origin 证书时曾因 Caddy 校验失败导致公网 `/api` 502；VPS 侧改动前有备份 `/etc/caddy/Caddyfile.bak-20260807-api-fix`）。
- **证书替换流程**：Cloudflare 控制台 SSL/TLS → Origin Server → Create Certificate（RSA 2048，主机名 `aigcnews.cn` + `*.aigcnews.cn`）→ `openssl x509 -pubkey` 与 `pkey -pubout` 校验配对 → 旧证书备份到 `frontend/ssl/backup-<ts>/` → 替换四个文件（`.key` 保持 `root:root` 600）→ `docker exec aigc-frontend nginx -t` → `nginx -s reload` → 验证本地 443 SNI 两个域名 + 公网 `/api/live`。
- **响应头与限流分层**：HTML 页面（`aigcnews.cn/` 静态资源）由远程 Caddy VPS 发布层负责，其安全响应头在 Caddy 侧配置；本 nginx 负责 `/api/*` 流量——安全响应头、`limit_req` 限流（认证 10 次/分、一般 20 次/秒）、`client_max_body_size 60m`、真实客户端 IP 还原。验证响应头时用 `/api/live` 等 API 路径，不要用首页（首页不经过本 nginx）。
- **真实 IP 还原**：cloudflared 以宿主机 WireGuard 地址（`10.20.0.1`）回源，主 server 用 `set_real_ip_from 10.20.0.1` + `real_ip_header CF-Connecting-IP` 还原真实客户端；转发给后端的 `X-Forwarded-For` 以还原值为准（后端限流按首跳取值）。若 cloudflared 部署形态变化（容器化或更换回源地址），必须同步该白名单，否则限流退化为全局限流。

## 故障处理约束

- 不要执行 `docker compose down --volumes` 或删除 bind mount 数据目录。
- 不要修改 Compose project name；否则可能创建第二套容器和网络。
- etcd 或 MinIO 不健康时不要反复启动 Milvus，先检查对应容器日志和宿主机磁盘延迟。
- systemd 启动失败时先运行 `scripts/manage_main_stack.sh config`，再检查 `journalctl` 和 `docker compose ... logs <service>`。
- 真正重启服务器应安排维护窗口；安装 unit 后可先用 `systemctl restart aigcnews-compose@kaixxrua.service` 验证协调流程。
