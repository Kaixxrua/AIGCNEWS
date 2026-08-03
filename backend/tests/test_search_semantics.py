from __future__ import annotations

import pytest

from backend.app.domain.search_semantics import (
    build_client_project_search_intent,
    build_project_lexical_retrieval_plan,
    build_project_search_intent,
)


def test_project_intent_normalizes_request_and_expands_known_bilingual_concepts() -> None:
    intent = build_project_search_intent("  帮我找一下学习 Agent 工作流的仓库  ")

    assert intent.schema_version == "project-search-intent-v1"
    assert intent.normalized_query == "学习 Agent 工作流的仓库"
    assert intent.language == "mixed"
    assert intent.semantic_queries[0] == intent.normalized_query
    assert "workflow automation" in intent.semantic_queries[1]
    assert intent.lexical_terms == ("Agent", "工作流")


def test_project_intent_extracts_bounded_chinese_concepts_and_aliases() -> None:
    intent = build_project_search_intent(
        "提升 AI 编程智能体编码速度 项目记忆 上下文压缩和任务依赖管理"
    )
    plan = build_project_lexical_retrieval_plan(intent)

    assert intent.lexical_terms == (
        "AI",
        "编程智能体",
        "编码速度",
        "项目记忆",
        "上下文压缩",
        "任务依赖管理",
    )
    assert intent.concept_ids == (
        "coding_assistant",
        "coding_productivity",
        "codebase_memory",
        "context_management",
        "agent_task_tracking",
    )
    assert "codebase memory" in intent.semantic_queries[1]
    assert "context compression" in intent.semantic_queries[1]
    assert plan.strict_terms == ()
    assert {concept.concept_id for concept in plan.concepts} == set(intent.concept_ids)
    assert all(
        alias not in plan.strict_terms
        for concept in plan.concepts
        for alias in concept.aliases
    )


def test_longest_chinese_phrase_wins_and_unknown_name_is_not_translated() -> None:
    intent = build_project_search_intent("星火智能体工作流")

    assert intent.lexical_terms == ("智能体工作流",)
    assert intent.concept_ids == ("workflow",)
    assert intent.intent_class == "general_discovery"
    assert "星火" not in " ".join(intent.bilingual_aliases)


def test_project_intent_preserves_technical_tokens() -> None:
    intent = build_project_search_intent("C++ .NET MCP RAG developer tools")

    assert intent.language == "en"
    assert intent.lexical_terms[:4] == ("C++", ".NET", "MCP", "RAG")
    # MCP/RAG/developer tools 现在是词法概念：命中后仍保留原查询，
    # 并为语义 lane 追加跨语言别名（mcp 概念的第一别名）。
    assert intent.concept_ids == ("mcp", "rag", "developer_tools")
    assert intent.semantic_queries[0] == "C++ .NET MCP RAG developer tools"
    assert "model context protocol" in intent.semantic_queries[1]


def test_client_intent_normalizes_deduplicates_and_preserves_server_query() -> None:
    intent = build_client_project_search_intent(
        "帮我找 MCP Python SDK",
        {
            "language": "mixed",
            "intent_class": "sdk",
            "lexical_terms": [" MCP ", "mcp", "Python", "SDK"],
            "semantic_queries": ["MCP Python SDK examples"],
            "topics": ["MCP", "mcp"],
            "languages": ["Python"],
            "artifact_types": ["SDK"],
            "must_have": ["MCP", "Python"],
            "should_have": ["examples"],
        },
    )

    assert intent.schema_version == "project-search-intent-client-v1"
    assert intent.normalized_query == "MCP Python SDK"
    assert intent.lexical_terms == ("MCP", "Python", "SDK")
    assert intent.topics == ("MCP",)


def test_client_intent_rejects_removed_protected_token() -> None:
    with pytest.raises(ValueError, match="protected"):
        build_client_project_search_intent(
            "C++ RAG framework",
            {
                "language": "en",
                "lexical_terms": ["framework"],
                "semantic_queries": ["retrieval framework"],
            },
        )


@pytest.mark.parametrize("control", ["\n", "\x7f", "\x85"])
def test_client_intent_rejects_control_characters(control: str) -> None:
    with pytest.raises(ValueError, match="control"):
        build_client_project_search_intent(
            "agent SDK",
            {
                "language": "en",
                "lexical_terms": [f"agent{control}SDK"],
                "semantic_queries": ["agent SDK"],
            },
        )


def test_client_intent_requires_exact_protected_token() -> None:
    with pytest.raises(ValueError, match="protected"):
        build_client_project_search_intent(
            "MCP SDK",
            {
                "language": "en",
                "lexical_terms": ["xmcp", "SDK"],
                "semantic_queries": ["Python SDK"],
            },
        )


def test_unknown_chinese_name_does_not_fabricate_translation() -> None:
    intent = build_project_search_intent("学习 LangGraph 星火教程")

    assert intent.language == "mixed"
    assert intent.semantic_queries == ("学习 LangGraph 星火教程", "学习 LangGraph 星火教程 tutorial learning")


def test_ascii_concept_triggers_require_word_boundaries() -> None:
    # client/digital/hotel/modern 不得误触发 cli/git/otel/mod；
    # database 作为正向对照必须命中。
    intent = build_project_search_intent("database client for modern digital hotel management")

    assert "database" in intent.concept_ids
    assert "cli" not in intent.concept_ids
    assert "git_tools" not in intent.concept_ids
    assert "game_mod" not in intent.concept_ids
    assert "llm_observability" not in intent.concept_ids

    bounded = build_project_search_intent("git cli tools")
    assert "git_tools" in bounded.concept_ids
    assert "cli" in bounded.concept_ids


def test_english_coding_cli_query_activates_bilingual_concepts() -> None:
    intent = build_project_search_intent("AI coding agent CLI")
    plan = build_project_lexical_retrieval_plan(intent)

    assert intent.concept_ids == ("coding_assistant", "cli")
    assert plan.strict_terms == ()
    groups = {concept.concept_id: concept for concept in plan.concepts}
    assert "编程助手" in groups["coding_assistant"].aliases
    assert "终端" in groups["cli"].aliases


def test_chinese_concept_expands_english_alias_for_semantic_lane() -> None:
    intent = build_project_search_intent("截图")

    assert intent.concept_ids == ("screenshot",)
    assert len(intent.semantic_queries) == 2
    assert "screenshot" in intent.semantic_queries[1]


_CONCEPT_TRIGGER_CASES: dict[str, tuple[str, ...]] = {
    "coding_productivity": ("开发效率工具", "developer productivity"),
    "context_management": ("上下文压缩", "context compression"),
    "codebase_memory": ("代码库记忆", "codebase memory"),
    "agent_task_tracking": ("任务依赖管理", "task tracking"),
    "coding_assistant": ("编程助手", "coding assistant"),
    "developer_tools": ("开发者工具", "developer tools"),
    "workflow": ("工作流编排", "workflow engine"),
    "rag": ("知识库问答", "rag pipeline"),
    "self_hosted": ("自托管部署", "self-hosted"),
    "learning": ("入门教程", "tutorial"),
    "agent": ("智能体", "agent"),
    "llm": ("大模型应用", "llm tools"),
    "prompt_engineering": ("提示词管理", "prompt engineering"),
    "llm_evaluation": ("模型评测", "llm eval"),
    "mcp": ("mcp 服务", "model context protocol"),
    "function_calling": ("工具调用", "function calling"),
    "multi_agent": ("多智能体", "multi-agent orchestration"),
    "agent_memory": ("智能体记忆", "agent memory"),
    "llm_observability": ("可观测性", "llm observability"),
    "llm_serving": ("模型推理加速", "llm serving"),
    "fine_tuning": ("模型微调", "fine-tuning"),
    "vector_search": ("向量数据库", "vector database"),
    "embedding": ("文本嵌入", "embedding model"),
    "speech_tts": ("语音合成", "text to speech"),
    "speech_asr": ("语音识别", "speech to text"),
    "image_generation": ("文生图", "text to image"),
    "video_generation": ("视频生成", "text to video"),
    "code_review": ("代码审查", "code review"),
    "cli": ("命令行工具", "cli"),
    "terminal_emulator": ("终端模拟器", "terminal emulator"),
    "chatbot": ("聊天机器人", "chatbot"),
    "text2sql": ("自然语言查询数据库", "text2sql"),
    "local_llm": ("本地大模型", "local llm"),
    "crypto": ("加密工具", "encryption"),
    "password_manager": ("密码管理", "password manager"),
    "screenshot": ("截图工具", "screenshot"),
    "screen_recording": ("录屏软件", "screen recording"),
    "note_taking": ("笔记软件", "note-taking"),
    "photo_management": ("相册管理", "photo management"),
    "video_download": ("视频下载", "video downloader"),
    "file_sync": ("文件同步", "file sync"),
    "file_manager": ("文件管理器", "file manager"),
    "pdf_tools": ("pdf 工具", "pdf"),
    "database": ("数据库", "database"),
    "monitoring": ("监控系统", "monitoring"),
    "log_management": ("日志分析", "log management"),
    "ci_cd": ("持续集成", "ci/cd"),
    "message_queue": ("消息队列", "message queue"),
    "search_engine": ("搜索引擎", "search engine"),
    "crawler": ("爬虫框架", "web scraping"),
    "admin_panel": ("管理后台", "admin panel"),
    "dashboard": ("数据看板", "dashboard"),
    "wiki": ("维基", "wiki"),
    "blog": ("博客系统", "blog"),
    "forum": ("论坛程序", "forum"),
    "ecommerce": ("商城系统", "ecommerce"),
    "payment": ("支付网关", "payment"),
    "auth_sso": ("单点登录", "oauth2"),
    "crm": ("客户关系管理", "crm"),
    "erp": ("企业资源计划", "erp"),
    "project_management": ("项目管理", "kanban"),
    "todo": ("待办事项", "todo list"),
    "calendar": ("日历应用", "calendar"),
    "email_tools": ("邮件客户端", "email"),
    "markdown": ("markdown 笔记", "markdown"),
    "static_site": ("静态网站生成", "static site"),
    "cms": ("内容管理系统", "headless cms"),
    "reverse_proxy": ("反向代理", "reverse proxy"),
    "dns": ("域名解析", "dns server"),
    "vpn_proxy": ("科学上网", "vpn"),
    "ad_block": ("广告拦截", "ad blocker"),
    "torrent": ("磁力下载", "torrent"),
    "ebook": ("电子书管理", "ebook"),
    "game_engine": ("游戏引擎", "game engine"),
    "game_mod": ("游戏模组", "mods"),
    "emulator": ("模拟器", "emulator"),
    "home_automation": ("智能家居", "smart home"),
    "media_server": ("媒体服务器", "media server"),
    "music_player": ("音乐播放器", "music player"),
    "video_player": ("视频播放器", "video player"),
    "ocr": ("文字识别", "ocr"),
    "translation": ("翻译工具", "translation"),
    "clipboard": ("剪贴板", "clipboard"),
    "launcher": ("应用启动器", "launcher"),
    "remote_desktop": ("远程桌面", "remote desktop"),
    "backup": ("数据备份", "backup"),
    "rss": ("rss 阅读", "rss reader"),
    "api_client": ("接口调试", "api client"),
    "web_framework": ("web 框架", "web framework"),
    "low_code": ("低代码平台", "low-code"),
    "docker_container": ("容器化部署", "docker"),
    "kubernetes": ("k8s 部署", "kubernetes"),
    "git_tools": ("git 别名", "git"),
    "editor_ide": ("代码编辑器", "code editor"),
    "firewall": ("防火墙", "firewall"),
    "iot": ("物联网平台", "iot"),
    "printing_3d": ("3d打印", "3d printing"),
    "time_tracking": ("时间追踪", "time tracking"),
    "whiteboard": ("白板", "whiteboard"),
    "diagram": ("流程图", "diagram"),
    "image_optimization": ("图片压缩", "image compression"),
    "video_converter": ("视频转换", "transcoding"),
    "data_analysis": ("数据分析", "data analysis"),
    "etl": ("数据管道", "etl"),
    "data_labeling": ("数据标注", "data labeling"),
    "knowledge_management": ("知识管理", "second brain"),
    "mind_map": ("思维导图", "mind map"),
    "expense_tracking": ("记账软件", "expense tracker"),
    "status_page": ("状态页", "uptime"),
    "feature_flag": ("功能开关", "feature flags"),
    "api_gateway": ("api 网关", "api gateway"),
    "secrets_manager": ("密钥管理", "secrets management"),
    "code_search": ("代码搜索", "code search"),
    "diff_tool": ("文件对比", "diff tool"),
    "window_manager": ("平铺窗口", "tiling window"),
}


def test_concept_lexicon_covers_mainstream_scenarios_bilingually() -> None:
    for concept_id, queries in _CONCEPT_TRIGGER_CASES.items():
        for query in queries:
            intent = build_project_search_intent(query)
            assert concept_id in intent.concept_ids, f"{query!r} 未触发概念 {concept_id}"
