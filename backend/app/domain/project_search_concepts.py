"""Canonical bilingual project concepts; Go artifacts are generated from this table."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectConceptSpec:
    concept_id: str
    phrases: tuple[str, ...]
    aliases: tuple[str, ...]


# 词法概念表：触发词（phrases）在查询上命中，别名（aliases）同时用于
# SQL 概念组与语义查询扩展。约束：
# 1. 纯 ASCII 触发词按词边界匹配（cli 不命中 client、git 不命中 digital）；
#    含中文等宽字符的短语保持子串匹配。
# 2. SQL 对纯 ASCII 概念词使用字母/数字边界，避免 eval→retrieval、
#    rag→storage；中文概念词保持子串匹配，名称与普通词仍使用 ILIKE。
# 3. 每个概念的第一别名 = 跨语言规范词：多概念命中时仅第一别名参与语义扩展。
PROJECT_CONCEPT_LEXICON = (
    # —— 编程效率/上下文/记忆/任务/助手（既有概念，扩展双语触发与别名）——
    ProjectConceptSpec(
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
    ProjectConceptSpec(
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
    ProjectConceptSpec(
        "codebase_memory",
        (
            "代码库持久记忆",
            "项目持久记忆",
            "代码库记忆",
            "项目记忆",
            "代码库长期记忆",
            "项目长期记忆",
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
    ProjectConceptSpec(
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
    ProjectConceptSpec(
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
    ProjectConceptSpec(
        "developer_tools",
        ("开发者工具", "开发工具", "developer tools", "dev tools", "devtool", "devtools"),
        ("developer tools", "dev tools", "开发者工具", "开发工具"),
    ),
    ProjectConceptSpec(
        "workflow",
        ("智能体工作流", "工作流", "agent workflow", "workflow", "workflows"),
        ("workflow automation", "agent workflow", "工作流", "智能体工作流"),
    ),
    ProjectConceptSpec(
        "rag",
        ("知识库问答", "知识库", "retrieval augmented", "检索增强", "rag"),
        ("rag", "knowledge base", "retrieval augmented", "知识库", "检索增强"),
    ),
    ProjectConceptSpec(
        "self_hosted",
        ("本地部署", "自托管", "私有化部署", "self-hosted", "self hosted", "selfhost", "self hosting"),
        ("self-hosted", "self hosted", "local deployment", "自托管", "本地部署", "私有化部署"),
    ),
    # learning 的别名被测试精确冻结（"tutorial","learning"），只扩展触发词。
    ProjectConceptSpec(
        "learning",
        ("入门教程", "教程", "入门", "tutorial", "tutorials"),
        ("tutorial", "learning"),
    ),
    ProjectConceptSpec(
        "agent",
        ("智能体", "ai agent", "agent", "agents"),
        ("agent", "ai agent", "agents", "智能体", "助手"),
    ),
    # —— AI/LLM 工程 ——
    ProjectConceptSpec(
        "llm",
        ("大语言模型", "大模型", "large language model", "llms", "llm"),
        ("large language model", "llm", "大模型", "大语言模型"),
    ),
    ProjectConceptSpec(
        "prompt_engineering",
        ("提示词", "提示工程", "prompt engineering", "prompt management", "prompts", "prompt"),
        ("prompt engineering", "prompt management", "prompt", "提示词", "提示工程"),
    ),
    ProjectConceptSpec(
        "llm_evaluation",
        ("基准测试", "评测", "评估", "benchmarks", "benchmark", "evaluations", "evaluation", "evals", "eval"),
        ("evaluation", "evaluations", "benchmark", "benchmarks", "eval", "evals", "评测", "评估", "基准测试"),
    ),
    ProjectConceptSpec(
        "mcp",
        ("model context protocol", "mcp"),
        ("model context protocol", "mcp server", "mcp", "mcp 服务"),
    ),
    ProjectConceptSpec(
        "function_calling",
        ("工具调用", "工具使用", "function calling", "tool calling", "tool use"),
        ("function calling", "tool calling", "tool use", "工具调用"),
    ),
    ProjectConceptSpec(
        "multi_agent",
        ("多智能体", "multi-agent", "multi agent", "multiagent", "agent swarm"),
        ("multi-agent", "multi agent", "agent swarm", "多智能体", "swarm"),
    ),
    ProjectConceptSpec(
        "agent_memory",
        (
            "智能体长期记忆", "智能体持久记忆", "智能体记忆", "长期记忆", "持久记忆",
            "agent long-term memory", "agent long term memory", "long-term memory",
            "long term memory", "persistent memory", "agent memory", "agentic memory",
        ),
        (
            "agent memory", "agentic memory", "long-term memory", "long term memory",
            "persistent memory", "memory layer", "智能体记忆", "长期记忆", "持久记忆",
        ),
    ),
    ProjectConceptSpec(
        "llm_observability",
        ("链路追踪", "可观测", "observability", "opentelemetry", "tracing", "otel"),
        ("observability", "tracing", "trace", "opentelemetry", "可观测性", "链路追踪", "llm observability"),
    ),
    ProjectConceptSpec(
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
    ProjectConceptSpec(
        "fine_tuning",
        ("微调", "fine-tuning", "fine tuning", "finetuning", "fine-tune", "fine tune", "finetune"),
        ("fine-tuning", "fine tuning", "finetune", "lora", "qlora", "微调"),
    ),
    ProjectConceptSpec(
        "vector_search",
        ("向量数据库", "向量检索", "向量搜索", "向量库", "vector database", "vector search", "vector db"),
        ("vector database", "vector search", "vector index", "向量数据库", "向量检索"),
    ),
    ProjectConceptSpec(
        "embedding",
        ("嵌入模型", "文本嵌入", "向量化", "embeddings", "embedding"),
        ("embedding", "embeddings", "text embedding", "向量化", "嵌入"),
    ),
    ProjectConceptSpec(
        "speech_tts",
        ("语音合成", "语音播报", "配音", "text to speech", "tts"),
        ("text to speech", "tts", "speech synthesis", "语音合成", "配音"),
    ),
    ProjectConceptSpec(
        "speech_asr",
        ("语音识别", "语音转文字", "语音转写", "speech recognition", "speech to text", "asr"),
        ("speech recognition", "speech to text", "asr", "transcription", "语音识别", "语音转文字"),
    ),
    ProjectConceptSpec(
        "image_generation",
        ("图像生成", "图像合成", "文生图", "ai 绘画", "ai绘画", "text to image", "image generation"),
        ("text to image", "image generation", "stable diffusion", "图像生成", "文生图", "ai 绘画"),
    ),
    ProjectConceptSpec(
        "video_generation",
        ("视频生成", "ai 视频", "ai视频", "text to video", "video generation"),
        ("text to video", "video generation", "视频生成", "ai 视频"),
    ),
    ProjectConceptSpec(
        "code_review",
        ("代码审查", "代码评审", "code review", "code-review", "codereview"),
        ("code review", "code-review", "codereview", "代码审查", "代码评审"),
    ),
    ProjectConceptSpec(
        "cli",
        ("命令行", "终端", "command line", "command-line", "cli", "tui"),
        ("command line", "command-line", "cli", "terminal", "tui", "命令行", "终端"),
    ),
    ProjectConceptSpec(
        "terminal_emulator",
        ("终端模拟器", "terminal emulator"),
        ("terminal emulator", "终端模拟器", "terminal"),
    ),
    ProjectConceptSpec(
        "chatbot",
        ("聊天机器人", "对话机器人", "ai 聊天", "ai聊天", "chatbot", "chat bot"),
        ("chatbot", "chat bot", "conversational ai", "聊天机器人", "对话机器人"),
    ),
    ProjectConceptSpec(
        "text2sql",
        ("自然语言查询数据库", "自然语言查数", "text2sql", "text to sql", "text-to-sql", "nl2sql"),
        ("text2sql", "text-to-sql", "text to sql", "nl2sql", "自然语言查询"),
    ),
    ProjectConceptSpec(
        "local_llm",
        ("本地大模型", "本地模型", "离线大模型", "离线模型", "local llm", "local model"),
        ("local llm", "local model", "offline llm", "本地大模型", "本地模型"),
    ),
    ProjectConceptSpec(
        "crypto",
        ("密码学", "加密", "cryptography", "encryption", "crypto"),
        ("encryption", "cryptography", "crypto", "密码学", "加密"),
    ),
    # —— 桌面/系统/生产力工具 ——
    ProjectConceptSpec(
        "password_manager",
        ("密码管理", "密码库", "密码本", "password manager", "password vault", "密码"),
        ("password manager", "password vault", "credentials", "密码管理", "密码库", "密码"),
    ),
    ProjectConceptSpec(
        "screenshot",
        ("屏幕截图", "截图", "抓图", "screenshots", "screenshot", "screen capture", "screen shot", "snip"),
        ("screenshot", "screen capture", "screen shot", "snipping", "截图", "抓图"),
    ),
    ProjectConceptSpec(
        "screen_recording",
        ("屏幕录制", "录制屏幕", "录屏", "screen recording", "screen recorder"),
        ("screen recording", "screen recorder", "录屏", "屏幕录制"),
    ),
    ProjectConceptSpec(
        "note_taking",
        ("笔记", "备忘录", "便签", "note-taking", "note taking", "notes"),
        ("note-taking", "note taking", "notes", "笔记", "备忘录", "便签"),
    ),
    ProjectConceptSpec(
        "photo_management",
        ("相册", "照片", "图库", "photo management", "photo manager", "photography", "photos", "photo"),
        ("photo", "photos", "gallery", "photo manager", "相册", "照片", "图库"),
    ),
    ProjectConceptSpec(
        "video_download",
        ("视频下载", "下载视频", "下载器", "video downloader", "video download"),
        ("video downloader", "video download", "download video", "视频下载", "下载器"),
    ),
    ProjectConceptSpec(
        "file_sync",
        ("文件同步", "云同步", "同步盘", "网盘", "file sync", "cloud sync"),
        ("file sync", "cloud sync", "file synchronization", "文件同步", "云同步", "网盘"),
    ),
    ProjectConceptSpec(
        "file_manager",
        ("文件管理器", "文件管理", "file manager", "file browser"),
        ("file manager", "file browser", "文件管理", "文件管理器"),
    ),
    ProjectConceptSpec(
        "pdf_tools",
        ("pdf",),
        ("pdf", "pdf tools", "pdf editor", "pdf 工具"),
    ),
    ProjectConceptSpec(
        "clipboard",
        ("剪贴板", "clipboard"),
        ("clipboard", "剪贴板"),
    ),
    ProjectConceptSpec(
        "launcher",
        ("应用启动器", "启动器", "launcher"),
        ("launcher", "app launcher", "启动器", "应用启动器"),
    ),
    ProjectConceptSpec(
        "remote_desktop",
        ("远程桌面", "远程控制", "远程协助", "remote desktop", "remote access"),
        ("remote desktop", "remote access", "远程桌面", "远程控制", "远程协助"),
    ),
    ProjectConceptSpec(
        "backup",
        ("数据备份", "备份", "backups", "backup"),
        ("backup", "backups", "备份", "数据备份"),
    ),
    ProjectConceptSpec(
        "rss",
        ("订阅器", "rss 阅读", "feed reader", "rss"),
        ("rss", "rss reader", "feed reader", "rss 阅读器", "订阅"),
    ),
    ProjectConceptSpec(
        "ocr",
        ("文字识别", "光学字符识别", "ocr"),
        ("ocr", "optical character recognition", "文字识别", "光学字符识别"),
    ),
    ProjectConceptSpec(
        "translation",
        ("机器翻译", "翻译", "translation", "translator", "translate"),
        ("translation", "machine translation", "translate", "翻译", "机器翻译"),
    ),
    ProjectConceptSpec(
        "window_manager",
        ("平铺窗口", "窗口管理", "window manager", "tiling window", "tiling wm"),
        ("window manager", "tiling window", "窗口管理", "平铺窗口"),
    ),
    # —— 内容与知识 ——
    ProjectConceptSpec(
        "wiki",
        ("维基", "wiki"),
        ("wiki", "维基", "知识库", "documentation"),
    ),
    ProjectConceptSpec(
        "blog",
        ("博客", "blogging", "blog"),
        ("blog", "blogging", "static blog", "博客"),
    ),
    ProjectConceptSpec(
        "forum",
        ("社区论坛", "论坛", "forums", "forum", "bbs"),
        ("forum", "forums", "discussion board", "论坛", "社区", "bbs"),
    ),
    ProjectConceptSpec(
        "markdown",
        ("markdown 笔记", "md 笔记", "md 文档", "markdown"),
        ("markdown", "markdown editor", "mdx", "markdown 笔记"),
    ),
    ProjectConceptSpec(
        "static_site",
        ("静态网站", "静态站点", "static site", "ssg"),
        ("static site", "static site generator", "静态网站", "静态站点", "ssg"),
    ),
    ProjectConceptSpec(
        "cms",
        ("内容管理系统", "内容管理", "cms"),
        ("cms", "headless cms", "content management", "内容管理"),
    ),
    ProjectConceptSpec(
        "ebook",
        ("电子书", "e-books", "ebook", "e-book", "epub"),
        ("ebook", "e-book", "epub", "mobi", "电子书"),
    ),
    ProjectConceptSpec(
        "knowledge_management",
        ("知识管理", "第二大脑", "knowledge management", "second brain", "pkm"),
        ("knowledge management", "second brain", "pkm", "知识管理", "第二大脑"),
    ),
    ProjectConceptSpec(
        "mind_map",
        ("思维导图", "脑图", "mind map", "mindmap"),
        ("mind map", "mindmap", "思维导图", "脑图"),
    ),
    # —— 互联网/自建服务 ——
    ProjectConceptSpec(
        "reverse_proxy",
        ("反向代理", "反代", "reverse proxy"),
        ("reverse proxy", "反向代理", "反代"),
    ),
    ProjectConceptSpec(
        "dns",
        ("域名解析", "dns"),
        ("dns", "dns server", "域名解析"),
    ),
    ProjectConceptSpec(
        "vpn_proxy",
        ("科学上网", "翻墙", "代理", "proxy server", "proxy", "vpn"),
        ("proxy", "vpn", "proxy server", "代理", "翻墙", "科学上网"),
    ),
    ProjectConceptSpec(
        "ad_block",
        ("去广告", "广告拦截", "广告过滤", "ad blocker", "adblock", "ad block"),
        ("ad blocker", "adblock", "ad block", "去广告", "广告拦截", "广告过滤"),
    ),
    ProjectConceptSpec(
        "torrent",
        ("种子", "磁力", "bt 下载", "bittorrent", "torrent"),
        ("torrent", "bittorrent", "bt 下载", "种子", "磁力"),
    ),
    ProjectConceptSpec(
        "media_server",
        ("媒体服务器", "媒体库", "影音库", "media server", "media center"),
        ("media server", "media center", "媒体服务器", "媒体库", "影音"),
    ),
    ProjectConceptSpec(
        "music_player",
        ("音乐播放器", "音乐播放", "music player"),
        ("music player", "audio player", "音乐播放器", "音乐"),
    ),
    ProjectConceptSpec(
        "video_player",
        ("视频播放器", "播放器", "video player", "media player"),
        ("video player", "media player", "视频播放器", "播放器"),
    ),
    ProjectConceptSpec(
        "home_automation",
        ("智能家居", "家庭自动化", "smart home", "home automation"),
        ("smart home", "home automation", "智能家居", "家庭自动化"),
    ),
    ProjectConceptSpec(
        "status_page",
        ("可用性监控", "状态页", "status page", "uptime"),
        ("status page", "uptime monitor", "状态页", "可用性监控"),
    ),
    # —— 电商/企业/协作 ——
    ProjectConceptSpec(
        "ecommerce",
        ("网上购物", "商城", "电商", "online store", "online shop", "e-commerce", "ecommerce"),
        ("ecommerce", "e-commerce", "online store", "商城系统", "电商", "商城"),
    ),
    ProjectConceptSpec(
        "payment",
        ("支付", "收银", "payments", "payment", "checkout"),
        ("payment", "payments", "payment gateway", "checkout", "支付", "收银"),
    ),
    ProjectConceptSpec(
        "auth_sso",
        ("单点登录", "认证", "鉴权", "登录", "authentication", "oauth2", "oauth", "sso"),
        ("authentication", "sso", "oauth", "单点登录", "认证", "鉴权", "登录"),
    ),
    ProjectConceptSpec(
        "crm",
        ("客户关系管理", "crm"),
        ("crm", "customer relationship management", "客户关系管理"),
    ),
    ProjectConceptSpec(
        "erp",
        ("企业资源计划", "erp"),
        ("erp", "enterprise resource planning", "企业资源计划"),
    ),
    ProjectConceptSpec(
        "project_management",
        ("项目管理", "项目协作", "看板", "project management", "kanban", "task board"),
        ("project management", "kanban", "task board", "项目管理", "看板", "项目协作"),
    ),
    ProjectConceptSpec(
        "todo",
        ("待办事项", "待办", "任务清单", "todo list", "to-do", "todos", "todo"),
        ("todo", "to-do", "todo list", "task list", "待办", "待办事项"),
    ),
    ProjectConceptSpec(
        "calendar",
        ("日历", "日程", "calendars", "calendar"),
        ("calendar", "schedule", "scheduling", "日历", "日程"),
    ),
    ProjectConceptSpec(
        "email_tools",
        ("邮件", "邮箱", "e-mail", "email", "mail"),
        ("email", "mail", "e-mail", "smtp", "邮件", "邮箱"),
    ),
    ProjectConceptSpec(
        "time_tracking",
        ("时间追踪", "时间管理", "time tracking", "time tracker", "timesheet"),
        ("time tracking", "time tracker", "timesheet", "时间追踪", "时间管理"),
    ),
    ProjectConceptSpec(
        "expense_tracking",
        ("记账", "账单", "expense tracker", "expense tracking", "budget"),
        ("expense tracker", "expense tracking", "budget", "记账", "账单"),
    ),
    # —— 开发基础设施 ——
    ProjectConceptSpec(
        "database",
        ("数据库", "databases", "database", "dbms"),
        ("database", "databases", "sql", "dbms", "数据库"),
    ),
    ProjectConceptSpec(
        "monitoring",
        ("监控", "告警", "monitoring", "alerting", "monitor"),
        ("monitoring", "alerting", "monitor", "metrics", "监控", "告警"),
    ),
    ProjectConceptSpec(
        "log_management",
        ("日志管理", "日志分析", "日志收集", "log management", "log analysis", "log aggregation"),
        ("log management", "log analysis", "log aggregation", "日志管理", "日志分析", "日志"),
    ),
    ProjectConceptSpec(
        "ci_cd",
        ("持续集成", "持续部署", "ci/cd", "ci cd", "cicd"),
        ("ci/cd", "continuous integration", "continuous deployment", "cicd", "持续集成", "持续部署"),
    ),
    ProjectConceptSpec(
        "message_queue",
        ("消息队列", "消息中间件", "message queue", "message broker", "pub/sub", "pubsub"),
        ("message queue", "message broker", "pub/sub", "pubsub", "消息队列", "消息中间件"),
    ),
    ProjectConceptSpec(
        "search_engine",
        ("搜索引擎", "全文检索", "全文搜索", "search engine", "full-text search", "full text search"),
        ("search engine", "full-text search", "full text search", "搜索引擎", "全文检索"),
    ),
    ProjectConceptSpec(
        "crawler",
        ("网页抓取", "网页爬取", "爬虫", "web scraping", "crawler", "scraper", "spider"),
        ("crawler", "scraper", "web scraping", "spider", "爬虫", "网页抓取"),
    ),
    ProjectConceptSpec(
        "admin_panel",
        ("管理后台", "后台管理", "管理面板", "admin dashboard", "admin panel", "admin ui"),
        ("admin panel", "admin dashboard", "admin ui", "管理后台", "后台管理", "管理面板"),
    ),
    ProjectConceptSpec(
        "dashboard",
        ("数据看板", "仪表盘", "dashboards", "dashboard"),
        ("dashboard", "dashboards", "metrics dashboard", "仪表盘", "数据看板"),
    ),
    ProjectConceptSpec(
        "api_client",
        ("接口调试", "接口测试", "api 调试", "api 测试", "api client", "http client"),
        ("api client", "http client", "rest client", "api 调试", "api 测试", "接口调试"),
    ),
    ProjectConceptSpec(
        "web_framework",
        ("web 框架", "web框架", "web framework"),
        ("web framework", "webframework", "web 框架"),
    ),
    ProjectConceptSpec(
        "low_code",
        ("低代码", "零代码", "low-code", "low code", "no-code", "no code"),
        ("low-code", "low code", "no-code", "低代码", "零代码"),
    ),
    ProjectConceptSpec(
        "docker_container",
        ("容器化", "容器", "containers", "container", "docker"),
        ("docker", "container", "containers", "容器", "容器化"),
    ),
    ProjectConceptSpec(
        "kubernetes",
        ("kubernetes", "k8s"),
        ("kubernetes", "k8s", "容器编排"),
    ),
    ProjectConceptSpec(
        "git_tools",
        ("git",),
        ("git", "git 工具", "version control", "版本控制"),
    ),
    ProjectConceptSpec(
        "editor_ide",
        ("代码编辑器", "编辑器", "editors", "editor", "ide"),
        ("editor", "code editor", "编辑器", "代码编辑器"),
    ),
    ProjectConceptSpec(
        "firewall",
        ("防火墙", "firewall"),
        ("firewall", "waf", "防火墙"),
    ),
    ProjectConceptSpec(
        "iot",
        ("物联网", "iot"),
        ("iot", "internet of things", "物联网"),
    ),
    ProjectConceptSpec(
        "printing_3d",
        ("3d 打印", "3d打印", "3d printing"),
        ("3d printing", "3d 打印", "3d打印"),
    ),
    ProjectConceptSpec(
        "game_engine",
        ("游戏引擎", "game engine"),
        ("game engine", "game development", "游戏引擎"),
    ),
    ProjectConceptSpec(
        "game_mod",
        ("游戏模组", "模组", "mod 管理", "mod管理", "mod 加载", "mods", "mod"),
        ("game mod", "mod manager", "mod loader", "游戏模组", "模组", "游戏 mod"),
    ),
    ProjectConceptSpec(
        "emulator",
        ("模拟器", "仿真器", "emulation", "emulator"),
        ("emulator", "emulation", "模拟器", "仿真器"),
    ),
    ProjectConceptSpec(
        "whiteboard",
        ("白板", "画板", "whiteboard"),
        ("whiteboard", "白板", "画板"),
    ),
    ProjectConceptSpec(
        "diagram",
        ("流程图", "架构图", "图表", "diagramming", "diagrams", "diagram"),
        ("diagram", "diagrams", "chart", "流程图", "架构图", "图表"),
    ),
    ProjectConceptSpec(
        "image_optimization",
        ("图片压缩", "图像压缩", "图片优化", "image optimization", "image compression"),
        ("image optimization", "image compression", "图片压缩", "图像压缩", "图片优化"),
    ),
    ProjectConceptSpec(
        "video_converter",
        ("视频转换", "格式转换", "转码", "video transcoding", "video converter", "transcoding"),
        ("video converter", "transcoding", "ffmpeg", "视频转换", "转码", "格式转换"),
    ),
    ProjectConceptSpec(
        "data_analysis",
        ("数据分析", "数据可视化", "data analysis", "data analytics", "business intelligence", "data visualization"),
        ("data analysis", "data analytics", "business intelligence", "data visualization", "数据分析", "数据可视化"),
    ),
    ProjectConceptSpec(
        "etl",
        ("数据集成", "数据管道", "data pipeline", "data integration", "etl", "elt"),
        ("etl", "elt", "data pipeline", "data integration", "数据集成", "数据管道"),
    ),
    ProjectConceptSpec(
        "data_labeling",
        ("数据标注", "标注工具", "data labeling", "data annotation"),
        ("data labeling", "data annotation", "数据标注", "标注工具"),
    ),
    ProjectConceptSpec(
        "feature_flag",
        ("功能开关", "灰度发布", "feature flags", "feature flag", "feature toggle"),
        ("feature flag", "feature flags", "feature toggle", "功能开关", "灰度发布"),
    ),
    ProjectConceptSpec(
        "api_gateway",
        ("api 网关", "api网关", "网关", "api gateway"),
        ("api gateway", "api 网关", "网关"),
    ),
    ProjectConceptSpec(
        "secrets_manager",
        ("密钥管理", "密钥", "secrets management", "secret management"),
        ("secrets management", "secret manager", "vault", "密钥管理", "密钥"),
    ),
    ProjectConceptSpec(
        "code_search",
        ("代码搜索", "代码检索", "code search"),
        ("code search", "代码搜索", "代码检索"),
    ),
    ProjectConceptSpec(
        "diff_tool",
        ("文件对比", "对比工具", "diff tool", "diff"),
        ("diff tool", "merge tool", "文件对比", "对比工具"),
    ),
)
