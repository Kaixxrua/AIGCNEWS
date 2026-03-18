# AIGC_NEWS 项目代码深度分析报告

> 生成时间: 2026-03-17  
> 目的: 为架构设计文档收集信息，覆盖前端聊天、PDF阅读器、布局样式、认证、后端认证、聊天多模态、数据库共 7 大模块 20+ 文件

---

## 1. 前端 — 聊天相关

### 1.1 `frontend/src/views/ChatView.vue` (566 行)

**核心结构：**
- `<script setup lang="ts">` 单文件组件，使用 Composition API
- 依赖：`vue`, `vue-router`, `markdown-it`, `katex`, `chatStore`, `authStore`
- 核心 ref：`inputText`, `listRef`, `showSettings`, `isSending`, `localSettings`, `rawModeSet`, `thinkingExpanded`, `autoScroll`

**消息渲染逻辑：**
- 使用 `computed(() => store.messages)` 获取消息列表
- 每条消息通过 `msg.role` 区分 `user` / `assistant`
- AI 消息分三层渲染：
  1. **思维链区域** (`msg.thinking || msg.isThinking`) — 可折叠面板，`isThinking` 时显示 spinner + "思考中…"，完成后变为"查看思维链"可展开
  2. **等待点动画** — 当 `!msg.content && !msg.thinking && !msg.isThinking` 时显示三个 bounce 动画点
  3. **正文区域** (`msg.content`) — 渲染 Markdown + LaTeX，支持"源码/渲染"切换和"复制公式"

**Loading Spinner：**
- 发送按钮内有 spinner（`isSending` 时显示旋转 SVG）
- AI 消息等待时有三点 bounce 动画
- 思维链进行时有 `animate-spin` 的 SVG spinner
- **没有全局 loading overlay/spinner**

**思维链(think)处理：**
- `thinkingExpanded` ref 记录每个消息索引的展开状态
- `toggleThinking(idx)` 切换展开/折叠
- 思维链内容显示为 `font-mono text-[11px]` 的等宽字体 pre-wrap
- 思维链进行时有光标闪烁动画 `animate-pulse`

**输入框结构：**
- `<textarea>` 元素，`rows="1"`, 可调整大小 `resize-y`, 最大高度 `max-h-36`
- Enter 发送，Shift+Enter 换行
- `isSending` 时 disabled

**Markdown/LaTeX 渲染管线：**
- `renderLatex(text)` → 先保护代码块 → 依次处理 `$$`, `\[`, `\begin{env}`, `\(`, `$` → 恢复代码块
- `renderMarkdown(text)` → 先走 `renderLatex` → 再走 `markdown-it` 渲染 → 后处理 `<code>` 中残留 LaTeX
- KaTeX 块级公式外包 `formula-wrap` 容器，含浮动复制按钮

**关键发现与限制：**
- **无 paper_id 绑定**：ChatView 的聊天是全局的，不与特定论文关联
- **未登录拦截**：`handleSend` 中检测 `!authStore.isLoggedIn` 时缓存消息并跳转 `/login`
- **消息历史仅内存**：`store.messages` 是 Pinia 内存状态，刷新即丢失
- **自动滚动**：通过 `autoScroll` ref + wheel/touch 事件监听实现，用户上滚时停止自动滚动
- 来源卡片 `sourceTypeBadgeClass` 函数始终返回同一个类名（`bg-white text-stone-600`），未按类型区分颜色 — **潜在 UI 改进点**

**架构建议：**
- 若需持久化聊天历史，需新增 conversations/chat_history 表并改造 chatStore
- 思维链 UI 已完善，后续可直接复用
- 可考虑将 LaTeX 渲染管线抽离为独立 composable，ChatView 和 PaperReadView 当前各自重复实现

---

### 1.2 `frontend/src/stores/chatStore.ts` (217 行)

**类型定义：**
```typescript
type ChatRole = 'user' | 'assistant'

interface ChatMessage {
  role: ChatRole
  content: string
  thinking: string
  isThinking: boolean
  sources: unknown[]
}

type StreamPayload =
  | { type: 'sources'; data: unknown[] }
  | { type: 'content'; data: string }
  | { type: 'thinking'; data: string }
  | { type: 'status'; data: string }
  | { type: string; data?: unknown }

interface ChatSettings {
  maxHistoryTurns: number  // 默认 5
  temperature: number      // 默认 0.7
}
```

**状态管理：**
- Pinia Options Store (`defineStore('chat', { state, actions })`)
- `messages: ChatMessage[]` — 纯内存，无持久化
- `settings: ChatSettings` — 无持久化

**核心 Action `sendMessage(text)`：**
1. 构建 `history` — 取最近 `maxHistoryTurns * 2` 条消息，过滤空内容
2. 追加 user 消息 + 空 assistant 占位消息
3. 通过 `useEventSource().connect()` 发起 SSE 连接到 `/chat/stream`
4. **打字机效果**：
   - `contentQueue` / `thinkingQueue` 存放待显示字符
   - `setInterval(16ms)` — 约 60fps
   - thinking: 每帧 12 字符 ≈ 720字/秒（快速扫过）
   - content: 每帧 3 字符 ≈ 180字/秒（丝滑打字感）
5. SSE 结束后等打字队列消费完才收尾
6. 错误处理：立即停止打字机，显示错误消息

**与 paper_id 的绑定：**
- **完全没有 paper_id 概念**。chatStore 是通用聊天，不区分论文上下文
- 发送请求体：`{ message, history, temperature }` — 无 paper_id 字段

**历史记录管理：**
- `clearMessages()` 清空所有消息
- **无分页、无本地持久化、无服务端历史同步**

**架构建议：**
- 若需实现"按论文聊天"，需改造为 `Map<paperId, ChatMessage[]>` 或引入 conversation_id
- 打字机实现很精巧但耦合在 store 里，可考虑抽离
- 建议添加 localStorage/sessionStorage 持久化或服务端历史

---

### 1.3 `frontend/src/composables/useEventSource.ts` (126 行)

**核心结构：**
```typescript
type SseConnectParams = {
  url: string
  body: Record<string, unknown>
  onMessage: (payload: unknown) => void
  onDone?: () => void
  onError?: (error: unknown) => void
}

function parseSseEvent(rawEvent: string): unknown | null
function useEventSource(): { connect: (params: SseConnectParams) => Promise<AbortController> }
```

**SSE 实现方式：**
- **不使用原生 EventSource API**，而是用 `fetch` + `ReadableStream` 手动解析
- 原因：需要 POST 请求体（原生 EventSource 只支持 GET）
- 从 `localStorage` 读取 `auth_token` 附加到 `Authorization: Bearer` header

**事件解析：**
- 用 `\n\n` 分割事件块
- 每个块内提取 `data:` 行
- `[DONE]` 视为结束信号 → 调用 `onDone()`
- JSON 解析失败时回退为 `{ type: 'content', data: dataText }`

**限制与 Bug：**
- `AbortController` 被创建但 `connect()` 返回后外部无法获取（返回值被忽略）— 无法从外部取消请求
- 没有超时机制
- 没有重连机制
- 缓冲区处理基本正确，兼容 `\r\n` 换行

**架构建议：**
- 可增加 `abort()` 方法导出，支持用户取消生成
- 可增加连接超时和自动重连
- 当前实现健壮，适合作为统一 SSE 基础设施

---

## 2. 前端 — PDF 阅读器

### 2.1 `frontend/src/views/PaperReadView.vue` (682 行)

**布局结构：**
- 水平分屏：左 35% 聊天区 + 右 65% PDF 阅读区
- 使用模块级 `<script>` 块持久化对话记录（`persistedMessages`, `persistedInputText`），组件重建不丢失

**左侧聊天区特点：**
- 独立于全局 ChatView，有自己的消息列表 `PaperMsg[]`
- `PaperMsg` 接口扩展了 `imageBase64`, `visionExtract`, `showRaw` 字段
- 支持两种发送模式：
  1. `sendText()` — 普通文本问答，调 `/chat/stream`
  2. `sendVision()` — 截图视觉问答，先调 `/chat/upload-screenshot` 上传，再调 `/chat/vision-relay` SSE

**与聊天的关联方式：**
- `sendText()` 调用全局 `/chat/stream` 端点（与 ChatView 相同）
- `sendVision()` 发送 `paper_id`（从路由 `route.params.id` 获取）
- 历史记录取最近 12 条（vision）/ 10 条（text），**不使用 chatStore**

**切换文档时的状态处理：**
- `watch(paperId)` 监听路由参数变化
- 切换时：关闭 visionPopup，重新加载论文元数据
- **左侧对话保持不变**（模块级 ref 不清空）

**Vision 弹窗流程：**
1. 用户在 PDF 上左键拖选区域
2. `PdfCanvasViewer` emit `rightclick-region` 事件，携带 `base64` 截图
3. 弹出浮窗显示截图预览 + 输入框
4. 用户输入问题后 → `sendVision()`

**LaTeX 渲染：**
- 与 ChatView 完全重复的实现（`renderLatex`, `renderMd`, `tryKatex` 等）
- **代码重复**：两个文件各自实现了完整的 KaTeX 渲染管线

**限制：**
- PaperReadView 的聊天不共享 chatStore，两个页面的历史完全独立
- 模块级 ref 意味着所有论文共享同一个对话记录（不按 paper_id 分组）
- 没有 thinking/思维链 UI（PaperReadView 的 PaperMsg 没有 thinking 字段）

**架构建议：**
- LaTeX 渲染管线应抽为共享 composable
- 对话记录应按 paper_id 分组持久化
- 可考虑统一 ChatView 和 PaperReadView 的消息模型

---

### 2.2 `frontend/src/components/PdfCanvasViewer.vue` (476 行)

**核心结构：**
- Props: `pdfUrl: string | null | undefined`
- Emits: `rightclick-region` (payload: `{ pageIndex, base64, x, y, w, h }`)
- 使用 `pdfjs-dist` 库，Worker 通过 Vite `?url` 语法导入

**PDF 渲染流程：**
1. `onMounted` → `startRenderWhenReady(url)` — 检查祖先容器是否有正高度
2. 若祖先高度为 0（Transition 动画期间），用 `ResizeObserver` 等待
3. `loadPdf(url)` → `pdfjsLib.getDocument()` → 逐页 `getPage()` → `page.render()` 到 Canvas
4. Canvas 手动创建并 `appendChild` 到容器

**渲染进度信息：**
- `isLoading` ref — 显示 spinner + "PDF 加载中…"
- `totalPages` ref — 记录总页数，但**未在 UI 中显示渲染进度（如 "第 3/10 页"）**
- `errorMessage` ref — 显示错误详情
- `pageEntries` ref — 已渲染页面数组，可用于计算进度

**选区截图：**
- 左键拖选（mousedown → mousemove → mouseup），显示蓝色半透明矩形
- 支持跨页长截图 — 通过 offscreen canvas 合并多页片段
- Base64 输出：优先 JPEG 0.85 质量，超 500KB 降至 0.6
- **阈值**：选区宽高 < 8px 时忽略

**限制：**
- 缩放比例 `scale = 1.5` 硬编码，无用户调节
- 没有页码导航/跳转功能
- 没有文本选择层（纯 Canvas，不支持复制文本）
- `contextmenu` 被 `preventDefault` — 用户无法右键操作

**架构建议：**
- 可添加缩放控制条和页码显示
- 可通过 PDF.js TextLayer 添加文本选择支持
- 渲染进度可以通过 `pageEntries.length / totalPages` 暴露给父组件

---

## 3. 前端 — 布局与样式

### 3.1 `frontend/src/views/LayoutView.vue` (314 行)

**主布局结构：**
```
全屏容器 (h-screen w-full flex items-center justify-center)
├── 居中悬浮画板 .main-canvas (92% width, max-width 1400px, 84vh height)
│   ├── 顶部全局搜索条 (absolute, 44px height, z-100)
│   └── 内容区 (absolute inset-0, pt-[44px])
│       └── <router-view>
├── 底部悬浮 Dock 导航栏 (fixed bottom-28px, 胶囊形)
│   ├── Dashboard
│   ├── Chat
│   ├── Report
│   └── Monitor (requiresAdmin)
└── 右上角 Auth 浮岛 (fixed top-28px right-28px)
    └── 登录/退出按钮
```

**关键发现：**
- **没有 Footer 区域** — 底部 Dock 是 fixed 定位悬浮的，不属于内容流
- 主面板是毛玻璃效果 (`backdrop-filter: blur(32px) saturate(180%)`)
- 导航栏是 macOS 风格的 Dock，带 hover 放大和 tooltip 效果
- **没有路由切换动画**（`router-view` 没有 `<Transition>` 包裹，虽然 CSS 中定义了 `spatial-fade` 但未使用）
- Monitor 导航项需要 admin 权限 (`v-show="!item.requiresAdmin || authStore.isAdmin"`)

**架构建议：**
- 若需添加全局 Footer，可在 `.main-canvas` 内部 `router-view` 下方添加
- 底部 Dock 的 28px bottom 间距需与内容区协调，避免遮挡
- 可激活路由切换动画提升体验

---

### 3.2 `frontend/src/views/ReportView.vue` (260 行)

**布局结构：**
- 垂直 flex 布局：页头 → 控制面板(Admin) → 错误提示 → 内容区
- 控制面板仅 Admin 可见 (`v-if="authStore.isAdmin"`)
- 非 Admin 用户只能看到页头 + 缓存内容

**报告类型：**
- 6 种：综合简报(all), 学术(arxiv), 工程(github), 行业(news), 产品(producthunt), 社区(hackernews)
- 3 种周期：日报(daily), 周报(weekly), 月报(monthly)
- 限制：all/news/producthunt/hackernews 仅支持日报

**生成流程：**
- SSE 连接到 `/report/daily/stream`
- 内容累加显示，支持自动滚动
- 有缓存检测（`/report/latest` GET）
- 生成中显示 "正在生成" + 光标闪烁

**样式特点：**
- 使用全局 `glass-card` 毛玻璃卡片
- `prose-content` 类渲染 Markdown
- 胶囊形 Tab 按钮选中状态为 `bg-stone-700 text-white`

---

### 3.3 `frontend/src/style.css` (268 行)

**全局样式变量/设计系统：**
- 字体：`Inter` (无衬线) + `Playfair Display` (衬线/标题)
- 底色：`#F9F9F8`（暖调米白）
- 主色系：stone 色系（stone-400 到 stone-900）
- 圆角策略：全部胶囊形（`rounded-full` 按钮/输入框/标签）

**组件类：**
| 类名 | 用途 |
|------|------|
| `.glass` | 毛玻璃效果基础 |
| `.glass-card` | 毛玻璃 + 圆角 24px |
| `.card-hover` | 悬浮提升效果 |
| `.btn-primary` | 主按钮（stone-700 底色，白字） |
| `.btn-secondary` | 次按钮（透明底色，stone-600 字） |
| `.btn-danger` | 危险按钮（红色） |
| `.btn-ghost` | 幽灵按钮（透明） |
| `.tab-active` / `.tab-inactive` | Tab 标签 |
| `.badge` | 徽章 |
| `.input` | 输入框（`rounded-full` 胶囊形） |
| `.divider` | 分割线 |
| `.status-dot` | 状态点 |
| `.prose-content` | Markdown 排版样式 |
| `.stagger-enter` | 卡片进场动画 |

**prose-content 排版：**
- h1/h2 使用 Playfair Display 衬线字体
- 正文 stone-500，标题 stone-900/stone-800
- 表格有 hover 行高亮

---

### 3.4 `frontend/tailwind.config.js` (85 行)

**自定义主题扩展：**

| 分类 | 配置 |
|------|------|
| **colors.surface** | DEFAULT=#fff, subtle=#fafaf9, muted=#f5f5f4 |
| **colors.border** | DEFAULT=#e7e5e4, strong=#d6d3d1 |
| **colors.ink** | DEFAULT=#1c1917, secondary=#57534e, muted=#78716c, faint=#a8a29e |
| **colors.accent** | DEFAULT=#44403c, hover=#57534e |
| **colors.brand** | green/purple/blue/amber/rose/teal/sky/lime |
| **fontFamily** | sans: Inter, serif: Playfair Display, mono: JetBrains Mono |
| **fontSize** | 2xs: 0.65rem |
| **animation** | fade-in, slide-up, pulse-dot |
| **boxShadow** | card, card-md, card-lg, inner-sm |

---

## 4. 前端 — 认证

### 4.1 `frontend/src/views/LoginView.vue` (141 行)

**表单结构：**
- 手机号输入 (`type="tel"`, `autocomplete="tel"`)
- 密码输入 (`type="password"`, `autocomplete="current-password"`)
- 登录按钮（loading 时显示 spinner）
- 底部"立即注册"链接 → `/register`

**登录逻辑：**
- 调用 `authStore.login(phone, password)`
- 成功后跳转 `route.query.redirect` 或 `/`
- 错误显示在 `fade-msg` 过渡动画中

**限制：**
- 没有"忘记密码"功能
- 没有密码强度提示
- 手机号没有前端格式校验（仅后端校验）

---

### 4.2 `frontend/src/views/RegisterView.vue` (255 行)

**SMS OTP 注册流程：**
1. 输入手机号（前端校验 `^1[3-9]\d{9}$`）
2. 点击"获取验证码"→ `POST /auth/send-otp`
3. 60 秒倒计时防重发
4. 输入 6 位数字验证码 + 设置密码 + 确认密码
5. 点击注册 → `POST /auth/register { phone, sms_code, password }`
6. 注册成功后自动调用 `authStore.login()` 登录
7. 跳转到 `redirect` 参数页或首页

**表单字段：**
- 手机号 + 验证码按钮（横排）
- 验证码输入（`inputmode="numeric"`, `maxlength="6"`）
- 密码 + 确认密码
- 实时校验：手机号格式、密码一致性

**架构建议（替换为邮箱验证码）：**
- 前端改动点：`phone` → `email`，校验正则改为邮箱格式
- `sendOtp` 调用端点改为 `/auth/send-email-otp`
- 后端 `SmsService` 替换为 `EmailService`
- OTP 存储逻辑可复用（Redis key 前缀从 `sms:` 改为 `email:`）

---

### 4.3 `frontend/src/stores/authStore.ts` (97 行)

**类型定义：**
```typescript
interface AuthUser {
  user_id: number
  phone: string
  role: 'user' | 'admin'
}
```

**状态：**
- `token: ref<string | null>` — 从 localStorage 恢复
- `user: ref<AuthUser | null>` — 从 `/auth/me` 拉取
- `pendingChatMessage: ref<string>` — 未登录时缓存的聊天消息

**Computed：**
- `isLoggedIn` — `!!token.value`
- `isAdmin` — `user.value?.role === 'admin'`

**Actions：**
- `login(phone, password)` → `POST /auth/login` → 保存 token → `fetchMe()`
- `logout()` → 清除 token/user → 跳转 `/login`
- `fetchMe()` → `GET /auth/me`
- `initFromStorage()` → 从 localStorage 恢复 token + 调 `fetchMe()` 验证
- `savePendingMessage(msg)` / `consumePendingMessage()` — 聊天消息暂存

**限制：**
- 没有 token 自动刷新机制
- `AuthUser` 接口只有 `phone`，若改为邮箱需加 `email` 字段
- `logout()` 中动态 import router 有轻微性能开销

---

## 5. 后端 — 认证

### 5.1 `backend/app/api/routes_auth.py` (166 行)

**API 端点：**

| 方法 | 路径 | 功能 | 认证 |
|------|------|------|------|
| POST | `/auth/send-otp` | 发送短信验证码 | 无 |
| POST | `/auth/register` | 注册（手机+密码+验证码） | 无 |
| POST | `/auth/login` | 登录（手机+密码） | 无 |
| GET | `/auth/me` | 获取当前用户信息 | RequireUser |

**请求体 Schema：**
```python
class SendOtpRequest(BaseModel):
    phone: str

class RegisterRequest(BaseModel):
    phone: str
    password: str
    sms_code: str

class LoginRequest(BaseModel):
    phone: str
    password: str
```

**注册流程细节：**
1. 校验手机号格式 (`^1[3-9]\d{9}$`)
2. `sms.verify_otp(phone, code, consume=False)` — 先验证不删除
3. `db.get_user_by_phone()` — 检查重复
4. `hash_password()` → `db.create_user(phone, "", hashed, "user")`
5. `sms.consume_otp()` — 全部成功后才删除验证码

**登录流程：**
1. 校验手机号格式
2. `db.get_user_by_phone()` + `verify_password()`
3. `create_access_token({ user_id, role, phone })`
4. 返回 `{ access_token, token_type, role }`

**`/auth/me` 返回：**
```json
{ "user_id": 1, "phone": "13800138000", "role": "user" }
```

---

### 5.2 `backend/app/core/auth.py` (98 行)

**密码哈希：**
- 使用 `bcrypt` 库（不依赖 passlib）
- `hash_password(plain)` → `bcrypt.hashpw()`
- `verify_password(plain, hashed)` → `bcrypt.checkpw()`

**JWT：**
- 使用 `python-jose` (`jose.jwt`)
- `create_access_token(data)` — payload 含 `exp` 字段
- `decode_access_token(token)` — 失败抛 HTTP 401
- 配置从 `settings`: `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`

**FastAPI 依赖：**
- `RequireUser` — 要求有效 Bearer JWT，返回 payload dict
- `RequireAdmin` — 在 RequireUser 基础上检查 `role == 'admin'`
- 使用 `HTTPBearer(auto_error=False)` — 缺 token 时不自动报错，手动处理

---

### 5.3 `backend/app/services/sms_service.py` (125 行)

**类结构：**
```python
class SmsService:
    def __init__(self, redis_client, sms_api_key: str = "")
    async def send_otp(self, phone: str) -> None
    async def verify_otp(self, phone: str, code: str, consume: bool = True) -> bool
    async def consume_otp(self, phone: str) -> None
```

**Redis Key 设计：**
- `sms:code:<phone>` — OTP 验证码，TTL 300s (5分钟)
- `sms:lock:<phone>` — 防刷锁，TTL 60s

**Dev 模式：**
- `SMS_API_KEY` 为空时，OTP 打印到日志而非发送短信
- Redis 不可用时，OTP 功能完全降级（无法验证）

**替换为邮箱验证码的改造点：**
- Key 前缀改为 `email:code:` / `email:lock:`
- `send_otp` 中替换短信 API 调用为邮件发送（如 SMTP / SendGrid / AWS SES）
- 校验逻辑完全可复用
- 建议创建 `EmailService` 继承或平行于 `SmsService`

---

## 6. 后端 — 聊天与多模态

### 6.1 `backend/app/api/routes_chat.py` (75 行)

**端点：**
| 方法 | 路径 | 功能 | 认证 |
|------|------|------|------|
| POST | `/chat/stream` | RAG 流式聊天 | RequireUser |

**请求体：**
```python
class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
```

**SSE 流格式：**
```
data: {"type": "status", "data": "searching"}
data: {"type": "status", "data": "reranking"}
data: {"type": "sources", "data": [...]}
data: {"type": "thinking", "data": "..."}
data: {"type": "content", "data": "..."}
data: [DONE]
```

**关键发现：**
- **无 paper_id / conversation_id** — 每次请求独立，无服务端会话管理
- `HybridRetriever` 和 `ChatService` 每次请求重新实例化（无连接池复用）
- 认证使用 `RequireUser` 但**当前用户信息（`_`）被丢弃**，未用于个性化或日志

**架构建议：**
- 添加 `paper_id` 可选字段，用于限定 RAG 检索范围
- 添加 `conversation_id` 用于服务端历史管理
- `HybridRetriever` / `ChatService` 可改为应用级单例

---

### 6.2 `backend/app/api/routes_vision.py` (294 行)

**端点：**
| 方法 | 路径 | 功能 | 认证 |
|------|------|------|------|
| POST | `/chat/upload-screenshot` | 上传截图到内存缓存 | RequireUser |
| POST | `/chat/vision-relay` | 流式视觉问答 | RequireUser |

**截图上传：**
```python
class UploadScreenshotRequest(BaseModel):
    image_base64: str  # min_length=10
    mime_type: str = "image/jpeg"
# 返回: { "image_id": "<uuid>" }
```

**内存缓存：**
- `_screenshot_cache: Dict[str, Tuple[base64_str, mime_type, expire_ts]]`
- TTL 300 秒（5分钟）
- `asyncio.Lock` 保护并发访问
- 每次写入时清理过期条目

**视觉问答请求：**
```python
class VisionRelayRequest(BaseModel):
    paper_id: Optional[str] = None
    question: str  # max_length=2000
    image_id: str
    history: List[dict] = []
```

**模型调用：**
- 直接用 `httpx` 调 SiliconFlow API (`https://api.siliconflow.cn/v1`)
- 模型：`Pro/moonshotai/Kimi-K2.5`
- **API Key 硬编码在源码中** — 严重安全隐患
- 带 3 次退避重试（429 限速时等待 30s × attempt）

**SSE 流格式：**
```
data: {"type": "status", "data": "🔍 正在分析图像内容…"}
data: {"type": "content", "data": "..."}
data: [DONE]
```

**限制：**
- API Key 硬编码 — 应迁移到环境变量
- 内存缓存在多进程/多实例部署时不共享 — 应改用 Redis
- 没有 `vision_extract` 事件（前端 PaperReadView 监听了但后端未发送）
- System Prompt 硬编码为中文

---

### 6.3 `backend/app/services/rag/chat_service.py` (264 行)

**类结构：**
```python
class ChatService:
    def __init__(self, retriever: HybridRetriever)
    async def stream_chat(self, query, history, max_history_turns, temperature) -> AsyncGenerator[Dict, None]
    @staticmethod def _build_context(docs: List[Document]) -> str
    @staticmethod def _build_sources(docs: List[Document]) -> List[Dict]
    @staticmethod def _safe_meta(meta: Dict) -> Dict
```

**流式生成过程：**
1. `yield status "searching"` — 检索状态
2. `retriever.search(query)` — 混合检索
3. `yield status "reranking"` — 精排状态
4. `rerank(query, raw_docs)` — LLM 二次精排
5. `_build_context(ranked_docs)` — 构建上下文字符串
6. `_format_history(history)` — 格式化对话历史
7. `yield sources` — 推送参考来源
8. `llm.astream(prompt)` — 流式生成回答

**思维链提取（`_extract_thinking_and_content`）：**
兼容 4 种格式：
1. Anthropic 原生 `content` 列表（`thinking`/`thinking_delta`/`text`/`text_delta`）
2. `additional_kwargs["reasoning_content"]`（OpenAI 兼容代理）
3. `additional_kwargs["thinking"]`
4. `<think>...</think>` 标签（DeepSeek-R1/QwQ）

**来源构建（`_build_sources`）：**
- 只展示 `retriever='vector'` 或 `'hybrid'` 的文档
- 按 rerank_score 降序排列
- URL 去重
- 返回字段：`id, score, source, title, url, published_date`

**Prompt 模板：**
```
你是一个专业的 AIGC 技术助手。请基于以下上下文（Context）回答用户的问题。
上下文来自三类数据源：[arxiv], [github], [news], [neo4j]
...
[上下文开始]
{context_str}
[上下文结束]
{chat_history}
用户问题: {query}
```

**架构建议：**
- `get_chat_model()` 每次调用可能创建新连接，建议缓存
- 可添加 `paper_id` 参数用于限定检索范围（如只检索特定论文的 chunks）
- 思维链提取逻辑非常完备，直接可用

---

## 7. 后端 — 数据库

### 7.1 `backend/app/repositories/mysql_repo.py` (1198 行)

**数据库连接：**
- 使用 `DBUtils.PooledDB` 连接池（pymysql）
- `mincached=2, maxcached=5, maxconnections=20`
- `autocommit=False` — 每次操作需手动 commit

**表结构一览：**

| 表名 | 主键 | 用途 |
|------|------|------|
| `documents` | id VARCHAR(255) | 文档元数据（论文/新闻/项目） |
| `ingestion_tasks` | id INT AUTO_INCREMENT | 数据采集任务记录 |
| `briefings` | id INT AUTO_INCREMENT | 自动化简报内容 |
| `rag_evaluations` | id INT AUTO_INCREMENT | RAG 评测结果 |
| `github_repo_candidates` | repo_id VARCHAR(255) | GitHub 仓库候选 |
| `github_repo_snapshots` | id INT AUTO_INCREMENT | GitHub 仓库指标快照 |
| `github_trending_hits` | id INT AUTO_INCREMENT | GitHub 趋势榜命中记录 |
| `document_rank_snapshots` | id INT AUTO_INCREMENT | 文档排名快照 |
| `users` | id INT AUTO_INCREMENT | 用户表 |

**users 表详细结构：**
```sql
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    username VARCHAR(64),
    hashed_password VARCHAR(256) NOT NULL,
    role ENUM('user', 'admin') DEFAULT 'user',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

**用户相关方法：**
- `get_user_by_phone(phone)` → `Dict | None`
- `create_user(phone, username, hashed_password, role)` → `int` (new id)

**关键发现：**
- **没有 conversations / chat_history 相关表** — 聊天历史完全在前端内存中
- **没有 email 字段** — users 表只有 phone，若改为邮箱登录需 ALTER TABLE
- `username` 字段在注册时传空字符串，从未被使用
- 所有方法都是同步的（`pymysql` 不支持 async），在路由中通过 `asyncio.to_thread()` 包装
- `_init_schema()` 在每次实例化时执行 — 包含 CREATE TABLE IF NOT EXISTS + ALTER TABLE（增量迁移）

**documents 表关键字段：**
- `local_pdf_path VARCHAR(512)` — PDF 本地路径
- `indexed TINYINT` — 是否已建索引
- `in_daily/in_weekly/in_monthly TINYINT` — 是否已入选简报
- `score/raw_score DOUBLE` — 评分
- `rank_in_period INT` — 期内排名

**架构建议：**
- 新增 `conversations` 表：`id, user_id, paper_id(nullable), title, created_at, updated_at`
- 新增 `chat_messages` 表：`id, conversation_id, role, content, thinking, sources_json, created_at`
- users 表添加 `email VARCHAR(255) UNIQUE` 字段（或将 phone 改为 email）
- 考虑添加 `email_verified BOOLEAN DEFAULT FALSE` 字段
- 同步 pymysql 在高并发下可能成为瓶颈，可考虑迁移到 aiomysql

---

## 8. 跨模块关键发现总结

### 8.1 聊天系统现状

| 维度 | 现状 | 建议 |
|------|------|------|
| 消息存储 | 纯前端内存（Pinia） | 需新增 DB 表 + API |
| 会话管理 | 无 conversation_id | 需设计会话模型 |
| 论文关联 | ChatView 无关联，PaperReadView 有 paper_id 但仅用于 vision | 统一 paper_id 到 chat API |
| 思维链 | 前端完整支持，后端完整提取 | 可直接使用 |
| 打字机效果 | 精巧的帧率控制（thinking 720字/秒, content 180字/秒） | 可保持 |

### 8.2 认证系统现状

| 维度 | 现状 | 建议 |
|------|------|------|
| 登录方式 | 手机号 + 密码 | 改为邮箱 + 密码 |
| 注册验证 | SMS OTP（Redis 存储） | 改为邮箱 OTP |
| JWT | 标准实现（jose + bcrypt） | 可保持 |
| Token 刷新 | 无 | 建议添加 |
| 权限 | user / admin 两级 | 可保持 |

### 8.3 安全问题

1. **Vision API Key 硬编码**：`routes_vision.py` 第 51 行 `_VISION_API_KEY = "sk-zrzg..."` — 必须迁移到环境变量
2. **截图内存缓存**：单进程有效，多实例部署会失效 — 改用 Redis
3. **无 CSRF 保护**：SSE POST 请求无 CSRF token（JWT 部分缓解）
4. **无速率限制**：聊天 API 无速率限制（除 SMS 有 Redis 锁）

### 8.4 代码重复

- **LaTeX 渲染管线**：`ChatView.vue` 和 `PaperReadView.vue` 各自独立实现了完整的 KaTeX 渲染逻辑（约 100+ 行重复）
- **copyToClipboard**：两个文件各自实现
- **建议**：抽离为 `composables/useLatexRenderer.ts` 和 `composables/useClipboard.ts`

### 8.5 数据库缺失表

当前数据库**没有**以下后续需求可能需要的表：
- `conversations` — 会话管理
- `chat_messages` — 聊天历史持久化
- `user_preferences` — 用户偏好设置
- `email_verification_tokens` — 邮箱验证（若不用 Redis OTP 方案）
