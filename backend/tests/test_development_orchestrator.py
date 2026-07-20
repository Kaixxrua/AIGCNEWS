from backend.app.services.rag.development_orchestrator import (
    ComplexityScores,
    assess_candidate,
    classify_development_request,
)


def test_score_total_uses_six_dimensions():
    assert ComplexityScores(3, 3, 3, 3, 3, 3).total == 18


def test_local_change_hard_skip_wins_over_auth_keyword():
    decision = classify_development_request("修改 LoginView.vue 登录认证按钮的文案")
    assert decision.route == "direct"
    assert "narrow_local_change" in decision.reasons


def test_explicit_self_build_skips_search():
    decision = classify_development_request("做一个权限功能，但这次明确自己实现，从零开发")
    assert decision.route == "direct"


def test_complete_subsystem_hard_triggers_search():
    decision = classify_development_request("开发一个完整平台，包含前端、后端、数据库和工作流引擎")
    assert decision.route == "search_and_ask"
    assert decision.score >= 9


def test_vague_greenfield_product_triggers_search():
    decision = classify_development_request("我们做个电商的AGENT")
    assert decision.route == "search_and_ask"
    assert decision.search_mode == "ai"
    assert "greenfield_product_without_local_anchor" in decision.reasons


def test_greenfield_rule_does_not_override_local_anchor():
    decision = classify_development_request("在 ShopAgent.vue 里修改电商 Agent 的按钮文案")
    assert decision.route == "direct"


def test_explicit_open_source_request_hard_triggers_search():
    decision = classify_development_request("帮我找一个类似 iShot 的开源截图项目")
    assert decision.route == "search_and_ask"
    assert "explicit_open_source_request" in decision.reasons


def test_non_development_question_keeps_existing_rag():
    assert classify_development_request("今天 GitHub 排行榜有哪些项目").route == "existing_rag"


def test_ai_mode_and_language_hint():
    decision = classify_development_request("开发一个完整的 Python RAG Agent 平台")
    assert decision.search_mode == "ai"
    assert decision.language_hint == "Python"


def test_follow_up_scratch_choice_does_not_search_again():
    history = [{"role": "assistant", "content": "请选择下一步：A 复用；B 从零开发；C 重新搜索"}]
    assert classify_development_request("B", history).route == "direct"


def test_candidate_quality_and_route_impact():
    result = assess_candidate({
        "description": "A maintained server platform and database workflow",
        "tags": ["platform", "server"],
        "stars": 8000,
        "pushed_at": "2026-07-01",
    })
    assert result.worthwhile
    assert result.requires_user_choice
