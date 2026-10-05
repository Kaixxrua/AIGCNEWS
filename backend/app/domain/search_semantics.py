from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping

if TYPE_CHECKING:
    from backend.app.repositories.project_catalog import ProjectLexicalRetrievalPlan

TECHNICAL_TOKEN_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9_+#-]|\.(?=[A-Za-z0-9]))*|\.[A-Za-z][A-Za-z0-9]*|[㐀-䶿一-鿿]+"
)
_HAN_RE = re.compile(r"[㐀-䶿一-鿿]")
_PROJECT_REQUEST_PHRASES = (
    "帮我找一下",
    "帮我找",
    "给我推荐",
    "我想要学习",
    "我想学习",
    "find me",
    "recommend me",
)


@dataclass(frozen=True)
class _ProjectConceptSpec:
    concept_id: str
    phrases: tuple[str, ...]
    aliases: tuple[str, ...]


# 词法概念表：触发词（phrases）在查询上命中，别名（aliases）同时用于
# SQL ILIKE 概念组与语义查询扩展。约束：
# 1. 纯 ASCII 触发词按词边界匹配（cli 不命中 client、git 不命中 digital）；
#    含中文等宽字符的短语保持子串匹配。
# 2. 别名会进入 SQL ILIKE 子串匹配，禁用会被常见词误吞的短 ASCII
#    （如 ide→video、md→amd64、otel→hotel、mod→modern、diff→different）。
# 3. 每个概念的第一别名 = 跨语言规范词：多概念命中时仅第一别名参与语义扩展。
_PROJECT_CONCEPT_LEXICON = (
    # —— 编程效率/上下文/记忆/任务/助手（既有概念，扩展双语触发与别名）——
    _ProjectConceptSpec(
        "coding_productivity",
        ("编程开发效率", "编程效率", "开发效率", "编码速度", "coding productivity", "developer productivity"),
        (
            "coding productivity",
            "developer productivity",
            "code intelligence",
            "context optimization",
            "context window optimization",
            "coding agent memory",
            "memory upgrade",
            "开发效率",
            "编程效率",
        ),
    ),
    _ProjectConceptSpec(
        "context_management",
        (
            "上下文管理",
            "上下文压缩",
            "上下文优化",
            "token 消耗",
            "token 节省",
            "令牌消耗",
            "令牌节省",
            "上下文",
            "context management",
            "context compression",
            "context window",
        ),
        (
            "context compression",
            "context management",
            "context optimization",
            "context window",
            "token reduction",
            "上下文窗口",
            "上下文压缩",
            "上下文管理",
        ),
    ),
    _ProjectConceptSpec(
        "codebase_memory",
        (
            "代码库持久记忆",
            "项目持久记忆",
            "代码库记忆",
            "项目记忆",
            "长期记忆",
            "codebase memory",
            "code intelligence",
            "codebase indexing",
        ),
        (
            "codebase memory",
            "code intelligence",
            "codebase indexing",
            "persistent memory",
            "knowledge graph",
            "编程智能体",
            "代码库索引",
            "知识图谱",
        ),
    ),
    _ProjectConceptSpec(
        "agent_task_tracking",
        (
            "Agent 任务跟踪",
            "智能体任务跟踪",
            "任务依赖管理",
            "依赖管理",
            "任务跟踪",
            "任务管理",
            "task tracking",
            "dependency tracking",
            "task management",
        ),
        (
            "task tracking",
            "dependency tracking",
            "coding agent memory",
            "persistent memory",
            "context memory",
            "任务跟踪",
            "持久记忆",
            "上下文记忆",
        ),
    ),
    _ProjectConceptSpec(
        "coding_assistant",
        (
            "编程智能体",
            "编程助手",
            "编码助手",
            "coding agent",
            "coding assistant",
            "ai coding",
            "编程",
        ),
        (
            "coding agent",
            "coding assistant",
            "ai coding",
            "编程智能体",
            "编程助手",
            "编码助手",
            "ai 编程",
        ),
    ),
    _ProjectConceptSpec(
        "developer_tools",
        ("开发者工具", "开发工具", "developer tools", "dev tools", "devtool", "devtools"),
        ("developer tools", "dev tools", "开发者工具", "开发工具"),
    ),
    _ProjectConceptSpec(
        "workflow",
        ("智能体工作流", "工作流", "agent workflow", "workflow", "workflows"),
        ("workflow automation", "agent workflow", "工作流", "智能体工作流"),
    ),
    _ProjectConceptSpec(
        "rag",
        ("知识库问答", "知识库", "retrieval augmented", "检索增强", "rag"),
        ("rag", "knowledge base", "retrieval augmented", "知识库", "检索增强"),
    ),
    _ProjectConceptSpec(
        "self_hosted",
        ("本地部署", "自托管", "私有化部署", "self-hosted", "self hosted", "selfhost", "self hosting"),
        ("self-hosted", "self hosted", "local deployment", "自托管", "本地部署", "私有化部署"),
    ),
    # learning 的别名被测试精确冻结（"tutorial","learning"），只扩展触发词。
    _ProjectConceptSpec(
        "learning",
        ("入门教程", "教程", "入门", "tutorial", "tutorials"),
        ("tutorial", "learning"),
    ),
    _ProjectConceptSpec(
        "agent",
        ("智能体", "ai agent", "agent", "agents"),
        ("agent", "ai agent", "agents", "智能体", "助手"),
    ),
    # —— AI/LLM 工程 ——
    _ProjectConceptSpec(
        "llm",
        ("大语言模型", "大模型", "large language model", "llms", "llm"),
        ("large language model", "llm", "大模型", "大语言模型"),
    ),
    _ProjectConceptSpec(
        "prompt_engineering",
        ("提示词", "提示工程", "prompt engineering", "prompt management", "prompts", "prompt"),
        ("prompt engineering", "prompt management", "prompt", "提示词", "提示工程"),
    ),
    _ProjectConceptSpec(
        "llm_evaluation",
        ("基准测试", "评测", "评估", "benchmarks", "benchmark", "evaluation", "evals", "eval"),
        ("evaluation", "benchmark", "eval", "评测", "评估", "基准测试"),
    ),
    _ProjectConceptSpec(
        "mcp",
        ("model context protocol", "mcp"),
        ("model context protocol", "mcp server", "mcp", "mcp 服务"),
    ),
    _ProjectConceptSpec(
        "function_calling",
        ("工具调用", "工具使用", "function calling", "tool calling", "tool use"),
        ("function calling", "tool calling", "tool use", "工具调用"),
    ),
    _ProjectConceptSpec(
        "multi_agent",
        ("多智能体", "multi-agent", "multi agent", "multiagent", "agent swarm"),
        ("multi-agent", "multi agent", "agent swarm", "多智能体", "swarm"),
    ),
    _ProjectConceptSpec(
        "agent_memory",
        ("智能体记忆", "agent memory", "agentic memory"),
        ("agent memory", "agentic memory", "智能体记忆"),
    ),
    _ProjectConceptSpec(
        "llm_observability",
        ("链路追踪", "可观测", "observability", "opentelemetry", "tracing", "otel"),
        ("observability", "tracing", "trace", "opentelemetry", "可观测性", "链路追踪", "llm observability"),
    ),
    _ProjectConceptSpec(
        "llm_serving",
        (
            "模型推理",
            "推理框架",
            "推理加速",
            "模型部署",
            "模型服务",
            "llm serving",
            "model serving",
            "inference server",
            "llm inference",
        ),
        ("model serving", "llm serving", "inference", "模型推理", "推理框架", "模型服务"),
    ),
    _ProjectConceptSpec(
        "fine_tuning",
        ("微调", "fine-tuning", "fine tuning", "finetuning", "fine-tune", "fine tune", "finetune"),
        ("fine-tuning", "fine tuning", "finetune", "lora", "qlora", "微调"),
    ),
    _ProjectConceptSpec(
        "vector_search",
        ("向量数据库", "向量检索", "向量搜索", "向量库", "vector database", "vector search", "vector db"),
        ("vector database", "vector search", "vector index", "向量数据库", "向量检索"),
    ),
    _ProjectConceptSpec(
        "embedding",
        ("嵌入模型", "文本嵌入", "向量化", "embeddings", "embedding"),
        ("embedding", "embeddings", "text embedding", "向量化", "嵌入"),
    ),
    _ProjectConceptSpec(
        "speech_tts",
        ("语音合成", "语音播报", "配音", "text to speech", "tts"),
        ("text to speech", "tts", "speech synthesis", "语音合成", "配音"),
    ),
    _ProjectConceptSpec(
        "speech_asr",
        ("语音识别", "语音转文字", "语音转写", "speech recognition", "speech to text", "asr"),
        ("speech recognition", "speech to text", "asr", "transcription", "语音识别", "语音转文字"),
    ),
    _ProjectConceptSpec(
        "image_generation",
        ("图像生成", "图像合成", "文生图", "ai 绘画", "ai绘画", "text to image", "image generation"),
        ("text to image", "image generation", "stable diffusion", "图像生成", "文生图", "ai 绘画"),
    ),
    _ProjectConceptSpec(
        "video_generation",
        ("视频生成", "ai 视频", "ai视频", "text to video", "video generation"),
        ("text to video", "video generation", "视频生成", "ai 视频"),
    ),
    _ProjectConceptSpec(
        "code_review",
        ("代码审查", "代码评审", "code review", "code-review", "codereview"),
        ("code review", "code-review", "codereview", "代码审查", "代码评审"),
    ),
    _ProjectConceptSpec(
        "cli",
        ("命令行", "终端", "command line", "command-line", "cli", "tui"),
        ("command line", "command-line", "cli", "terminal", "tui", "命令行", "终端"),
    ),
    _ProjectConceptSpec(
        "terminal_emulator",
        ("终端模拟器", "terminal emulator"),
        ("terminal emulator", "终端模拟器", "terminal"),
    ),
    _ProjectConceptSpec(
        "chatbot",
        ("聊天机器人", "对话机器人", "ai 聊天", "ai聊天", "chatbot", "chat bot"),
        ("chatbot", "chat bot", "conversational ai", "聊天机器人", "对话机器人"),
    ),
    _ProjectConceptSpec(
        "text2sql",
        ("自然语言查询数据库", "自然语言查数", "text2sql", "text to sql", "text-to-sql", "nl2sql"),
        ("text2sql", "text-to-sql", "text to sql", "nl2sql", "自然语言查询"),
    ),
    _ProjectConceptSpec(
        "local_llm",
        ("本地大模型", "本地模型", "离线大模型", "离线模型", "local llm", "local model"),
        ("local llm", "local model", "offline llm", "本地大模型", "本地模型"),
    ),
    _ProjectConceptSpec(
        "crypto",
        ("密码学", "加密", "cryptography", "encryption", "crypto"),
        ("encryption", "cryptography", "crypto", "密码学", "加密"),
    ),
    # —— 桌面/系统/生产力工具 ——
    _ProjectConceptSpec(
        "password_manager",
        ("密码管理", "密码库", "密码本", "password manager", "password vault", "密码"),
        ("password manager", "password vault", "credentials", "密码管理", "密码库", "密码"),
    ),
    _ProjectConceptSpec(
        "screenshot",
        ("屏幕截图", "截图", "抓图", "screenshots", "screenshot", "screen capture", "screen shot", "snip"),
        ("screenshot", "screen capture", "screen shot", "snipping", "截图", "抓图"),
    ),
    _ProjectConceptSpec(
        "screen_recording",
        ("屏幕录制", "录制屏幕", "录屏", "screen recording", "screen recorder"),
        ("screen recording", "screen recorder", "录屏", "屏幕录制"),
    ),
    _ProjectConceptSpec(
        "note_taking",
        ("笔记", "备忘录", "便签", "note-taking", "note taking", "notes"),
        ("note-taking", "note taking", "notes", "笔记", "备忘录", "便签"),
    ),
    _ProjectConceptSpec(
        "photo_management",
        ("相册", "照片", "图库", "photo management", "photo manager", "photography", "photos", "photo"),
        ("photo", "photos", "gallery", "photo manager", "相册", "照片", "图库"),
    ),
    _ProjectConceptSpec(
        "video_download",
        ("视频下载", "下载视频", "下载器", "video downloader", "video download"),
        ("video downloader", "video download", "download video", "视频下载", "下载器"),
    ),
    _ProjectConceptSpec(
        "file_sync",
        ("文件同步", "云同步", "同步盘", "网盘", "file sync", "cloud sync"),
        ("file sync", "cloud sync", "file synchronization", "文件同步", "云同步", "网盘"),
    ),
    _ProjectConceptSpec(
        "file_manager",
        ("文件管理器", "文件管理", "file manager", "file browser"),
        ("file manager", "file browser", "文件管理", "文件管理器"),
    ),
    _ProjectConceptSpec(
        "pdf_tools",
        ("pdf",),
        ("pdf", "pdf tools", "pdf editor", "pdf 工具"),
    ),
    _ProjectConceptSpec(
        "clipboard",
        ("剪贴板", "clipboard"),
        ("clipboard", "剪贴板"),
    ),
    _ProjectConceptSpec(
        "launcher",
        ("应用启动器", "启动器", "launcher"),
        ("launcher", "app launcher", "启动器", "应用启动器"),
    ),
    _ProjectConceptSpec(
        "remote_desktop",
        ("远程桌面", "远程控制", "远程协助", "remote desktop", "remote access"),
        ("remote desktop", "remote access", "远程桌面", "远程控制", "远程协助"),
    ),
    _ProjectConceptSpec(
        "backup",
        ("数据备份", "备份", "backups", "backup"),
        ("backup", "backups", "备份", "数据备份"),
    ),
    _ProjectConceptSpec(
        "rss",
        ("订阅器", "rss 阅读", "feed reader", "rss"),
        ("rss", "rss reader", "feed reader", "rss 阅读器", "订阅"),
    ),
    _ProjectConceptSpec(
        "ocr",
        ("文字识别", "光学字符识别", "ocr"),
        ("ocr", "optical character recognition", "文字识别", "光学字符识别"),
    ),
    _ProjectConceptSpec(
        "translation",
        ("机器翻译", "翻译", "translation", "translator", "translate"),
        ("translation", "machine translation", "translate", "翻译", "机器翻译"),
    ),
    _ProjectConceptSpec(
        "window_manager",
        ("平铺窗口", "窗口管理", "window manager", "tiling window", "tiling wm"),
        ("window manager", "tiling window", "窗口管理", "平铺窗口"),
    ),
    # —— 内容与知识 ——
    _ProjectConceptSpec(
        "wiki",
        ("维基", "wiki"),
        ("wiki", "维基", "知识库", "documentation"),
    ),
    _ProjectConceptSpec(
        "blog",
        ("博客", "blogging", "blog"),
        ("blog", "blogging", "static blog", "博客"),
    ),
    _ProjectConceptSpec(
        "forum",
        ("社区论坛", "论坛", "forums", "forum", "bbs"),
        ("forum", "forums", "discussion board", "论坛", "社区", "bbs"),
    ),
    _ProjectConceptSpec(
        "markdown",
        ("markdown 笔记", "md 笔记", "md 文档", "markdown"),
        ("markdown", "markdown editor", "mdx", "markdown 笔记"),
    ),
    _ProjectConceptSpec(
        "static_site",
        ("静态网站", "静态站点", "static site", "ssg"),
        ("static site", "static site generator", "静态网站", "静态站点", "ssg"),
    ),
    _ProjectConceptSpec(
        "cms",
        ("内容管理系统", "内容管理", "cms"),
        ("cms", "headless cms", "content management", "内容管理"),
    ),
    _ProjectConceptSpec(
        "ebook",
        ("电子书", "e-books", "ebook", "e-book", "epub"),
        ("ebook", "e-book", "epub", "mobi", "电子书"),
    ),
    _ProjectConceptSpec(
        "knowledge_management",
        ("知识管理", "第二大脑", "knowledge management", "second brain", "pkm"),
        ("knowledge management", "second brain", "pkm", "知识管理", "第二大脑"),
    ),
    _ProjectConceptSpec(
        "mind_map",
        ("思维导图", "脑图", "mind map", "mindmap"),
        ("mind map", "mindmap", "思维导图", "脑图"),
    ),
    # —— 互联网/自建服务 ——
    _ProjectConceptSpec(
        "reverse_proxy",
        ("反向代理", "反代", "reverse proxy"),
        ("reverse proxy", "反向代理", "反代"),
    ),
    _ProjectConceptSpec(
        "dns",
        ("域名解析", "dns"),
        ("dns", "dns server", "域名解析"),
    ),
    _ProjectConceptSpec(
        "vpn_proxy",
        ("科学上网", "翻墙", "代理", "proxy server", "proxy", "vpn"),
        ("proxy", "vpn", "proxy server", "代理", "翻墙", "科学上网"),
    ),
    _ProjectConceptSpec(
        "ad_block",
        ("去广告", "广告拦截", "广告过滤", "ad blocker", "adblock", "ad block"),
        ("ad blocker", "adblock", "ad block", "去广告", "广告拦截", "广告过滤"),
    ),
    _ProjectConceptSpec(
        "torrent",
        ("种子", "磁力", "bt 下载", "bittorrent", "torrent"),
        ("torrent", "bittorrent", "bt 下载", "种子", "磁力"),
    ),
    _ProjectConceptSpec(
        "media_server",
        ("媒体服务器", "媒体库", "影音库", "media server", "media center"),
        ("media server", "media center", "媒体服务器", "媒体库", "影音"),
    ),
    _ProjectConceptSpec(
        "music_player",
        ("音乐播放器", "音乐播放", "music player"),
        ("music player", "audio player", "音乐播放器", "音乐"),
    ),
    _ProjectConceptSpec(
        "video_player",
        ("视频播放器", "播放器", "video player", "media player"),
        ("video player", "media player", "视频播放器", "播放器"),
    ),
    _ProjectConceptSpec(
        "home_automation",
        ("智能家居", "家庭自动化", "smart home", "home automation"),
        ("smart home", "home automation", "智能家居", "家庭自动化"),
    ),
    _ProjectConceptSpec(
        "status_page",
        ("可用性监控", "状态页", "status page", "uptime"),
        ("status page", "uptime monitor", "状态页", "可用性监控"),
    ),
    # —— 电商/企业/协作 ——
    _ProjectConceptSpec(
        "ecommerce",
        ("网上购物", "商城", "电商", "online store", "online shop", "e-commerce", "ecommerce"),
        ("ecommerce", "e-commerce", "online store", "商城系统", "电商", "商城"),
    ),
    _ProjectConceptSpec(
        "payment",
        ("支付", "收银", "payments", "payment", "checkout"),
        ("payment", "payments", "payment gateway", "checkout", "支付", "收银"),
    ),
    _ProjectConceptSpec(
        "auth_sso",
        ("单点登录", "认证", "鉴权", "登录", "authentication", "oauth2", "oauth", "sso"),
        ("authentication", "sso", "oauth", "单点登录", "认证", "鉴权", "登录"),
    ),
    _ProjectConceptSpec(
        "crm",
        ("客户关系管理", "crm"),
        ("crm", "customer relationship management", "客户关系管理"),
    ),
    _ProjectConceptSpec(
        "erp",
        ("企业资源计划", "erp"),
        ("erp", "enterprise resource planning", "企业资源计划"),
    ),
    _ProjectConceptSpec(
        "project_management",
        ("项目管理", "项目协作", "看板", "project management", "kanban", "task board"),
        ("project management", "kanban", "task board", "项目管理", "看板", "项目协作"),
    ),
    _ProjectConceptSpec(
        "todo",
        ("待办事项", "待办", "任务清单", "todo list", "to-do", "todos", "todo"),
        ("todo", "to-do", "todo list", "task list", "待办", "待办事项"),
    ),
    _ProjectConceptSpec(
        "calendar",
        ("日历", "日程", "calendars", "calendar"),
        ("calendar", "schedule", "scheduling", "日历", "日程"),
    ),
    _ProjectConceptSpec(
        "email_tools",
        ("邮件", "邮箱", "e-mail", "email", "mail"),
        ("email", "mail", "e-mail", "smtp", "邮件", "邮箱"),
    ),
    _ProjectConceptSpec(
        "time_tracking",
        ("时间追踪", "时间管理", "time tracking", "time tracker", "timesheet"),
        ("time tracking", "time tracker", "timesheet", "时间追踪", "时间管理"),
    ),
    _ProjectConceptSpec(
        "expense_tracking",
        ("记账", "账单", "expense tracker", "expense tracking", "budget"),
        ("expense tracker", "expense tracking", "budget", "记账", "账单"),
    ),
    # —— 开发基础设施 ——
    _ProjectConceptSpec(
        "database",
        ("数据库", "databases", "database", "dbms"),
        ("database", "databases", "sql", "dbms", "数据库"),
    ),
    _ProjectConceptSpec(
        "monitoring",
        ("监控", "告警", "monitoring", "alerting", "monitor"),
        ("monitoring", "alerting", "monitor", "metrics", "监控", "告警"),
    ),
    _ProjectConceptSpec(
        "log_management",
        ("日志管理", "日志分析", "日志收集", "log management", "log analysis", "log aggregation"),
        ("log management", "log analysis", "log aggregation", "日志管理", "日志分析", "日志"),
    ),
    _ProjectConceptSpec(
        "ci_cd",
        ("持续集成", "持续部署", "ci/cd", "ci cd", "cicd"),
        ("ci/cd", "continuous integration", "continuous deployment", "cicd", "持续集成", "持续部署"),
    ),
    _ProjectConceptSpec(
        "message_queue",
        ("消息队列", "消息中间件", "message queue", "message broker", "pub/sub", "pubsub"),
        ("message queue", "message broker", "pub/sub", "pubsub", "消息队列", "消息中间件"),
    ),
    _ProjectConceptSpec(
        "search_engine",
        ("搜索引擎", "全文检索", "全文搜索", "search engine", "full-text search", "full text search"),
        ("search engine", "full-text search", "full text search", "搜索引擎", "全文检索"),
    ),
    _ProjectConceptSpec(
        "crawler",
        ("网页抓取", "网页爬取", "爬虫", "web scraping", "crawler", "scraper", "spider"),
        ("crawler", "scraper", "web scraping", "spider", "爬虫", "网页抓取"),
    ),
    _ProjectConceptSpec(
        "admin_panel",
        ("管理后台", "后台管理", "管理面板", "admin dashboard", "admin panel", "admin ui"),
        ("admin panel", "admin dashboard", "admin ui", "管理后台", "后台管理", "管理面板"),
    ),
    _ProjectConceptSpec(
        "dashboard",
        ("数据看板", "仪表盘", "dashboards", "dashboard"),
        ("dashboard", "dashboards", "metrics dashboard", "仪表盘", "数据看板"),
    ),
    _ProjectConceptSpec(
        "api_client",
        ("接口调试", "接口测试", "api 调试", "api 测试", "api client", "http client"),
        ("api client", "http client", "rest client", "api 调试", "api 测试", "接口调试"),
    ),
    _ProjectConceptSpec(
        "web_framework",
        ("web 框架", "web框架", "web framework"),
        ("web framework", "webframework", "web 框架"),
    ),
    _ProjectConceptSpec(
        "low_code",
        ("低代码", "零代码", "low-code", "low code", "no-code", "no code"),
        ("low-code", "low code", "no-code", "低代码", "零代码"),
    ),
    _ProjectConceptSpec(
        "docker_container",
        ("容器化", "容器", "containers", "container", "docker"),
        ("docker", "container", "containers", "容器", "容器化"),
    ),
    _ProjectConceptSpec(
        "kubernetes",
        ("kubernetes", "k8s"),
        ("kubernetes", "k8s", "容器编排"),
    ),
    _ProjectConceptSpec(
        "git_tools",
        ("git",),
        ("git", "git 工具", "version control", "版本控制"),
    ),
    _ProjectConceptSpec(
        "editor_ide",
        ("代码编辑器", "编辑器", "editors", "editor", "ide"),
        ("editor", "code editor", "编辑器", "代码编辑器"),
    ),
    _ProjectConceptSpec(
        "firewall",
        ("防火墙", "firewall"),
        ("firewall", "waf", "防火墙"),
    ),
    _ProjectConceptSpec(
        "iot",
        ("物联网", "iot"),
        ("iot", "internet of things", "物联网"),
    ),
    _ProjectConceptSpec(
        "printing_3d",
        ("3d 打印", "3d打印", "3d printing"),
        ("3d printing", "3d 打印", "3d打印"),
    ),
    _ProjectConceptSpec(
        "game_engine",
        ("游戏引擎", "game engine"),
        ("game engine", "game development", "游戏引擎"),
    ),
    _ProjectConceptSpec(
        "game_mod",
        ("游戏模组", "模组", "mod 管理", "mod管理", "mod 加载", "mods", "mod"),
        ("game mod", "mod manager", "mod loader", "游戏模组", "模组", "游戏 mod"),
    ),
    _ProjectConceptSpec(
        "emulator",
        ("模拟器", "仿真器", "emulation", "emulator"),
        ("emulator", "emulation", "模拟器", "仿真器"),
    ),
    _ProjectConceptSpec(
        "whiteboard",
        ("白板", "画板", "whiteboard"),
        ("whiteboard", "白板", "画板"),
    ),
    _ProjectConceptSpec(
        "diagram",
        ("流程图", "架构图", "图表", "diagramming", "diagrams", "diagram"),
        ("diagram", "diagrams", "chart", "流程图", "架构图", "图表"),
    ),
    _ProjectConceptSpec(
        "image_optimization",
        ("图片压缩", "图像压缩", "图片优化", "image optimization", "image compression"),
        ("image optimization", "image compression", "图片压缩", "图像压缩", "图片优化"),
    ),
    _ProjectConceptSpec(
        "video_converter",
        ("视频转换", "格式转换", "转码", "video transcoding", "video converter", "transcoding"),
        ("video converter", "transcoding", "ffmpeg", "视频转换", "转码", "格式转换"),
    ),
    _ProjectConceptSpec(
        "data_analysis",
        ("数据分析", "数据可视化", "data analysis", "data analytics", "business intelligence", "data visualization"),
        ("data analysis", "data analytics", "business intelligence", "data visualization", "数据分析", "数据可视化"),
    ),
    _ProjectConceptSpec(
        "etl",
        ("数据集成", "数据管道", "data pipeline", "data integration", "etl", "elt"),
        ("etl", "elt", "data pipeline", "data integration", "数据集成", "数据管道"),
    ),
    _ProjectConceptSpec(
        "data_labeling",
        ("数据标注", "标注工具", "data labeling", "data annotation"),
        ("data labeling", "data annotation", "数据标注", "标注工具"),
    ),
    _ProjectConceptSpec(
        "feature_flag",
        ("功能开关", "灰度发布", "feature flags", "feature flag", "feature toggle"),
        ("feature flag", "feature flags", "feature toggle", "功能开关", "灰度发布"),
    ),
    _ProjectConceptSpec(
        "api_gateway",
        ("api 网关", "api网关", "网关", "api gateway"),
        ("api gateway", "api 网关", "网关"),
    ),
    _ProjectConceptSpec(
        "secrets_manager",
        ("密钥管理", "密钥", "secrets management", "secret management"),
        ("secrets management", "secret manager", "vault", "密钥管理", "密钥"),
    ),
    _ProjectConceptSpec(
        "code_search",
        ("代码搜索", "代码检索", "code search"),
        ("code search", "代码搜索", "代码检索"),
    ),
    _ProjectConceptSpec(
        "diff_tool",
        ("文件对比", "对比工具", "diff tool", "diff"),
        ("diff tool", "merge tool", "文件对比", "对比工具"),
    ),
)
_PROTECTED_PROJECT_TOKENS = frozenset({"c++", "c#", ".net", "mcp", "rag", "langgraph"})
_PROJECT_TRANSPORT_TERMS = {
    "github",
    "repo",
    "repository",
    "repositories",
    "project",
    "projects",
    "项目",
    "仓库",
    "工具",
}


ProjectQueryLanguage = Literal["zh", "en", "mixed", "und"]
ProjectIntentClass = Literal[
    "exact_lookup",
    "learning",
    "examples",
    "sdk",
    "framework",
    "self_hosted",
    "general_discovery",
]


@dataclass(frozen=True)
class ProjectSearchIntent:
    schema_version: str
    normalized_query: str
    language: ProjectQueryLanguage
    lexical_terms: tuple[str, ...]
    semantic_queries: tuple[str, ...]
    intent_class: ProjectIntentClass = "general_discovery"
    topics: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    artifact_types: tuple[str, ...] = ()
    must_have: tuple[str, ...] = ()
    should_have: tuple[str, ...] = ()
    concept_ids: tuple[str, ...] = ()
    bilingual_aliases: tuple[str, ...] = ()


def normalize_search_query(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").strip().split())


def search_terms(
    value: str,
    *,
    max_terms: int = 8,
    blocked_terms: set[str] | None = None,
) -> list[str]:
    normalized = normalize_search_query(value)
    blocked = {term.casefold() for term in (blocked_terms or set())}
    terms: list[str] = []
    seen: set[str] = set()
    for token in TECHNICAL_TOKEN_RE.findall(normalized):
        key = token.casefold()
        if key in blocked or key in seen:
            continue
        if len(token) == 1 and not token.isdigit():
            continue
        seen.add(key)
        terms.append(token)
        if len(terms) >= max(1, max_terms):
            break
    return terms


def project_search_terms(value: str, *, max_terms: int = 8) -> list[str]:
    return search_terms(value, max_terms=max_terms, blocked_terms=_PROJECT_TRANSPORT_TERMS)


def _ascii_phrase_boundary_ok(folded: str, start: int, end: int) -> bool:
    """纯 ASCII 触发词的词边界守卫：相邻字符若是 ASCII 字母/数字/下划线则拒绝命中。

    防止 cli 命中 client、git 命中 digital、otel 命中 hotel；中文邻居不拦截，
    因此 "部署mcp服务" 这类中英混排查询仍能命中 ASCII 触发词。
    """
    for neighbor in (
        folded[start - 1] if start > 0 else "",
        folded[end] if end < len(folded) else "",
    ):
        if neighbor and neighbor.isascii() and (neighbor.isalnum() or neighbor == "_"):
            return False
    return True


def _project_concept_matches(
    value: str,
    *,
    max_concepts: int = 8,
) -> tuple[tuple[int, str, _ProjectConceptSpec], ...]:
    candidates: list[tuple[int, int, str, _ProjectConceptSpec]] = []
    folded = value.casefold()
    for spec in _PROJECT_CONCEPT_LEXICON:
        for phrase in spec.phrases:
            needle = phrase.casefold()
            needs_boundary = needle.isascii()
            start = folded.find(needle)
            while start >= 0:
                end = start + len(needle)
                if not needs_boundary or _ascii_phrase_boundary_ok(folded, start, end):
                    candidates.append((start, end, phrase, spec))
                start = folded.find(needle, start + 1)
    occupied: list[tuple[int, int]] = []
    selected: list[tuple[int, str, _ProjectConceptSpec]] = []
    seen: set[str] = set()
    for start, end, phrase, spec in sorted(
        candidates,
        key=lambda item: (-(item[1] - item[0]), item[0], item[3].concept_id),
    ):
        if spec.concept_id in seen or any(start < stop and end > begin for begin, stop in occupied):
            continue
        seen.add(spec.concept_id)
        occupied.append((start, end))
        selected.append((start, value[start:end] or phrase, spec))
        if len(selected) >= max(1, max_concepts):
            break
    return tuple(sorted(selected, key=lambda item: item[0]))


def han_concept_english_aliases() -> dict[str, tuple[str, ...]]:
    """中文触发词（NFKC 后 casefold）→ 所属概念的英文别名，按概念表顺序去重。

    供关键词追踪做整词中译英扩展；项目搜索不经过这里，行为不变。
    """
    mapping: dict[str, list[str]] = {}
    for spec in _PROJECT_CONCEPT_LEXICON:
        english = [alias for alias in spec.aliases if alias.isascii()]
        for phrase in spec.phrases:
            if not _HAN_RE.search(phrase):
                continue
            bucket = mapping.setdefault(unicodedata.normalize("NFKC", phrase).casefold(), [])
            bucket.extend(alias for alias in english if alias not in bucket)
    return {phrase: tuple(aliases) for phrase, aliases in mapping.items() if aliases}


def _project_literal_terms(
    value: str,
    matches: tuple[tuple[int, str, _ProjectConceptSpec], ...],
) -> list[tuple[int, str]]:
    covered = [(start, start + len(phrase)) for start, phrase, _ in matches]
    terms: list[tuple[int, str]] = []
    for match in TECHNICAL_TOKEN_RE.finditer(value):
        token = match.group(0)
        if _HAN_RE.search(token) or any(
            match.start() < stop and match.end() > begin for begin, stop in covered
        ):
            continue
        if token.casefold() in _PROJECT_TRANSPORT_TERMS:
            continue
        terms.append((match.start(), token))
    return terms


def _project_intent_terms(
    value: str,
    matches: tuple[tuple[int, str, _ProjectConceptSpec], ...],
    *,
    max_terms: int = 8,
) -> tuple[str, ...]:
    terms = [
        *((start, phrase) for start, phrase, _ in matches),
        *_project_literal_terms(value, matches),
    ]
    result: list[str] = []
    seen: set[str] = set()
    for _, term in sorted(terms, key=lambda item: item[0]):
        key = term.casefold()
        if key in seen or (len(term) == 1 and not term.isdigit()):
            continue
        seen.add(key)
        result.append(term)
        if len(result) >= max(1, max_terms):
            break
    return tuple(result or project_search_terms(value, max_terms=max_terms))


def build_project_lexical_retrieval_plan(
    intent: ProjectSearchIntent,
) -> ProjectLexicalRetrievalPlan:
    from backend.app.repositories.project_catalog import (
        ProjectLexicalConcept,
        ProjectLexicalRetrievalPlan,
    )

    matches = _project_concept_matches(intent.normalized_query)
    concepts = tuple(
        ProjectLexicalConcept(
            concept_id=spec.concept_id,
            primary_terms=(phrase,),
            aliases=spec.aliases,
        )
        for _, phrase, spec in matches
        if spec.concept_id in intent.concept_ids
    )
    literal_terms = tuple(
        term
        for _, term in _project_literal_terms(intent.normalized_query, matches)
        if term.casefold() != "ai"
    )
    return ProjectLexicalRetrievalPlan(
        normalized_query=intent.normalized_query,
        strict_terms=literal_terms,
        concepts=concepts,
    )


def build_project_search_intent(value: str, *, max_chars: int = 120) -> ProjectSearchIntent:
    normalized = normalize_search_query(value)[:max_chars]
    cleaned = normalized
    for phrase in _PROJECT_REQUEST_PHRASES:
        cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.IGNORECASE)
    cleaned = normalize_search_query(cleaned) or normalized
    has_han = bool(_HAN_RE.search(cleaned))
    latin_terms = [term for term in TECHNICAL_TOKEN_RE.findall(cleaned) if not _HAN_RE.search(term)]
    prose_latin = [term for term in latin_terms if term.casefold() not in {"ai", "llm", "rag", "mcp"}]
    language: ProjectQueryLanguage = (
        "mixed" if has_han and prose_latin else "zh" if has_han else "en" if latin_terms else "und"
    )
    concept_matches = _project_concept_matches(cleaned)
    aliases = tuple(
        alias
        for _, _, spec in concept_matches
        for alias in (spec.aliases if len(concept_matches) == 1 else spec.aliases[:1])
    )
    expanded = cleaned
    compact_aliases: list[str] = []
    alias_seen: set[str] = set()
    for alias in aliases:
        key = alias.casefold()
        if key not in expanded.casefold() and key not in alias_seen:
            alias_seen.add(key)
            compact_aliases.append(alias)
    if compact_aliases:
        expanded = f"{expanded} {' '.join(compact_aliases)}"
    variants: list[str] = []
    seen: set[str] = set()
    for query in (cleaned, normalize_search_query(expanded)):
        bounded = query[:max_chars].rstrip()
        key = bounded.casefold()
        if bounded and key not in seen:
            seen.add(key)
            variants.append(bounded)
    terms = _project_intent_terms(cleaned, concept_matches)
    lowered = cleaned.casefold()
    intent_class: ProjectIntentClass = "general_discovery"
    raw_terms = tuple(project_search_terms(cleaned))
    if "/" in cleaned or (
        len(raw_terms) == 1
        and raw_terms[0].casefold() == cleaned.casefold()
        and not concept_matches
    ):
        intent_class = "exact_lookup"
    elif any(value in lowered for value in ("学习", "教程", "入门", "learn", "tutorial", "beginner")):
        intent_class = "learning"
    elif any(value in lowered for value in ("example", "sample", "示例")):
        intent_class = "examples"
    elif "sdk" in lowered:
        intent_class = "sdk"
    elif any(value in lowered for value in ("framework", "框架")):
        intent_class = "framework"
    elif any(value in lowered for value in ("本地部署", "self-hosted", "self hosted")):
        intent_class = "self_hosted"
    return ProjectSearchIntent(
        schema_version="project-search-intent-v1",
        normalized_query=cleaned,
        language=language,
        lexical_terms=terms,
        semantic_queries=tuple(variants),
        intent_class=intent_class,
        concept_ids=tuple(spec.concept_id for _, _, spec in concept_matches),
        bilingual_aliases=tuple(compact_aliases),
    )


def normalize_client_intent_values(
    values: list[str] | tuple[str, ...],
    *,
    max_items: int,
    max_chars: int,
) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values[:max_items]:
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("intent values must be non-empty, bounded text without control characters")
        clean = normalize_search_query(value)
        if not clean or len(clean) > max_chars:
            raise ValueError("intent values must be non-empty, bounded text without control characters")
        key = clean.casefold()
        if key not in seen:
            seen.add(key)
            normalized.append(clean)
    return tuple(normalized)


def client_intent_preserves_protected_tokens(
    query: str,
    lexical_terms: tuple[str, ...],
    semantic_queries: tuple[str, ...],
) -> bool:
    protected = {
        token.casefold()
        for token in TECHNICAL_TOKEN_RE.findall(normalize_search_query(query))
        if token.casefold() in _PROTECTED_PROJECT_TOKENS
    }
    output_tokens = {
        token.casefold()
        for token in TECHNICAL_TOKEN_RE.findall(
            " ".join((*lexical_terms, *semantic_queries))
        )
    }
    return protected.issubset(output_tokens)


def build_client_project_search_intent(
    query: str,
    payload: Mapping[str, Any],
) -> ProjectSearchIntent:
    deterministic = build_project_search_intent(query)
    lexical_terms = normalize_client_intent_values(
        list(payload.get("lexical_terms") or ()),
        max_items=8,
        max_chars=40,
    )
    semantic_queries = normalize_client_intent_values(
        list(payload.get("semantic_queries") or ()),
        max_items=3,
        max_chars=120,
    )
    if not lexical_terms or not semantic_queries:
        raise ValueError("client intent requires lexical_terms and semantic_queries")
    if not client_intent_preserves_protected_tokens(
        deterministic.normalized_query,
        lexical_terms,
        semantic_queries,
    ):
        raise ValueError("client intent must preserve protected technical tokens from q")
    return ProjectSearchIntent(
        schema_version="project-search-intent-client-v1",
        normalized_query=deterministic.normalized_query,
        language=payload["language"],
        lexical_terms=lexical_terms,
        semantic_queries=semantic_queries,
        intent_class=payload.get("intent_class", "general_discovery"),
        topics=normalize_client_intent_values(
            list(payload.get("topics") or ()), max_items=6, max_chars=40
        ),
        languages=normalize_client_intent_values(
            list(payload.get("languages") or ()), max_items=3, max_chars=30
        ),
        artifact_types=normalize_client_intent_values(
            list(payload.get("artifact_types") or ()), max_items=6, max_chars=40
        ),
        must_have=normalize_client_intent_values(
            list(payload.get("must_have") or ()), max_items=6, max_chars=40
        ),
        should_have=normalize_client_intent_values(
            list(payload.get("should_have") or ()), max_items=8, max_chars=40
        ),
        concept_ids=deterministic.concept_ids,
        bilingual_aliases=deterministic.bilingual_aliases,
    )


def escape_like_literal(value: str, *, escape: str = "=") -> str:
    return value.replace(escape, escape * 2).replace("%", f"{escape}%").replace("_", f"{escape}_")
