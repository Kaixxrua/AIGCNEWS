# 使用轻量级的 Python 3.10 镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 先拷贝依赖文件并安装，利用 Docker 缓存加速构建
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝所有后端代码
COPY . .

# 暴露 8000 端口
EXPOSE 8000

# 启动 FastAPI
CMD["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]