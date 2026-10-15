"""사람이 「하나하나 열 필요 없다」고 한 과제 — 이름표·안내·줄 수·경고가 같은 말을 한다 (2026-10-04 레딧 기준선 판 92b3776a).

엑셀 25줄을 제대로 낸 판이 「부분 완료」로 찍히고 답에 헛경고 셋이 붙었다:
- 대조표가 「25개 이상 **직접 열어 읽기**」라 모델이 판 내내 「열어라」를 들었다(답에 「시스템이 본문 읽기를 요구했다」고 적었다).
- 엑셀을 상자로 만들어서 표의 줄 수가 안 세어졌다(「답에 5개」).
- 「25개 중 3개만 열어 읽었습니다」 · 「읽지 않고 적은 것: 댓글 수, 추천 수」(칸 이름).

좁게 고친다 — 「표로 정리」뿐인 과제(사람인 공고의 자격 요건, YES24 의 쪽수·ISBN)는 상세를 열어야 답이 나온다.
그런 과제의 이름표·경고는 **그대로**다.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from alture_jarvis import agent, plan

LIST_ONLY = (
    "레딧 r/LocalLLM 게시판의 글 목록에서 글 25개의 제목 · 댓글 수 · 추천 수를 엑셀 파일 「기준선.xlsx」로 정리해줘. "
    "글을 하나하나 열 필요는 없고 목록에 보이는 숫자만 적어."
)
NEEDS_DETAIL = "사람인에서 여수 지역 회계 채용 공고 3개를 찾아, 각 공고의 회사명·마감일·자격 요건을 비교표로 정리한 엑셀 파일을 만들어줘."


def _count(prompt: str) -> plan.Requirement:
    return next(req for req in plan.extract(prompt) if req.kind == "count")


def test_the_label_follows_what_the_person_said() -> None:
    said = _count(LIST_ONLY)
    assert said.label == "25개 이상 목록으로 담기" and said.list_only is True


def test_a_table_request_that_needs_details_keeps_the_open_and_read_label() -> None:
    """「표로 정리」만으로 가르면 안 된다 — 자격 요건·쪽수·ISBN 은 상세를 열어야 나온다(교보·사람인 3/3 의 배선)."""
    for prompt in (NEEDS_DETAIL, "YES24 사이트에서 파이썬 책 2권을 찾아 쪽수와 ISBN 을 확인해 표로 정리해줘."):
        req = _count(prompt)
        assert req.label.endswith("직접 열어 읽기"), prompt
        assert req.list_only is False, prompt


def test_reading_asked_in_the_same_breath_wins() -> None:
    assert not plan.says_list_only("목록에 보이는 숫자만 적어. 다만 상위 3개는 본문을 열어서 읽고 요약해줘")


def test_the_next_step_hint_says_list_not_open() -> None:
    unmet = [(_count(LIST_ONLY), False, "0개 읽음")]
    assert agent._next_plan_step_hint(unmet) == agent._LIST_IS_THE_ANSWER_HINT
    assert "열어 읽을 필요가 없다" in agent._LIST_IS_THE_ANSWER_HINT
    # 상세가 필요한 과제는 예전 그대로 「본문을 열어라」.
    assert agent._next_plan_step_hint([(_count(NEEDS_DETAIL), False, "0개 읽음")]) != agent._LIST_IS_THE_ANSWER_HINT


def test_rows_in_a_file_made_some_other_way_are_counted(tmp_path: Path) -> None:
    from openpyxl import Workbook

    made = tmp_path / "기준선.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(["순위", "제목", "댓글 수"])
    for index in range(25):
        sheet.append([index + 1, f"글 {index}", index])
    book.save(made)
    table = tmp_path / "t.csv"
    table.write_text("a,b\n1,2\n3,4\n\n", encoding="utf-8")

    assert plan._rows_in_file(made) == 25
    assert plan._rows_in_file(table) == 2
    assert plan._rows_in_file(tmp_path / "없음.xlsx") == 0
    assert plan._rows_in_file(tmp_path / "t.txt") == 0  # 표 파일이 아니다
    # 대조는 걸음마다 돈다 — 같은 파일을 매번 다시 열지 않는다.
    assert any(key[0] == str(made) for key in plan._ROWS_IN_FILE_CACHE)
    assert "_rows_in_file(path)" in inspect.getsource(plan._rows_written)


def test_the_short_read_warning_is_dropped_only_for_list_only_requests() -> None:
    source = inspect.getsource(agent)
    assert 'if item.kind == "count" and not getattr(item, "list_only", False)' in source


def test_a_table_about_the_requested_columns_is_not_a_list_of_names() -> None:
    assert {"요청 항목", "요청항목", "requested item"} <= agent.BrowserAgent._FIELD_LABEL_HEADERS


def test_the_english_labels_exist() -> None:
    from alture_jarvis import ui_i18n

    assert ui_i18n._MANUAL["{0}개 이상 목록으로 담기"] == "List at least {0} items"


# --- 말줄임표로 줄여 적은 이름 (de3228ec) ---------------------------------------

def test_a_title_shortened_with_an_ellipsis_counts_as_read_when_its_pieces_were() -> None:
    """25줄을 다 맞게 낸 답이 긴 제목을 「…」로 줄여 적었고, 그 다섯에 「읽지 않고 적은 것」 경고가 붙었다."""
    noise = agent.BrowserAgent._ENTITY_NOISE
    source = noise.sub("", "1. 「Tesla V100 32GB, RTX3090 and a 4060 for a home lab」 · 댓글 2  2. 「live-vibe: a full-duplex voice Mod for Claude Code」")

    assert agent._shortened_name_was_read(noise.sub("", "Tesla V100 32GB, RTX3090…"), source)
    assert agent._shortened_name_was_read(noise.sub("", "live-vibe: … voice Mod for Claude Code"), source)
    assert agent._shortened_name_was_read(noise.sub("", "Tesla V100 32GB..."), source)


def test_a_shortened_name_with_a_piece_that_was_never_read_still_warns() -> None:
    noise = agent.BrowserAgent._ENTITY_NOISE
    source = noise.sub("", "「Tesla V100 32GB, RTX3090 and a 4060 for a home lab」")

    assert not agent._shortened_name_was_read(noise.sub("", "Tesla V100 32GB… benchmark on M4 Max"), source)  # 뒷조각이 없다
    assert not agent._shortened_name_was_read(noise.sub("", "Totally Invented Product…"), source)
    assert not agent._shortened_name_was_read(noise.sub("", "A…"), source)          # 조각이 너무 짧다 — 판정하지 않는다
    assert not agent._shortened_name_was_read("TeslaV10032GB", source[:5])           # 말줄임표가 없으면 이 길이 아니다
    assert "and not _shortened_name_was_read(name, flat)" in inspect.getsource(agent)
