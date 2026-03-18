# 系统更新架构与逻辑设计文档

> 适用项目：AIGC_NEWS  
> 参考现状文档：[docs/architecture.md](docs/architecture.md)、[docs/code-analysis.md](docs/code-analysis.md)  
> 设计日期：2026-03-17

---

## 1. 文档概述

### 1.1 项目背景

AIGC_NEWS 当前已具备资讯聚合、RAG 智能问答、论文阅读、视觉问答、简报生成与基础认证能力。根据 [docs/architecture.md](docs/architecture.md) 的现状，前端主体采用 Vue 3 + TypeScript + Pinia + TailwindCSS，后端采用 FastAPI，数据层由 MySQL、Milvus、Neo4j、Redis 共同组成，聊天主链路已支持 SSE 流式输出与 reasoning/thinking 内容提取。

根据 [docs/code-analysis.md](docs/code-analysis.md) 的代码分析，当前系统的主要短板集中在以下方面：

- 前端视觉体系偏暖白极简风，尚未形成更强的科技感层次与统一动态反馈
- 聊天 Loading、PDF 解析进度、简报页面排版仍有提升空间
- 聊天历史仍以 Pinia 内存状态或模块级 ref 为主，缺乏服务端持久化与 LRU 生命周期管理
- 多模态能力分散在阅读器视图内，主聊天入口尚不支持图片/PDF 上传
- 认证仍采用手机号 + SMS OTP，与目标邮箱验证码方案不一致

### 1.2 本次更新范围

本次设计覆盖以下四大方向，共 11 项需求：

1. UI/UX 与交互优化
2. RAG 问答与多模态能力增强
3. 会话历史与状态管理
4. 认证鉴权改造

### 1.3 总体设计原则

- 保持现有技术栈不变，优先做增量式架构升级
- 前端交互反馈统一由全局状态驱动，而非由单页面零散控制
- 聊天历史采用 前端缓存 + 后端持久化 双层模型
- 论文阅读聊天与普通聊天统一到同一会话模型中，避免状态分叉
- 多模态能力优先复用已有 [backend/app/api/routes_vision.py](backend/app/api/routes_vision.py) 与 PDF 解析链路
- 认证改造尽量兼容现有 JWT、Redis OTP、MySQLRepository 结构

---

## 2. 需求 1-11 的逐条设计方案

### 需求 1：全局前端美化

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md) 的发现：

- [frontend/src/style.css](frontend/src/style.css) 当前主色仍是暖白 + stone 色系，整体气质偏 Editorial Warm Minimalism
- [frontend/src/views/LayoutView.vue](frontend/src/views/LayoutView.vue) 已有毛玻璃主画布与 Dock 导航，但缺少统一的科技感渐变、光晕、层次分区与路由切换动画
- [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue) 的来源徽章函数 `sourceTypeBadgeClass` 始终返回同一种样式，来源辨识度不足

#### 实现思路

在不推翻现有玻璃态设计的前提下，升级为 暖科技 Glassmorphism 2.0 风格：

- 保留现有圆角、毛玻璃与浅底背景
- 在 [frontend/src/style.css](frontend/src/style.css) 中增加全局设计 Token，如科技蓝、青色高亮、淡紫辅助色、发光阴影、渐变描边
- 在 [frontend/src/views/LayoutView.vue](frontend/src/views/LayoutView.vue) 的主画布背景层增加低透明 radial-gradient 与 noise 纹理伪元素
- 为 [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue)、[frontend/src/views/ReportView.vue](frontend/src/views/ReportView.vue)、[frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue) 统一卡片标题、段落、标签、按钮、悬浮动效与阴影层次
- 将来源标签改为按 `arxiv/github/news/neo4j/milvus` 分类上色
- 激活 [frontend/src/views/LayoutView.vue](frontend/src/views/LayoutView.vue) 已预留但未使用的路由过渡动画

#### 涉及的文件变更清单

- [frontend/src/style.css](frontend/src/style.css)
- [frontend/tailwind.config.js](frontend/tailwind.config.js)
- [frontend/src/views/LayoutView.vue](frontend/src/views/LayoutView.vue)
- [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue)
- [frontend/src/views/ReportView.vue](frontend/src/views/ReportView.vue)
- [frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue)

#### 关键代码逻辑描述

```pseudo
extend theme tokens:
  colors.tech.primary = cyan-blue
  colors.tech.secondary = violet
  shadows.glow = soft cyan shadow
  backgrounds.mesh = layered radial gradients

layout view render:
  mainCanvas = glass panel + gradient border + background glow
  routerView = wrap in Transition spatial-fade

chat source badge:
  switch sourceType:
    arxiv -> blue badge
    github -> slate badge
    news -> amber badge
    neo4j -> violet badge
    milvus -> cyan badge

shared card behavior:
  on hover -> translateY small + stronger shadow + border highlight
```

---

### 需求 2：等待回复转圈

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md)：

- [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue) 已存在发送按钮 spinner、思维链 spinner、三点 bounce 动画
- 但没有全局级 Loading overlay，也没有显式区分 请求发出中、检索中、模型生成中 三个状态
- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts) 当前只维护 `messages` 与 `settings`，未维护流式请求的全局状态

#### 实现思路

将聊天等待反馈拆为两层：

- 局部层：消息气泡内保留当前的占位与打字机效果
- 页面层：新增显式的聊天请求态，例如 `isStreaming`, `streamPhase`, `activeRequestId`

在 [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts) 中维护全局请求状态；在 [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue) 顶部工具栏或消息区中央增加 Loading Spinner + 文案，如 正在检索资料、正在生成回答。SSE 收到 `status` 事件时动态切换状态文案。

#### 涉及的文件变更清单

- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts)
- [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue)
- [frontend/src/composables/useEventSource.ts](frontend/src/composables/useEventSource.ts)

#### 关键代码逻辑描述

```pseudo
chatStore.state +=
  isStreaming: boolean
  streamPhase: 'idle' | 'searching' | 'reranking' | 'answering' | 'error'
  activeAbortController: AbortController | null

sendMessage:
  set isStreaming = true
  set streamPhase = 'searching'
  connect SSE

onMessage:
  if type == 'status':
    map status searching -> 'searching'
    map status reranking -> 'reranking'
  if type == 'thinking' or type == 'content':
    streamPhase = 'answering'

onDone or onError:
  isStreaming = false
  activeAbortController = null

ChatView template:
  if store.isStreaming:
    show overlay spinner + text by streamPhase
```

---

### 需求 3：加载 PDF 进度条

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md)：

- [frontend/src/components/PdfCanvasViewer.vue](frontend/src/components/PdfCanvasViewer.vue) 当前只有 `isLoading` 与文字提示 PDF 加载中
- 已维护 `totalPages` 与 `pageEntries`，但未把 `pageEntries.length / totalPages` 作为真实渲染进度暴露到 UI
- PDF 上传、解析、渲染涉及多个阶段，目前阶段状态未统一

#### 实现思路

将 PDF 生命周期细分为三段：

1. 上传阶段
2. 解析阶段
3. 渲染阶段

对于阅读器中的远程 PDF 渲染，优先落地解析与逐页渲染进度条；对于本地 PDF 上传问答场景，额外在聊天多模态入口展示上传与后端解析进度。

[frontend/src/components/PdfCanvasViewer.vue](frontend/src/components/PdfCanvasViewer.vue) 需要新增对外进度事件，例如 `progress`，向父组件上报：

- `phase = fetching`
- `phase = parsing`
- `phase = rendering`
- `loadedPages`
- `totalPages`
- `percent`

[frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue) 在顶部或 PDF 区域头部展示细线型进度条与页数进度。

#### 涉及的文件变更清单

- [frontend/src/components/PdfCanvasViewer.vue](frontend/src/components/PdfCanvasViewer.vue)
- [frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue)
- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts) 仅在未来本地 PDF 上传解析时复用同一进度模型

#### 关键代码逻辑描述

```pseudo
PdfCanvasViewer emits progress:
  on getDocument start -> phase='parsing', percent=5
  after pdfDoc loaded -> totalPages = numPages, percent=10
  each page rendered:
    loadedPages += 1
    percent = 10 + loadedPages / totalPages * 90
    emit progress
  on complete -> percent = 100, phase='done'

PaperReadView:
  listen progress event
  render top progress bar with label
  if error -> switch progress bar to error state
```

---

### 需求 4：日报界面美化

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md)：

- [frontend/src/views/ReportView.vue](frontend/src/views/ReportView.vue) 布局已经完整，但视觉结构仍以单一玻璃卡片为主
- 报告内容通过 `prose-content` 输出，缺少目录感、封面感、摘要区、状态区、历史切换信息层
- 类型与周期按钮的排版较密集，缺少信息分组

#### 实现思路

将 [frontend/src/views/ReportView.vue](frontend/src/views/ReportView.vue) 改为 三段式阅读布局：

- 顶部 Hero 标题区：展示简报标题、日期、来源、缓存状态、生成状态
- 中部操作区：按 类型、周期、日期、生成动作 四块分组
- 底部阅读区：增加 Markdown 内容容器、目录锚点、摘要卡片、生成元数据条

视觉上重点增强：

- 简报封面感
- Markdown 内容最大宽度与行长控制
- 二级标题的章节卡片化
- 引用块、表格、列表的阅读舒适度
- 生成中 skeleton 与流式光标效果

#### 涉及的文件变更清单

- [frontend/src/views/ReportView.vue](frontend/src/views/ReportView.vue)
- [frontend/src/style.css](frontend/src/style.css)

#### 关键代码逻辑描述

```pseudo
ReportView layout:
  section hero:
    report meta badges + cache status + generation status
  section control panel:
    report type group
    period group
    date selector
    generate button
  section content:
    if empty -> illustrated empty state
    if generating -> skeleton blocks + cursor
    if content -> render markdown with enhanced prose classes

optional markdown preprocess:
  extract first h1/h2 as reportTitle
  extract first paragraph as summary
  render summary card before article
```

---

### 需求 5：添加 Footer 版权标识

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md)：

- [frontend/src/views/LayoutView.vue](frontend/src/views/LayoutView.vue) 当前只有主画布、Dock、右上角 Auth Island
- 没有 Footer 区域
- 用户已确认文案采用可配置占位方案，即 `Powered by 品牌配置项`

#### 实现思路

在 [frontend/src/views/LayoutView.vue](frontend/src/views/LayoutView.vue) 的 `.main-canvas` 内部底部增加全局 Footer 区域，避免与 fixed Dock 冲突。Footer 文案来源采用配置注入：

- 前端运行时常量 `VITE_APP_BRAND_NAME`
- 默认回退值 `Brand`
- 展示文案：`Powered by ${brandName}`

Footer 需采用低视觉权重，但在暗/浅玻璃背景上保持可读。若未来需要品牌跳转，可扩展品牌官网链接。

#### 涉及的文件变更清单

- [frontend/src/views/LayoutView.vue](frontend/src/views/LayoutView.vue)
- [frontend/src/main.ts](frontend/src/main.ts) 或 [frontend/src/services/api.ts](frontend/src/services/api.ts) 若统一读取运行时配置
- [.env.example](.env.example)

#### 关键代码逻辑描述

```pseudo
const brandName = import.meta.env.VITE_APP_BRAND_NAME || 'Brand'
footerText = `Powered by ${brandName}`

LayoutView template:
  contentArea
  footer area at bottom of main canvas

styles:
  footer small font
  muted color
  top border gradient
```

---

### 需求 6：多模态支持 图片/PDF 上传

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md)：

- [frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue) 已支持截图视觉问答
- [backend/app/api/routes_vision.py](backend/app/api/routes_vision.py) 已支持图片 base64 上传和视觉 SSE 中继
- [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue) 主聊天框尚不支持图片、本地 PDF 上传
- [backend/app/api/routes_chat.py](backend/app/api/routes_chat.py) 仅接收 `{message, history, temperature}`
- 后端已有 [backend/app/services/ingestion/arxiv_pdf_downloader.py](backend/app/services/ingestion/arxiv_pdf_downloader.py) 的 PDF 解析基础，但未提供用户上传 PDF 的专用会话链路

#### 实现思路

设计统一多模态会话入口，分为两种附件类型：

1. 图片附件
2. 本地 PDF 附件

建议新增一个统一附件上传与解析路由组，而不是继续把所有能力塞在 [backend/app/api/routes_chat.py](backend/app/api/routes_chat.py) 中：

- `POST /api/chat/attachments`
- `GET /api/chat/attachments/{attachment_id}`
- `POST /api/chat/stream`
- `POST /api/chat/vision-relay`

图片流程：

- 继续复用现有视觉模型模式
- 但将内存缓存改为 Redis 或对象存储索引元数据，避免单进程限制

PDF 流程：

- 前端上传本地 PDF
- 后端将文件落到临时安全目录或对象存储
- 提取文本、页数、摘要、页面切片
- 生成 `attachment_id`
- 聊天请求通过 `attachment_id` 告知后端，在 RAG 检索时先检索该 PDF 局部索引

设计上允许用户在同一聊天会话中挂载多个附件，但第一期限制为 单轮最多 1 个主 PDF + 若干图片。

#### 涉及的文件变更清单

- [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue)
- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts)
- [frontend/src/services/api.ts](frontend/src/services/api.ts)
- [backend/app/api/routes_chat.py](backend/app/api/routes_chat.py)
- [backend/app/api/routes_vision.py](backend/app/api/routes_vision.py)
- 新增 [backend/app/api/routes_attachments.py](backend/app/api/routes_attachments.py)
- 新增 [backend/app/services/chat/attachment_service.py](backend/app/services/chat/attachment_service.py)
- [backend/app/repositories/mysql_repo.py](backend/app/repositories/mysql_repo.py)
- [backend/app/main.py](backend/app/main.py)

#### 关键代码逻辑描述

```pseudo
frontend ChatView:
  add upload button
  accept image/* and application/pdf
  after select file:
    call uploadAttachment(file)
    store pending attachment metadata
    show chip in input area

backend attachment upload:
  validate mime type and size
  create attachment row
  if image:
    store file or redis reference
    mark modality='image'
  if pdf:
    save temp file
    extract pages/text
    optionally chunk and embed into dedicated attachment index
    mark status='ready' or 'processing'

chat stream request:
  body += attachment_ids[]
  if contains image:
    route to multimodal model or vision sub-pipeline
  if contains pdf:
    retrieve from attachment chunks first
    then merge public knowledge docs
```

---

### 需求 7：修复思维链 CoT 不显示

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md)：

- [backend/app/services/rag/chat_service.py](backend/app/services/rag/chat_service.py) 的 `_extract_thinking_and_content` 已兼容 Anthropic、OpenAI reasoning、`<think>...</think>` 等多种格式
- [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue) 已有 `thinkingExpanded`、折叠面板与 spinner UI
- 但问题说明仍要求修复 `<think>...</think>` 不显示，说明问题大概率不在 UI 容器，而在前后端流式事件映射、消息模型或渲染阶段
- 用户已明确要求 默认折叠，仅显示摘要提示，点击后展开完整 think 内容

#### 实现思路

重点修复链路分三步：

1. 后端保证 `thinking` 事件稳定输出，而不是把 `<think>` 内容混入 `content`
2. 前端 store 为 assistant message 维护独立字段 `thinkingRaw`, `thinkingPreview`, `hasThinking`
3. 视图层默认折叠，仅显示摘要提示，如 已生成思维链，点击展开

对于模型直接返回整段 `<think>...</think>最终答案` 的情况，增加前端兜底解析：当收到 `content` 且包含闭合 `<think>` 标签时，执行拆分。后端仍作为主解析方，前端只做容错。

#### 涉及的文件变更清单

- [backend/app/services/rag/chat_service.py](backend/app/services/rag/chat_service.py)
- [backend/app/api/routes_chat.py](backend/app/api/routes_chat.py)
- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts)
- [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue)
- [frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue) 若阅读器聊天也统一支持 thinking

#### 关键代码逻辑描述

```pseudo
backend stream_chat:
  for each llm chunk:
    extract thinkingPart, answerPart
    if thinkingPart:
      yield { type: 'thinking', data: thinkingPart }
    if answerPart:
      yield { type: 'content', data: answerPart }

frontend chatStore assistant message:
  fields += hasThinking, thinkingRaw, thinkingPreview

onMessage content fallback parse:
  if chunk contains <think>...</think>:
    move think body into thinking queue
    move remaining into content queue

ChatView render:
  if hasThinking:
    collapsed summary row = '模型已输出思维链'
    on click expand full preformatted think content
```

---

### 需求 8：聊天控制功能 重新生成与删除消息

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md)：

- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts) 只有 `appendMessage`、`clearMessages`、`sendMessage`
- [frontend/src/composables/useEventSource.ts](frontend/src/composables/useEventSource.ts) 已指出 `AbortController` 返回后外部未被消费，无法取消请求
- 当前没有 regenerate、删除某条 user 消息、删除某条 assistant 回复 的上下文同步机制

#### 实现思路

将聊天控制能力设计为基于 message_id 的会话编辑：

- 重新生成回复：定位到指定 assistant 消息，将其之前的上下文切片重新发送
- 删除用户消息：删除该用户消息以及其后紧邻的 assistant 回复，并重建当前会话上下文
- 删除 AI 回复：仅删除该 assistant 消息，并刷新会话 `updated_at`
- 若目标消息位于中间位置，则后续派生消息标记为失效并一并裁剪，避免上下文污染

为此，消息必须具备稳定 ID，而不再只靠数组索引。前端 store 与后端 `chat_messages` 表统一采用 `message_id`。

#### 涉及的文件变更清单

- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts)
- [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue)
- [frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue)
- [frontend/src/composables/useEventSource.ts](frontend/src/composables/useEventSource.ts)
- [backend/app/api/routes_chat.py](backend/app/api/routes_chat.py)
- [backend/app/repositories/mysql_repo.py](backend/app/repositories/mysql_repo.py)
- 新增 [backend/app/services/chat/conversation_service.py](backend/app/services/chat/conversation_service.py)

#### 关键代码逻辑描述

```pseudo
message model:
  id
  conversationId
  role
  content
  thinking
  sources
  parentMessageId optional

regenerate(messageId):
  find target assistant message
  slice history before target assistant
  mark target assistant as regenerating
  call /chat/messages/{messageId}/regenerate
  replace assistant content with new stream

deleteMessage(messageId):
  call DELETE /chat/messages/{messageId}
  backend delete target and all descendant messages in same branch
  frontend sync conversation messages from latest snapshot

useEventSource:
  expose abort controller
  allow cancel generation before regenerate
```

---

### 需求 9：历史对话记录管理 LRU 与自动清理机制

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md)：

- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts) 消息仅在内存中
- [backend/app/repositories/mysql_repo.py](backend/app/repositories/mysql_repo.py) 没有 `conversations` 与 `chat_messages` 表
- 分析报告已明确建议新增会话表与消息表

#### 实现思路

采用 会话级 LRU + 消息级上限 双层机制：

- 每个用户最多保留 10 个会话
- 每个会话内部消息数可单独设上限，例如 100 条，本文按用户要求主描述为 最多存 10 条/会话，可解释为最多保留 10 条消息记录；实现上建议区分 会话数上限 与 消息数上限，文档中按需求落地为 每会话 10 条持久化消息
- 超限时删除最早记录
- 每 7 天自动清理 5 条最旧且最近未访问的会话记录或消息记录
- 点击历史对话时更新 `last_accessed_at` 与 `updated_at`

建议把清理逻辑放在两处：

- 触发式清理：在新建会话、新增消息、打开历史会话时执行轻量清理
- 定时清理：由 [backend/app/core/scheduler.py](backend/app/core/scheduler.py) 增加每日任务

#### 涉及的文件变更清单

- [backend/app/repositories/mysql_repo.py](backend/app/repositories/mysql_repo.py)
- [backend/app/core/scheduler.py](backend/app/core/scheduler.py)
- [backend/app/api/routes_chat.py](backend/app/api/routes_chat.py)
- 新增 [backend/app/services/chat/conversation_service.py](backend/app/services/chat/conversation_service.py)
- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts)
- [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue)

#### 关键代码逻辑描述

```pseudo
on create message:
  insert message
  update conversation.updated_at and last_accessed_at
  trim conversation messages keep latest 10
  trim user conversations keep latest 10

scheduled cleanup daily:
  find conversations/messages where datediff(now, last_accessed_at) >= 7
  delete 5 oldest rows per user or global batch

on open history conversation:
  update last_accessed_at = today
  update updated_at = now
```

---

### 需求 10：修复切换 PDF 对话消失问题

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md)：

- [frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue) 通过模块级 `persistedMessages` 持久化对话
- 但这是全局共享的，不按 `paper_id` 分组
- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts) 也没有 `paper_id` 概念
- [backend/app/api/routes_chat.py](backend/app/api/routes_chat.py) 请求体没有 `paper_id`

这意味着当前不是严格的 切换 PDF 后对话消失，而是 对话与论文绑定关系错误，无法稳定映射到某个文档上下文。

#### 实现思路

统一会话主键模型：

- 普通聊天：`conversation_scope = global`
- 论文聊天：`conversation_scope = paper`
- 作用域键：`scope_key = paper_id`

当前端进入 [frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue) 时：

- 以 `paper_id` 查询或创建专属 conversation
- 所有普通文字问答与视觉问答都写入该 conversation
- 切换到另一篇论文时，根据新的 `paper_id` 切换 conversation
- 返回原论文时恢复同一历史

#### 涉及的文件变更清单

- [frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue)
- [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts)
- [backend/app/api/routes_chat.py](backend/app/api/routes_chat.py)
- [backend/app/api/routes_vision.py](backend/app/api/routes_vision.py)
- [backend/app/repositories/mysql_repo.py](backend/app/repositories/mysql_repo.py)
- 新增 [backend/app/services/chat/conversation_service.py](backend/app/services/chat/conversation_service.py)

#### 关键代码逻辑描述

```pseudo
route /papers/:id/read enter:
  paperId = route.params.id
  conversation = ensureConversation(userId, scope='paper', scopeKey=paperId)
  load messages by conversationId

send text or vision:
  body += conversation_id and paper_id
  backend append messages into same conversation

switch paper:
  persist current conversation state
  fetch next conversation by new paperId
```

---

### 需求 11：注册流程改造 邮箱 + 邀请码

#### 现状分析

根据 [docs/code-analysis.md](docs/code-analysis.md)：

- [backend/app/api/routes_auth.py](backend/app/api/routes_auth.py) 当前仍是 `send-otp`、手机号注册、手机号登录
- [backend/app/services/sms_service.py](backend/app/services/sms_service.py) 使用 Redis 保存短信 OTP 与防刷锁
- [frontend/src/views/RegisterView.vue](frontend/src/views/RegisterView.vue) 仍为手机号 + 短信验证码表单
- [frontend/src/stores/authStore.ts](frontend/src/stores/authStore.ts) 的 `AuthUser` 只有 `phone`
- [backend/app/repositories/mysql_repo.py](backend/app/repositories/mysql_repo.py) 的 `users` 表也只有 `phone`

#### 实现思路

认证链路改造为 邮箱 OTP + 邀请码强校验：

- 废弃 `POST /api/auth/send-otp`
- 新增 `POST /api/auth/send-email-otp`
- `POST /api/auth/register` 改为接收 `email`, `email_code`, `password`, `invite_code`
- 唯一邀请码固定校验值为 `internal_testing`
- 登录改为 `email + password`
- JWT payload 由 `phone` 改为 `email`
- MySQL `users` 表新增 `email`，保留 `phone` 为可空兼容字段，后续逐步废弃

SMTP 设计采用配置驱动：

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `SMTP_FROM_NAME`
- `SMTP_USE_TLS`

邮件发送服务建议新增 [backend/app/services/email_service.py](backend/app/services/email_service.py)，结构与 [backend/app/services/sms_service.py](backend/app/services/sms_service.py) 平行，复用 Redis OTP 思路。

#### 涉及的文件变更清单

- [backend/app/api/routes_auth.py](backend/app/api/routes_auth.py)
- [backend/app/core/auth.py](backend/app/core/auth.py)
- [backend/app/core/config.py](backend/app/core/config.py)
- [backend/app/repositories/mysql_repo.py](backend/app/repositories/mysql_repo.py)
- 新增 [backend/app/services/email_service.py](backend/app/services/email_service.py)
- [frontend/src/views/RegisterView.vue](frontend/src/views/RegisterView.vue)
- [frontend/src/views/LoginView.vue](frontend/src/views/LoginView.vue)
- [frontend/src/stores/authStore.ts](frontend/src/stores/authStore.ts)
- [.env.example](.env.example)
- [backend/requirements.txt](backend/requirements.txt)

#### 关键代码逻辑描述

```pseudo
send email otp:
  validate email format
  check redis lock email:lock:{email}
  code = random 6 digits
  save redis email:code:{email} ttl 300
  send smtp mail with code
  set redis lock ttl 60

register:
  validate invite_code == 'internal_testing'
  verify email otp consume=false
  check email unique
  hash password
  create user with email and nullable phone
  consume otp

login:
  find user by email
  verify password
  create_access_token({ user_id, role, email })
```

---

## 3. 数据库表结构变更

### 3.1 现有表 ALTER 语句

#### `users` 表改造

```sql
ALTER TABLE users
    MODIFY phone VARCHAR(20) NULL,
    ADD COLUMN email VARCHAR(255) NULL UNIQUE AFTER phone,
    ADD COLUMN email_verified TINYINT(1) NOT NULL DEFAULT 1 AFTER email,
    ADD COLUMN invite_code_used VARCHAR(64) NULL AFTER email_verified,
    ADD COLUMN last_login_at DATETIME NULL AFTER invite_code_used;
```

说明：

- `phone` 改为可空，用于兼容老用户
- 新用户统一走 `email`
- `invite_code_used` 记录注册时使用的邀请码

### 3.2 新增会话表

#### `conversations`

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    scope ENUM('global', 'paper') NOT NULL DEFAULT 'global',
    scope_key VARCHAR(255) NULL,
    title VARCHAR(255) NULL,
    last_message_preview VARCHAR(500) NULL,
    message_count INT NOT NULL DEFAULT 0,
    last_accessed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_conv_user_updated (user_id, updated_at DESC),
    INDEX idx_conv_user_accessed (user_id, last_accessed_at DESC),
    INDEX idx_conv_scope (user_id, scope, scope_key),
    CONSTRAINT fk_conversations_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

### 3.3 新增消息表

#### `chat_messages`

```sql
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id BIGINT NOT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    content MEDIUMTEXT NOT NULL,
    thinking MEDIUMTEXT NULL,
    sources_json JSON NULL,
    attachments_json JSON NULL,
    status ENUM('done', 'streaming', 'deleted', 'regenerated') NOT NULL DEFAULT 'done',
    parent_message_id BIGINT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_msg_conversation_created (conversation_id, created_at ASC),
    INDEX idx_msg_parent (parent_message_id),
    CONSTRAINT fk_chat_messages_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
```

### 3.4 新增附件表

#### `chat_attachments`

```sql
CREATE TABLE IF NOT EXISTS chat_attachments (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    conversation_id BIGINT NULL,
    file_name VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    modality ENUM('image', 'pdf') NOT NULL,
    storage_path VARCHAR(512) NULL,
    file_size BIGINT NOT NULL DEFAULT 0,
    page_count INT NULL,
    parse_status ENUM('uploaded', 'processing', 'ready', 'failed') NOT NULL DEFAULT 'uploaded',
    extract_text MEDIUMTEXT NULL,
    meta_json JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_attachment_user_created (user_id, created_at DESC),
    INDEX idx_attachment_conv (conversation_id),
    CONSTRAINT fk_chat_attachments_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

### 3.5 建议的清理 SQL 逻辑

```sql
DELETE FROM chat_messages
WHERE conversation_id = ?
  AND id NOT IN (
    SELECT id FROM (
      SELECT id
      FROM chat_messages
      WHERE conversation_id = ?
      ORDER BY created_at DESC
      LIMIT 10
    ) latest
  );
```

```sql
DELETE FROM conversations
WHERE user_id = ?
  AND id NOT IN (
    SELECT id FROM (
      SELECT id
      FROM conversations
      WHERE user_id = ?
      ORDER BY last_accessed_at DESC, updated_at DESC
      LIMIT 10
    ) latest
  );
```

---

## 4. 后端 API 路由变更明细

### 4.1 认证路由

#### 新增 `POST /api/auth/send-email-otp`

请求：

```json
{
  "email": "user@example.com"
}
```

响应：

```json
{
  "detail": "验证码已发送"
}
```

#### 修改 `POST /api/auth/register`

请求：

```json
{
  "email": "user@example.com",
  "email_code": "123456",
  "password": "your_password",
  "invite_code": "internal_testing"
}
```

响应：

```json
{
  "detail": "注册成功",
  "user_id": 1001
}
```

#### 修改 `POST /api/auth/login`

请求：

```json
{
  "email": "user@example.com",
  "password": "your_password"
}
```

响应：

```json
{
  "access_token": "jwt-token",
  "token_type": "bearer",
  "role": "user"
}
```

#### 修改 `GET /api/auth/me`

响应：

```json
{
  "user_id": 1001,
  "email": "user@example.com",
  "role": "user"
}
```

### 4.2 聊天与会话路由

#### 修改 `POST /api/chat/stream`

请求：

```json
{
  "conversation_id": 2001,
  "paper_id": "paper_xxx",
  "message": "请总结这篇论文的贡献",
  "history": [
    {"role": "user", "content": "上一个问题"}
  ],
  "temperature": 0.7,
  "attachment_ids": [3001]
}
```

SSE 响应事件：

```text
data: {"type":"status","data":"searching"}

data: {"type":"sources","data":[...]}

data: {"type":"thinking","data":"..."}

data: {"type":"content","data":"..."}

data: {"type":"conversation","data":{"conversation_id":2001,"message_id":5002}}

data: [DONE]
```

#### 新增 `GET /api/chat/conversations`

查询参数：

- `scope`: `global|paper`
- `page`
- `page_size`

响应：

```json
{
  "items": [
    {
      "id": 2001,
      "title": "这篇论文讲了什么",
      "scope": "paper",
      "scope_key": "paper_xxx",
      "message_count": 8,
      "updated_at": "2026-03-17 14:00:00",
      "last_accessed_at": "2026-03-17 14:00:00"
    }
  ],
  "total": 1
}
```

#### 新增 `GET /api/chat/conversations/{conversation_id}`

响应：

```json
{
  "conversation": {
    "id": 2001,
    "scope": "paper",
    "scope_key": "paper_xxx"
  },
  "messages": [
    {
      "id": 5001,
      "role": "user",
      "content": "这篇论文讲了什么",
      "thinking": "",
      "sources": []
    }
  ]
}
```

#### 新增 `DELETE /api/chat/messages/{message_id}`

响应：

```json
{
  "detail": "删除成功"
}
```

#### 新增 `POST /api/chat/messages/{message_id}/regenerate`

请求：

```json
{
  "temperature": 0.7
}
```

响应：SSE，事件格式与 `/api/chat/stream` 一致。

### 4.3 附件路由

#### 新增 `POST /api/chat/attachments`

`multipart/form-data` 请求字段：

- `file`
- `conversation_id` 可选
- `paper_id` 可选

响应：

```json
{
  "attachment_id": 3001,
  "mime_type": "application/pdf",
  "modality": "pdf",
  "parse_status": "processing"
}
```

#### 新增 `GET /api/chat/attachments/{attachment_id}`

响应：

```json
{
  "attachment_id": 3001,
  "parse_status": "ready",
  "page_count": 12,
  "meta": {
    "title": "uploaded.pdf"
  }
}
```

### 4.4 视觉路由修改

#### 修改 `POST /api/chat/upload-screenshot`

- 缓存介质从进程内存改为 Redis 或统一附件表
- 返回结构可附带过期时间

#### 修改 `POST /api/chat/vision-relay`

请求新增：

```json
{
  "conversation_id": 2001,
  "paper_id": "paper_xxx",
  "question": "图 2 表达了什么",
  "image_id": "uuid",
  "history": []
}
```

---

## 5. 前端 Store 状态变更

### 5.1 `chatStore` 状态树变更

当前 [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts) 仅有 `messages` 与 `settings`。建议改为：

```typescript
interface ChatMessage {
  id: string
  conversationId: string
  role: 'user' | 'assistant'
  content: string
  thinking: string
  thinkingPreview: string
  hasThinking: boolean
  isThinking: boolean
  isStreaming: boolean
  sources: unknown[]
  attachments: ChatAttachmentRef[]
  createdAt?: string
}

interface ConversationSummary {
  id: string
  title: string
  scope: 'global' | 'paper'
  scopeKey?: string
  messageCount: number
  updatedAt: string
  lastAccessedAt: string
}

interface ChatAttachmentRef {
  id: string
  name: string
  mimeType: string
  modality: 'image' | 'pdf'
  parseStatus: 'uploaded' | 'processing' | 'ready' | 'failed'
  progress?: number
}

interface ChatState {
  activeConversationId: string | null
  activeScope: 'global' | 'paper'
  conversationMap: Record<string, ConversationSummary>
  messageMap: Record<string, ChatMessage[]>
  pendingAttachments: ChatAttachmentRef[]
  isStreaming: boolean
  streamPhase: 'idle' | 'searching' | 'reranking' | 'answering' | 'error'
  loadingHistory: boolean
  settings: {
    maxHistoryTurns: number
    temperature: number
  }
}
```

新增 Action：

- `loadConversations()`
- `openConversation(conversationId)`
- `ensurePaperConversation(paperId)`
- `uploadAttachment(file)`
- `sendMessage(payload)`
- `deleteMessage(messageId)`
- `regenerateMessage(messageId)`
- `syncConversationAccess(conversationId)`
- `cleanupExpiredLocalCache()`

### 5.2 `authStore` 状态树变更

当前 [frontend/src/stores/authStore.ts](frontend/src/stores/authStore.ts) 的 `AuthUser` 只有 `phone`。改造后建议为：

```typescript
interface AuthUser {
  user_id: number
  email: string
  role: 'user' | 'admin'
  email_verified?: boolean
}
```

`login()` 入参改为：

```typescript
login(email: string, password: string)
```

保留 `pendingChatMessage` 即可，无需额外大改。

---

## 6. 第三方依赖与基础设置

### 6.1 SMTP 邮件配置

需要在 [backend/app/core/config.py](backend/app/core/config.py) 与 [.env.example](.env.example) 中新增：

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=example_user
SMTP_PASSWORD=example_password
SMTP_FROM_EMAIL=no-reply@example.com
SMTP_FROM_NAME=AIGC_NEWS
SMTP_USE_TLS=true
AUTH_REGISTER_INVITE_CODE=internal_testing
FRONTEND_BRAND_NAME=Brand
VITE_APP_BRAND_NAME=Brand
VISION_API_KEY=
```

### 6.2 新增 Python 依赖

基于 [backend/requirements.txt](backend/requirements.txt)，建议新增：

- `aiosmtplib` 用于异步 SMTP 发信
- `email-validator` 用于邮箱格式校验

建议追加：

```txt
aiosmtplib
email-validator
```

### 6.3 新增前端依赖

前端原则上可不新增大型依赖，优先使用浏览器原生 `File`, `FormData`, `XMLHttpRequest upload progress` 实现上传进度。

若后续要增强 PDF 上传前预览，可选新增：

- `nanoid` 用于前端临时 ID

### 6.4 基础安全设置

- 将 [backend/app/api/routes_vision.py](backend/app/api/routes_vision.py) 中硬编码 `_VISION_API_KEY` 改为环境变量
- 图片缓存从进程内存迁移至 Redis 或统一附件表
- 附件上传增加 MIME 白名单与大小限制
- SMTP 失败时记录审计日志但不回显敏感错误

---

## 7. 开发分期计划

> 说明：按四大类划分为四个阶段。此处仅给出任务拆分，不给出时间估算。

### 第一阶段：UI/UX 与交互优化

具体任务：

- 升级 [frontend/src/style.css](frontend/src/style.css) 与 [frontend/tailwind.config.js](frontend/tailwind.config.js) 的设计 Token
- 改造 [frontend/src/views/LayoutView.vue](frontend/src/views/LayoutView.vue) 实现全局科技感背景与 Footer
- 改造 [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue) 增加页面级 Loading Spinner
- 改造 [frontend/src/components/PdfCanvasViewer.vue](frontend/src/components/PdfCanvasViewer.vue) 与 [frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue) 增加 PDF 真实进度条
- 重构 [frontend/src/views/ReportView.vue](frontend/src/views/ReportView.vue) 视觉层次与阅读体验

工作量等级：中

### 第二阶段：RAG 问答与多模态能力增强

具体任务：

- 为 [frontend/src/views/ChatView.vue](frontend/src/views/ChatView.vue) 增加图片/PDF 上传入口
- 设计并实现附件上传 API 与附件状态查询 API
- 新增 [backend/app/services/chat/attachment_service.py](backend/app/services/chat/attachment_service.py)
- 改造 [backend/app/api/routes_chat.py](backend/app/api/routes_chat.py) 支持 `attachment_ids`、`conversation_id`、`paper_id`
- 修复思维链事件拆分与前端默认折叠展示
- 实现重新生成、删除消息、终止生成等控制操作

工作量等级：高

### 第三阶段：会话历史与状态管理

具体任务：

- 在 [backend/app/repositories/mysql_repo.py](backend/app/repositories/mysql_repo.py) 增加 `conversations`、`chat_messages`、`chat_attachments` 表初始化与 CRUD
- 新增 [backend/app/services/chat/conversation_service.py](backend/app/services/chat/conversation_service.py)
- 改造 [frontend/src/stores/chatStore.ts](frontend/src/stores/chatStore.ts) 为多会话状态树
- 修复 [frontend/src/views/PaperReadView.vue](frontend/src/views/PaperReadView.vue) 与 `paper_id` 绑定问题
- 增加 LRU 裁剪、7 天清理 5 条、点击历史更新时间
- 在 [backend/app/core/scheduler.py](backend/app/core/scheduler.py) 增加会话清理 Job

工作量等级：高

### 第四阶段：认证鉴权改造

具体任务：

- 新增 [backend/app/services/email_service.py](backend/app/services/email_service.py)
- 改造 [backend/app/api/routes_auth.py](backend/app/api/routes_auth.py) 为邮箱 OTP 注册链路
- 改造 [backend/app/core/auth.py](backend/app/core/auth.py) 与 JWT payload 字段
- 改造 [frontend/src/views/RegisterView.vue](frontend/src/views/RegisterView.vue) 与 [frontend/src/views/LoginView.vue](frontend/src/views/LoginView.vue)
- 改造 [frontend/src/stores/authStore.ts](frontend/src/stores/authStore.ts) 使用邮箱身份
- 更新 `.env` 与依赖，移除 SMS 主路径

工作量等级：中

---

**这份架构设计是否符合您的期望？如果同意，我将为您开始按阶段编写代码。**
