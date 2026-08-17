# 自托管完整指南

> [English](self-hosting.md) | **简体中文**

在 Linux / WSL2 上运行 AIGCNEWS 的完整安装、运维与验证细节。[README](../README.zh-CN.md) 只保留快速通道，细节都在本文档。

## 前置要求

| 工具 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.12 | 后端运行时（镜像按 digest 锁定 `python:3.12-slim`） |
| Node.js | 22 | 前端构建与测试（与 CI 一致） |
| Docker + Compose | v2 | 基础设施与生产栈编排 |

## 1) 准备环境变量

```bash
cp .env.example .env
```

编辑 `.env` 填写本机参数。**`JWT_SECRET_KEY` 必须设置为强随机值**，缺失、等于示例值或长度不足 32 字符时应用拒绝启动（见 [adr/0001](adr/0001-jwt-secret-rotation-and-startup-guard.md)）：

```bash
openssl rand -hex 32
```

## 2) 安装依赖

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd frontend && npm ci && cd ..
```

`requirements-dev.txt` 在锁定的 `requirements.lock` 之上追加 pytest / pytest-cov / ruff，与 CI 使用同一份依赖基线。

## 3) 准备前端 TLS 证书（自签名即可）

`frontend-web` 的 nginx 以只读卷挂载 `frontend/ssl/`（已 gitignore，干净检出不存在），缺少证书会启动失败。本地部署生成自签名证书即可：

```bash
mkdir -p frontend/ssl
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout frontend/ssl/aigcnews.cn.key \
  -out frontend/ssl/aigcnews.cn_bundle.crt \
  -days 3650 -subj "/CN=aigcnews.cn"
# 加固后的 frontend-web 容器（cap_drop: ALL）要求私钥属主为 root
sudo chown root:root frontend/ssl/*.key && sudo chmod 600 frontend/ssl/*.key
```

## 4) 启动核心栈

```bash
scripts/manage_main_stack.sh up
```

该命令 reconcile 核心 Compose 栈（后端 API、前端、PostgreSQL、Redis、Milvus、MinIO 等）并等待健康检查通过，**干净检出即可运行**。常用子命令：`config`（校验编排，不打印秘密）、`status`、`logs`。

> 私有部署扩展（姊妹服务、外部编排网、私有 nginx server 等）不随仓库发布，以 overlay 形式注入：脚本探测到 `../aigcnews_private/deploy/docker-compose.private.yml`（可用 `AIGCNEWS_PRIVATE_COMPOSE` 覆盖）时自动并入；不存在时核心栈独立可用。机制详见 `docker/docker-compose.yml` 头部注释。

## 5) 本地开发（容器外热重载）

```bash
# 后端（读取 settings 中的 API_HOST / API_PORT，默认 8000）
backend/.venv/bin/python run_server.py

# 前端（Vite 开发服务器，默认 5173）
cd frontend && npm run dev
```

## 6) 默认管理员与 SMTP 配置

**用户表为空时，首次启动后端会自动种子一个默认管理员**，让暂时没有邮件通道的全新部署也能立即登录管理端：

- 账号 `admin@aigcnews.internal`，密码 `admin123456`（见 `.env.example` 的 `DEFAULT_ADMIN_*` 小节，可覆盖；任一值置空即禁用种子）；
- 仅空库种子一次：既有部署（用户表非空）完全不触发、不受影响；种子失败不阻断启动（记录 critical 日志）。

**默认密码是公开凭据，登录后必须立即改密。** 仍使用默认密码登录时，页面底部会出现常驻警示条；点击警示条或 Dock 栏钥匙按钮打开「修改密码」对话框——**凭账号邮箱收到的 6 位验证码改密**，改密成功后警示条自动消失。

注册新用户、找回密码、修改密码都需要邮箱验证码，因此 SMTP 必须尽早配置，二选一：

- 在 `.env` 配好 `SMTP_*`（见 `.env.example` 的 SMTP 小节）；或
- 保持 `SMTP_HOST` 为空进入 dev 模式，验证码直接打印在后端控制台日志里。

> 注意：非 dev 环境且 SMTP 未配置时，改密验证码无法投递（接口返回 503），种子管理员将暂时无法脱离默认密码——请先完成上述任一 SMTP 配置。

管理员登录后，可在 **监控页 → SMTP 邮件投递配置** 面板在线管理：配置存入数据库、保存即生效（后台任务最迟 60 秒内沿用新配置），并**优先于环境变量**；「发送测试邮件」按最新已保存配置真实投递一封邮件到当前管理员的登录邮箱。主机留空保存即删除数据库配置、回退到环境变量。

## 端口与健康检查

| 地址 | 用途 |
| --- | --- |
| `http://localhost`（80/443） | 前端站点（生产域名证书见 `frontend/ssl/`，key 必须 `root:root` 600） |
| `http://localhost:5173` | Vite 开发服务器 |
| `http://127.0.0.1:8000` | 后端 API（仅回环绑定；`/api/live`、`/api/ready` 健康检查） |
| `http://localhost:8000/api/mcp` | 本地 MCP endpoint |

基础设施（PostgreSQL / Redis / Milvus / MinIO / Attu）只在编排网络内部暴露，不向宿主机发布端口；后端通过服务名访问。宿主机侧临时调试用 `docker exec <容器> ...`，运维细节见 [linux-server-boot.md](linux-server-boot.md)。

## 测试

```bash
# 后端全套件（必须从仓库根目录运行，与 CI 一致）
backend/.venv/bin/python -m pytest backend/tests -q

# 后端 lint
backend/.venv/bin/python -m ruff check backend/app backend/tests --config backend/pyproject.toml

# 前端：单元测试、类型检查、lint、构建
cd frontend
npm run test:unit
npm run typecheck
npm run lint
npm run build

# 编排校验
docker compose -f docker/docker-compose.yml config --quiet
```

提交信息遵循 Conventional Commits（`<type>(<scope>): <subject>`，scope 必填），细节见 [git-workflow.md](git-workflow.md)。
