# GitHub 项目嵌入连接恢复（2026-10-08）

## 原因与修复

项目使用 SiliconFlow `BAAI/bge-m3`、1024 维向量。
故障现场直接连接 `api.siliconflow.cn` 与通过当前通用 Mihomo 出口连接，
均在 TLS 握手阶段出现 `UNEXPECTED_EOF_WHILE_READING`。
同机既有 SSH SOCKS 隧道可完成相同接口的鉴权与嵌入请求，返回 HTTP 200、1024 维向量。
这证明存在可用的同平台路径，不能把本次错误归为模型不存在或密钥失效。

新增 `EMBEDDING_PROXY`，仅作用于 OpenAI 兼容嵌入客户端：

- 显式配置时，同步与异步客户端使用该出口并忽略环境 `HTTP_PROXY` / `NO_PROXY`。
- 留空时保持兼容：SiliconFlow 直连，其它服务沿用 SDK 默认环境代理。
- 代理选择与分词行为分开：SiliconFlow 继续发送原始文本，其它提供商保留既有分词逻辑。
- 保持 API 地址、密钥、模型名和向量维数，不混用其它平台或模型的向量。
- 两类 HTTP 客户端继续由既有模型运行时负责关闭。

本机生产 `.env` 已在部署锁内备份并仅添加：

```dotenv
EMBEDDING_PROXY=socks5://host.docker.internal:11080
```

这是本机已有隧道端口，不是其它部署必须照抄的默认值。
通用代理和其它服务配置未修改；应用的常驻客户端随正常代码发布采用新配置。

## 已恢复的数据

在独立维护进程中加载本次模型工厂代码，使用真实生产配置和专用出口，完成同步、异步 API 实测。
维护过程未覆盖运行容器的源码，也没有手工重启生产服务。

已重新构建此前因身份污染而清理的 9 个项目：

| 仓库 | 向量条数 |
| --- | ---: |
| EchoMusicApp/Echo-Music | 12 |
| Factory-AI/factory | 2 |
| andrewrabert/jellium-desktop | 2 |
| feder-cr/invisible_dots | 5 |
| feder-cr/invisible_playwright_mcp | 6 |
| harbor-framework/terminal-bench | 12 |
| harbor-framework/terminal-bench-1 | 4 |
| jellyfin/jellyfin-desktop | 2 |
| preetsuthar17/HextaUI | 2 |

合计 47 条。PostgreSQL 中 9 个项目均为 `succeeded`，源指纹与索引指纹相同，
台账计数与 Milvus 实际条数一致。
通过修复后的嵌入客户端调用真实语义检索组件，两条包含用途描述的查询分别将
invisible_dots 与 invisible_playwright_mcp 排在第一位。
这属于维护进程的实际检索验收；常驻 Web 进程的新出口仍由正常发布激活。

操作前状态、运行日志与配置备份位于仓库外：
`~/.local/state/aigcnews-repairs/github-embedding-20261008/`。
配置备份包含部署密钥，权限为 `0600`，不得提交或输出内容。

## 验证

82 项相关测试通过，包括真实本地 HTTP 代理的同步/异步请求、
`NO_PROXY=*` 下的显式代理优先级、原始文本与模型/鉴权保留、
非 SiliconFlow 分词兼容、客户端生命周期、索引及检索、出站安全与 Compose 配置。
配置字段读取与生产 Compose 注入已单独验证；Python 变更通过 Ruff。

索引数据已恢复。代码按标准提交、自动推送及交付队列发布，不以维护进程成功代替应用已部署。
