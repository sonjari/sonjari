""""보고 왔다"고 말하려면 실제로 봤어야 한다.

2026-08-09 사고 둘. 같은 병의 두 증상이다.

**증상 1 — 코드를 한 줄도 안 읽고 "Based on Code".**
"C:\\work\\monorepo 여기 폴더 및 자비스 프로그램 … 분석해주라" 에 자비스가 **도구
호출 0건**으로 13초 만에 답했다(`agent_trace: null` — 에이전트에 가지도 않았다).
그러고는 표 제목에 "Based on Code" 라 적고 Intent Router · Prompt Layering ·
indexing · exporter · "Gemini/OpenAI 하이브리드" 를 근거로 들었다. **전부 이
저장소에 없는 이름이다.** 실제 LLM 은 로컬 Gemma 하나뿐이다. 그 위에 단가
1,500만~5,000만원까지 얹혔다 — 사업 판단에 쓰일 뻔했다.

파일 읽기 도구는 켜져 있었고 그 폴더는 허용 경로에도 있었다. 쓸 수 있었는데 안 썼다.

**증상 2 — 공고를 한 건도 안 열고 예산을 말함.**
크몽·위시켓 공고 조사에서 18스텝 중 검색이 10번, 실제로 읽은 본문은 네이버 블로그
2개. 개별 공고는 0건. 그런데 "기초 FAQ 챗봇 15만~30만원" 같은 숫자가 나왔다.

이 파일이 지키는 것:

  1. 경로·코드베이스를 대고 "분석해줘"라고 하면 도구를 쥔 쪽으로 보낸다
  2. 그러고도 안 읽고 "코드를 보니"라고 하면 그 답에 정정을 붙인다
  3. 없는 주소로 간 것은 "지어냈다"는 뜻이므로 회복할 길을 알려 준다
  4. 광고 링크는 애초에 결과에 넣지 않는다

CLAUDE.md 사고 I 와 같은 계열이다 — **출처 주장은 검증 대상이지 신뢰 대상이 아니다.**
그 교훈을 데이터의 `source` 컬럼뿐 아니라 모델 자신의 문장에도 적용한다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.serp import SEARCH_HOSTS, is_navigation

_REAL_PROMPT = (
    r'"C:\work\monorepo" 여기 폴더 및 자비스 프로그램 너가 할수있는거는'
    "(전부다 내가 너를 개발을 했으니) 나는 어느정도의 수준을 받을수있을지 한번 분석해주라"
)


# ── 1. 라우팅: 경로를 댔으면 가서 보게 한다 ──────────────────────────────────
def test_the_real_prompt_that_got_fabricated_now_routes_to_the_tools() -> None:
    assert JarvisRuntime._requires_local_inspection(_REAL_PROMPT) is True


def test_other_ways_of_naming_this_machine_count_too() -> None:
    for prompt in (
        "우리 코드 한번 검토해줘",
        "이 프로젝트 구조 좀 정리해줘",
        r"C:\RoboMetaFit 폴더 살펴봐줘",
        "소스 코드 읽어보고 알려줘",
    ):
        assert JarvisRuntime._requires_local_inspection(prompt) is True, prompt


def test_a_url_is_not_a_local_path() -> None:
    """`[A-Za-z]:[\\/]` 는 "https://" 의 "s://" 에도 걸린다 — 막아 뒀는지 본다."""
    assert JarvisRuntime._requires_local_inspection("https://wishket.com 분석해줘") is False


def test_plain_chat_is_left_alone() -> None:
    for prompt in ("오늘 기분 어때?", "학원 마케팅 전략 좀 얘기해줘", "1+1은?"):
        assert JarvisRuntime._requires_local_inspection(prompt) is False, prompt


# ── 2. 안전망: 에이전트에 가서도 안 읽었으면 답에 정정을 붙인다 ───────────────
def _step(tool: str, ok: bool = True) -> dict[str, object]:
    return {"tool": tool, "ok": ok, "error": "", "status": ""}


_FABRICATED = "코드를 분석한 결과, Intent Router 와 Prompt Layering 구조를 보유하고 있습니다."


def test_claiming_to_have_read_the_code_without_reading_gets_corrected() -> None:
    note = BrowserAgent._sourced_claim_check(_FABRICATED, [])
    assert "열어 보지 않고" in note


def test_a_failed_read_does_not_count_as_having_looked() -> None:
    note = BrowserAgent._sourced_claim_check(_FABRICATED, [_step("local_read_text_file", ok=False)])
    assert note != ""


def test_preparing_something_is_not_reading_something() -> None:
    note = BrowserAgent._sourced_claim_check(_FABRICATED, [_step("naver_blog_prepare_post")])
    assert note != "", "준비 도구를 '봤다'로 쳤다"


def test_actually_reading_draws_no_correction() -> None:
    assert BrowserAgent._sourced_claim_check(_FABRICATED, [_step("local_read_text_file")]) == ""
    assert BrowserAgent._sourced_claim_check(_FABRICATED, [_step("browser_extract")]) == ""


def test_an_answer_that_claims_nothing_is_left_alone() -> None:
    assert BrowserAgent._sourced_claim_check("네, 그렇게 하겠습니다.", []) == ""


# ── 3. 광고 링크는 결과가 아니다 ─────────────────────────────────────────────
def test_the_ad_redirect_that_broke_the_research_is_filtered() -> None:
    # 실제로 rank 3 에 실려 browser_open_result 를 죽인 그 호스트.
    assert "ader.naver.com" in SEARCH_HOSTS
    assert is_navigation("광고", "https://ader.naver.com/v1/r1AB_8lXDtDkt") is True


def test_naver_content_hosts_still_survive() -> None:
    """도메인 단위로 쓸면 blog.naver.com 이 통째로 사라진다 — 그게 원래 고장이었다."""
    assert is_navigation("어느 학원의 AI 도입기", "https://blog.naver.com/gaussian88/224351792501") is False


# ── 4. 목록을 본 것은 "본 것"이 아니다 ────────────────────────────────────────
#
# 라우팅을 고친 뒤 실측(2026-08-09): local_list_directory 한 번만 부르고 파일
# 이름에서 구조·역량·단가를 추론해 "폴더의 구조를 분석한 결과"라고 답했다. 이름
# 아홉 개는 실재했다 — 그래서 더 그럴듯했고, 해석은 전부 추측이었다.

_LISTING_ONLY_ANSWER = "폴더의 구조를 분석한 결과, 지식 그래프 구축 역량을 보유하고 있습니다."


def test_listing_a_folder_is_not_reading_it() -> None:
    note = BrowserAgent._sourced_claim_check(_LISTING_ONLY_ANSWER, [_step("local_list_directory")])
    assert "목록만 보고" in note


def test_opening_one_file_settles_it() -> None:
    note = BrowserAgent._sourced_claim_check(
        _LISTING_ONLY_ANSWER,
        [_step("local_list_directory"), _step("local_read_text_file")],
    )
    assert note == ""


def test_the_listing_result_tells_the_model_to_open_something() -> None:
    """목록 결과가 스스로 '이건 근거가 아니다'라고 말해야 한다 — 검색 결과와 같은 방식."""
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.local_computer import LocalComputerTools, SURVEY_READ_CHARS
    import pathlib, tempfile

    root = pathlib.Path(tempfile.mkdtemp())
    (root / "runtime.py").write_text("x = 1\n", encoding="utf-8")
    (root / "agent.py").write_text("y = 2\n", encoding="utf-8")
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(root)))

    first = tools.list_directory({"path": str(root)})
    assert "목록일 뿐이다" in first["instruction"]
    assert "runtime.py" in first["instruction"], "무엇을 열라는지 이름을 대야 한다"
    # ★ 로 시작해야 에이전트가 이걸 별도 메시지로 세운다 — 큰 목록에 묻히지 않게.
    assert first["instruction"].startswith("★")

    # 아무것도 안 읽고 또 목록만 보면 말이 세진다.
    second = tools.list_directory({"path": str(root)})
    assert "또 목록을 봤다" in second["instruction"]

    # 실제로 읽으면 잔소리가 기본으로 돌아간다.
    tools.read_text_file({"path": str(root / "runtime.py")})
    third = tools.list_directory({"path": str(root)})
    assert "또 목록을 봤다" not in third["instruction"]
    assert "번째" not in third["instruction"]


def test_surveying_code_no_longer_eats_the_whole_context() -> None:
    """한 파일이 창을 다 먹지 않게. 40,000자였을 때가 그랬다.

    2026-08-10 에 컨텍스트를 24,576 -> 65,536 으로 올리면서 이 값도 6,000 -> 15,000
    으로 같이 키웠다. 상한을 두는 이유는 창 크기가 아니라 **여러 파일을 견줘야
    한다**는 데 있다 — 한 파일이 전사를 독식하면 비교가 안 된다.
    """
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.local_computer import LocalComputerTools, SURVEY_READ_CHARS
    import pathlib, tempfile

    # 전사 예산(agent._bounded_transcript, 110,000자)의 1/5 이하. 최소 대여섯 개는
    # 함께 들고 있을 수 있어야 한다.
    assert SURVEY_READ_CHARS <= 22_000, "한 파일이 전사를 독식하면 여러 파일을 못 견준다"
    root = pathlib.Path(tempfile.mkdtemp())
    big = root / "big.py"
    big.write_text("a" * 50_000, encoding="utf-8")
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(root)))

    survey = tools.read_text_file({"path": str(big)})
    assert survey["char_count"] <= SURVEY_READ_CHARS
    assert survey["truncated"] is True
    assert "잘렸다" in survey["instruction"], "잘린 사실을 안 알리면 앞부분으로 단정한다"

    # 더 달라고 하면 준다.
    full = tools.read_text_file({"path": str(big), "max_chars": 40_000})
    assert full["char_count"] > SURVEY_READ_CHARS


# ── 5. "띄워 놨습니다"는 화면과 대조되는 주장이다 ─────────────────────────────
#
# 2026-08-10 실측: browser_open 이 wishket.com/login 을 ok=True 로 열었는데 답변은
# "정상적으로 열리지 않고 있습니다"였고, 이어서 "메인 페이지를 띄워 두었습니다"라고
# 했다. 그때 화면의 탭은 about:blank 였다. 도구 결과와도 화면과도 어긋났다.
#
# 이런 거짓말은 들통나는 방식이 나쁘다 — 사람은 빈 화면을 보고 "또 안 됐네"라고
# 읽지 "거짓말했다"고 읽지 않는다. 그래서 조용히 신뢰만 깎인다.

_LEFT_OPEN = "위시켓 메인 페이지를 브라우저에 띄워 두었습니다."


def _opened(url: str, ok: bool = True) -> dict[str, object]:
    return {"tool": "browser_open", "ok": ok, "error": "", "status": "", "evidence": {"url": url}}


def test_claiming_a_page_is_open_with_nothing_opened_gets_flagged() -> None:
    note = BrowserAgent._left_open_check(_LEFT_OPEN, [])
    assert "열어 둔 페이지가 없습니다" in note


def test_a_blank_tab_does_not_count_as_opened() -> None:
    note = BrowserAgent._left_open_check(_LEFT_OPEN, [_opened("about:blank")])
    assert "열어 둔 페이지가 없습니다" in note, "빈 탭을 열어 둔 것으로 쳤다"


def test_a_real_page_gets_its_address_shown() -> None:
    note = BrowserAgent._left_open_check(_LEFT_OPEN, [_opened("https://www.wishket.com/")])
    assert "wishket.com" in note
    assert "없습니다" not in note


def test_an_answer_that_claims_nothing_open_is_left_alone() -> None:
    assert BrowserAgent._left_open_check("조사 결과를 정리했습니다.", []) == ""


# ── 6. 시킨 만큼 했는가 ──────────────────────────────────────────────────────
#
# _commit_reality_check(한 척) · _sourced_claim_check(본 척) ·
# _left_open_check(띄운 척) 의 마지막 짝 — **시킨 만큼 한 척.**
#
# 2026-08-10 실측: "공고를 최소 4개는 직접 열어 읽어라"라고 했는데 본문까지 연 것은
# 2개였고, 답변은 그 사실을 한 줄도 적지 않았다. 표가 그럴듯해서 부족하다는 것을
# 알아챌 방법이 없었다. 모자란 것 자체는 흠이 아니다 — 흠은 모자란 줄 모르게 하는 것이다.

_FOUR = "위시켓과 크몽에서 공고를 최소 4개는 직접 열어 읽고 예산·기간을 표로 정리해줘"


def _read(url: str, ok: bool = True, tool: str = "browser_extract") -> dict[str, object]:
    return {"tool": tool, "ok": ok, "error": "", "status": "", "arguments": {}, "evidence": {"url": url}}


def test_reading_fewer_than_asked_is_said_out_loud() -> None:
    steps = [_read("https://www.wishket.com/project/132082/"), _read("https://www.wishket.com/p/2")]
    note = BrowserAgent._goal_shortfall_check(_FOUR, steps)
    assert "4개 중 2개" in note


def test_reading_enough_draws_no_note() -> None:
    steps = [_read(f"https://www.wishket.com/project/{n}/") for n in range(4)]
    assert BrowserAgent._goal_shortfall_check(_FOUR, steps) == ""


def test_reading_nothing_at_all_is_called_out_harder() -> None:
    note = BrowserAgent._goal_shortfall_check(_FOUR, [])
    assert "하나도 없습니다" in note


def test_the_same_page_twice_is_one_source() -> None:
    """같은 글을 두 번 열어도 하나다 — 두 개로 세면 '네 개 읽었다'가 거짓이 된다."""
    same = "https://www.wishket.com/project/132082/"
    assert BrowserAgent._sources_read([_read(same), _read(same)]) == [same]


def test_a_search_page_is_not_a_source() -> None:
    """검색 결과 화면은 출처가 아니다. 거기서 들어간 글이 출처다."""
    steps = [_read("https://search.naver.com/search.naver?query=x", tool="browser_open")]
    assert BrowserAgent._sources_read(steps) == []


def test_a_failed_read_is_not_a_source() -> None:
    assert BrowserAgent._sources_read([_read("https://a.com/1", ok=False)]) == []


def test_numbers_that_are_not_a_reading_quota_are_left_alone() -> None:
    """'3박4일'·'4개월'·'3개국'·'500만 원'이 개수 요구로 걸리면 안 된다."""
    for prompt in (
        "제주도 3박4일 여행 경비 알려줘",
        "4개월치 매출 정리해줘",
        "3개국 시장 비교해줘",
        "예산 500만 원짜리 공고 찾아줘",
        "학원 운영 팁 알려줘",
    ):
        assert BrowserAgent._goal_shortfall_check(prompt, []) == "", prompt


# ── 7. 라우터가 직접 답하는 길에도 검증이 있어야 한다 ────────────────────────
#
# 사실 검사 넷이 전부 에이전트 안에만 있었다. 라우터가 도구 없이 답해 버리면
# 에이전트에 가지도 않으므로 그 검사들이 통째로 건너뛰어진다.
#
# 2026-08-10 실측: "공고를 최소 4개는 직접 열어 읽어라"에 도구 0건·20초로 956자를
# 냈다(agent_trace: null). 어휘에 '찾아서'가 없어 조사 갈래에 안 걸렸고, 그러고 나니
# 아무도 그 답을 검사하지 않았다.
#
# 어휘를 늘리는 것은 두더지 잡기라 두 겹으로 막는다: 어휘도 넓히고, 낱말이 아니라
# **답 자체**를 봐서 근거 없는 답이면 제대로 된 답을 가지러 보낸다.

_WISHKET = (
    "위시켓과 크몽에서 AI 챗봇·업무자동화 외주 공고를 찾아서, 개별 공고를 최소 4개는 "
    "직접 열어 읽고 예산·기간·요구기술을 표로 정리해줘."
)


def test_the_prompt_that_slipped_past_the_router_now_routes_to_research() -> None:
    assert JarvisRuntime._requires_web_research(_WISHKET) is True


def test_small_talk_still_does_not_open_a_browser() -> None:
    for prompt in ("오늘 기분 어때", "1+1은?", "고마워", "짧게 인사만 해줘"):
        assert JarvisRuntime._requires_web_research(prompt) is False, prompt


def test_a_toolless_answer_that_claims_grounding_is_caught_with_no_steps() -> None:
    """라우터 경로에는 steps 가 없다 — 그 상태에서도 검사가 걸려야 한다."""
    assert BrowserAgent._sourced_claim_check("코드를 분석한 결과 이렇습니다.", []) != ""
    assert BrowserAgent._goal_shortfall_check(_WISHKET, []) != ""


def test_a_wrong_path_says_where_the_thing_actually_is() -> None:
    """못 찾았으면 **근처에 무엇이 있는지** 같이 줘야 한다.

    2026-08-29 라이브: 자비스가 `tools/alture-jarvis/evals` 를 찍었는데 실제
    `evals` 는 저장소 루트에 있었다. 판정은 맞았지만 도구가 돌려준 것은
    `path_not_found` 다섯 글자와 `{}` 뿐이라, 모델은 고칠 근거 없이 계속 찍었다.

    경로를 더 열어 주는 것은 답이 아니다 — 없는 경로는 넓혀도 없다. 「여기엔 없고
    저기 있다」는 사실을 결정론으로 준다.
    """
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.local_computer import LocalComputerTools
    import pathlib, tempfile

    # 사용자 이름이 8자를 넘는 PC 의 임시 폴더는 짧은 이름(`RUNNER~1`)으로 온다 — 도구는 푼 경로로 말한다.
    root = pathlib.Path(tempfile.mkdtemp()).resolve()
    (root / "evals").mkdir()
    (root / "tools").mkdir()
    (root / "tools" / "src").mkdir()
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(root)))

    try:
        tools.list_directory({"path": str(root / "tools" / "evals")})
    except FileNotFoundError as exc:
        message = str(exc)
    else:  # pragma: no cover - 없는 경로가 성공하면 그 자체가 고장이다
        raise AssertionError("없는 경로인데 성공했다")

    assert message.startswith("path_not_found"), "무슨 일인지는 계속 말해야 한다"
    # 답이 되는 것이 앞에 와야 한다 — 오류는 500자에서 잘려 모델에게 간다.
    assert "같은 이름이 여기 있다" in message
    assert str(root / "evals") in message
    assert message.index("같은 이름") < message.index("안에는"), "답이 뒤에 있으면 잘린다"
    # 형제도 보여 줘서 이름을 잘못 쓴 경우도 스스로 고치게 한다.
    assert "src" in message


def test_the_not_found_hint_fits_in_what_the_model_actually_receives() -> None:
    """도구 오류는 `str(exc)[:500]` 로 잘려 모델에게 간다(tool_gateway)."""
    from alture_jarvis.local_computer import LocalComputerTools

    assert LocalComputerTools._NOT_FOUND_HINT_CHARS <= 500


def test_a_bold_heading_is_not_a_company_name() -> None:
    """★ 2026-09-03. 이 검사가 최근 186판에서 **16번 울렸고 16번 다 틀렸다.**

        읽지 않고 적은 것이 있습니다: 검증수행, 가격정보, 데이터근거

    전부 굵은 글씨 소제목이었다. 경고가 늘 틀리면 아무도 안 읽는다 —
    그러면 진짜 사고가 났을 때도 못 잡는다.
    """
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    headings = (
        "1. **검증 수행:** 상위 5개를 확인했습니다\n"
        "2. **가격 정보:** 표에 적었습니다\n"
        "3. **데이터 근거:** 상세를 읽었습니다\n"
    )
    note = BrowserAgent._listed_entity_grounding_check(
        headings, [{"role": "tool", "tool_name": "browser_extract", "content": "아무 본문"}]
    )

    assert note == "", f"소제목을 이름으로 잡았다: {note[:80]}"


def test_the_real_incident_is_still_caught() -> None:
    """★ 반대 방향. 2026-09-02 사람인 사고는 표였고, 그건 그대로 잡아야 한다."""
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    table = (
        "| 순위 | 회사 |\n| --- | --- |\n"
        "| 1 | **미르** |\n| 2 | **도담스페이스** |\n| 3 | **바름터** |\n"
    )
    note = BrowserAgent._listed_entity_grounding_check(
        table,
        [{"role": "tool", "tool_name": "browser_extract", "content": "미르 채용 공고입니다"}],
    )

    assert "도담스페이스" in note and "바름터" in note


def test_a_plain_name_bullet_is_still_checked() -> None:
    """소제목만 걸러야지, 이름 글머리표까지 잃으면 안 된다."""
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    bullets = "- **코드나루**\n- **한울솔루션**\n- **바름터**\n"
    note = BrowserAgent._listed_entity_grounding_check(
        bullets,
        [{"role": "tool", "tool_name": "browser_extract", "content": "코드나루 한울솔루션 공고"}],
    )

    assert "바름터" in note


# ★ 2026-09-23 라이브(나래 계정, 온텔릭에게 로그인 확인 네 곳을 맡긴 판). 네 사이트를 **다 열어 읽었는데**
#   「읽지 않고 적은 것: GeekNewshada.io」 경고가 붙었다. 답의 표 칸은 「GeekNews (hada.io)」였고,
#   괄호·공백을 지우며 **붙여서** 원문 어디에도 없는 이름을 만들었다. 괄호 안은 덧붙인 설명이지 이름이 아니다.
def test_a_parenthetical_note_is_not_part_of_the_name() -> None:
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    table = (
        "| 사이트 | 로그인 상태 |\n|---|---|\n"
        "| Reddit | 로그인 안 됨 |\n| GeekNews (hada.io) | 로그인 안 됨 |\n| GitHub | 로그인 안 됨 |\n"
    )
    read = "Reddit Sign in … GeekNews - 개발/기술/스타트업 뉴스 서비스 로그인 … GitHub Sign in"
    note = BrowserAgent._listed_entity_grounding_check(
        table, [{"role": "tool", "tool_name": "browser_read", "content": read}]
    )

    assert note == "", f"실제로 읽은 사이트를 안 읽었다고 했다: {note[:80]}"


def test_a_made_up_name_with_a_note_is_still_caught() -> None:
    """반대 방향 — 괄호를 떼 준다고 지어낸 **본이름**까지 통과하면 안 된다."""
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    table = (
        "| 순위 | 회사 |\n| --- | --- |\n"
        "| 1 | **미르 (서울)** |\n| 2 | **도담스페이스 (서울)** |\n"
    )
    note = BrowserAgent._listed_entity_grounding_check(
        table, [{"role": "tool", "tool_name": "browser_extract", "content": "미르 채용 공고 · 근무지 서울"}]
    )

    assert "도담스페이스" in note and "미르" not in note.split("도담스페이스")[0].split(":")[-1]


# ★ 2026-09-23 비용 실험(맡기기 전용 팔): 정답(OpenAI · 3.5)에 「읽지 않고 적은 것: 게시자, 평균별점」 경고가 붙었고,
#   호스트 클로드가 그 경고를 사용자에게 그대로 전했다. 「| 항목 | 내용 |」 설명 표의 첫 칸은 **항목 이름**이다.
def test_a_field_label_column_is_not_a_list_of_names() -> None:
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    table = (
        "| 항목 | 내용 |\n|---|---|\n"
        "| **게시자(퍼블리셔)** | OpenAI |\n| **평균 별점** | 3.5 (106개 등급 기준) |\n"
    )
    read = "ChatGPT OpenAI 3.5 aggregateRating ratingValue 106"
    note = BrowserAgent._listed_entity_grounding_check(
        table, [{"role": "tool", "tool_name": "browser_extract", "content": read}]
    )

    assert note == "", f"항목 이름을 안 읽은 이름으로 잡았다: {note[:80]}"


def test_a_name_table_under_a_real_header_is_still_checked() -> None:
    """반대 방향 — 머리가 「회사」면 첫 칸은 이름이다. 설명 표 예외가 이름 표까지 풀면 안 된다."""
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    table = "| 회사 | 마감 |\n|---|---|\n| 미르 | 10.01 |\n| 도담스페이스 | 10.03 |\n"
    note = BrowserAgent._listed_entity_grounding_check(
        table, [{"role": "tool", "tool_name": "browser_extract", "content": "미르 채용 공고 마감 10.01"}]
    )

    assert "도담스페이스" in note
