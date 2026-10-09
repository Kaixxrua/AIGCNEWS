# 基础镜像按 digest 锁定（更新方式：docker pull python:3.12-slim 后
# docker inspect --format '{{index .RepoDigests 0}}' 取新值替换）。
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

# 设置工作目录为 src
WORKDIR /src

# 官方索引配合有界并行下载，避免第三方镜像超时和大包串行下载拖慢发布。
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN --mount=type=cache,id=aigcnews-uv-bootstrap,target=/root/.cache/pip,sharing=locked \
    pip install --timeout 30 --retries 2 --index-url "$PIP_INDEX_URL" --no-deps uv==0.11.29

# 拷贝依赖锁定文件（requirements.lock 由 uv pip compile 生成，见 requirements.txt 文首）
COPY requirements.lock build_wheel_cache.py ./
RUN --mount=type=cache,id=aigcnews-uv,target=/root/.cache/uv,sharing=locked \
    --mount=type=cache,id=aigcnews-wheels,target=/wheelhouse,readonly,sharing=shared \
    export UV_HTTP_TIMEOUT=30 UV_HTTP_RETRIES=2 UV_CONCURRENT_DOWNLOADS=8 UV_CONCURRENT_INSTALLS=4 \
    && uv pip compile requirements.lock --default-index "$PIP_INDEX_URL" \
        --generate-hashes --no-header --no-annotate --quiet -o /tmp/requirements-hashed.lock \
    && python build_wheel_cache.py /tmp/requirements-hashed.lock /wheelhouse /tmp/requirements-cached.lock \
    && uv pip install --system --no-index --find-links=/wheelhouse --no-deps --link-mode=copy \
        --require-hashes -r /tmp/requirements-cached.lock \
    && uv pip install --system --default-index "$PIP_INDEX_URL" --link-mode=copy \
        --require-hashes -r /tmp/requirements-hashed.lock \
    && pip uninstall --yes uv \
    && rm /tmp/requirements-hashed.lock /tmp/requirements-cached.lock build_wheel_cache.py

# 【核心修复】把后端代码整个打包进一个叫 backend 的文件夹里！
COPY . /src/backend

# 告诉 Python 从 /src 开始寻找包，这样 import backend 就能完美找到了
ENV PYTHONPATH=/src

# HuggingFace 镜像源（国内加速，容器重启后自动生效）
ENV HF_ENDPOINT=https://hf-mirror.com
ENV HF_HUB_OFFLINE=0
ENV TRANSFORMERS_OFFLINE=0

# 最小权限运行：固定 uid/gid 1000 的 app 用户，与部署主机实例用户
# （应用目录与存储卷属主）一致。绑定挂载的代码/存储保持可写，
# 容器内不再向宿主目录写入 root 属主文件（如 __pycache__）。
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /src/storage/papers /hf-cache \
    && chown -R app:app /src/storage /hf-cache

# HuggingFace 缓存落在非 root 可写路径；compose 将 ../storage/hf_cache/huggingface 挂载到这里
ENV HF_HOME=/hf-cache

# 暴露端口
EXPOSE 8000

# 镜像级健康检查（compose 中的 healthcheck 定义优先于此处，行为一致）
HEALTHCHECK --interval=10s --timeout=7s --start-period=30s --retries=18 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=5)"]

USER app

# 启动命令也改成带有 backend 前缀（注意这里 CMD 和 [ 之间有空格啦！）
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
