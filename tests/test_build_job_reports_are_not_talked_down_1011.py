"""만드는 일을 잘 해 놓고 마무리 보고에서 스스로 깎아내리지 않는다 (2026-10-11).

대표가 코드 모드에 한 문장으로 맡긴 쇼핑몰 과제 두 판과 검토 한 판에서 나온 것. 결과물은 돌아갔는데(둘러보기 · 상세 · 장바구니
모두 됨) 보고가 틀렸다 — 답은 맞고 하네스가 틀린 종류다.

  b897ea34  답이 「검토: 문제 없음」 한 줄 — 검토 걸음이 임시 파일 하나를 지웠다고 쥔 답을 버렸다
            「도구가 준 적 없는 숫자 44개」 — 손자리가 쓴 CSS 의 글자 크기·여백이었다
  e936d144  「읽지 않고 적은 것이 있습니다: styles.css, shop.js」 — 자기가 방금 만든 파일이다
            「만든·고친 파일: index.html, index.html, index.html …」
  e691c1c5  이 PC 의 파일만 읽고 쓴 검토 답의 소제목 셋이 「읽지 않고 적은 것」으로 찍힘

같은 판에서 **맞았던** 판정 하나는 그대로 둔다: 마지막으로 고친 뒤 페이지를 열어 보기만 하고(누르지 않고) 끝난 판에
「확인하지 못한 채 끝났다」고 한 것 — 그 뒤 실제로 눈에 보이는 결함이 남아 있었다.
"""
from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent, _answer_after_code_review
from alture_jarvis.answer_gate import _code_unverified_head
from alture_jarvis.code_runtime import code_verification_is_current
from alture_jarvis.delegation import summarize_job

HELD = "완성했습니다. index.html · style.css · app.js 세 파일로 가게 사이트를 만들었고, 상품을 눌러 장바구니에 담는 것까지 확인했습니다."


# --- 1. 검토가 할 말이 없으면 쥔 답을 낸다 ----------------------------------------

def test_a_review_that_only_says_no_problem_keeps_the_held_answer_even_if_the_folder_changed() -> None:
    assert _answer_after_code_review(HELD, "검토: 문제 없음", changed=True) == HELD
    assert _answer_after_code_review(HELD, "검토: 문제 없음.", changed=True) == HELD


def test_a_review_that_wrote_something_new_still_wins_when_the_folder_changed() -> None:
    new = "빈 장바구니 처리를 추가했고 다시 눌러 확인했습니다."
    assert _answer_after_code_review(HELD, new, changed=True) == new
    assert _answer_after_code_review(HELD, "검토: 문제 없음\n\n" + new, changed=True) == new


def test_with_nothing_held_the_review_line_is_all_there_is() -> None:
    assert _answer_after_code_review("", "검토: 문제 없음", changed=True) == "검토: 문제 없음"


# --- 2. 코드를 만드는 일에서 쓴 코드의 숫자는 주장이 아니다 -------------------------

def _build_job(answer: str, css: str, *, code: bool, tool_numbers: list[str] | None = None) -> dict[str, Any]:
    steps = [
        {"tool": "local_write_file", "ok": True, "arguments": {"path": "style.css", "content": css},
         "evidence": {"output_path": "C:/work/shop/style.css"},
         "evidence_record": {"effect": "write_local", "source_id": "c:/work/shop/style.css"}},
        {"tool": "browser_read", "ok": True, "evidence": {},
         "evidence_record": {"effect": "read_web", "source_id": "http://127.0.0.1:5173/index.html"}},
    ]
    payload = {"prompt": "디저트 가게 사이트를 만들어 줘", **({"workspace_mode": "code", "code_workspace": "C:/work/shop"} if code else {})}
    return {"id": "j1", "status": "completed", "payload": payload,
            "result": {"answer": answer, "completion_state": "complete",
                       "agent_trace": {"steps": steps, "tool_numbers": tool_numbers or [], "tool_numbers_body": []}}}


CSS = "body { line-height: 1.65; max-width: 1080px; padding: 24px 18px; } h1 { font-size: 2.4rem; letter-spacing: 0.02em; }"


def test_numbers_in_code_a_build_job_wrote_are_not_unsupported() -> None:
    summary = summarize_job(_build_job("사이트를 만들었습니다.", CSS, code=True))

    assert summary["unsupported_numbers"] == [] and summary["status"] == "done"


def test_what_the_job_wrote_supports_what_the_answer_says_about_it() -> None:
    summary = summarize_job(_build_job("본문 폭은 1080px, 줄 높이는 1.65 로 잡았습니다.", CSS, code=True))

    assert summary["unsupported_numbers"] == []


def test_a_build_job_answer_still_cannot_invent_a_number() -> None:
    summary = summarize_job(_build_job("방문자가 하루 4200명인 가게 사이트를 만들었습니다.", CSS, code=True))

    assert summary["unsupported_numbers"] == ["4200"] and summary["status"] == "needs_review"


def test_outside_code_jobs_written_numbers_are_checked_as_before() -> None:
    summary = summarize_job(_build_job("정리했습니다.", "연봉 9900만원", code=False))

    assert summary["unsupported_numbers"] == ["9900"]


# --- 3. 자기가 만든 파일 · 자기가 단 소제목은 「읽지 않고 적은 것」이 아니다 -----------

_READ_INDEX = [{"role": "tool", "tool_name": "local_read_text_file", "content": "<html><body><h1>달다</h1><main id='top'></main></body></html>"}]


def _ledger(*rows: tuple[str, str, str]) -> list[dict[str, Any]]:
    return [{"type": kind, "effect": effect, "ok": True, "source_id": source} for kind, effect, source in rows]


def test_files_this_job_wrote_are_not_reported_as_unread() -> None:
    answer = (
        "완성했습니다.\n\n## 만든 것\n| 파일 | 내용 |\n|---|---|\n"
        "| `index.html` | 페이지 구조 |\n| `styles.css` | 배색과 글꼴 |\n| `shop.js` | 상품 데이터와 장바구니 |\n"
    )
    ledger = _ledger(
        ("body_read", "read_local", r"C:\work\shop\index.html"),
        ("artifact", "write_local", r"C:\work\shop\styles.css"),
        ("mutation", "write_local", r"C:\work\shop\shop.js"),
    )

    assert BrowserAgent._listed_entity_grounding_check(answer, _READ_INDEX, ledger=ledger) == ""


def test_headings_of_a_review_that_read_only_local_files_are_not_names() -> None:
    answer = (
        "**디자인에서 이상한 곳:**\n\n"
        "1. **품절 배지가 제자리에 안 뜸**\n   - 부모 칸에 기준 줄이 없습니다.\n\n"
        "2. **닫힌 장바구니가 초점을 받음**\n   - 화면 밖으로만 밀려 있습니다.\n\n"
        "3. **그 외는 일관성 있음**\n"
    )
    ledger = _ledger(("body_read", "read_local", r"C:\work\shop\index.html"))

    assert BrowserAgent._listed_entity_grounding_check(answer, _READ_INDEX, ledger=ledger) == ""


def test_the_same_headings_are_checked_when_a_web_listing_was_seen() -> None:
    """웹 목록을 본 판에서는 굵은 번호 줄이 옮겨 적은 이름일 수 있다 — 예전 그대로 본다."""
    answer = "1. **도담스페이스**\n\n2. **바름터**\n"
    messages = [{"role": "tool", "tool_name": "browser_extract", "content": "코드나루 채용 공고 본문. 근무지는 서울입니다."}]
    ledger = _ledger(("listing", "read_web", "https://jobs.example.com/list"), ("body_read", "read_web", "https://jobs.example.com/a"))

    said = BrowserAgent._listed_entity_grounding_check(answer, messages, ledger=ledger)

    assert "도담스페이스" in said and "바름터" in said


# --- 4. 같은 파일 이름을 되풀이하지 않는다 -----------------------------------------

def test_the_unverified_line_names_each_file_once() -> None:
    line = _code_unverified_head({"mutated": True}, ["C:/w/index.html"] * 6 + ["C:/w/styles.css", "C:/w/shop.js"])

    assert line.count("index.html") == 1 and "styles.css" in line and "shop.js" in line and "외" not in line


# --- 그대로 두는 판정 --------------------------------------------------------------

def test_looking_without_touching_after_the_last_edit_is_still_not_a_check() -> None:
    """둘째 판의 끝: 고친 뒤 페이지를 열어 읽기만 했다. 그 판에는 실제로 결함이 남아 있었다 — 이 판정은 맞았다."""
    def step(tool: str, **evidence: Any) -> dict[str, Any]:
        return {"tool": tool, "ok": True, "evidence": evidence, "arguments": {}}

    url = "http://127.0.0.1:54513/index.html"
    steps = [
        step("local_write_file", output_path="C:/w/index.html", created=True),
        step("browser_open", url=url), step("browser_click", url=url), step("browser_read", url=url),
        step("local_apply_edit", output_path="C:/w/styles.css"),
        step("browser_open", url=url), step("browser_read", url=url),
    ]

    assert code_verification_is_current(steps[:4]) is True
    assert code_verification_is_current(steps) is False


def test_files_the_job_neither_read_nor_wrote_are_still_reported() -> None:
    """쓴 파일을 아는 것으로 쳐도, 읽지도 쓰지도 않은 파일을 설명한 줄은 그대로 잡힌다."""
    answer = (
        "## 파일 구성\n| 파일 | 내용 |\n|---|---|\n"
        "| `index.html` | 페이지 구조 |\n| `checkout.php` | 결제 처리 |\n| `admin.php` | 관리자 화면 |\n"
    )
    ledger = _ledger(
        ("body_read", "read_local", r"C:\work\shop\index.html"),
        ("artifact", "write_local", r"C:\work\shop\styles.css"),
    )

    said = BrowserAgent._listed_entity_grounding_check(answer, _READ_INDEX, ledger=ledger)

    assert "checkout.php" in said and "admin.php" in said and "index.html" not in said
