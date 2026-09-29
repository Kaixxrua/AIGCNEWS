# aigcnews_private

AIGCNEWS 私有配套仓（不随开源仓库发布）。承载两类内容：

1. **源插件包 `aigcnews_private/`** —— 开源版剥离的敏感采集实现：
   - `sources/x_transport.py`：X/Twitter 传输层（twitter-cli 内部
     GraphQL、cookie 凭据池、响应解析补丁）。

   公共仓只保留契约（`backend/app/services/source_plugins/`），经
   `x_source_enabled` 开关门控加载本包；插件缺失时对应路由 404、
   采集轮自动跳过（fail closed）。

   微信公众号链路已于 2026-09-29 整体下线：公共仓删除页面/接口/契约，
   本仓同步删除 `sources/wechat/`、`sources/wechat_sogou/`、
   `wechat_facade.py` 及其测试；数据库 wechat_* 表仅存历史数据。

2. **部署 overlay `deploy/`** —— 宿主机专用编排与 nginx 私有面
   （sub2api 网络、PriceAI 姊妹服务、插件包 bind-mount）。

## 目录

```
aigcnews_private/   # Python 插件包（容器内 /opt/aigcnews_private）
deploy/             # docker-compose overlay + nginx inc
scripts/            # 运维脚本（x_ingestion_spike.py 等）
tests/              # 私有实现契约测试（含 fixtures/）
pylibs/             # 运行时依赖供给（gitignored，见下）
```

## 运行时依赖供给（pylibs）

公共仓镜像不再安装 `twitter-cli`；插件包所需依赖经 `pip --target`
注入 `pylibs/`，由 overlay 的 `PYTHONPATH=/opt/aigcnews_private/pylibs:...`
提供给容器。供给命令（宿主机，需 Python 3.12 与 uv）：

```bash
uv pip install --python 3.12 --target /home/kaixxrua/aigcnews_private/pylibs \
  twitter-cli==0.8.5 --constraint /tmp/pylibs_constraints.txt
```

constraints 锁定与公共仓历史 lock 一致的版本（twitter-cli==0.8.5、
browser-cookie3==0.20.1、curl-cffi==0.16.0、xclienttransaction==1.0.3、
beautifulsoup4==4.15.0、click==8.4.2、pyyaml==6.0.3、rich==15.0.0 及
其传递依赖）。`pylibs/` 为构建产物，已 gitignore；重建镜像或升级
twitter-cli 时按上式重装。

## 部署接线

`deploy/docker-compose.private.yml` 由公共仓
`scripts/manage_main_stack.sh` 自动探测并入（可用
`AIGCNEWS_PRIVATE_COMPOSE` 覆盖路径）。backend-api 服务经 overlay 获得：

- bind-mount：`/home/kaixxrua/aigcnews_private` → `/opt/aigcnews_private:ro`
- `PYTHONPATH=/opt/aigcnews_private/pylibs:/opt/aigcnews_private:/src`

`.env`（公共仓根目录，gitignored）需开启开关：

```bash
X_SOURCE_ENABLED=true
```

接线顺序兼容：旧镜像（仓库内含过渡期实现）+ 新 overlay 时 loader
私有优先候选命中挂载包；新镜像（已删除仓库内实现）+ 旧 overlay 时
loader 返回 None，X 链路优雅降级（路由 404、采集跳过），不炸。

## 测试

```bash
# 在公共仓根目录执行（conftest.py 自动注入双仓 sys.path；
# 公共仓位置可用 AIGCNEWS_PUBLIC_REPO 覆盖，缺省取同级 ../AIGCNEWS）
backend/.venv/bin/python -m pytest /home/kaixxrua/aigcnews_private/tests
```

覆盖：X 传输层/解析补丁（test_x_source_contracts.py）、私有实现与
公共契约的身份同一性与 loader 默认候选加载
（test_source_plugin_identity.py）。
