"""어느 스킬의 것인지 **코드가 고른다.** 그리고 못 고르면 안 연다.

## 왜 한국어 표를 따로 쓰는가

수확한 61종의 `description` 은 트리거 문구로 꽉 차 있다 — 그런데 **전부 영어다.**

    copywriting: "...write copy for, improve this copy, headline help,
                  value proposition, this copy is weak..."

사용자님은 "상세페이지 문구 좀 다듬어줘"라고 하신다. 영어 트리거에는 한 번도 안
걸린다. 그대로 뒀으면 이 갈래는 **영원히 안 열렸을 것이다** — 만들어 놓고 한 번도
안 불리는, 이 저장소가 다섯 번 겪은 그 모양으로.

## 왜 낱말 하나로 안 여는가

「라우팅 낱말표 → 78% 창작」이 이미 있었다. 그래서 다른 갈래와 같은 어법을 쓴다:

    무엇에 대한 일인가(대상)  ∧  만들거나 고쳐 달라는 말(동사)

이 파일의 절반은 **열리면 안 되는 경우**다. 오탐이 정탐보다 비싸기 때문이다 —
날씨를 물었는데 마케팅 강의가 나오면 그 순간 자비스를 안 쓰게 된다.
"""

from __future__ import annotations

from _harvest import needs_harvest
import pytest

from alture_jarvis.skills import SKILL_TRIGGERS_KO, match_skill


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("우리 학원 상세페이지 문구 좀 써줘", "copywriting"),
        ("랜딩 카피 다듬어줘", "copywriting"),
        ("이 문장들 윤문 좀 해줘", "copy-editing"),
        ("상담 신청률이 낮은데 어떻게 하면 좋을까 개선 방향 잡아줘", "cro"),
        ("우리 사이트 검색 노출 검토해줘", "seo-audit"),
        ("수강료 가격 책정 어떻게 해야 할지 조언해줘", "pricing"),
        ("겨울방학 특강 런칭 계획 짜줘", "launch"),
        ("학부모 안내문 하나 작성해줘", "internal-comms"),
        ("인스타 피드 글 만들어줘", "social"),
        ("상담 스크립트 만들어줘", "sales-enablement"),
        ("이 글 ai 티 나는데 자연스럽게 고쳐줘", "humanizer"),
        ("이 계획 뭐가 잘못될 수 있는지 검토해줘", "thinking-pre-mortem"),
        ("지금 제일 큰 병목이 뭔지 정리해줘", "thinking-theory-of-constraints"),
        ("이 웹앱 테스트를 플레이라이트로 만들어줘", "webapp-testing"),
        ("이 서비스용 MCP 서버를 만들어줘", "mcp-builder"),
        ("자비스 스킬 하나 만들어줘", "skill-creator"),
        ("클로드 API 연동 코드를 작성해줘", "claude-api"),
        ("이 보고서에 쓸 색상 팔레트를 만들어줘", "theme-factory"),
        ("관리자 웹 화면 디자인을 개선해줘", "frontend-design"),
    ],
)
def test_real_korean_requests_find_the_right_skill(prompt: str, expected: str) -> None:
    match = match_skill(prompt)
    assert match is not None, f"안 걸렸다: {prompt}"
    assert match[0] == expected, f"{prompt} -> {match[0]} (기대: {expected})"


@pytest.mark.parametrize(
    "prompt",
    [
        # 그냥 물어본 것. 동사가 없다.
        "우리 수강료가 얼마였지",
        "요즘 광고비 얼마나 나가",
        "전환율이 뭐야",
        # 대상이 없다. 일을 시켰지만 스킬의 것이 아니다.
        "시간표 만들어줘",
        "이번 주 일정 정리해줘",
        "엑셀 파일 하나 만들어줘",
        # 아예 다른 갈래
        "지금 몇 시야",
        "카메라 정면으로 돌려줘",
        "지금 네 상태 점검해봐",
    ],
)
def test_ordinary_talk_does_not_open_the_skill_branch(prompt: str) -> None:
    """★ 이 파일에서 가장 중요한 검사.

    오탐 하나가 정탐 열보다 비싸다. 「지금 몇 시야」에 마케팅 스킬이 붙으면
    그 순간 자비스가 이상해진 것으로 보인다.
    """
    assert match_skill(prompt) is None, f"열리면 안 되는데 열렸다: {prompt}"


@pytest.mark.parametrize(
    "prompt",
    [
        "네이버 블로그에 글 써줘",
        "이 내용으로 블로그 글 작성해줘",
        "학부모들한테 메일 보내줘",
        "다음주 상담 일정 잡아줘",
        "경쟁 학원 요즘 뭐 하는지 검색해줘",
    ],
)
def test_other_branches_keep_their_own_work(prompt: str) -> None:
    """★ 실제로 **하는** 갈래를 가로채면 안 된다.

    `naver_blog` 는 편집기를 열어 진짜로 쓴다. 여기서 가로채면 자비스가
    "카피를 써 드렸습니다" 하고 아무 데도 안 올린다 — 안 한 일을 했다고 말하는
    것이 이 저장소가 제일 싫어하는 실패다.
    """
    assert match_skill(prompt) is None, f"다른 갈래의 일을 가로챘다: {prompt}"


def test_only_offers_skills_that_are_actually_there() -> None:
    """갈래만 만들고 물건을 안 주면 모델이 빈손으로 받아 지어낸다.

    `_requires_inhouse_data` 가 "도구가 실제로 있을 때만 연다"고 한 그 규칙이다.
    """
    assert match_skill("상세페이지 문구 써줘", available={"copywriting"}) is not None
    assert match_skill("상세페이지 문구 써줘", available=set()) is None


@needs_harvest
def test_every_trigger_points_at_a_harvested_skill() -> None:
    """★ 표가 낡으면 조용히 안 열린다.

    스킬 이름이 바뀌거나 수확에서 빠졌는데 표에 남아 있으면, 그 대상은 영원히
    매칭되고도 물건이 없다. **표와 수확물이 갈리는 순간 여기서 걸린다.**
    """
    from pathlib import Path

    from alture_jarvis.skills import load_skills

    root = Path(__file__).resolve().parents[1] / "skills"
    if not (root / "vendor").is_dir():  # pragma: no cover - 수확 전이면 건너뛴다
        return
    harvested = {name for name, doc in load_skills(root).items() if doc.served}
    # 팩에 든 스킬도 수확물이다(2026-09-27 팩 0판) — 팩이 켜져야 보이지만 표의 이름은 실재해야 한다.
    for pack_skills in root.parent.glob("packs/*/skills"):
        harvested |= {name for name, doc in load_skills(pack_skills).items() if doc.served}

    missing = sorted(set(SKILL_TRIGGERS_KO) - harvested)
    assert not missing, f"표에는 있는데 수확물에 없는 스킬: {missing}"


@needs_harvest
def test_new_anthropic_skills_keep_their_apache_notice() -> None:
    """가져온 본문보다 고지가 먼저다. 고지가 없으면 배급하지 않는다."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "skills" / "vendor" / "anthropic"
    imported = {
        "webapp-testing", "mcp-builder", "skill-creator", "claude-api", "theme-factory"
    }
    for name in imported:
        license_text = (root / name / "LICENSE.txt").read_text(encoding="utf-8-sig")
        assert "Apache License" in license_text
        assert "Version 2.0, January 2004" in license_text
    assert not ({"docx", "pdf", "pptx", "xlsx"} & {p.name for p in root.iterdir()})


# ═══════════════════════════════════════════════════════════════════════════
# 배선 — 꺼져 있으면 한 글자도 안 바뀐다
# ═══════════════════════════════════════════════════════════════════════════


class _Events:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    def publish(self, name: str, payload: dict) -> None:
        self.published.append((name, payload))


class _Store:
    """★ 진짜 장부. `events.publish` 와 **다른 곳**이다.

    처음엔 이 검사가 `_Events` 가 받은 것만 확인했다. 그래서 라이브에서 갈래가
    붙었는데 `audit_log` 의 `skill_route_selected` 가 0 건인 것을 못 잡았다 —
    `events.publish` 는 화면으로 흘러가 사라지고, 남기는 것은 `store.add_audit`
    뿐이다. **어디로 갔는지를 안 보면 계측한 것이 아니다.**
    """

    def __init__(self) -> None:
        self.audited: list[tuple[str, str, dict]] = []

    def add_audit(self, event: str, subject_id: str = "", payload=None) -> None:  # noqa: ANN001
        self.audited.append((event, subject_id, payload or {}))


class _Runtime:
    """`_skill_instruction` 만 떼어 쓴다. 전체 런타임은 하드웨어가 있어야 뜬다."""

    from alture_jarvis.runtime import JarvisRuntime

    _skill_instruction = JarvisRuntime._skill_instruction
    # staticmethod 라 그대로 붙이면 self 가 첫 인자로 들어간다.
    _skill_prompt_note = staticmethod(JarvisRuntime._skill_prompt_note)

    # 이 가짜는 낱말표 배선만 시험한다. 모델 분류는 아래의 전용 가짜가 따로
    # 시험하므로 여기서는 빈 문자열을 돌려 기존 테스트의 경계를 보존한다.
    def _skill_guess(self, prompt: str, available: set[str]) -> str:
        return ""

    def __init__(self, config, library) -> None:  # noqa: ANN001
        self.config = config
        self.skills = library
        self.events = _Events()
        self.store = _Store()


def _library(tmp_path):  # noqa: ANN001
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.skills import SkillLibrary

    d = tmp_path / "vendor" / "marketing" / "copywriting"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: copywriting\ndescription: write copy\n---\n\n# Copywriting\nBe clear.\n",
        encoding="utf-8",
    )
    (tmp_path / "vendor" / "marketing" / "LICENSE").write_text("MIT", encoding="utf-8")
    config = JarvisConfig()
    config.skills_dir = tmp_path
    config.skills_enabled = True
    return config, SkillLibrary(config)


def test_disabled_route_changes_nothing(tmp_path) -> None:
    """★ 기본값은 꺼짐이고, 꺼져 있으면 프롬프트에 아무것도 안 붙는다."""
    config, library = _library(tmp_path)
    assert config.skills_route_enabled is False  # 태어날 때부터 꺼져 있다

    runtime = _Runtime(config, library)

    assert runtime._skill_instruction("상세페이지 문구 써줘") == ""
    assert runtime.events.published == []
    assert runtime.store.audited == []


def test_enabled_route_attaches_the_playbook_and_logs_it(tmp_path) -> None:
    config, library = _library(tmp_path)
    config.skills_route_enabled = True
    runtime = _Runtime(config, library)

    note = runtime._skill_instruction("상세페이지 문구 써줘", job_id="j1")

    assert "Be clear." in note
    # 봉투와 한국어 규칙이 같이 간다.
    assert "<untrusted-skill>" in note
    assert "답은 반드시 한국어로" in note
    # 화면으로도 가고,
    assert runtime.events.published[0][0] == "skill_route_selected"
    assert runtime.events.published[0][1]["skill"] == "copywriting"
    # ★ **장부에도 남는다.** 이 줄이 없어서 라이브 0 건을 못 잡았다.
    assert [e[0] for e in runtime.store.audited] == ["skill_route_selected"]
    assert runtime.store.audited[0][2]["skill"] == "copywriting"
    assert runtime.store.audited[0][1] == "j1"


def test_asked_skill_beats_guess_and_triggers(tmp_path) -> None:
    config, library = _library(tmp_path)
    config.skills_route_enabled = True
    runtime = _Runtime(config, library)

    note = runtime._skill_instruction(
        "지금 몇 시야", job_id="asked", asked="copywriting"
    )

    assert "Be clear." in note
    record = runtime.store.audited[0][2]
    assert record["skill"] == "copywriting"
    assert record["picked_by"] == "asked"


def test_model_guess_is_recorded_separately(tmp_path) -> None:
    config, library = _library(tmp_path)
    config.skills_route_enabled = True
    runtime = _Runtime(config, library)
    runtime._skill_guess = lambda prompt, available: "copywriting"

    note = runtime._skill_instruction("낱말표에는 없는 요청", job_id="guess")

    assert "Be clear." in note
    record = runtime.store.audited[0][2]
    assert record["skill"] == "copywriting"
    assert record["picked_by"] == "guess"


def test_enabled_but_unmatched_still_changes_nothing(tmp_path) -> None:
    config, library = _library(tmp_path)
    config.skills_route_enabled = True
    runtime = _Runtime(config, library)

    assert runtime._skill_instruction("지금 몇 시야") == ""
    assert runtime.events.published == []
    assert runtime.store.audited == []


def test_one_job_is_only_counted_once(tmp_path) -> None:
    """★ 두 자리에서 불린다 — 라우터와 `_contextual_answer`.

    한 판을 두 번 세면 분모가 틀리고, **틀렸다는 사실조차 안 보인다.**
    두 번 불러도 장부에는 한 번만 남고, 플레이북은 두 번 다 나온다.
    """
    config, library = _library(tmp_path)
    config.skills_route_enabled = True
    runtime = _Runtime(config, library)

    first = runtime._skill_instruction("상세페이지 문구 써줘", job_id="j1")
    second = runtime._skill_instruction("상세페이지 문구 써줘", job_id="j1")

    assert first == second
    assert "Be clear." in second  # 두 번째도 플레이북을 준다
    assert len(runtime.store.audited) == 1  # 그런데 장부는 하나
    assert len(runtime.events.published) == 1


def test_different_jobs_are_counted_separately(tmp_path) -> None:
    config, library = _library(tmp_path)
    config.skills_route_enabled = True
    runtime = _Runtime(config, library)

    runtime._skill_instruction("상세페이지 문구 써줘", job_id="j1")
    runtime._skill_instruction("상세페이지 문구 써줘", job_id="j2")

    assert len(runtime.store.audited) == 2


# ═══════════════════════════════════════════════════════════════════════════
# 조사하는 판에도 붙는가 (2026-08-22)
# ═══════════════════════════════════════════════════════════════════════════
#
# 실측: "크몽에서 … 가격 책정 전략을 짜줘" 는 매칭이 ('pricing', 1) 인데
# 장부에는 0 건이었다. `_requires_named_source`("크몽에서…")가 먼저 걸려
# `return "agent"` 로 나가는데, 스킬을 붙인 자리는 그 **뒤**에 있었기 때문이다.
#
# 어제 수강료 질문(사이트 안 댐)은 붙었고 오늘 크몽 질문(사이트 댐)은 안 붙었다.
# **사이트 이름 한 조각으로 갈렸다.**


_KMONG = (
    "크몽에서 AI 자동화 외주를 받으려는데 가격 책정 전략을 짜줘. "
    "경쟁자들은 대부분 단순 챗봇 붙여주는 수준이야."
)


def test_a_question_with_a_named_site_still_finds_its_skill() -> None:
    """사이트 이름이 붙어도 매칭 자체는 된다 — 문제는 붙이는 자리였다."""
    assert match_skill(_KMONG) == ("pricing", 1)


def test_agent_path_gets_the_playbook_too(tmp_path) -> None:
    """★ 이 검사가 그 구멍을 막는다.

    조사하러 나가는 판이야말로 플레이북이 필요하다 — **무엇을 찾을지**가 거기서
    정해지기 때문이다. 없던 동안 그 판은 경쟁사 가격표만 보고 왔다.
    """
    config, library = _library(tmp_path)
    config.skills_route_enabled = True
    runtime = _Runtime(config, library)

    note = runtime._skill_instruction("상세페이지 문구 써줘", job_id="j1", for_agent=True)

    assert "Be clear." in note, "조사 판에 플레이북이 안 붙는다"
    assert runtime.store.audited[0][2]["path"] == "agent", "어느 경로인지 안 남는다"


def test_the_two_paths_speak_differently(tmp_path) -> None:
    """답할 때는 「이렇게 써라」, 나갈 때는 「무엇을 볼까」다.

    같은 문서라도 쓰임이 다르면 소개가 달라야 한다.
    """
    config, library = _library(tmp_path)
    config.skills_route_enabled = True

    answer = _Runtime(config, library)._skill_instruction("문구 써줘", job_id="a")
    agent = _Runtime(config, library)._skill_instruction("문구 써줘", job_id="b", for_agent=True)

    assert "무엇을 봐야 하는지" in agent
    assert "무엇을 봐야 하는지" not in answer
    # 둘 다 한국어로 답하라는 말은 유지된다.
    assert "한국어" in answer and "한국어" in agent


def test_agent_path_is_given_a_tighter_budget(tmp_path) -> None:
    """★ 에이전트는 걸음마다 도구 규율과 자리를 다툰다.

    답변용 예산을 그대로 넣으면 플레이북이 절차를 밀어낸다. 그리고 **넓히지는
    못한다** — 인자로 상한을 올릴 수 있으면 설정이 설정이 아니게 된다.
    """
    config, library = _library(tmp_path)
    config.skills_body_max_chars = 3000

    wide = library.read_skill({"name": "copywriting"})
    narrow = library.read_skill({"name": "copywriting", "max_chars": 800})
    too_wide = library.read_skill({"name": "copywriting", "max_chars": 999999})

    assert len(narrow["body"]) <= len(wide["body"])
    # 설정값(3000)을 넘겨 달라고 해도 안 넘어간다.
    assert len(too_wide["body"]) <= len(wide["body"])

def test_every_thinking_skill_is_reachable() -> None:
    """사고 틀 28종은 **전부 갈래가 있어야 한다.**

    2026-08-31 실측: 8종만 갈래가 있어 **20종이 도달 불가**였다. 상시 목록
    (`SkillLibrary.thinking_card`)을 띄워도 모델은 `skill_read` 를 안 부른다 —
    장부 10,548건 중 2건이 전부다.

    반면 낱말표는 **걸리는 것이 라이브에서 확인됐다**: 「병목이 어디인지 판단해줘」에
    `skill_route_selected` 2건이 찍혔고 답도 TOC 형식이었다. 되는 쪽을 넓힌다.

    `thinking-*` 은 **사람이 그 이름을 말하지 않는 스킬**이라, 새로 추가할 때마다
    갈래를 같이 안 달면 조용히 죽는다. 그래서 개수가 아니라 **전수**로 검사한다.
    """
    from pathlib import Path

    from alture_jarvis.skills import SKILL_TRIGGERS_KO, load_skills

    docs = load_skills(Path(__file__).resolve().parents[1] / "skills")
    thinking = {name for name, doc in docs.items() if (doc.collection or "") == "thinking"}
    assert thinking, "사고 틀을 하나도 못 읽었다"
    missing = sorted(thinking - set(SKILL_TRIGGERS_KO))
    assert not missing, f"갈래 없는 사고 틀: {missing}"


def test_the_new_thinking_triggers_open_and_do_not_steal() -> None:
    """새 낱말이 **자기 판에서 열리고, 남의 판을 안 훔친다.**

    흔한 한 낱말(가설·근거·확률)을 넣으면 남의 판을 가져간다 — `brainstorming` 의
    "방향 잡아" 가 `cro` 를 훔친 적이 있고 이 파일이 잡았다.
    """
    from alture_jarvis.skills import match_skill

    opens = [
        ("이거 언제까지 찾아야 하는지 정리해줘", "thinking-bounded-rationality"),
        ("어디서부터 손대야 할지 조언해줘", "thinking-cynefin"),
        ("사용자가 왜 안 쓰는지 검토해줘", "thinking-jobs-to-be-done"),
        ("문서랑 다르게 도는데 원인 정리해줘", "thinking-map-territory"),
        ("성공 가능성이 얼마나 되는지 검토해줘", "thinking-probabilistic"),
        ("가장 강한 반대 입장을 정리해줘", "thinking-steel-manning"),
        ("고치면 딴 데가 터지는데 봐줘", "thinking-systems"),
        ("둘 다 만족시킬 방법 제안해줘", "thinking-triz"),
        ("기능을 빼는 게 나을지 검토해줘", "thinking-via-negativa"),
    ]
    for prompt, expected in opens:
        got = match_skill(prompt)
        assert got is not None, f"안 열렸다: {prompt}"
        assert got[0] == expected, f"{prompt} → {got[0]} (기대 {expected})"

    # 기존 판이 새 낱말에 안 밀렸는가.
    for prompt, expected in (
        ("수강료 정책 짜줘", "pricing"),
        ("병목이 어디인지 판단해줘", "thinking-theory-of-constraints"),
    ):
        got = match_skill(prompt)
        assert got and got[0] == expected, f"{prompt} → {got} (기대 {expected})"


def test_the_most_common_job_in_this_repo_finally_gets_a_playbook() -> None:
    """★ 2026-09-03. 스킬 주입률이 5%(10/186)였다. 원인은 스킬이 없어서가 아니라
    **트리거가 사람 말과 안 맞아서**였다 — 이 저장소에서 제일 흔한 판(테스트 실패
    고치기)이 통째로 맨손이었다.

    경량 모델은 아는 것이 아니라 **절차를 받아야** 잘한다. 그래서 이 자리가
    모델 등급보다 크다.

    실측: 90문장 중 매칭 14 → 39. 잃은 것 0.
    """
    from alture_jarvis.skills import match_skills  # noqa: PLC0415

    asks = {
        "이 저장소에서 다음 테스트가 실패한다: tests/test_sandbox.py "
        "실패 출력: ImportError while importing test module. 원인을 찾아 고쳐줘.":
            "systematic-debugging",
        "INSTRUCTIONS.md 를 읽고 book_store.py 를 구현해줘. 테스트 파일은 수정하지 마. "
        "테스트를 실행해 전부 통과시켜줘.":
            "verification-before-completion",
        "unique_tags가 순서를 보존하게 고쳐줘. 기존 공개 테스트 파일은 수정하지 말고 "
        "그대로 실행해 검증해줘.":
            "verification-before-completion",
    }
    for ask, expected in asks.items():
        picked = [name for name, _ in match_skills(ask)]
        assert picked, f"아무 스킬도 안 붙는다: {ask[:40]}"
        assert expected in picked, f"{expected} 가 없다 — 붙은 것: {picked}"


def test_a_reproduction_task_is_not_a_bug_report() -> None:
    """★ 넓히다 생긴 오탐을 되돌린 자리.

    「각 개선을 **검증할 재현 과제**를 제시해라」의 「재현」까지 물어서 분석 판이
    디버깅 스킬로 끌려갔다. 넓힐 때는 새로 생긴 오탐을 같이 센다.
    """
    from alture_jarvis.skills import match_skills  # noqa: PLC0415

    analysis = (
        "복합 분석 실전 점검이다. 파일을 수정하지 말고 조사·분석만 해라. "
        "강점 3개와 병목 3개, 각 개선을 검증할 재현 과제를 제시해라."
    )
    picked = [name for name, _ in match_skills(analysis)]

    assert "systematic-debugging" not in picked[:1], f"분석 판이 디버깅으로 갔다: {picked}"


def test_the_most_common_ending_in_this_repo_opens_the_gate() -> None:
    """★ 「…알려줘」가 과업 동사에 없어서, 트리거가 둘이나 맞는 판이 떨어졌다.

        사람인에서 연구비 관리 정규직 공고 3개를 … 알려줘
        → career-job-search 트리거 「공고」·「사람인」 적중 2
        → 그런데 동사가 없어 문 앞에서 잘림

    게이트는 `동사 × 대상` 논리곱이라 **한쪽이 좁으면 다른 쪽이 아무리 맞아도**
    안 열린다. 실측: 매칭 34 → 39, 1순위 뒤집힘 0, 잃은 것 0.
    """
    from alture_jarvis.skills import match_skills  # noqa: PLC0415

    asks = {
        "사람인에서 연구비 관리 정규직 공고 3개를 각각 상세 페이지까지 직접 열어 "
        "읽고 회사명과 마감일을 알려줘": "career-job-search",
        "사람인에서 연구비 관리 공고 3개 찾아서 각각 고용형태와 마감일을 알려줘":
            "career-job-search",
    }
    for ask, expected in asks.items():
        picked = [name for name, _ in match_skills(ask)]
        assert expected in picked, f"{expected} 가 없다 — 붙은 것: {picked}"


def test_a_plain_lookup_still_gets_nothing() -> None:
    """★ 반대 방향. 동사를 넓혔다고 아무 데나 붙으면 시스템 자리를 낭비한다.

    「크몽에서 상위 3개 제목 알려줘」는 플레이북이 필요한 일이 아니다 —
    목록을 읽어 오는 것뿐이다.
    """
    from alture_jarvis.skills import match_skills  # noqa: PLC0415

    for ask in (
        "크몽에서 AI 자동화 관련 서비스 상위 3개의 제목과 가격을 알려줘",
        "위시켓에서 AI 에이전트 관련 프로젝트 상위 3개의 제목과 예산을 알려줘",
    ):
        assert match_skills(ask) == [], ask
