"""「미리보기로 보여 줘」는 요구다, 「…지는 마」는 금지다 (2026-09-23 스토어 촬영에서 발견)."""

from __future__ import annotations

from alture_jarvis.plan import extract


def _actions(prompt: str) -> list[str]:
    return [str(r.target) for r in extract(prompt) if r.kind == "action"]


def test_asking_to_preview_a_built_page_is_a_requirement() -> None:
    prompt = ("이 폴더에 할 일 목록 웹페이지를 index.html 하나로 만들어 줘. 할 일 추가, 완료 체크, 삭제가 되고, "
              "깔끔한 카드 디자인이면 좋겠어. 다 만들면 미리보기로 보여 줘.")
    assert "local_preview_page" in _actions(prompt), "미리보기를 시켰는데 「시킨 것」에 없으면 안 띄우고 끝나도 다 된 것처럼 보인다"


def test_preview_outside_a_web_page_is_not_demanded() -> None:
    """★ 좋은 표본 — 코워크엔 미리보기 도구가 없다. 영원히 못 채우는 요구를 만들지 않는다."""
    assert "local_preview_page" not in _actions("다나와 마우스 3개 비교해서 엑셀로 만들고 미리보기로 보여줘")
    assert "local_preview_page" not in _actions("index.html 로 계산기 페이지 만들어줘")


def test_a_ji_neun_ma_prohibition_is_read_as_a_prohibition() -> None:
    assert "naver_blog_publish" not in _actions("블로그 글 써서 임시저장만 해줘. 발행하지는 마.")
    assert "naver_blog_save_draft" in _actions("블로그 글 써서 임시저장만 해줘. 발행하지는 마.")
    assert "local_preview_page" not in _actions("웹페이지 만들어 줘. 미리보기로 보여주지는 마.")
    assert "google_gmail_send" not in _actions("보고서 만들어서 메일로 보내지 마세요")


def test_a_name_starting_with_ji_ma_is_not_a_prohibition() -> None:
    """★ 좋은 표본 — 「지마켓」의 「지마」는 금지가 아니다."""
    assert "google_gmail_send" in _actions("지마켓에서 마우스 찾아서 메일로 보내줘")


# ── 사람이 내용을 불러준 파일 만들기에는 「읽기」 요구가 없다 (2026-09-23 스토어 촬영) ─────────────────
# 「바탕화면에 회의 메모.txt 만들고 …라고 적어 줘」에 「근거가 되는 대상 실제로 읽기」가 붙어 영원히 미달 → 조사용 재촉 →
# 모델이 시킨 일 대신 재촉에 「지침을 완벽히 이해했습니다」로 답했다.


def _kinds(prompt: str, **kwargs) -> list[str]:
    return [r.kind for r in extract(prompt, **kwargs)]


def test_a_dictated_memo_has_nothing_to_read() -> None:
    prompt = "바탕화면에 '회의 메모.txt' 파일을 만들고, 내일 오전 10시 제품 회의 — 스토어 제출 점검 이라고 적어 줘."
    assert "observe" not in _kinds(prompt, must_observe=True)
    assert "artifact" in _kinds(prompt, must_observe=True)


def test_a_report_to_be_researched_still_has_to_read() -> None:
    """★ 좋은 표본 — 내용을 불러주지 않은 산출물(조사해서 채울 것)은 여전히 읽어야 한다."""
    assert "observe" in _kinds("국내 전기차 충전 요금을 조사해서 워드 보고서로 만들어줘", must_observe=True)


def test_reading_a_source_then_writing_dictated_text_still_reads() -> None:
    """★ 좋은 표본 — 읽을 대상을 댔으면 「…라고 적어」가 있어도 읽기 요구는 남는다."""
    prompt = "회의록.docx 를 읽고 요약해서 memo.txt 를 만들고 맨 위에 '초안'이라고 적어줘"
    assert "observe" in _kinds(prompt, must_observe=True) or "count" in _kinds(prompt, must_observe=True)
