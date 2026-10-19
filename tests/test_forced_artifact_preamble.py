"""★ 이어받기 4판이 엑셀을 못 만든 진짜 이유 (2026-09-16 실측).

21걸음을 돌고 표를 완성해 놓고도 파일이 안 나왔다. 계획 층은 「실제 산출물 파일 만들기 —
열 수 있는 산출물 없음」이라고 알고 있었고, 강제 산출물 장치(`_forced_artifact_decision`)도
있었다. 그런데 그 장치가 **`answer_is_a_plan` 으로 물러났다.**

답이 이렇게 생겼기 때문이다:

    「…2개의 공고를 바탕으로 비교표를 작성하겠습니다.」   ← 머리말
    | 회사명 | 마감일 | 자격 요건 |                      ← 진짜 산출물
    | (주)늘봄플러스 | 2026.09.27 | … |

「만들겠다는 예고는 문서가 아니다」를 막으려던 관문이 **예고 + 진짜 표**를 같이 막았다.
막기만 하면 안 된다 — 사고 R 의 교훈 둘째와 같은 자리다.

판별자는 **순서**다. 계획문은 예고로 끝나고, 예고 뒤에 데이터가 든 표가 오면 그 예고는
머리말이다. 이 파일은 그 선을 양쪽으로 못 박는다.
"""

from __future__ import annotations

from alture_jarvis.agent import _forced_artifact_decision


class _Artifact:
    kind = "artifact"
    label = "실제 산출물 파일 만들기"


UNMET = [(_Artifact(), False, "열 수 있는 산출물 없음")]
XLSX_PROMPT = "사람인에서 여수 회계 채용 공고 3개를 찾아서 회사·마감일·자격 요건 비교표를 엑셀로 만들어줘"

PREAMBLE_THEN_TABLE = """사용자의 요청에 따라, 실제로 본문을 읽는 데 성공한 2개의 공고를 바탕으로 비교표를 작성하겠습니다.

**여수 회계 채용 공고 비교표**

| 회사명 | 마감일 | 자격 요건 |
| :--- | :--- | :--- |
| (주)늘봄플러스 | 2026.09.27 | 경력 5~15년, 회계학/경영학/경제학 전공자, 해외근무 가능자 |
| 푸른캡(주) | 2026.09.24 | 경력 5년 이상, 제조업 재무/회계 관리 경험자, 운전면허 소지자 |

**조사 결과 요약:**
* **성공한 읽기:** 총 2건
* **미달 사유:** 브라우저 오류로 세 번째 공고 본문을 읽지 못했습니다.
"""

PLAN_ONLY = """사람인에서 검색된 여수 지역 회계 채용 공고 2곳의 요건을 분석했습니다.

### 1. 분석한 채용 공고 요건

- **경력직 지원 시:** 경력 3년 이상 요건에 맞춰 과거 경력을 수치 중심으로 기술합니다.
- **신입 지원 시:** 자격증과 꼼꼼한 문서 관리 능력을 중심으로 작성합니다.

이 내용을 바탕으로 두 곳 모두에 활용할 수 있는 비교표를 작성하겠습니다.
"""


def test_a_preamble_before_a_real_table_no_longer_blocks_the_file() -> None:
    """★ 고친 것 — 예고 뒤에 데이터 표가 오면 그 예고는 머리말이다."""
    call, reason = _forced_artifact_decision(UNMET, [], PREAMBLE_THEN_TABLE, XLSX_PROMPT)

    assert reason == ""
    assert call is not None
    tool, args = call
    assert tool == "local_write_document"
    assert args["path"].endswith(".xlsx"), "엑셀을 시켰으면 엑셀이어야 한다"


def test_the_preamble_does_not_end_up_inside_the_file() -> None:
    """산출물에 「작성하겠습니다」가 남으면 안 된다 — 사람이 받는 것은 그 파일이다."""
    call, _reason = _forced_artifact_decision(UNMET, [], PREAMBLE_THEN_TABLE, XLSX_PROMPT)
    texts = [str(b.get("text") or "") for b in call[1]["blocks"] if b.get("type") != "table"]

    assert not any("작성하겠습니다" in text for text in texts)


def test_the_file_is_named_after_the_content_not_the_preamble() -> None:
    """예전엔 `사용자의_요청에_따라_실제로_본문을_읽는_데_성공한….xlsx` 가 나왔다(실측).

    2026-10-19 부터 이름은 답이 아니라 **시킨 글**에서 짓는다(`artifact_name_from_task` · 판 bb5ab643) — 시킨 글의 목적어
    「회사·마감일·자격 요건 비교표를」. 문서 안의 제목은 답의 표제 그대로다.
    """
    call, _reason = _forced_artifact_decision(UNMET, [], PREAMBLE_THEN_TABLE, XLSX_PROMPT)

    assert call[1]["path"] == "회사_마감일_자격_요건_비교표.xlsx"
    assert str(call[1]["blocks"][0].get("text") or "") == "여수 회계 채용 공고 비교표"


def test_the_title_is_not_repeated_as_a_paragraph() -> None:
    call, _reason = _forced_artifact_decision(UNMET, [], PREAMBLE_THEN_TABLE, XLSX_PROMPT)
    blocks = call[1]["blocks"]
    title = str(blocks[0].get("text") or "").strip(" *")

    repeats = [b for b in blocks[1:]
               if b.get("type") != "table" and str(b.get("text") or "").strip(" *") == title]
    assert repeats == []


def test_our_own_checklist_never_reaches_the_deliverable() -> None:
    """★ 답 끝에 **우리가** 붙인 대조표가 엑셀 안에 들어갔다(실측)."""
    answer = PREAMBLE_THEN_TABLE + "\n\n**시킨 것 대조**\n- ❌ 3개 이상 직접 열어 읽기 — 2개 읽음\n- ✅ 사람인에서 하기 — 1건\n"
    call, reason = _forced_artifact_decision(UNMET, [], answer, XLSX_PROMPT)

    assert reason == ""
    texts = " ".join(str(b.get("text") or "") for b in call[1]["blocks"])
    assert "시킨 것 대조" not in texts
    assert "3개 이상 직접 열어 읽기" not in texts


def test_a_plan_that_ends_with_the_promise_is_still_blocked() -> None:
    """막아야 하는 것은 그대로 막혀야 한다 — 예고로 **끝나면** 그건 계획문이다."""
    call, reason = _forced_artifact_decision(UNMET, [], PLAN_ONLY, XLSX_PROMPT)

    assert call is None
    assert reason == "answer_is_a_plan"


def test_a_promise_followed_only_by_a_header_row_is_blocked() -> None:
    """머리글만 있는 표는 산출물이 아니다 — 빈 엑셀은 없는 것보다 나쁘다."""
    answer = PLAN_ONLY.rstrip() + "\n\n| 회사명 | 마감일 |\n| :--- | :--- |\n"
    call, reason = _forced_artifact_decision(UNMET, [], answer, XLSX_PROMPT)

    assert call is None
    assert reason == "answer_is_a_plan"
