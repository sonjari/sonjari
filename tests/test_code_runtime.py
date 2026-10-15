from __future__ import annotations

from alture_jarvis.code_runtime import (
    CODE_CORE_TOOL_NAMES,
    CODE_RESEARCH_TOOL_NAMES,
    CODE_SANDBOX_TOOL_NAMES,
    code_verification_is_current,
    qwen_code_tools,
    route_code_profile,
    select_code_tool_profile,
)
from alture_jarvis.ollama import OllamaClient


def test_code_profile_routes_explanation_patch_and_repeated_failure() -> None:
    assert route_code_profile("이 함수가 하는 일을 설명해줘", configured="fast") == "fast"
    assert route_code_profile("이 버그를 수정해줘", configured="balanced") == "medium"
    failed = {
        "tool": "local_run_project_command",
        "evidence": {"verified": False, "failure_fingerprint": "same"},
        "code_phase": "repair",
    }
    assert route_code_profile("계속 진행", steps=[failed, failed]) == "deep"


def test_verification_survives_cleanup_of_a_new_verify_helper() -> None:
    steps = [
        {"tool": "local_write_file", "ok": True,
         "arguments": {"path": "index.html"},
         "evidence": {"output_path": r"C:\work\index.html", "created": False}},
        {"tool": "local_write_file", "ok": True,
         "arguments": {"path": "verify_ui.py"},
         "evidence": {"output_path": r"C:\work\verify_ui.py", "created": True}},
        {"tool": "local_run_project_command", "ok": True,
         "evidence": {"verified": True}},
        {"tool": "local_delete_file", "ok": True,
         "arguments": {"path": "verify_ui.py"},
         "evidence": {"output_path": r"C:\work\verify_ui.py", "verified": True}},
    ]
    assert code_verification_is_current(steps) is True


def test_verification_is_stale_after_a_real_edit_or_existing_file_delete() -> None:
    verified = {"tool": "local_run_project_command", "ok": True,
                "evidence": {"verified": True}}
    real_edit = {"tool": "local_apply_edit", "ok": True,
                 "evidence": {"output_path": r"C:\work\index.html"}}
    existing_delete = {"tool": "local_delete_file", "ok": True,
                       "evidence": {"output_path": r"C:\work\app.js"}}
    assert code_verification_is_current([verified, real_edit]) is False
    assert code_verification_is_current([verified, existing_delete]) is False


def test_architecture_filename_alone_does_not_force_deep_thinking() -> None:
    prompt = "Read docs/ARCHITECTURE.md, reproduce tests, and implement the fix."
    assert route_code_profile(prompt) == "medium"


def test_qwen_tool_schema_is_closed_and_compact() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "local_read_text_file",
                "description": "very long generic description",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "long path help"},
                    },
                    "required": ["path"],
                },
            },
        },
        {"type": "function", "function": {"name": "gmail_send", "parameters": {}}},
    ]

    compact = qwen_code_tools(tools, {"local_read_text_file"})

    assert len(compact) == 1
    parameters = compact[0]["function"]["parameters"]
    assert parameters["additionalProperties"] is False
    assert "description" not in parameters["properties"]["path"]


def test_code_tool_profile_keeps_normal_repo_work_small() -> None:
    profile = select_code_tool_profile("로그인 버그를 읽고 수정한 뒤 테스트해줘")

    assert profile.name == "core"
    assert profile.tool_names == CODE_CORE_TOOL_NAMES
    assert not (profile.tool_names & CODE_RESEARCH_TOOL_NAMES)
    assert not (profile.tool_names & CODE_SANDBOX_TOOL_NAMES)


def test_frontend_work_can_open_and_click_its_preview() -> None:
    from alture_jarvis.code_runtime import CODE_PREVIEW_TOOL_NAMES

    for prompt in ("첫 화면을 만들어줘", "프론트엔드 버튼을 고쳐줘", "제품을 눌러 보고 검증해줘"):
        profile = select_code_tool_profile(prompt)
        assert CODE_PREVIEW_TOOL_NAMES <= profile.tool_names, prompt
        assert "preview" in profile.name, prompt
    assert select_code_tool_profile("웹소켓 핸들러 고쳐줘").name == "core"


def test_local_preview_tool_names_do_not_open_external_research() -> None:
    profile = select_code_tool_profile(
        "프론트 화면을 만들고 local_preview_page, browser_open, browser_snapshot으로 확인해줘"
    )
    assert profile.name == "core+preview"
    assert "browser_site_search" not in profile.tool_names
    assert "browser_open_result" not in profile.tool_names


def test_reviewed_and_reverified_code_is_ready_for_one_final_answer() -> None:
    from alture_jarvis.code_runtime import code_ready_for_final_answer

    steps = [
        {"tool": "local_write_file", "ok": True,
         "evidence": {"output_path": r"C:\work\index.html", "created": True}},
        {"tool": "local_run_project_command", "ok": True, "evidence": {"verified": True}},
        {"tool": "local_write_file", "ok": True,
         "evidence": {"output_path": r"C:\work\verify.py", "created": True}},
        {"tool": "local_run_project_command", "ok": True, "evidence": {"verified": True}},
        {"tool": "local_delete_file", "ok": True,
         "evidence": {"output_path": r"C:\work\verify.py", "verified": True}},
    ]
    assert code_ready_for_final_answer(steps, plan_met=True, review_requested_step=2)
    assert not code_ready_for_final_answer(steps, plan_met=False, review_requested_step=2)
    assert not code_ready_for_final_answer(steps[:2], plan_met=True, review_requested_step=2)


def test_qwen_keeps_browser_expectation_enum() -> None:
    tools = [{"type": "function", "function": {
        "name": "browser_click", "description": "click", "parameters": {
            "type": "object", "properties": {"expect": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["text_appears", "url_changes"]}
            }}}
        }
    }}]
    compact = qwen_code_tools(tools, {"browser_click"})
    kind = compact[0]["function"]["parameters"]["properties"]["expect"]["properties"]["kind"]
    assert kind["enum"] == ["text_appears", "url_changes"]


def test_code_tool_profile_opens_read_only_research_without_sandbox() -> None:
    profile = select_code_tool_profile(
        "최신 코딩 에이전트 트렌드를 GitHub와 Reddit에서 조사해서 비교해줘"
    )

    assert profile.name == "core+research"
    assert {"github_search", "reddit_hot", "browser_search", "browser_extract"} <= profile.tool_names
    assert not (profile.tool_names & CODE_SANDBOX_TOOL_NAMES)


def test_code_tool_profile_opens_sandbox_only_for_explicit_scratch_work() -> None:
    profile = select_code_tool_profile("파이썬으로 직접 계산하고 그래프를 만들어줘")

    assert profile.name == "core+sandbox"
    assert CODE_SANDBOX_TOOL_NAMES <= profile.tool_names
    assert not (profile.tool_names & CODE_RESEARCH_TOOL_NAMES)


def test_code_tool_profile_can_force_sandbox_for_folderless_code_artifact() -> None:
    profile = select_code_tool_profile("작은 코드를 만들어줘", force_sandbox=True)

    assert profile.name == "core+sandbox"
    assert CODE_SANDBOX_TOOL_NAMES <= profile.tool_names


def test_ollama_inference_observation_does_not_claim_unacknowledged_options() -> None:
    contract = OllamaClient._inference_contract(role="code", profile="deep", think=True)
    observation = OllamaClient._inference_observation(
        requested=contract,
        payload={"done": True},
        messages=[{"role": "assistant", "thinking": "kept"}],
        thinking_chars=123,
    )

    assert contract == {"reasoning_effort": "high", "preserve_thinking": True}
    assert observation["request_sent"] is True
    assert observation["response_acknowledged"] == {
        "reasoning_effort": None,
        "preserve_thinking": None,
    }
    assert observation["thinking_history_messages_sent"] == 1


def test_ollama_inference_observation_preserves_q4_speed_and_token_telemetry() -> None:
    observation = OllamaClient._inference_observation(
        requested={"reasoning_effort": "medium"},
        payload={
            "message": {}, "prompt_eval_count": 1200, "eval_count": 300,
            "eval_duration": 15_000_000_000, "total_duration": 20_000_000_000,
        },
        messages=[], thinking_chars=0,
    )

    assert observation["telemetry"]["prompt_eval_count"] == 1200
    assert observation["telemetry"]["eval_count"] == 300
    assert observation["telemetry"]["eval_tokens_per_sec"] == 20.0


def test_natural_phrasings_open_the_research_tools() -> None:
    """도구가 안 열리면 모델은 거절하지 않고 **지어낸다.**

    2026-08-28 실측으로 뚫린 구멍들이다. "이 API 문서 좀 보고 고쳐줘" 와
    "requests 쓰는 법 알려줘" 가 전부 core 로 떨어져 웹 도구 14 개가 안 열렸다.
    「라우팅 낱말표 → 78% 창작」과 같은 자리라 낱말표를 넓히고 역검증까지 박는다.
    """
    from alture_jarvis.code_runtime import select_code_tool_profile

    for prompt in (
        "이 API 문서 좀 보고 고쳐줘",
        "requests 쓰는 법 알려줘",
        "이 함수 어떻게 쓰는지 알려줘",
        "예제 코드 좀 찾아줘",
        "이거 deprecated 됐나 확인해줘",
        "레퍼런스 확인하고 고쳐줘",
        "마이그레이션 가이드 보고 올려줘",
    ):
        assert "research" in select_code_tool_profile(prompt).name, prompt


def test_natural_phrasings_open_the_sandbox_tools() -> None:
    from alture_jarvis.code_runtime import select_code_tool_profile

    for prompt in (
        "이 함수 성능 측정해서 표로 만들어줘",
        "결과를 표로 정리해줘",
        "엑셀로 뽑아줘",
        "시각화해줘",
    ):
        assert "sandbox" in select_code_tool_profile(prompt).name, prompt


def test_repo_only_work_does_not_open_web_or_sandbox() -> None:
    """넓히기만 하고 역검증을 안 하면 반대편이 깨진다.

    도구를 과하게 주면 Qwen 의 도구 선택 정확도가 떨어진다(code_runtime 주석의
    2026-08-26 실측). 특히 `찾아줘`·맨 `검색` 은 저장소 안 일까지 끌어온다.
    """
    from alture_jarvis.code_runtime import select_code_tool_profile

    for prompt in (
        "이 저장소 테스트 깨진 거 고쳐줘",
        "agent.py 리팩터링 해줘",
        "이 에러 스택트레이스 원인 찾아줘",
        "버그 원인 찾아줘",
        "이 검색 함수 고쳐줘",
        "config.py 읽어줘",
        "pytest 돌려줘",
        "타입 힌트 추가해줘",
        "이 테스트가 왜 실패하는지 봐줘",
        "이 클래스 문서화 주석 달아줘",
    ):
        assert select_code_tool_profile(prompt).name == "core", prompt


def test_naming_the_surface_opens_it() -> None:
    """도구 이름을 직접 부르면 연다 — 의도 추측이 아니라 **명시적 요청**이다.

    2026-08-28 라이브: 사용자님이 "브라우저나 이런거 이용해서 … 깃허브나 이런데에서
    … 브라우저 조사라던지" 라고 다섯 번 말했는데 프로필이 `core` 로 떨어져 web
    도구가 하나도 안 열렸다. `깃허브에서` 는 조사 '에서' 를 요구해 "깃허브나" 를,
    `조사해` 는 "조사라던지" 를 놓쳤고 `브라우저` 는 낱말표에 없었다.

    자비스는 지어내지 않고 "쓸 수 있는 도구는 local_* 8개뿐" 이라고 정직하게
    답했다. 손을 묶은 것은 모델이 아니라 우리 낱말표였다.
    """
    from alture_jarvis.code_runtime import select_code_tool_profile

    spoken = (
        "그냥 그 너가 자비스 너 스스로 코드를 보고 그다음에 이제 그머라고하지 "
        "브라우저나 이런거 이용해서 이제 한번 해달라는거였어 그 깃허브나 "
        "이런데에서 이제 그 브라우저 조사라던지 이런것들을"
    )
    assert "research" in select_code_tool_profile(spoken).name

    for prompt in ("브라우저 이용해서", "깃허브나 이런데에서", "조사라던지", "네이버에서 찾아봐"):
        assert "research" in select_code_tool_profile(prompt).name, prompt


def test_web_prefixed_code_words_do_not_open_the_web() -> None:
    """`웹` 을 통째로 받으면 웹소켓·웹팩 같은 저장소 일까지 끌어온다."""
    from alture_jarvis.code_runtime import select_code_tool_profile

    for prompt in ("웹소켓 핸들러 고쳐줘", "웹팩 설정 바꿔줘"):
        assert select_code_tool_profile(prompt).name == "core", prompt


def test_code_mode_can_reach_the_skills() -> None:
    """스킬 66종이 있고 로더도 도는데 **코드 모드만 못 불렀다.**

    2026-08-29: `skill_list`·`skill_read` 가 코드 프로필에 없었다. 코워크는 부르고
    있었으니, 같은 저장소 안에서 한쪽 문만 잠겨 있던 셈이다. 코딩 규약·절차를
    담는 그릇이라 코드 판에서 가장 쓸모가 큰데도 그랬다.
    """
    from alture_jarvis.code_runtime import CODE_CORE_TOOL_NAMES, select_code_tool_profile

    assert {"skill_list", "skill_read"} <= CODE_CORE_TOOL_NAMES
    # 낱말표와 무관하게 **항상** 있어야 한다 — 스킬을 부를지는 모델이 정한다.
    assert {"skill_list", "skill_read"} <= select_code_tool_profile("이 버그 고쳐줘").tool_names


def test_tools_do_not_vanish_on_the_next_turn() -> None:
    """대화는 이어지는데 손은 매 턴 새로 정해졌다.

    2026-08-29 라이브 재현:
        세 턴 전  "브라우저로 깃허브 조사해줘"  -> core+research
        이번 턴   "1부터 한번 해보자"            -> core  (손이 사라짐)

    자비스는 지어내지 않고 "내가 지금 가진 것은 local_* 과 skill_* 뿐"이라고
    정직하게 말했지만, 시킨 일을 못 한 것은 그대로다. 낱말표 구멍이 아니라
    **범위** 문제였다.
    """
    from alture_jarvis.code_runtime import recent_user_context, select_code_tool_profile

    history = [
        {"role": "user", "content": "브라우저로 깃허브에서 스킬 조사해줘"},
        {"role": "assistant", "content": "찾았습니다"},
        {"role": "user", "content": "괜찮네"},
    ]
    context = recent_user_context(history)

    assert select_code_tool_profile("1부터 한번 해보자").name == "core", "재현 전제"
    assert "research" in select_code_tool_profile("1부터 한번 해보자", context=context).name


def test_only_the_user_can_open_a_hand() -> None:
    """모델이 제 말로 제 손을 여는 길은 열지 않는다."""
    from alture_jarvis.code_runtime import recent_user_context, select_code_tool_profile

    history = [
        {"role": "assistant", "content": "브라우저로 깃허브를 조사하겠습니다"},
        {"role": "tool", "content": "브라우저 조사 결과"},
    ]
    assert recent_user_context(history) == ""
    assert select_code_tool_profile("이 버그 고쳐줘", context=recent_user_context(history)).name == "core"


def test_the_context_is_bounded() -> None:
    """맥락은 전사가 아니다 — 오래된 말이 손을 영원히 열어 두면 안 된다."""
    from alture_jarvis.code_runtime import (
        _PROFILE_CONTEXT_CHARS,
        _PROFILE_CONTEXT_TURNS,
        recent_user_context,
    )

    history = [{"role": "user", "content": f"발화 {i}"} for i in range(20)]
    got = recent_user_context(history)
    assert "발화 19" in got and "발화 0" not in got
    assert len(got) <= _PROFILE_CONTEXT_CHARS
    assert _PROFILE_CONTEXT_TURNS <= 5


def test_the_context_is_actually_wired_into_the_loop() -> None:
    """만들어 놓고 부르는 자리가 없으면 아무 일도 안 일어난다."""
    import inspect

    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent.run)
    assert "recent_user_context(history)" in source
    assert source.count("context=profile_context") == 2, "재개 경로에도 걸려야 한다"
