"""**안 보고 답하기**를 코드가 막는지 (2026-08-24).

## 무엇을 재는가

라이브 잡 639건(사람·완료)을 세어 보니, 조사·브라우저를 말한 156건 중 48건이
도구를 한 번도 안 썼다. 원인이 둘이었다:

    32건   낱말표 구멍 — 갈래가 아예 안 열렸다
    16건   갈래는 열렸는데 모델이 도구를 안 불렀다

이 파일은 둘 다 지킨다. 앞쪽은 `_requires_web_research` 의 판정을, 뒤쪽은
`must_observe` 되받기가 실제로 배선돼 있는지를 본다.

## 왜 시제를 안 보나

기존 되받기는 `PROMISED_ACTION`("~하겠습니다")에만 걸렸다. 그런데 실제로 나온
답은 정반대 시제였다:

    "제가 국내외 시장을 면밀히 조사해본 결과, 사용자님의 직관이 정확합니다…"
    (도구 0회 · 2,387자)

「한 척」을 잡는 그물에 「본 척」이 그대로 통과했다. 그래서 새 되받기는 답의
말투를 보지 않는다 — **이미 내린 갈래 판정**만 본다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.runtime import JarvisRuntime


# 라이브에서 실제로 놓쳤던 말들. 하나도 안 바꿨다.
MISSED_IN_LIVE = [
    "아니 브라우저로 조사해달라니까",
    "그러면 진짜 너의 추정이 맞는지 직접 브라우저에서 조사해줘",
    "자비스 혹시 오늘자 국내 이슈나 이런 것들 너가 조사해서 나한테 말해줄 수 있어?",
    "근데 진짜 너가한번 조사해서 알아봐줘 실제 벤치 성능이 어느정도 차이가나는지",
    "너가 직접 깃허브나 이런거 조사해서 말해주라",
    "부산 근교에 가성비 숙박업체 쪽 조사해서 나한테 얘기 좀 해주라",
    "이미 지금 로그인되어있어 너가 지금 보면돼 브라우저들어가서",
    "근데 이런 솔루션이 국내에있느지 너가 한번 조사해줘",
]


@pytest.mark.parametrize("prompt", MISSED_IN_LIVE)
def test_the_words_that_slipped_through_are_caught_now(prompt: str) -> None:
    """옛 규칙은 **대상 낱말 목록**을 요구해서 이것들을 다 흘려보냈다.

    「브라우저」조차 그 목록에 없었다 — 우리 도구 이름을 직접 부른 말이 조사로
    안 잡히고 있었다.
    """
    assert JarvisRuntime._requires_web_research(prompt), prompt


# 걸리면 안 되는 말. **이쪽이 무너지면 조용한 고장이다** — 잡담까지 브라우저로
# 끌고 가면 대화가 느려지고, 사람은 이유를 모른다.
LEAVE_ALONE = [
    "고마워 잘했어",
    "지금 몇 시야",
    "방금 그거 다시 말해줘",
    "1+1은?",
    # ★ 하지 말라고 분명히 말한 것. 규칙이 "애매하면 보낸다"이므로 이건 낱말로 막는다.
    "오늘 날짜와 요일, 지금 시각을 알려줘. 검색하지 말고 아는 대로만.",
    "검색하지 말고 네가 아는 선에서 설명해줘",
    "학원 강사 관리가 왜 어려운지 여덟 문단으로 아주 길게 설명해줘. 검색하지 말고 네 생각만 길게.",
    # 안쪽을 가리킨 것. 로컬 갈래의 일이다.
    "내 파일 좀 찾아봐",
    "어제 만든 파일 좀 찾아봐",
    "내 다운로드 폴더에서 계약서 찾아봐",
    "이 프로젝트 코드베이스 좀 찾아봐",
    "바탕화면에서 그 엑셀 찾아줘",
]


@pytest.mark.parametrize("prompt", LEAVE_ALONE)
def test_ordinary_talk_and_local_work_are_left_alone(prompt: str) -> None:
    assert not JarvisRuntime._requires_web_research(prompt), prompt


def test_refusal_beats_every_other_signal() -> None:
    """「조사하지 마」가 「조사」보다 세다. 순서가 곧 정책이다."""
    assert JarvisRuntime._requires_web_research("브라우저로 조사해줘")
    assert not JarvisRuntime._requires_web_research("브라우저로 조사하지 말고 그냥 답해")


def test_the_agent_can_be_told_it_must_look_first() -> None:
    """되받기가 **배선돼 있는지**. 인자가 없으면 위 판정은 아무 데도 안 닿는다.

    이 저장소가 여섯 번 겪은 모양이다 — 도구를(여기서는 판정을) 만들어 놓고
    부르는 자리가 없으면 아무 일도 안 일어난다.
    """
    assert "must_observe" in inspect.signature(BrowserAgent.run).parameters


def test_the_router_actually_passes_it() -> None:
    """라우터가 그 인자를 실제로 채워 보내는가. 기본값으로 두면 영원히 꺼져 있다."""
    # `_chat_job` 은 Code 잡을 코더 핀으로 감싸는 얇은 겉껍질이고, 실제 배선은
    # `_chat_job_inner` 에 있다. 겉껍질만 읽으면 이 검사가 통째로 헛돈다.
    source = inspect.getsource(JarvisRuntime._chat_job_inner)
    assert "must_observe=must_observe" in source, "agent.run 에 안 넘기고 있다"
    # 2026-09-30 부터 판정은 **이유 이름**으로 모은다(웹·출처·로컬 …) — 참/거짓은 그 집합에서 나온다.
    assert "must_observe = bool(observe_reasons)" in source, "판정을 안 하고 있다"
    assert "observe_reasons=frozenset(observe_reasons)" in source, "이유를 계획 층에 안 넘기고 있다"


def test_the_pushback_does_not_look_at_tense() -> None:
    """되받기 조건에 답의 말투가 끼어들면 「본 척」이 또 빠져나간다."""
    source = inspect.getsource(BrowserAgent.run)
    start = source.index("must_observe")
    block = source[start : start + 700]
    assert "PROMISED_ACTION" not in block, (
        "must_observe 되받기가 말투를 보고 있다 — 「해본 결과」는 예고형이 아니라서 빠져나간다"
    )


# ── 계획 층: 「세 군데」를 세는가 (2026-08-24) ────────────────────────────
#
# 라이브 실측에서 나온 판이다:
#
#     「여수 쪽 괜찮은 국밥집 조사해서 **세 군데만** 알려줘」
#        → 계획 {} · 1걸음 · browser_search 한 번으로 끝
#
# 도구 자신은 "안 읽은 결과 12건이 있다. browser_open_result 로 **들어가라**"라고
# 말하고 있었는데 한 페이지도 안 열었다. 개수 요구가 안 뽑혔으니 `_forced_read_call`
# 이 밀어 줄 것도 없었다 — 그 장치는 `count` 요구가 있을 때만 일한다.
#
# 원인은 `_COUNT` 가 `\d{1,2}` 만 봤기 때문이다. 사람은 「3군데」만큼이나
# 「세 군데」라고 말하는데, 숫자만 보는 눈금은 말하는 방식 절반을 못 봤다.


@pytest.mark.parametrize(
    "prompt,want",
    [
        ("여수 쪽 괜찮은 국밥집 조사해서 세 군데만 알려줘", 3),
        ("국밥집 두 군데 조사해서 알려줘", 2),
        ("맛집 다섯 개 찾아서 알려줘", 5),
        ("삼국지 인물 세 명만 조사해서 나열해줘", 3),
    ],
)
def test_korean_numerals_are_counted(prompt: str, want: int) -> None:
    from alture_jarvis.plan import extract

    labels = [
        item.label
        for item in extract(prompt)
        if item.kind == "count"
    ]
    assert labels, f"개수 요구를 못 뽑았다: {prompt}"
    assert f"{want}개" in labels[0], labels


@pytest.mark.parametrize(
    "prompt",
    [
        # ★ 실측으로 잡은 오탐들. 낱말 **속**의 글자가 수사로 읽혔다.
        "통신 서명·권한 검증 등 안전 설계를 조사해줘",
        "경계에서 명령이 떨리지 않게 하는 법 조사해줘",
        "인터넷 개발 관련해서 조사해줘",
        # 기간·단위는 개수가 아니다.
        "3개월 뒤에 뭐 하는지 조사해줘",
    ],
)
def test_words_that_merely_contain_a_numeral_are_not_counted(prompt: str) -> None:
    """901건 실측에서 「통신 **서명**」이 3으로, 「에**서 명**령」이 3으로 읽혔다.

    앞에 경계를 요구하고 '서·너·석·넉'을 빼서 막았다. 예측이 아니라 **재서** 잡은
    것이다 — 내가 걱정한 「열」은 901건에 한 번도 안 나왔고, 예상 못 한 「서」가
    두 번 걸렸다.
    """
    from alture_jarvis.plan import extract

    assert not [
        item
        for item in extract(prompt)
        if item.kind == "count"
    ], prompt


def test_research_without_a_named_source_still_counts() -> None:
    """출처도 안 대고 읽기 동사도 없는 조사 요청.

    「여수 국밥집 세 곳 알려줘」 — `has_named_source` 도 `_READ_INTENT` 도 안 걸린다.
    라우터가 이미 "가서 봐야 안다"고 정했으므로 그 판정을 계획 층에도 넘긴다.
    """
    from alture_jarvis.plan import extract

    assert not extract("여수 국밥집 세 곳 알려줘")
    assert extract("여수 국밥집 세 곳 알려줘", must_observe=True)


def test_reading_forever_without_writing_is_caught() -> None:
    """★ 20분 동안 읽기 50회 · 쓰기 0회 (2026-08-28, 10과제 벤치).

    실패한 5건 중 3건이 파일을 한 번도 안 고쳤다. 한 판은 같은 저장소를
    **여섯 번** 색인했고, 읽기 → 목록 → 읽기 → 목록 을 반복했다.

    기존 `coding_verification_missing` 은 모델이 **답을 내려 할 때**만 걸린다.
    이 판들은 답을 안 내고 계속 도구를 불러서 20분을 다 쓴 뒤에야 죽었다.
    """
    from alture_jarvis.agent import _LOOKS_WITHOUT_WRITE_LIMIT, looks_without_write

    # 실제로 있었던 순서 그대로 (939b3c31 판)
    real = ["local_index_codebase"] + [
        tool
        for _ in range(10)
        for tool in ("local_read_text_file", "local_list_directory")
    ]
    steps = [{"tool": tool, "ok": True} for tool in real]

    assert looks_without_write(steps) >= _LOOKS_WITHOUT_WRITE_LIMIT, (
        "20분 동안 보기만 한 판을 못 잡는다"
    )


def test_one_write_resets_the_count() -> None:
    """고치기 시작했으면 되받지 않는다 — 막는 게 아니라 밀어 주는 장치다."""
    from alture_jarvis.agent import _LOOKS_WITHOUT_WRITE_LIMIT, looks_without_write

    steps = [{"tool": "local_read_text_file", "ok": True} for _ in range(20)]
    steps.append({"tool": "local_apply_edit", "ok": True})
    steps += [{"tool": "local_read_text_file", "ok": True} for _ in range(3)]

    assert looks_without_write(steps) == 3
    assert looks_without_write(steps) < _LOOKS_WITHOUT_WRITE_LIMIT


def test_a_healthy_patch_run_is_never_pushed_back() -> None:
    """통과한 판(읽기 8 · 쓰기 1~2)은 건드리지 않아야 한다.

    막기만 하면 안 된다 — 이 저장소가 「끈기가 없던 게 아니라 눈을 가렸다」로
    한 번 겪은 실수다.
    """
    from alture_jarvis.agent import _LOOKS_WITHOUT_WRITE_LIMIT, looks_without_write

    # 실제로 통과한 판의 모양 (b455ed0b: 색인1 검색5 읽기13 쓰기1 검증5)
    healthy = (
        ["local_index_codebase"]
        + ["local_search_files"] * 5
        + ["local_read_text_file"] * 6
        + ["local_apply_edit"]
        + ["local_read_text_file"] * 7
        + ["local_run_project_command"]
    )
    steps = [{"tool": tool, "ok": True} for tool in healthy]

    assert looks_without_write(steps) < _LOOKS_WITHOUT_WRITE_LIMIT, (
        "정상적으로 고치고 있는 판을 되받으면 안 된다"
    )


def test_the_pushback_is_actually_wired_into_the_loop() -> None:
    """만들어 놓고 부르는 자리가 없으면 아무 일도 안 일어난다.

    이 저장소가 여섯 번 겪은 모양이라 배선까지 검사한다.
    """
    source = inspect.getsource(BrowserAgent.run)
    assert "looks_without_write(steps)" in source, "루프에서 안 부른다"
    assert "agent_looking_without_writing" in source, "무슨 일이 있었는지 안 남긴다"
    assert "look_pushbacks" in source, "되받기 횟수를 안 센다"


def test_second_look_pushback_allows_only_a_write_until_one_is_attempted() -> None:
    """말을 두 번 무시한 뒤에도 읽기 도구를 주면 20분 루프가 그대로 산다."""
    from alture_jarvis.agent import code_tools_after_look_pushback

    tools = frozenset(
        {
            "local_read_text_file",
            "local_search_files",
            "local_apply_edit",
            "local_write_file",
            "local_run_project_command",
        }
    )
    steps = [{"tool": "local_read_text_file", "ok": True} for _ in range(10)]

    assert code_tools_after_look_pushback(tools, steps, 1) == tools
    assert code_tools_after_look_pushback(tools, steps, 2) == frozenset(
        {"local_apply_edit", "local_write_file"}
    )

    # old_text_not_found 뒤에는 정확한 줄을 다시 읽어야 한다. 쓰기 **시도**가
    # 장부에 생기면 원래 도구를 돌려 준다.
    steps.append({"tool": "local_apply_edit", "ok": False})
    assert code_tools_after_look_pushback(tools, steps, 2) == tools


def test_write_only_fallback_is_wired_to_both_tool_call_paths() -> None:
    """Ollama 구조화 호출과 텍스트 호출 복구가 같은 제한을 써야 한다."""
    source = inspect.getsource(BrowserAgent.run)

    assert "code_tools_after_look_pushback(" in source
    # 2026-10-09: 모델에게 **보내는** 목록(shown)과 **받는** 손(active)이 갈렸다 — 읽기 관문은 목록을 그대로 두고
    # 디스패치에서 가른다(`offered_code_tools`). 받는 쪽 두 자리는 그대로 active 를 본다.
    assert "allowed_code_tools=shown_code_tools" in source
    assert "set(active_code_tools)" in source
    assert "name not in active_code_tools" in source
    assert "agent_code_write_tools_only" in source


def test_a_failed_write_does_not_reset_the_look_count() -> None:
    """시도와 성공이 같은 값이면 조용히 고장 난다.

    실측(2026-08-28, 3fbeed24 마지막 판): 26·29·31 걸음이 전부
    ``old_text_not_found`` 로 실패한 편집인데, `looks_without_write` 가 이름만
    보고 끊어서 그때마다 카운터가 0 으로 리셋됐다. 그래서 32 걸음 중 23 번을
    읽기만 하고도 진단이 한 번도 안 걸렸다.
    """
    from alture_jarvis.agent import _LOOKS_WITHOUT_WRITE_LIMIT, looks_without_write

    steps = [{"tool": "local_read_text_file", "ok": True} for _ in range(6)]
    steps.append({"tool": "local_apply_edit", "ok": False})  # old_text_not_found
    steps += [{"tool": "local_read_text_file", "ok": True} for _ in range(6)]

    assert looks_without_write(steps) == 12, "실패한 편집이 경계 노릇을 했다"
    assert looks_without_write(steps) >= _LOOKS_WITHOUT_WRITE_LIMIT

    # 성공한 편집은 그대로 경계다.
    ok_steps = list(steps)
    ok_steps[6] = {"tool": "local_apply_edit", "ok": True}
    assert looks_without_write(ok_steps) == 6


def test_the_gate_uses_attempts_so_a_failed_edit_cannot_deadlock() -> None:
    """관문이 진단값을 그대로 쓰면 실패한 편집 뒤에 손이 묶인다.

    쓰기전용 손만 남은 채로 ``old_text_not_found`` 가 나면 정확한 줄을 다시
    읽을 길이 없어진다. 그래서 진단은 성공만, 관문은 시도까지 센다.
    """
    from alture_jarvis.agent import (
        code_tools_after_look_pushback,
        looks_since_write_attempt,
        looks_without_write,
    )

    steps = [{"tool": "local_read_text_file", "ok": True} for _ in range(12)]
    steps.append({"tool": "local_apply_edit", "ok": False})

    # 진단은 실패한 쓰기를 경계로 안 친다.
    assert looks_without_write(steps) == 12
    # 관문은 친다 — 그래야 다시 읽을 수 있다.
    assert looks_since_write_attempt(steps) == 0

    tools = frozenset({"local_read_text_file", "local_apply_edit", "local_write_file"})
    assert code_tools_after_look_pushback(tools, steps, 2) == tools, "교착"



def test_voice_in_code_mode_carries_the_code_workspace() -> None:
    """말로 시킨 것도 화면과 **같은 모드**로 가야 한다.

    실측(2026-08-28, 사용자님 라이브): 같은 Code 탭에서
      · 타이핑한 판 3/3 완료
      · 말한 판   3/3 실패(전부 타임아웃)
    실패한 판들의 페이로드에는 `workspace_mode` 가 아예 없었다(`mode: None`).

    `_transcribe_command_job` 이 자식 잡을 만들 때 모드를 안 실어서, Code 탭에서
    말한 것이 cowork 로 돌았다. 그러면 `pin_role("code")` 도 코드 도구 프로필도
    안 걸린다 — 젬마(16.8GB)가 올라오려고 3090 에서 Qwen(16.5GB)을 쫓아내고,
    도구가 없어 「읽기만 함」으로 예산을 다 쓴다.
    """
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime._transcribe_command_job)
    assert "workspace_code_context()" in source, "화면 모드를 안 물어본다"
    assert source.count("**voice_extra") == 2, (
        "자식 잡 페이로드는 둘이다 — 조사 갈래와 일반 갈래 모두에 실려야 한다"
    )
    assert "resolve_allowed_path" in source, "검증 안 한 경로를 잡에 넣는다"

    presence = inspect.getsource(JarvisRuntime.note_workspace_presence)
    assert "workspace_mode" in presence, "presence 가 모드를 안 받는다"

    context = inspect.getsource(JarvisRuntime.workspace_code_context)
    assert "workspace_session()" in context, (
        "화면이 꺼졌는데 옛 모드를 기억하면 엉뚱한 저장소에 붙는다"
    )


def test_the_models_thinking_actually_leaves_the_backend() -> None:
    """사고 원문을 **받고 있으면서 버리고 있었다.**

    2026-08-29: `on_chunk` 가 `chunk["thinking"]` 을 받아 글자 수만 세고, 고정 문구
    하나만 내보냈다. 그래서 화면에는 "판단하고 있습니다" 가 몇 분씩 떠 있었고
    무슨 근거로 그 도구를 골랐는지 볼 수가 없었다.

    답과 달리 사고는 되받혀 지워지지 않는다 — 계획 대조가 건드리지 않기 때문이다.
    그래서 흘려도 「답이 나왔다 사라지는」 사고가 나지 않는다.
    """
    import inspect

    from alture_jarvis.agent import (
        _THINKING_EMIT_SEC,
        _THINKING_STREAM_CHARS,
        BrowserAgent,
    )

    source = inspect.getsource(BrowserAgent._model_message)
    assert "agent_thinking_text" in source, "원문이 화면으로 안 나간다"
    assert "flush_thinking()" in source, (
        "시간으로 묶어 보내므로 마지막 조각을 안 비우면 사고의 끝이 늘 잘린다"
    )
    # 조각마다 보내면 초당 수십 번이라 웹소켓이 막힌다. 총량도 잘라야 한다.
    assert 0 < _THINKING_EMIT_SEC <= 1.0
    assert 0 < _THINKING_STREAM_CHARS <= 100_000


def test_the_reasoning_is_written_for_the_person_reading_it() -> None:
    """사고 원문을 화면에 띄우기로 한 이상, 읽는 사람의 말로 쓰여야 한다.

    2026-08-29: 사고가 영어로 나왔다. 이유는 단순했다 — 계약(`_QWEN_CODE_PROMPT`)이
    전부 영어라 모델이 프롬프트 언어를 따라갔다.

    ★ 식별자는 번역하지 않는다. 도구 이름·경로·코드·오류 문자열이 번역되면 그 사고를
    근거로 뭘 확인할 수가 없다.
    """
    from alture_jarvis.agent import _QWEN_CODE_PROMPT

    # ★ 자리와 말이 둘 다 중요하다 (2026-08-30 실측).
    #
    # 처음에는 영어 한 줄을 계약 **맨 끝**(1,971자 중 1,764자째)에 붙였다.
    # 안 먹었다 — 영어 벽에 묻혔고, 영어로 쓰인 지시가 스스로 반례가 됐다.
    # 맨 앞으로 옮기고 한국어로 다시 썼다.
    # ★ 두 번 옮겼다. 계약 맨 끝(1,764자째, 영어) -> 계약 맨 앞(한국어) -> 그래도
    #   안 먹어서 **시스템 메시지 맨 앞**(`_VOICE_AND_MANNER`)으로. 계약 상수는
    #   `AGENT_SYSTEM_PROMPT`(12,109자) 뒤에 붙으므로 상수 안에서 앞이어도
    #   전체로 보면 12,000자째였다.
    from alture_jarvis.agent import _VOICE_AND_MANNER

    assert "생각도 한국어로 한다" in _VOICE_AND_MANNER
    # 식별자는 번역하지 않는다 — 번역되면 화면에서 그 이름을 찾을 수 없다.
    assert "원문 그대로" in _VOICE_AND_MANNER
    assert "local_apply_edit" in _VOICE_AND_MANNER, "본보기가 있어야 흉내낸다"


def test_a_failed_job_still_says_how_far_it_got() -> None:
    """실패한 판이 증거를 남겨야 한다.

    2026-08-29: 관찰 초소 6건이 600초에 죽었는데 `result` 가 통째로 `None` 이라
    걸음을 볼 수가 없었다. 그리고 나는 **없는 것을 「0걸음」으로 읽어** 엉뚱한
    가설을 넷 세웠다 — 벤치에서 이미 한 번 고친 `steps=0` 거짓말과 같은 자리다.

    원인은 둘이었다:
      1. 걸음 장부(`observations`)가 순수 메모리라 재기동에 사라진다.
      2. 실패 경로의 `set_status(FAILED, result=None)` 이 result_json 을 NULL 로 덮었다.
    """
    import inspect

    from alture_jarvis.jobs import JobStore
    from alture_jarvis.runtime import JarvisRuntime

    # 1) 죽기 전에 장부를 디스크로 옮긴다.
    guard = inspect.getsource(JarvisRuntime._guard_job)
    assert "_attach_failure_trace" in guard

    attach = inspect.getsource(JarvisRuntime._attach_failure_trace)
    assert "observations.list_steps" in attach
    assert '"agent_trace"' in attach, "완료한 판과 같은 자리에 넣어야 같은 방법으로 읽는다"

    # 2) 뒤이은 FAILED 갱신이 그걸 지우면 안 된다.
    set_status = inspect.getsource(JobStore.set_status)
    assert "COALESCE(?, result_json)" in set_status, "result=None 이 결과를 지운다"
    assert hasattr(JobStore, "attach_result")


def test_the_manner_block_is_actually_first() -> None:
    """맨 앞에 있는 것만 확실히 읽힌다.

    2026-08-30: 사고 언어 지시를 `_QWEN_CODE_PROMPT` 안 맨 앞에 뒀는데 안 먹었다.
    그 상수는 `AGENT_SYSTEM_PROMPT`(12,109자) **뒤에** 이어붙으므로 전체로 보면
    12,000자째였다. 자리가 셋이다 — 상수 안의 위치 · 상수들의 순서 · 조립부.
    셋째가 제일 안 보인다(사고 Q 와 같은 모양).
    """
    import inspect

    from alture_jarvis.agent import (
        AGENT_SYSTEM_PROMPT,
        BrowserAgent,
        _VOICE_AND_MANNER,
    )

    assembled = _VOICE_AND_MANNER + AGENT_SYSTEM_PROMPT
    assert assembled.index("말투와-사고") < 50, "묻히면 안 먹는다"
    assert assembled.index("생각도 한국어로") < 400

    # 조립부가 실제로 맨 앞에 붙이는가 — 상수만 고치고 배선을 안 하면 아무 일도 없다.
    #
    # 2026-08-31: 조립이 `+` 이어붙이기에서 **목록**(`fit_system`)으로 바뀌었다.
    # 확인할 것은 그대로다 — 말투가 첫 칸이고, 계약보다 앞이다.
    source = inspect.getsource(BrowserAgent.run)
    # 2026-10-02 영어판: 말투는 `_voice_and_manner()` 로 고른다(한국어 화면이면 `_VOICE_AND_MANNER` 그대로).
    assert "manner = _voice_and_manner(prompt)" in source
    voice_at = source.index('("voice", manner')
    # 2026-10-05: 계약 칸은 영어로 시킨 판에서 답 언어 줄을 바꿔 넣으므로 여러 줄이 됐다 — 칸 이름으로 찾는다.
    contract_at = source.index('("contract",')
    assert "AGENT_SYSTEM_PROMPT" in source[contract_at:contract_at + 200]
    assert voice_at < contract_at, "말투가 계약 뒤로 밀렸다"
    # 그리고 **버릴 수 없는 칸**이어야 한다. 버려지면 또 쏘아붙인다.
    assert '("voice", manner, False)' in source


def test_jarvis_is_told_how_to_speak_to_the_person() -> None:
    """두 프롬프트 합쳐 14,091자에 말투에 관한 말이 **한 글자도 없었다.**

    그래서 사용자님이 같은 문장을 두 번 보내셨을 때 "네 번째라 이번엔 같은 말 안
    하겠습니다" 라고 쏘아붙였다. 모델의 인성 문제가 아니라 우리가 아무 말도 안
    해 준 것이다.
    """
    from alture_jarvis.agent import _VOICE_AND_MANNER as V

    assert "무례하지 않다" in V
    assert "훈계하지 않는다" in V
    assert "같은 말이 반복돼도 지적하지 않는다" in V, (
        "반복을 지적하는 것이 실제로 났던 사고다"
    )
    assert "모르면 모른다고 한다" in V


def test_the_code_contract_actually_reaches_the_model() -> None:
    """만들어 놓은 계약이 **잘려서 한 번도 도착하지 않았다.**

    2026-08-30: `transcript.bounded(system_max=7_000)` 이 시스템 메시지를 7,000자로
    잘랐는데 조립된 것이 14,305자였다. 뒤쪽 51%가 조용히 사라졌고 그 안에
    RECON→PLAN→PATCH→VERIFY 상태기계와 `skill_note` 가 통째로 들어 있었다.

    벤치에서 "32걸음·편집 5회·검증 0회" 로 죽던 판이 VERIFY 규칙 없이 돈 판이다.
    상한이 셋인데(전사 예산 180,000 · num_ctx 102,400 · **system_max**) 제일 낮은
    셋째가 함수 기본값으로 숨어 있었다 — 사고 Q 와 같은 모양.
    """
    from alture_jarvis.agent import (
        AGENT_SYSTEM_PROMPT,
        _QWEN_CODE_PROMPT,
        _TOOL_RESULT_MAX_CHARS,
        _VOICE_AND_MANNER,
    )
    from alture_jarvis.transcript import bounded

    assembled = _VOICE_AND_MANNER + AGENT_SYSTEM_PROMPT + _QWEN_CODE_PROMPT
    kept = bounded(
        [{"role": "system", "content": assembled}, {"role": "user", "content": "x"}],
        max_chars=180_000,
        tool_result_max=_TOOL_RESULT_MAX_CHARS,
    )[0]["content"]

    assert len(kept) == len(assembled), f"{len(assembled)-len(kept)}자가 잘렸다"
    for needle in ("무례하지 않다", "생각도 한국어로", "RECON", "VERIFY", "</qwen-code-contract>"):
        assert needle in kept, f"{needle!r} 이 모델에 안 간다"


def test_thinking_is_translated_for_the_screen_not_forced_on_the_model() -> None:
    """모델은 영어로 생각하게 두고 **화면에만** 한국어를 그린다.

    2026-08-30 분포 측정: 시스템 맨 앞 한국어 지시로 5회 돌려 한글 비율이
    0%·1%·2%·4% (평균 2%) 였다. 사고 첫 줄이 ``We need answer in Korean.`` 이었다 —
    지시가 안 닿은 게 아니라 닿아도 사고 채널이 영어로 굳어 있다.

    유일하게 움직인 prefill(47%)은 매 걸음 가짜 assistant 턴을 끼워야 해서
    도구 흐름이 더러워지고 접두사 캐시가 매 걸음 깨진다. 절반짜리 한글을 얻자고
    치를 값이 아니다.
    """
    import inspect

    from alture_jarvis.agent import BrowserAgent
    from alture_jarvis.thinking_ko import BUDGET_CHARS, SEGMENT_CHARS, ThinkingTranslator

    # 원문을 먼저 내보내고 번역이 뒤따른다 — 번역이 늦어도 화면이 안 멈춘다.
    source = inspect.getsource(BrowserAgent._model_message)
    assert "thinking_ko.feed(job_id, delta)" in source
    assert source.index('"agent_thinking_text"') < source.index("thinking_ko.feed")
    assert "thinking_ko.finish(job_id)" in source, "마지막 덩이가 안 나간다"

    # 3060 정찰기에게 시킨다 — 3090 의 주 모델을 건드리면 서로 축출한다.
    ask = inspect.getsource(ThinkingTranslator._ask)
    assert "code_scout_base_url" in ask and "code_scout_model" in ask
    assert '"think": False' in ask, "thinking 모델이면 예산이 추론에 다 쓰여 빈 답이 온다"

    # 실패는 조용히 접는다. 사고 번역 때문에 일이 늦어지면 그게 고장이다.
    translate = inspect.getsource(ThinkingTranslator._translate)
    assert "except Exception" in translate and "return" in translate

    assert 0 < SEGMENT_CHARS <= 2_000
    assert 0 < BUDGET_CHARS <= 40_000


def test_the_model_is_handed_line_ranges_instead_of_whole_files() -> None:
    """찾은 줄 범위가 **그대로 다음 호출**로 손에 쥐여져야 한다.

    2026-08-31. 조각은 다 있는데 이어져 있지 않았다:

    - `local_index_codebase` 는 이미 ``chunks[].lines = [407, 530]`` 을 준다
    - `local_read_text_file` 은 ``line_start``/``line_end`` 를 받는다
    - 기본 스키마는 "outline 의 범위를 그대로 넣으면 된다"라고까지 적어 뒀다

    그런데 **코드 모드가 그 안내를 통째로 버렸다** — `qwen_code_tools` 가 도구 설명을
    갈아끼우고 인자 설명을 전부 지워, 모델이 보는 건 이름 네 개뿐이었다. 그래서 파일을
    통째로 읽었고(기본 15,000자), 어젯밤 프롬프트가 67,744토큰이 됐다.

    안내문은 안 먹는다. 그래서 **답을 쥐여 준다**(`next_reads`).
    """
    from alture_jarvis.code_runtime import (
        _KEEP_PARAM_DESCRIPTIONS,
        CODE_CORE_TOOL_NAMES,
        qwen_code_tools,
    )
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.local_computer import LocalComputerTools, _looks_like_symbol

    tools = LocalComputerTools(JarvisConfig.from_env())._build_definitions()
    compact = qwen_code_tools(tools, set(CODE_CORE_TOOL_NAMES))
    read = next(
        t["function"] for t in compact if t["function"]["name"] == "local_read_text_file"
    )
    # 도구 설명이 줄 범위를 가리켜야 한다.
    assert "line_start" in read["description"]
    # 그리고 그 인자의 설명은 **안 지워져야** 한다.
    properties = read["parameters"]["properties"]
    assert properties["line_start"].get("description"), "인자 설명이 또 지워졌다"
    assert {"line_start", "line_end"} <= set(_KEEP_PARAM_DESCRIPTIONS)

    # 심볼처럼 생긴 것과 파일 이름을 가른다 — 틀린 안내는 없는 것보다 나쁘다.
    assert _looks_like_symbol("chat_messages_stream")
    assert not _looks_like_symbol("report.md")
    assert not _looks_like_symbol("2026")


def test_tool_calls_record_their_shape_so_we_can_count_them() -> None:
    """도구를 어떻게 불렀는지 셀 수 있어야 한다 — 값이 아니라 모양으로.

    어젯밤 `local_read_text_file` 이 47번 불렸는데 **몇 번이 줄 범위를 지목했는지 셀 수가
    없었다.** 장부에 `tool`/`ok`/`status` 만 있었다. 가설은 있는데 분모가 없었다.
    """
    from alture_jarvis.tool_gateway import audit_shape

    ranged = audit_shape(
        "local_read_text_file",
        {"path": r"E:\ollama.py", "line_start": 407, "line_end": 530},
        {"content": "x" * 1234},
    )
    assert ranged["line_start"] == 407 and ranged["line_end"] == 530
    assert ranged["file"] == "ollama.py", "경로 전체가 아니라 이름만 남긴다"
    assert ranged["out_chars"] == 1234

    whole = audit_shape("local_read_text_file", {"path": "/x/agent.py"}, {"content": "y" * 9})
    assert "line_start" not in whole, "통째로 읽은 판이 구별돼야 한다"

    # 본문은 절대 안 담는다.
    assert "content" not in ranged and "content" not in whole


def test_switching_models_makes_room_first() -> None:
    """모드를 바꿀 때 **먼저 자리를 비운다** — Ollama 는 스스로 축출하지 않는다.

    2026-08-31 실측. 코드 모드에서 코워크로 넘어가면 타임아웃이 났다. 같은 요청·같은
    인자로 두 번 쟀다:

        스스로 교체하게 두면   420초 무응답 (헤더조차 안 옴)
        먼저 내리고 부르면      24.4초 정상

    ``OLLAMA_MAX_LOADED_MODELS=1`` 인데도 그랬고, 그동안 남아 있던 모델로 오는 프로브는
    607ms 에 처리됐다 — 서버가 죽은 것도 바쁜 것도 아니다. ``OLLAMA_LOAD_TIMEOUT`` 이
    5분인데 그 에러조차 안 왔으니 **적재를 시작조차 안 한 것이다.**

    원인은 Ollama 안이라 우리가 못 고친다. 자리는 우리가 비울 수 있고, 0.2초면 된다.
    """
    import inspect

    from alture_jarvis.ollama import OllamaClient

    # ★ 2026-09-20: 검사 하네스가 이 메서드를 가짜로 덮는다(진짜 GPU 에서 모델을 내리면 안 된다).
    #   속성에서 읽으면 가짜의 소스를 보게 되므로 **파일에서** 읽는다.
    import alture_jarvis.ollama as _ollama_module

    room = Path(inspect.getfile(_ollama_module)).read_text(encoding="utf-8")
    room = room[room.index("def _make_room_for"):]
    room = room[: room.index("\n    def ", 10)]
    assert '"keep_alive": 0' in room, "내리라고 말하지 않으면 안 내려간다"
    assert "_same_model" in room, "원하는 모델이 이미 올라와 있으면 건드리면 안 된다"
    assert "except Exception" in room, "자리를 못 비웠다고 판을 죽이면 안 된다"

    # 실제로 모델을 부르는 모든 경로가 자리를 비워야 한다 — 하나만 빠져도 그 경로에서
    # 그대로 재발한다(도구를 만들어도 갈래가 없으면 안 쓰인다는 그 교훈과 같은 자리).
    for name in ("chat_message", "chat_messages", "chat_messages_stream"):
        source = inspect.getsource(getattr(OllamaClient, name))
        assert "self._make_room_for(selected)" in source, f"{name} 이 자리를 안 비운다"
        assert "httpx.Timeout(" in source, f"{name} 이 읽기 자를 판 예산과 안 가른다"


def test_the_system_message_is_trimmed_by_section_not_by_slicing() -> None:
    """시스템 메시지는 **반쪽으로 잘리지 않는다.** 못 버리는 것은 통째로 남는다.

    2026-08-31, 하루에 두 번 당하고 나서 만든 가드다:

        상한 7,000    RECON→PLAN→PATCH→VERIFY 가 통째로 사라짐 (계약이 안 도착)
        상한 16,000   저장소 지도가 잘리고 **맨 끝 시각 줄까지** 날아감

    둘 다 에러가 아니라 침묵으로 나타나 「모델이 계약을 안 지킨다」로 오해했다.
    상한을 올리는 것은 두더지잡기다 — 프롬프트가 자라면 또 걸린다. 그래서 이
    저장소가 이미 아는 규율을 여기에도 쓴다: **자를 땐 글자 말고 목록을.**
    """
    from alture_jarvis.transcript import fit_system

    sections = [
        ("voice", "A" * 400, False),
        ("contract", "B" * 12_000, False),
        ("thinking_card", "C" * 2_500, True),
        ("repo_card", "D" * 3_000, True),
        ("now", "E" * 40, False),
    ]
    # 넉넉하면 아무것도 안 버린다.
    whole, dropped = fit_system(sections, budget=26_000)
    assert not dropped and "C" * 2_500 in whole and "D" * 3_000 in whole

    # 모자라면 **버려도 되는 것만 통째로** 빠지고, 계약과 시각은 온전하다.
    tight, dropped = fit_system(sections, budget=14_000)
    assert "B" * 12_000 in tight, "계약이 반쪽으로 잘렸다"
    assert "E" * 40 in tight, "맨 끝 시각 줄이 또 날아갔다"
    assert set(dropped) == {"thinking_card", "repo_card"}
    assert "자리가 모자라 뺀 것" in tight, "무엇이 빠졌는지 모델이 알아야 한다"

    # 조립하는 쪽이 이 함수를 실제로 쓰는가 — 안 쓰면 위 성질이 아무 의미가 없다.
    import inspect

    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent.run)
    # 2026-10-07 부터는 `fit_system_split` — 고르기는 같고(`_fit_sections`), 판마다 바뀌는 칸만 요청 메시지 쪽으로 따로 준다.
    assert "fit_system_split(" in source, "조립부가 아직 + 로 잇고 뭉텅 자른다"
    assert "agent_system_sections_dropped" in source, "빠진 사실이 조용하다"


def test_the_real_system_message_actually_fits() -> None:
    """**상수만 세지 말고 실제 조립을 재라.** 두 번 다 그래서 틀렸다.

    처음엔 프롬프트 상수 셋(14,305자)만 세고 상한을 16,000 으로 정했는데, 실제 조립엔
    저장소 지도·자사데이터 절이 더 붙어 17,617자였다 — 정한 그날부터 잘리고 있었다.
    """
    from alture_jarvis.agent import (
        AGENT_SYSTEM_PROMPT,
        _QWEN_CODE_PROMPT,
        _SYSTEM_BUDGET_CHARS,
        _VOICE_AND_MANNER,
    )
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.skills import SkillLibrary
    from alture_jarvis.transcript import bounded

    card = SkillLibrary(JarvisConfig.from_env()).thinking_card()
    fixed = len(_VOICE_AND_MANNER) + len(AGENT_SYSTEM_PROMPT) + len(_QWEN_CODE_PROMPT)
    # 못 버리는 부분만으로 예산을 넘으면 `fit_system` 도 못 구한다.
    assert fixed < _SYSTEM_BUDGET_CHARS * 0.8, "계약만으로 예산의 80%를 넘었다"
    # 사고 카드는 상시로 실리는 것이라 여기 포함해서 잰다.
    assert fixed + len(card) < _SYSTEM_BUDGET_CHARS

    # 마지막 안전망(뭉텅 자르기)은 우리 예산보다 **커야** 한다 — 작으면 그쪽이 먼저 자른다.
    backstop = inspect_default(bounded, "system_max")
    assert backstop >= _SYSTEM_BUDGET_CHARS, "안전망이 예산보다 낮아 그쪽이 먼저 자른다"


def inspect_default(function: object, name: str) -> int:
    import inspect

    return int(inspect.signature(function).parameters[name].default)


def test_git_can_leave_a_commit_but_only_on_a_branch() -> None:
    """고칠 수는 있어도 **남길 수가 없었다.** 열되, 되돌리기가 쉬운 만큼만.

    2026-09-01 사용자님 승인으로 git 쓰기를 열었다. 기준은 하나다 —
    **되돌리기가 「브랜치 하나 삭제」로 끝나는 범위까지만.**

    그래서 두 겹으로 막는다:
      1. 인자 검사 — force · amend · 브랜치 삭제 · 맨 checkout 은 거부
      2. 실행 직전 — 보호 가지(main 등) 위면 commit 거부

    2번이 이 문을 열 수 있게 만든 근거다. 없으면 main 에 직접 커밋이 가능해지고,
    그러면 되돌리기가 브랜치 삭제보다 어려워진다.
    """
    import inspect

    import pytest

    from alture_jarvis.local_computer import (
        _GIT_PROTECTED_BRANCHES,
        _GIT_WRITE_COMMANDS,
        LocalComputerTools,
        _check_git_write_args,
    )

    # 열린 것
    for allowed in (["add", "."], ["commit", "-m", "x"], ["switch", "-c", "feat/x"], ["branch", "feat/y"]):
        _check_git_write_args(allowed)

    # 막힌 것 — 하나라도 열리면 되돌리기가 어려워진다
    for blocked in (
        ["commit"],                      # 메시지 없으면 편집기가 열려 멈춘다
        ["commit", "-m", "x", "--amend"],  # 이미 남긴 것을 고쳐 쓴다
        ["checkout", "."],               # 작업 중인 변경을 덮어쓴다
        ["switch", "main"],              # 딴 가지로 옮긴다
        ["branch", "-D", "x"],           # 남의 가지를 지운다
        ["add", "--force", "x"],
    ):
        with pytest.raises(PermissionError):
            _check_git_write_args(blocked)

    # 위험한 것들은 이름부터 목록에 없어야 한다.
    assert not (_GIT_WRITE_COMMANDS & {"push", "reset", "clean", "rebase", "merge", "cherry-pick"})
    assert {"main", "master"} <= _GIT_PROTECTED_BRANCHES

    # 실행 직전 확인이 배선돼 있는가 — 인자 검사만으로는 **어디에** 커밋하는지 모른다.
    source = inspect.getsource(LocalComputerTools.run_project_command)
    assert "_GIT_PROTECTED_BRANCHES" in source, "보호 가지 확인이 실행 경로에 없다"
    assert "_current_branch" in source

    # 가지를 못 알아내면 **막히는 쪽**으로 떨어져야 한다.
    from pathlib import Path

    assert LocalComputerTools._current_branch(Path("C:/Windows")) in _GIT_PROTECTED_BRANCHES


def test_autonomy_budgets_fit_the_observed_successes() -> None:
    """상한이 **성공 분포 한가운데** 있으면 그건 상한이 아니라 방해다.

    통과한 판의 걸음 수 실측(2026-08-28·08-31): 19 · 24 · 26 · 32 · 34 · 44.
    상한이 30이었다 — 44걸음짜리가 통과했는데 30에서 끊고 있었다.

    그리고 전체 회귀 한 번이 277초로 900초 리스의 31% 다. "고치고 → 돌려보고"가
    두 번이면 테스트만으로 예산이 끝난다.
    """
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig.from_env()
    assert config.agent_autonomous_max_steps >= 44, "관측된 성공(44걸음)을 못 담는다"
    assert config.agent_autonomous_lease_sec >= 1200, "회귀 한 번(277초)을 두 번 못 돌린다"
    # dataclass 기본값과 로더가 갈리면 로더가 이긴다 — 한쪽만 고치면 아무 일도 없다.
    assert JarvisConfig().agent_autonomous_max_steps == config.agent_autonomous_max_steps
    assert JarvisConfig().agent_autonomous_lease_sec == config.agent_autonomous_lease_sec


def test_the_agent_can_grep_instead_of_skimming() -> None:
    """내용을 **정규식으로 찾을** 수 있어야 한다 — 없으면 읽기로 때운다.

    2026-09-01. 도구 124개 중 로컬 코드 작업이 9개였고, 그중 내용 검색이 없었다:

        local_search_files    파일 **이름**만 본다 (find, grep 아님)
        local_index_codebase  심볼 단위 색인

    그래서 「이 값이 어디서 정해지나」를 알려면 파일을 열어 눈으로 훑는 수밖에
    없었고, 벤치 실패 판의 공통 모양이 **읽기 8~11회 · 쓰기 0회**였다.
    """
    from alture_jarvis.code_runtime import CODE_CORE_TOOL_NAMES, qwen_code_tools
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.local_computer import LocalComputerTools

    project_root = Path(__file__).resolve().parents[1]
    tools = LocalComputerTools(
        JarvisConfig(local_file_allowed_roots=str(project_root))
    )
    for name in ("local_grep", "local_glob"):
        assert name in tools.names, f"{name} 스키마에 없다"
        assert hasattr(tools, {'local_grep': 'grep_files', 'local_glob': 'glob_files'}[name])
        assert name in CODE_CORE_TOOL_NAMES, f"{name} 이 코드 모드에 안 보인다"

    # 모델이 보는 스키마에도 있어야 한다 — 만들어도 목록에 없으면 안 쓰인다.
    compact = qwen_code_tools(tools._build_definitions(), set(CODE_CORE_TOOL_NAMES))
    names = {t["function"]["name"] for t in compact}
    assert {"local_grep", "local_glob"} <= names

    # 실제로 찾는가.
    root = str(project_root / "src")
    hit = tools.grep_files(
        {"pattern": r"_GIT_PROTECTED_BRANCHES", "path": root, "extension": ".py"}
    )
    assert hit["count"] >= 1 and hit["items"][0]["line"] > 0

    # 0건은 「없다」와 「덜 봤다」를 구별해서 말한다.
    empty = tools.grep_files({"pattern": "zzz_no_such_token_zzz", "path": root, "extension": ".py"})
    assert empty["count"] == 0 and empty.get("hint")

    # 틀린 정규식은 「못 찾음」이 아니라 「틀렸다」로 온다.
    with pytest.raises(ValueError):
        tools.grep_files({"pattern": "([unclosed", "path": root})


def test_python_dash_c_is_allowed_but_scripts_are_not() -> None:
    """`python -c` 는 열고 `python foo.py` 는 안 연다.

    위험도가 새로 늘지 않는다 — `pytest` 가 **이미 임의 코드를 실행한다.** 테스트
    파일 하나 쓰고 돌리면 되는 일을 한 줄로 못 하게 막고 있었을 뿐이다. 파일 지정
    실행은 작업 폴더 밖 스크립트를 부를 통로가 되므로 그대로 둔다.
    """
    from alture_jarvis.local_computer import LocalComputerTools

    LocalComputerTools._validated_project_command(["python", "-c", "import json;print(1)"])
    LocalComputerTools._validated_project_command(["python", "-m", "pytest", "-q"])
    for blocked in (["python", "foo.py"], ["python", "-m", "os"], ["python", "-c"]):
        with pytest.raises(PermissionError):
            LocalComputerTools._validated_project_command(blocked)
    # 셸 메타문자는 여전히 막힌다 — 파이프로 딴 프로그램을 부르는 통로다.
    with pytest.raises(ValueError):
        LocalComputerTools._validated_project_command(["python", "-c", "print(1) | more"])


def test_a_list_answer_carries_the_addresses() -> None:
    """목록으로 답하면 **주소를 같이 남긴다** — 다음 턴이 신원으로 집게.

    2026-09-01 라이브 사고. 「공고 찾아줘」에 순위표로 답한 다음 턴에 「저 순위대로
    스크랩해줘」가 왔는데, 자비스는 **사람인을 새로 검색해서 새 rank 1~5 를 스크랩**했다.
    앞 답의 그 회사들이 아니었다.

    셋 다 정상이었다 — 대화 이력도 들어갔고(`context_messages` 6개), 레시피도
    `job_id`(rec_idx)를 받고, `forget_results` 가 판 경계에서 순위를 버리는 것도 옳다
    (순위는 그 검색의 것이라, 안 버리면 딴 사이트 순위로 남의 페이지를 연다).

    끊긴 곳은 **앞 답에 주소가 없었다**는 것 하나였다. 순위는 판을 못 넘지만
    주소는 넘는다. 안내문으로는 안 적으므로(사고 R) 코드가 붙인다.
    """
    from alture_jarvis.agent import with_addresses

    steps = [
        {
            "tool": "site_run",
            "result": {
                "results": [
                    {"rank": 1, "title": "연구비 관리", "url": "https://www.saramin.co.kr/a?rec_idx=1"},
                    {"rank": 2, "title": "임상관리팀", "url": "https://www.saramin.co.kr/b?rec_idx=2"},
                ]
            },
        }
    ]
    listed = with_addresses("순위표입니다.\n1. 연구비 관리\n2. 임상관리팀", steps)
    assert "rec_idx=1" in listed and "rec_idx=2" in listed, "주소가 안 붙었다"

    # 목록이 아니면 건드리지 않는다 — 모든 답 뒤에 링크가 붙으면 그게 소음이다.
    assert with_addresses("그냥 한 문장 답", steps) == "그냥 한 문장 답"
    # 이미 주소를 쓴 답도 그대로 둔다.
    assert with_addresses("1. http://x 있음", steps) == "1. http://x 있음"
    # 결과가 하나뿐이면 목록이 아니다.
    assert with_addresses("1. 하나", [{"result": {"results": steps[0]["result"]["results"][:1]}}]) == "1. 하나"

    # 배선 — 최종 답에 실제로 걸려 있는가.
    import inspect

    from alture_jarvis.agent import BrowserAgent

    assert "with_addresses(answer, steps)" in inspect.getsource(BrowserAgent.run)


def test_a_made_document_can_actually_be_found() -> None:
    """**만든 것을 사람이 못 찾으면 안 만든 것과 같다.**

    2026-09-01 라이브. HWPX 를 11,410바이트로 제대로 만들어 놓고 답에는 파일명만
    적었다. 실제 파일은 잡별 UUID 폴더 안이었다:

        outputs/workspace/764b7920-2d0f-4ab2-afdf-a77fd7793d8c/나래_이력서.hwpx

    사용자님은 「아무 문서가 없는데 링크를 주는 것도 아니고」라고 하셨고, 맞는 말이다.
    잡별 폴더는 중간 산출물의 자리지 **결과물의 자리가 아니다.**
    """
    import inspect

    from alture_jarvis.local_computer import LocalComputerTools
    from alture_jarvis.runtime import JarvisRuntime

    # 상대 경로는 「내 문서\JARVIS」로 간다 — 탐색기에서 바로 보이는 곳.
    # (2026-09-30: 경로 풀기를 `_document_arguments` 하나로 모았다 — 쓰기·위험도·승인 카드가 같은 자리를 본다.)
    source = inspect.getsource(LocalComputerTools.write_document_file)
    assert "_document_arguments" in source, "쓰기가 공용 경로 풀기를 안 쓴다"
    assert "documents_root" in inspect.getsource(LocalComputerTools._document_arguments), "결과물이 아직 UUID 폴더로 간다"

    # 그리고 그 폴더는 승인 없이 쓸 수 있어야 한다 — 문서 한 장에 사람을 부르면 안 된다.
    risk = inspect.getsource(LocalComputerTools._mutation_risk)
    assert "_inside_documents_root" in risk

    # 만든 내용을 **바로 볼 수 있어야** 한다 — hwpx·xlsx 는 브라우저에서 못 그린다.
    # 파일만 던지고 "만들었습니다"는 주장일 뿐이다.
    from alture_jarvis.documents import write_document

    import tempfile

    made = write_document(
        Path(tempfile.mkdtemp()) / "x.hwpx",
        "hwpx",
        {"blocks": [{"type": "heading", "text": "검토"}, {"type": "table", "rows": [["a", "b"]]}]},
    )
    assert made["preview"].startswith("# 검토"), "미리보기가 안 나온다"
    assert "a | b" in made["preview"]

    # 화면에서 열 수 있어야 한다 — 결과물 폴더가 `viewable` 판정에 들어가야 한다.
    #
    # ★ 예전엔 `_inside_outputs` 의 **소스에** "Documents" 가 있는지 봤다. 그런데
    #   자리 이름이 `config.documents_dir` 한 곳으로 모이면서 그 글자가 사라졌다 —
    #   소스를 보는 검사는 옳은 리팩터링에도 터진다. **하는 일**을 본다.
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.local_computer import LocalComputerTools

    room = Path(tempfile.mkdtemp())
    config = JarvisConfig(
        runtime_root=room,
        data_dir=room / "data",
        output_dir=room / "outputs",
        documents_dir=room / "documents",
        local_computer_enabled=True,
    )
    made_here = LocalComputerTools(config).documents_root / "결과물.docx"
    made_here.parent.mkdir(parents=True, exist_ok=True)
    made_here.write_bytes(b"x")
    holder = type("_C", (), {"config": config})()
    assert JarvisRuntime._inside_outputs(holder, made_here) is True, "만든 문서가 「열 수 없음」으로 뜬다"
    # 사람의 다른 문서는 여전히 안 내려준다.
    outside = room / "남의_문서.docx"
    outside.write_bytes(b"x")
    assert JarvisRuntime._inside_outputs(holder, outside) is False

    # 경로가 답과 화면에 실려야 한다. 여기 없으면 「만든 파일:」 줄도 「만든 것」 탭도 빈다.
    for name in ("local_write_document", "local_edit_spreadsheet"):
        assert name in JarvisRuntime._OUTPUT_TOOLS, f"{name} 산출물이 화면에 안 뜬다"
        assert "path" in JarvisRuntime._OUTPUT_TOOLS[name]


def test_a_wedged_model_call_is_cut_before_it_eats_the_run() -> None:
    """굳은 요청을 판 예산만큼 기다리지 않는다.

    2026-08-31 실측: Ollama 가 요청을 받고 **생성을 시작조차 안 한 채** 굳었다.
    3090 0% · 슬롯 idle · 모델 상주인데 자비스는 ``_receive_response_headers`` 에서
    3분 넘게 같은 스택이었다. ``timeout=<판 예산>`` 하나뿐이라 그대로 두면 900초를
    기다린다 — 벤치 예산이 1,200초니 **멈춤 한 번이 판을 통째로 먹는다.**

    스트리밍이라 생성이 시작되면 토큰은 연속으로 온다. 그래서 조각 사이가 벌어지는
    것 자체가 고장이고, 읽기 자를 판 예산과 **따로** 둔다.
    """
    import inspect

    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.ollama import OllamaClient

    source = inspect.getsource(OllamaClient.chat_messages_stream)
    assert "httpx.Timeout(" in source, "읽기 자가 판 예산과 안 갈려 있다"
    assert "ollama_stall_timeout_sec" in source
    assert "connect=" in source
    # 상한을 다시 정하려면 근거가 있어야 한다 — 첫 바이트 지연을 남긴다.
    assert "_first_byte_sec" in source, "프리필 비용을 아무도 안 재고 있다"

    config = JarvisConfig.from_env()
    # 그날 성공한 호출의 총 소요 최대가 233초였다. 그보다 넉넉하되 판 예산보다는
    # 확실히 짧아야 한다 — 안 그러면 자를 따로 둔 의미가 없다.
    assert 233 < config.ollama_stall_timeout_sec < config.timeout_for("code")


def test_thinking_is_drawn_in_both_modes() -> None:
    """사고는 코워크(젬마)에서도 화면에 보인다.

    서버는 처음부터 두 역할 모두의 사고를 흘리고 있었다 — ``flush_thinking()`` 은
    ``model_role`` 을 안 가리고, 번역기도 마찬가지다. 그런데 **그리는 곳이 코드
    작업공간에만 있었다.** 그래서 코워크에서는 젬마가 몇 분을 생각해도 화면에는
    고정 문구 한 줄이었고, 정찰기가 번역한 한국어는 만들어지자마자 버려졌다.

    상한이 여러 자리에 있으면 낮은 쪽만 일한다는 그 사고와 같은 모양이다. 여기서
    낮은 쪽은 값이 아니라 **그리는 곳**이었다.
    """
    ui = Path(__file__).resolve().parents[1] / "ui" / "src"
    pane = (ui / "workspace" / "ComputerPane.tsx").read_text(encoding="utf-8")
    app = (ui / "WorkspaceApp.tsx").read_text(encoding="utf-8")

    assert "export function ThinkingTrace" in pane, "코드 모드 밖에서 못 쓴다"
    assert "ThinkingTrace" in app.split("import")[1] or "ThinkingTrace }" in app, (
        "WorkspaceApp 이 안 가져온다"
    )
    # 대화 칸에서도 그린다 — 코드 모드는 오른쪽 칸이 이미 그리므로 거기서만 뺀다.
    assert 'workspaceMode !== "code" && (' in app
    assert "<ThinkingTrace text={thinkingText} ko={thinkingKo}" in app
