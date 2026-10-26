"""열어 보지 않은 곳의 줄에 값이 채워졌으면 답 끝에 밝힌다 (2026-10-24 운영 판 bf69599d · `unopened_places`).

그 판: 「큐레이션 사이트를 찾아 **곳마다 직접 열어 보고** 이름 · 주소 · 얼마나 자주 · 대상 · 로그인 없이 목록 · 최근 글 제목을 엑셀로」.
엑셀의 영어 줄 셋은 「최근 글 제목 = 확인 불가 (직접 열지 못함)」인데 같은 줄의 주기 · 대상 · 「로그인 없이 목록 = 예」가 채워져 있었다.
그 주소들은 한 번도 열리지 않았고(하나는 `not_this_stage` 로 막힘), 값은 블로그 소개 글에서 옮기거나 지은 것이었다. 숫자가 아니라
근거 검사(`unsupported_numbers`)가 통과시켰다.

시험은 걸음 기록의 모양(도구 · 성공 여부 · 인자 · 증거의 주소)으로 짠다. 사이트 · 이름은 전부 지어낸 것이다.
"""
from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult
from alture_jarvis.unopened_places import (
    address_cell,
    rows_about_unopened_places,
    unopened_rows_note,
    visited_places,
)

from test_agent import FakeBrowser

HEAD = ["이름", "주소", "언어", "얼마나 자주", "대상", "로그인 없이 목록", "최근 글 제목"]


def _step(tool: str, landed: str = "", /, *, ok: bool = True, error: str = "", **arguments) -> dict:
    step = {"tool": tool, "ok": ok, "error": error, "arguments": arguments, "evidence": {"url": landed} if landed and ok else {}}
    if landed:
        step["evidence_record"] = {"source_id": landed, "ok": ok, "type": "page_open"}
    return step


def _the_night_run() -> tuple[list[dict], dict]:
    """bf69599d 의 모양 — 소개 글 둘을 읽고 · 한국어 곳 둘을 열고 · 영어 곳 하나는 막히고 · 엑셀을 썼다."""
    steps = [
        _step("browser_search", "https://search.portal.example/search?query=ai+newsletter", query="AI 뉴스레터"),
        _step("browser_open_result", "https://blog.portal.example/someone/1001", rank=3),
        _step("browser_extract", "https://blog.portal.example/someone/1001"),
        _step("browser_open", "https://www.dailyai.example.kr", url="https://www.dailyai.example.kr"),
        _step("browser_extract", "https://www.dailyai.example.kr"),
        _step("browser_open", "https://aimatters.example.kr/", url="https://aimatters.example.kr"),
        _step("browser_open", "https://brief.example.tech/ai", ok=False, error="not_this_stage", url="https://brief.example.tech/ai"),
    ]
    sheets = {
        "비고": [["항목", "설명"], ["영어 5개 이상", "직접 확인한 3개만 포함."]],
        "영어": [
            HEAD,
            ["Brief AI", "https://brief.example.tech/ai", "영어", "매일", "일반인·직장인 (요약 중심)", "예", "확인 불가 (직접 열지 못함)"],
            ["Weekly Bot", "https://www.weeklybot.example.com/newsletter", "영어", "매주", "개발자·연구자", "예", "확인 불가 (직접 열지 못함)"],
        ],
        "한국어": [
            HEAD,
            ["데일리AI", "https://www.dailyai.example.kr", "한국어", "매일", "업계·일반인", "예", "오늘의 AI 소식 (2026.10.23)"],
            ["AI 매터스", "https://aimatters.example.kr", "한국어", "매일", "일반인", "예", "프롬프트 하나로 사진 고치기 (2026.10.23)"],
            ["픽미", "https://contents.premium.portal.example/pickme/tech", "한국어", "매일", "업계·비즈니스", "예", "메타의 새 앱 1,000만 명 (2026.10.22)"],
        ],
    }
    return steps, sheets


def _write(path: str, sheets: dict) -> dict:
    return {"tool": "local_write_document", "ok": True, "error": "",
            "arguments": {"format": "xlsx", "path": path, "sheets": sheets},
            "evidence": {"output_path": "C:/out/" + path, "format": "xlsx", "rows": 8, "sheets": list(sheets)}}


def _found(steps: list[dict], answer: str = "") -> list[dict]:
    """agent.py 의 마무리 자리와 같은 순서로 부른다."""
    return rows_about_unopened_places(BrowserAgent._rows_with_urls(answer, steps), visited_places(steps))["rows"]


def test_rows_of_places_never_opened_are_found_and_opened_ones_are_not() -> None:
    steps, sheets = _the_night_run()
    found = _found(steps + [_write("큐레이션.xlsx", sheets)])
    names = [row["name"] for row in found]
    assert names == ["Brief AI", "Weekly Bot", "픽미"], names
    # 막혀서 못 연 열기는 연 것이 아니다 · 모델 스스로 「확인 불가」라 적은 칸이 있는 줄은 따로 센다.
    assert [row["unknown"] for row in found] == [1, 1, 0]
    assert "매주" in found[1]["values"] and "예" in found[1]["values"]
    # 이웃 호스트(blog.portal.example ↔ contents.premium.portal.example)는 다른 곳이다.
    assert found[2]["place"] == "contents.premium.portal.example"


def test_the_note_names_the_rows_in_the_run_language() -> None:
    steps, sheets = _the_night_run()
    found = _found(steps + [_write("큐레이션.xlsx", sheets)])
    ko = unopened_rows_note(found, lambda ko, en: ko)
    assert "열어 보지 않은 곳의 줄 3개" in ko and "「Brief AI」(brief.example.tech)" in ko
    assert "2줄은 같은 줄에 「확인 불가」 칸과 채운 칸이 함께" in ko
    en = unopened_rows_note(found, lambda ko, en: en)
    assert "3 rows describe places that were never opened" in en and "\"Weekly Bot\"" in en
    words = en
    for row in found:
        words = words.replace(row["name"], "")  # 줄 이름(「픽미」)은 자료다 — 우리가 쓴 글만 본다
    assert not any("\uac00" <= ch <= "\ud7a3" for ch in words), "영어 판의 글에 한국어가 섞였다"
    assert unopened_rows_note([], lambda ko, en: ko) == ""


def test_a_row_and_its_copy_in_the_answer_table_count_once() -> None:
    steps, sheets = _the_night_run()
    answer = (
        "| 이름 | 주소 | 얼마나 자주 |\n|---|---|---|\n"
        "| Brief AI | https://brief.example.tech/ai | 매일 |\n"
    )
    found = _found(steps + [_write("큐레이션.xlsx", sheets)], answer)
    assert [row["name"] for row in found].count("Brief AI") == 1


def test_a_row_with_only_a_name_and_an_address_is_a_candidate_not_a_claim() -> None:
    steps, _ = _the_night_run()
    rows = [["Brief AI", "https://brief.example.tech/ai", "확인 불가"], ["Weekly Bot", "https://weeklybot.example.com", ""]]
    assert rows_about_unopened_places(rows, visited_places(steps))["rows"] == []


def test_a_listing_on_the_same_shop_counts_as_that_shop() -> None:
    """가게 검색 화면(`gmarket.example.co.kr`)에서 옮긴 상품 줄(`item.gmarket.example.co.kr`)은 그 가게에서 본 값이다 — 첫 규칙 대조의 가격 판 24개."""
    steps = [
        _step("browser_open", "https://www.gmarket.example.co.kr/n/search?keyword=mouse", url="https://www.gmarket.example.co.kr"),
        _step("browser_extract", "https://www.gmarket.example.co.kr/n/search?keyword=mouse"),
        _step("browser_open", "https://search.danawa.example.com/dsearch.php?query=mouse"),
    ]
    rows = [
        ["G마켓", "마우스 정품", "102,870원", "무료", "https://item.gmarket.example.co.kr/Item?goodscode=4389353840"],
        ["다나와", "마우스 정품", "110,680원", "무료", "https://m.danawa.example.com/product/product.html?code=73432709"],
    ]
    assert rows_about_unopened_places(rows, visited_places(steps))["rows"] == []


def test_an_address_inside_a_sentence_or_a_list_of_sources_is_not_the_rows_place() -> None:
    """첫 규칙 대조의 헛걸림 모양 — 저장소 설명 속 홈페이지 · ChatGPT 답의 출처 여럿 · 레딧 댓글 인용 · 문서 예시 주소."""
    steps = [_step("browser_open", "https://code.example.com/trending/python", url="https://code.example.com/trending/python")]
    rows = [
        [3, "team/cli-anything", "53,266", "\"CLI-Anything\" -- CLI-Hub: https://clianything.example.cc/"],
        ["ChatGPT", 1, "What local agent?", "아니오", "https://ollama.example.com/blog, https://aider.example.chat/docs/"],
        ["`X-User-Pic`", "프로필 사진 주소", "\"Filled with the picture URL (for example, https://example.com/photo.jpg).\""],
    ]
    assert rows_about_unopened_places(rows, visited_places(steps))["rows"] == []
    assert address_cell("[바로가기](https://jobs.example.com/view/72584)") == "https://jobs.example.com/view/72584"
    assert address_cell("**https://jobs.example.com/view/1**") == "https://jobs.example.com/view/1"
    assert address_cell("https://a.example.com, https://b.example.com") == ""


def test_a_run_that_opened_nothing_is_not_checked() -> None:
    """「방금 정리한 것을 엑셀로」 — 앞 판이 연 곳을 이 판은 모른다(첫 규칙 대조의 헛걸림 6판)."""
    rows = [["MBC 뉴스", "https://imnews.example.com/article/1", "10/16 06:02", "코스피 폭락"]]
    steps = [_write("뉴스.xlsx", {"뉴스": [["제목", "주소", "시각", "요지"], rows[0]]})]
    assert visited_places(steps) == set()
    assert rows_about_unopened_places(rows, visited_places(steps))["rows"] == []


def test_an_open_that_was_redirected_counts_as_opening_the_asked_place() -> None:
    steps = [_step("browser_open", "https://www.newplace.example.org/home", url="https://oldplace.example.org")]
    rows = [["옛 이름", "https://oldplace.example.org", "매주", "개발자"]]
    assert rows_about_unopened_places(rows, visited_places(steps))["rows"] == []


# ── 판 하나를 끝까지 돌려 본다: 답 끝의 한 줄과 판 기록 ─────────────────────────────────────────────


class _Tools:
    names = {"browser_open", "browser_extract", "local_write_document"}
    ollama_tools = [
        {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}}}
        for name in sorted(names)
    ]


class _Gateway:
    def __init__(self, out: Path) -> None:
        self.out = out

    def execute(self, name, arguments, *, job_id=""):
        if name == "browser_open":
            url = str(arguments.get("url") or "")
            return ToolResult(True, name, result={"url": url, "title": "데일리AI", "action": "opened"})
        if name == "browser_extract":
            return ToolResult(True, name, result={"url": "https://www.dailyai.example.kr/", "title": "데일리AI",
                                                  "text": "데일리AI 오늘의 AI 소식 (2026.10.23) 매일 업데이트", "char_count": 30})
        if name == "local_write_document":
            from alture_jarvis.documents import write_document

            target = self.out / str(arguments.get("path") or "out.xlsx")
            shape = write_document(target, "xlsx", dict(arguments))
            return ToolResult(True, name, result={"action": "local_write_document", "output_path": str(target),
                                                  "format": "xlsx", "verified": True, **shape})
        return ToolResult(False, name, error="unknown_tool")


class _Model:
    def __init__(self, sheets: dict) -> None:
        self.calls = 0
        self.sheets = sheets

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        script = [
            ("browser_open", {"url": "https://www.dailyai.example.kr"}),
            ("browser_extract", {}),
            ("local_write_document", {"format": "xlsx", "path": "큐레이션.xlsx", "sheets": self.sheets}),
        ]
        if self.calls <= len(script):
            name, arguments = script[self.calls - 1]
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}
        return {"role": "assistant", "content": "엑셀 파일을 만들었습니다. 데일리AI 는 직접 열어 확인했고, 영어 곳은 소개 글에서 옮겼습니다."}


def test_a_whole_run_ends_with_the_note_and_records_the_rows(tmp_path) -> None:
    sheets = {
        "한국어": [HEAD, ["데일리AI", "https://www.dailyai.example.kr", "한국어", "매일", "업계·일반인", "예", "오늘의 AI 소식 (2026.10.23)"]],
        "영어": [HEAD, ["Brief AI", "https://brief.example.tech/ai", "영어", "매일", "일반인·직장인", "예", "확인 불가 (직접 열지 못함)"]],
    }
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    agent = BrowserAgent(config, _Model(sheets), _Gateway(tmp_path), FakeBrowser(), _Tools(), store, EventBus())
    prompt = "AI 뉴스레터를 곳마다 직접 열어 보고 이름 · 주소 · 얼마나 자주를 엑셀로 정리해 줘."
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()

    result = agent.run(prompt, job_id=job["id"], origin="chat")

    assert "이번에 열어 보지 않은 곳의 줄 1개에 값이 채워져 있습니다" in result.answer, result.answer
    assert "「Brief AI」(brief.example.tech)" in result.answer
    assert "데일리AI」(" not in result.answer, "연 곳의 줄까지 걸었다"
    recorded = result.verification["unopened_place_rows"]
    assert [row["name"] for row in recorded] == ["Brief AI"] and recorded[0]["unknown"] == 1


def test_repositories_opened_without_reading_their_body_are_opened_places() -> None:
    """운영 판 e9098192(10-24 · 깃허브 영상 도구 11개)의 모양 — 다섯 저장소는 `browser_open` 이 성공하고 화면 보기만 했다(본문 읽기 없음).
    이 검사의 물음은 「그 곳을 열었나」다 — 열었으면 연 곳이다(본문까지 읽었는지는 이름 검사 · 읽기 개수가 따로 본다)."""
    steps = []
    rows = []
    for repo in ("siddharthvaddem/openscreen", "Anil-matcha/Open-Generative-AI", "HBAI-Ltd/Toonflow-app"):
        url = "https://github.com/" + repo
        steps += [_step("browser_open", url, url=url), {"tool": "browser_snapshot", "ok": True, "error": "", "arguments": {"limit": 30},
                                                         "evidence": {"url": url}, "evidence_record": {"source_id": url, "type": "listing"}}]
        rows.append([repo.split("/")[1], url, "19,060", "2026-10-23", "AI 영상 제작", "확인 불가"])
    found = rows_about_unopened_places(rows, visited_places(steps))
    assert found["rows"] == [] and found["opened_rows"] == 3
