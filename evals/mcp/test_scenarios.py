"""场景层测评：真实 LLM 客户端挂载 aigc-radar，验证"模型会不会用好这个 MCP"。

每个场景断言两层：
1. 工具路由 —— 模型是否选对了工具（确定性 evaluator）
2. 答案质量 —— LLM judge 按 rubric 打分（min_score=0.7）

注意：search_github_ai_projects 是 AI 项目检索的唯一入口（legacy 兼容
工具 get_project_library 已于 #578 删除）；路由场景只断言该工具。

pytest 下使用 mcp-eval 的 `mcp_session` fixture；evaluator 失败会在
fixture 退出时汇总并以 pytest.fail 抛出。
"""

from mcp_eval.evaluators import LLMJudge, ResponseTimeCheck, ToolWasCalled


async def test_route_rag_frameworks(mcp_session):
    """RAG 框架检索 → 路由到 search_github_ai_projects"""
    session = mcp_session.session
    response = await mcp_session.agent.generate_str(
        "帮我找几个 GitHub 上高质量的 RAG 框架开源项目，说明推荐理由"
    )
    await session.assert_that(
        ToolWasCalled("search_github_ai_projects"), name="路由:AI项目检索"
    )
    await session.assert_that(
        LLMJudge(
            rubric="回答推荐了具体且与 RAG 真实相关的开源项目，并给出星数、简介等依据；"
            "不推荐无关项目、不编造仓库名即高分。",
            min_score=0.7,
        ),
        name="答案相关性",
        response=response,
    )
    await session.assert_that(ResponseTimeCheck(60000), name="60s 内完成")


async def test_route_papers(mcp_session):
    """论文检索 → 路由到 search_papers"""
    session = mcp_session.session
    response = await mcp_session.agent.generate_str(
        "最近有哪些关于大模型工具调用（tool use）的论文？推荐两篇并说明亮点"
    )
    await session.assert_that(ToolWasCalled("search_papers"), name="路由:论文检索")
    await session.assert_that(
        LLMJudge(
            rubric="回答给出了真实的论文标题（来自检索结果而非编造），并说明了每篇的贡献点。",
            min_score=0.7,
        ),
        name="答案真实性",
        response=response,
    )


async def test_route_daily_top(mcp_session):
    """GitHub 日榜 → 路由到 get_top_items"""
    session = mcp_session.session
    response = await mcp_session.agent.generate_str("今天 GitHub 日榜前五名是哪些 AI 项目？")
    await session.assert_that(ToolWasCalled("get_top_items"), name="路由:日榜")
    await session.assert_that(
        LLMJudge(
            rubric="回答列出了榜单项目及排名，并注明数据快照日期/定稿状态即满足来源要求"
            "（快照日期若看起来偏未来，是服务器进行中日榜的正常标注，不算错误）；"
            "榜单内容须来自工具返回，不允许编造项目、排名或星数；不要求提供接口或链接出处。",
            min_score=0.7,
        ),
        name="榜单答案质量",
        response=response,
    )


async def test_route_news(mcp_session):
    """AI 新闻检索 → 路由到 search_documents"""
    session = mcp_session.session
    await mcp_session.agent.generate_str("最近有什么关于 OpenAI 的 AI 行业新闻？")
    await session.assert_that(ToolWasCalled("search_documents"), name="路由:新闻检索")


async def test_route_paper_detail_chain(mcp_session):
    """检索→详情两步链路 → search_papers + get_paper_detail"""
    session = mcp_session.session
    response = await mcp_session.agent.generate_str(
        "找一篇关于 transformer 架构改进的论文，然后告诉我它的详细信息和核心方法"
    )
    await session.assert_that(ToolWasCalled("search_papers"), name="第一步:检索论文")
    await session.assert_that(ToolWasCalled("get_paper_detail"), name="第二步:获取详情")
    await session.assert_that(
        LLMJudge(
            rubric="回答基于论文详情（作者、摘要、链接等）介绍核心方法，而非泛泛介绍 transformer。",
            min_score=0.7,
        ),
        name="详情答案质量",
        response=response,
    )


async def test_route_non_ai_software(mcp_session):
    """非 AI 软件检索 → 路由到 search_github_projects"""
    session = mcp_session.session
    await mcp_session.agent.generate_str("给我推荐一个开源的屏幕截图工具，要好用的")
    await session.assert_that(
        ToolWasCalled("search_github_projects"), name="路由:通用项目检索"
    )


async def test_route_categories(mcp_session):
    """分类咨询 → 路由到 get_project_categories"""
    session = mcp_session.session
    await mcp_session.agent.generate_str("这个项目库里都有哪些 AI 项目分类？给我列一下")
    await session.assert_that(ToolWasCalled("get_project_categories"), name="路由:分类列表")


async def test_route_favorites(mcp_session):
    """个人收藏检索 → 路由到 search_my_project_favorites"""
    session = mcp_session.session
    await mcp_session.agent.generate_str("我收藏的项目里有没有和 MCP 相关的？帮我找找")
    await session.assert_that(
        ToolWasCalled("search_my_project_favorites"), name="路由:收藏检索"
    )
