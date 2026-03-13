FROM python:3.10-slim

# 设置工作目录为 src
WORKDIR /src

# 先拷贝依赖文件
COPY requirements.txt .

# 极速安装依赖
RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple -r requirements.txt

# 【核心修复】把后端代码整个打包进一个叫 backend 的文件夹里！
COPY . /src/backend

# 告诉 Python 从 /src 开始寻找包，这样 import backend 就能完美找到了
ENV PYTHONPATH=/src

# 暴露端口
EXPOSE 8000

# 启动命令也改成带有 backend 前缀（注意这里 CMD 和 [ 之间有空格啦！）
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
