# RAG AIGC Agent

## 快速开始 (Quick Start)

### 1) 准备环境变量
1. 复制示例文件并重命名为 `.env`：
   ```bash
   copy .env.example .env
   ```
2. 编辑 `.env`，根据本机环境填写参数。

### 2) 安装依赖
在 Windows 下建议直接使用启动脚本：

```bash
start.bat setup
```

等价的手动命令：

```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
cd frontend
npm install
```

### 3) 启动基础设施（Milvus + Attu + Neo4j）

```bash
start.bat up
```

默认访问地址：
- Milvus gRPC: `localhost:19530`
- Milvus HTTP: `localhost:9091`
- Attu 管理界面: `http://localhost:8000`
- Neo4j Browser: `http://localhost:7475`
- Neo4j Bolt: `bolt://localhost:7688`

默认账号与密码：
- Neo4j: `neo4j / your_password`（请在 `.env` 中修改）
- MinIO: `minioadmin / minioadmin`

### 4) 启动开发服务

```bash
start.bat dev
```

启动后：
- 后端 FastAPI: `http://localhost:8000`
- 前端 Vite: `http://localhost:5173`

---

## 常用命令

- `start.bat setup`：创建虚拟环境并安装后端与前端依赖
- `start.bat up`：启动 Milvus + Attu + Neo4j
- `start.bat down`：停止基础设施容器
- `start.bat dev`：启动后端与前端开发服务器
