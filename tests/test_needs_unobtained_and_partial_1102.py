# -*- coding: utf-8 -*-
"""2026-11-02: 「못 얻었다」는 말과 일부만 찬 칸을 「채웠다(met=True)」로 세던 것.

대표 PC 판 둘이 근거다 — 유튜브 쇼츠 조사(7356c221) · 11-07 행사 조사(31f78a75).
"""
from alture_jarvis.outbound import check_needs
from alture_jarvis import delegation


def _met(needs, answer):
    return {item["label"]: item for item in check_needs(needs, answer)}


def test_korean_could_not_read_line_is_not_filled():
    answer = "- **해시태그**: Shorts 페이지에서 설명란(#태그 포함)이 화면에 렌더링되지 않아 읽을 수 없었습니다.\n"
    item = _met(["해시태그"], answer)["해시태그"]
    assert item["met"] is None and "읽을 수 없었" in item["negative"]


def test_heading_with_cannot_confirm_body_is_not_filled():
    answer = "## 자주 쓰는 해시태그\n**확인 불가** — Shorts 페이지에서 설명란·해시태그를 읽을 수 없었습니다.\n"
    item = _met(["자주 쓰는 해시태그"], answer)["자주 쓰는 해시태그"]
    assert item["met"] is None and item["negative"]


def test_bold_lead_with_failure_in_first_sentence_is_not_filled():
    answer = "- **주최·사전등록 마감·입장료·공식 주소** — 위 8건 모두 개별 공식 페이지를 직접 열지 못해 확인 불가로 표시했습니다.\n"
    assert _met(["공식 주소"], answer)["공식 주소"]["met"] is None


def test_table_cells_saying_cannot_confirm_are_not_filled():
    answer = "| 이름 | 배너 바탕 |\n|---|---|\n| 가 | 확인 불가 |\n| 나 | 확인 불가 |\n"
    assert _met(["배너 바탕"], answer)["배너 바탕"]["met"] is None


def test_column_filled_in_some_rows_only_is_partial():
    answer = ("| 제목 | 채널 이름 |\n|---|---|\n| a | 채널1 |\n| b | 채널2 |\n| c |  |\n| d |  |\n| e |  |\n\n"
              "- **채널 이름**: 15개 중 2개만 쇼츠 페이지를 직접 열어 확인했습니다.\n")
    item = _met(["채널 이름", "제목"], answer)
    assert item["채널 이름"]["met"] is None and item["채널 이름"]["partial"] == "2/5"
    assert item["제목"]["met"] is True


# ── 진짜 답을 실패로 보지 않는다(옛 · 새 대조에서 잘못 바뀐 셋) ──

def test_plain_none_is_an_answer():
    answer = "| 도구 | 미리 색인 여부 |\n|---|---|\n| A | 없음 — 코드베이스 색인은 없고 컨텍스트 파일만 읽는다 |\n"
    assert _met(["미리 색인 여부"], answer)["미리 색인 여부"]["met"] is True


def test_only_first_sentence_decides():
    answer = "- **자막을 열었는지**: 열었다. 0:00~16:09 자막을 읽었고 16분 이후 부분은 읽지 못했다.\n"
    assert _met(["자막을 열었는지"], answer)["자막을 열었는지"]["met"] is True


def test_caveat_in_brackets_does_not_unfill():
    answer = "- **가격**: 12,000원 (재고 확인 불가)\n"
    assert _met(["가격"], answer)["가격"]["met"] is True


def test_notes_name_partial_and_said_not_separately():
    answer = ("| 제목 | 채널 이름 |\n|---|---|\n| a | 채널1 |\n| b |  |\n\n"
              "- **해시태그**: 설명란이 보이지 않아 읽을 수 없었습니다.\n")
    job = {"id": "t1102", "status": "completed",
           "payload": {"needs": ["채널 이름", "해시태그", "구독자 수"]},
           "result": {"answer": answer, "agent_trace": {"steps": [{"tool": "browser_extract", "ok": True}], "tool_numbers": ["1", "2"]}}}
    text = " ".join(str(v) for v in delegation.summarize_job(job).values())
    assert "일부 줄만 채운 항목: 채널 이름(1/2)" in text
    assert "얻지 못했다」고 적은 항목: 해시태그" in text
    # 자리를 못 찾은 것만 「확인하지 못한 항목」이다 — 위 둘이 거기 섞이면 거꾸로 말하는 것이다.
    unchecked = [part for part in text.split("—") if "확인하지 못한 항목" in part]
    assert unchecked and "구독자 수" in unchecked[0] and "해시태그" not in unchecked[0] and "채널 이름" not in unchecked[0]


def test_could_not_do_it_in_any_verb_is_not_filled():
    # 11-02 27B 시험 3판(2c6406a1): 「설치하지 못했습니다」가 채움이었다 — 「읽·찾·열·보지 못」만 있었다.
    answer = "## ③ 명사.txt 내용\n\nsandbox_run에서 kiwipiepy를 설치하지 못했습니다(의존성 충돌). 실제 결과를 드릴 수 없습니다.\n"
    assert _met(["명사.txt 내용"], answer)["명사.txt 내용"]["met"] is None
    assert _met(["보증금"], "- **보증금**: 가격대 필터를 설정하지 못했습니다.\n")["보증금"]["met"] is None
