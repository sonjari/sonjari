"""**칭찬은 일이 아니다** — 낱말이 아니라 그 낱말이 놓인 모양을 본다 (2026-09-18 저녁).

## 무엇이 있었나 (나래 계정 · 클로드 한도 → 온텔릭 이어받기 대화)

    20:32  「이거는 그 문서로 만들어줘 클로드가 나중에 제한 풀리면 보고 검토해달라고하게」
           → 계약: analyze + mutate_or_create. 「검토」는 **클로드가 나중에 할 일**인데 온텔릭 일로 읽고,
             「근거 읽기」가 계획에 들어가 시키지 않은 웹 검색 2건. 답은 검색 요약이었다.
    20:37  「고맙다 … 온텔릭 역시 내가 만들었지만 ㅋㅋㅋㅋ 대박인기능이다 …」
           → 계약: mutate_or_create(「만들었지만」). 게다가 앞 턴이 「테스트를 시작할까요?」로 끝나서
             **앞 턴 예고 → 에이전트** 갈래에 걸렸다. 같은 문서를 또 만들었다.
    20:39  같은 칭찬 + 「나는 문서를 만들어달라는게아니라 이 질문에 답변을 해달라는거였어」
           → 유튜브를 열고 검색어를 쳐 넣었다. 사람이 취소했다.

## 고친 것

- 계약: 이미 한 일(「만들었」「검토했」)과 남의 말(「검토해달라고 하게」「만들어달라는 게 아니라」)은 시킨 일이 아니다.
- 라우팅: 앞 턴이 제안으로 끝났어도 **칭찬·감사이고 요청으로 끝나지 않는 말**은 승낙이 아니다.

두 쪽 다 **좋은 표본으로도** 잰다 — 고치다가 진짜 요청을 놓치면 그게 더 큰 고장이다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.runtime import _is_social_remark
from alture_jarvis.task_contract import _operations

PRAISE = (
    "고맙다 아니 말이안되는게 이어가지는게 대박이네 온텔릭 역시 내가 만들었지만 ㅋㅋㅋㅋ "
    "대박인기능이다 클로드에서 사용량 한도로 이어가게 하는거"
)
PRAISE_THEN_CLARIFY = (
    PRAISE + "를 되게 한다니 이게 대박이네 나는 문서를 만들어달라는게아니라 이 질문에 답변을 해달라는거였어"
)
DOC_FOR_CLAUDE = "이거는 그 문서로 만들어줘 클로드가 나중에 제한 풀리면 보고 검토해달라고하게"


# ── 계약: 낱말이 아니라 모양 ─────────────────────────────────────────────────


def test_praise_that_mentions_making_something_is_not_a_request_to_make() -> None:
    assert "mutate_or_create" not in _operations(PRAISE), "「내가 만들었지만」을 만들어 달라는 말로 읽었다"


def test_a_clarification_that_negates_the_document_is_not_a_request_for_one() -> None:
    assert "mutate_or_create" not in _operations(PRAISE_THEN_CLARIFY)


def test_review_meant_for_someone_else_is_not_our_analysis() -> None:
    ops = _operations(DOC_FOR_CLAUDE)
    assert "mutate_or_create" in ops, "문서를 만들어 달라는 것은 그대로 시킨 일이다"
    assert "analyze" not in ops, "「클로드가 검토해달라고 하게」는 클로드의 일이다 — 온텔릭이 웹을 뒤질 이유가 없다"


@pytest.mark.parametrize(
    ("text", "operation"),
    [
        ("보고서 만들어줘", "mutate_or_create"),
        ("이거 분석해줘", "analyze"),
        ("작성한 다음 메일로 보내줘", "mutate_or_create"),
        ("엑셀로 정리해서 저장해줘", "mutate_or_create"),
        ("결과를 검증해 줘", "verify"),
        ("이 두 문서 비교하고 분석해서 표로 만들어", "analyze"),
    ],
)
def test_real_requests_are_still_requests(text: str, operation: str) -> None:
    """★ 좋은 표본. 과거·인용을 걸러내다가 진짜 요청을 놓치면 판이 통째로 헛돈다."""
    assert operation in _operations(text)


@pytest.mark.parametrize(
    "text",
    [
        "어제 보고서 만들었는데 괜찮았어",
        "그건 이미 분석했어",
        "지난번에 검증했잖아",
    ],
)
def test_things_already_done_are_not_asked_again(text: str) -> None:
    ops = set(_operations(text))
    assert not ({"mutate_or_create", "analyze", "verify"} & ops), ops


# ── 라우팅: 칭찬은 승낙이 아니다 ─────────────────────────────────────────────


@pytest.mark.parametrize("text", [PRAISE, PRAISE_THEN_CLARIFY, "대박이네 ㅋㅋㅋ", "고마워 진짜 최고다"])
def test_praise_does_not_accept_the_previous_offer(text: str) -> None:
    assert _is_social_remark(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "어엉 좀해줘",  # 2026-09-04 야놀자 — 이 갈래가 생긴 이유. 계속 승낙이어야 한다
        "어엉 해줘",
        "고마워 그럼 바로 진행해줘",
        "좋네 ㅋㅋ 테스트 시작",
        "대박 그대로 해 ㅋㅋ",
        "응",
    ],
)
def test_consent_is_still_consent_even_with_praise(text: str) -> None:
    """★ 좋은 표본. 칭찬이 섞여도 **요청으로 끝나면** 승낙이다."""
    assert _is_social_remark(text) is False


def test_the_promise_handoff_checks_for_praise_first() -> None:
    """앞 턴 예고 → 에이전트 갈래가 칭찬을 먼저 거르는지 — 순서가 곧 정책이다."""
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime._general_route)
    assert "self._last_turn_promised(session_id) and not _is_social_remark(prompt)" in source


# ── 같은 병, 섀도 DOM 시험에서 하나 더 (2026-09-18 밤) ─────────────────────────
#
# 「lit.dev 문서에서 Lit 컴포넌트를 만들 때 쓰는 데코레이터 3개의 이름과 …」 — 브라우저는 정답 페이지를 열어
# 8,503자를 읽었는데, 계약이 「로컬 · 만들기」로 읽어서 모델이 「읽을 로컬 파일을 지정해 달라」고 답했다.

LIT = "lit.dev 문서에서 Lit 컴포넌트를 만들 때 쓰는 데코레이터 3개의 이름과 각각 무슨 일을 하는지 알려줘"


def test_a_named_domain_makes_its_documents_web_documents() -> None:
    from alture_jarvis.plan import _scoped_count_targets
    from alture_jarvis.task_contract import _source_scope

    assert _source_scope(LIT) == "web"
    assert ("local", 3) not in _scoped_count_targets(" ".join(LIT.split())), "로컬 파일 3개를 읽으라는 요구가 생겼다"


def test_making_as_a_modifier_is_not_a_request_to_make() -> None:
    assert "mutate_or_create" not in _operations(LIT), "「만들 때 쓰는」은 만들어 달라는 말이 아니다"
    assert "mutate_or_create" not in _operations("파이썬으로 만들 수 있는 게임 알려줘")


@pytest.mark.parametrize(
    ("text", "scope"),
    [
        ("로컬 문서 3개를 읽고 요약해줘", "local"),
        ("내 문서 폴더에서 보고서 찾아줘", "local"),
        ("공개 웹 자료 3개와 로컬 문서 2개를 비교해줘", "mixed"),
        ("porsche.com/korea 에서 911 가격 알려줘", "web"),
    ],
)
def test_local_documents_are_still_local(text: str, scope: str) -> None:
    """★ 좋은 표본. 주소가 없으면 「문서」는 여전히 내 PC 의 문서다."""
    from alture_jarvis.task_contract import _source_scope

    assert _source_scope(text) == scope


# ── 칭찬에 도구 메뉴를 주면 작은 모델이 도구를 고른다 (2026-09-20 노트북 실측) ──────────────
#
# qwen3.5:4b · 「고마워 오늘 잘했어」 → 라우터 모델이 `use_scheduler` 를 골랐다(이벤트
# `agent_route_selected {"route":"scheduler","reason":"model_selected"}`). 에이전트가 도구 설명을 다 읽느라
# 프롬프트 19,390토큰 · 18.2초. 같은 말이 예전 판에서는 3초였다. 고를 수 없으면 틀리게 고르지도 않는다.


def _general_route_tools(tmp_path, prompt: str) -> list[str]:
    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="t", camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False,
        camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    )
    runtime = create_app(config, start_services=False).state.jarvis
    seen: list[list[str]] = []

    def fake_chat(prompt, **kwargs):
        seen.append([tool["function"]["name"] for tool in kwargs.get("tools") or []])
        return {"content": "별말씀을요."}

    runtime.ollama.chat_message = fake_chat
    runtime._general_route(prompt, "s1")
    return seen[0]


@pytest.mark.parametrize("text", ["고마워 오늘 잘했어", "잘했어 최고야", "대박이네 ㅋㅋㅋ", "오 신기하다 좋네"])
def test_a_short_praise_is_answered_without_a_tool_menu(tmp_path, text: str) -> None:
    assert _general_route_tools(tmp_path, text) == []


@pytest.mark.parametrize("text", ["오늘 일정 알려줘", "고마워 그럼 내일 일정도 알려줘"])
def test_real_requests_still_get_the_tool_menu(tmp_path, text: str) -> None:
    """★ 좋은 표본. 칭찬이 섞여도 요청으로 끝나면 도구가 있어야 한다."""
    assert "use_scheduler" in _general_route_tools(tmp_path, text)


# ── 소식·계획 공유도 일이 아니다 (2026-09-20 이 PC · Qwen 3.6) ────────────────────────────────
#
# 「…브라우저 벤치는 완성했어 … 창작은 없었어 아직 표본은 작지만 그래도 계속 해볼려고」 — 사장님이 결과를 **전한** 말이다.
# 규칙 `explicit_research_request` 가 「브라우저·테스트」 낱말을 보고 조사 에이전트로 보냈다 → 5턴 · 254초 · 생각 4만 자 끝에
# 「벤치 결과 URL 을 알려 주세요」 + 「근거 대상 읽기 0개」. 칭찬 거름망은 40자 이하만 봐서 이 긴 말은 빠졌다.
# 낱말이 아니라 **말 끝 모양**: 어디에도 요청형이 없고, 질문이 아니고, 보고·계획 어미로 끝나면 대화로 답한다.

REPORT = (
    "맞제 브라우저 밴치는 완성했어 충격인거는 브라우저 use랑 이제 우리 자체 브라우저 mcp를 이제 했는데 심지어 "
    "온텔릭 자체에서 테스트한게아니라 클로드 cli를 활용해서 했는데 이제 대박인거는 이제 그 우리 mcp는 이제 "
    "브라우저 usse는 이제 창작까지 이제 해버렸는데 (클로드가 이제 그 목록만 읽음) 이제 그 우리 브라우저 mcp는 "
    "조금 느렸지만 창작은 없었어 아직 표본은 작지만 그래도 계속 해볼려고"
)


@pytest.mark.parametrize("text", [
    REPORT,
    "어제 보고서 다 만들었어",
    "내일 부산 갈려고",
    "벤치 결과가 생각보다 좋게 나왔거든",
    "오늘 노트북 업데이트 버튼 눌러봤는데 잘 됐어",
])
def test_news_and_plans_are_sharing_not_requests(text: str) -> None:
    from alture_jarvis.runtime import _is_sharing_not_request

    assert _is_sharing_not_request(text) is True


@pytest.mark.parametrize("text", [
    "보고서 만들어줘",
    "다나와에서 무선 마우스 최저가 찾아줘",
    "브라우저 벤치 돌려봐",
    "이거 어떻게 생각해?",
    "오늘 일정 뭐야",
    "벤치 결과 정리했는데 표로 만들어 줘",
    "어제 보고서 만들었는데 한 번 봐",
    "밀양 가는데 제로페이 되는 곳 알려줘",
])
def test_real_requests_and_questions_are_not_sharing(text: str) -> None:
    """★ 좋은 표본 — 공유 어미가 섞여도 어디에 요청형이 있거나 질문이면 일이다."""
    from alture_jarvis.runtime import _is_sharing_not_request

    assert _is_sharing_not_request(text) is False


def test_sharing_is_answered_without_the_research_agent(tmp_path) -> None:
    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="t", camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False,
        camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    )
    runtime = create_app(config, start_services=False).state.jarvis
    seen: list[dict] = []

    def fake_chat(prompt, **kwargs):
        seen.append(kwargs)
        return {"content": "와, 창작이 없었다니 반가운 결과네요. 표본 늘려 가시면 더 확실해지겠어요."}

    runtime.ollama.chat_message = fake_chat
    route, answer, _ = runtime._general_route(REPORT, "s1")
    assert route == "answer" and "창작" in answer
    assert not (seen[0].get("tools") or []), "소식에 도구 메뉴를 주면 작은 모델이 일을 만든다"
