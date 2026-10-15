"""붙여넣은 글의 숫자는 시킨 개수가 아니다 · 화면의 폼에 넣는 것은 파일 만들기가 아니다 (2026-10-07 대표 실사용).

사람이 자기 글(자기소개서·경력기술서)을 붙여넣고 고쳐 달라고 했다. 본문의 「9개 분관」에서 「9개 이상 직접
열어 읽기」가 뽑혔고, 하네스는 폼 화면에서 「목록 말고 본문을 읽어라」고 되받았다. 모델은 그 말에 대답하느라 일을 놓쳤다.
「초안 … 폼 넣어주라」는 「파일 만들기」가 돼, 모델이 「워드 파일부터 만들겠습니다」로 빠졌다.

운영 요청 1,643개에 옛·새 판정을 나란히 돌려 달라지는 것은 6개였다 — 위 세 판과, 붙여넣은 기록·긴 말의 숫자 셋.
"""

from __future__ import annotations

from alture_jarvis.plan import extract, wants_an_artifact

#: 붙여넣은 자기소개서(지어낸 글) — 진술 문장 안에 「9개」가 있다.
ESSAY = (
    "1. 지원동기: 도서관 장서를 맡아 온 실무자로서 귀 기관의 자료 관리에 보탬이 되고자 지원했습니다. 저는 지난 직장에서 "
    "서가의 상태를 매주 점검했고, 분류가 잘못된 책을 대출 전에 찾아내 바로잡았습니다. 2. 협업: 저는 본관에서 "
    "9개 분관의 대출 현황을 월간 자료로 만들어 사서들이 자기 서가의 흐름을 한눈에 파악하도록 지원했습니다. "
    "그 결과 반납 독촉 시기를 놓치는 일이 줄었고, 정기 점검에서도 지적 없이 마쳤습니다. 3. 포부: 맡은 일을 끝까지 "
    "책임지는 담당자가 되겠습니다. 규정 안에서 이용자가 불편하지 않은 길을 찾는 사람이 되겠습니다. "
    "입사 뒤에는 분관 담당자들과 먼저 만나 지금의 정리 방식에서 불편한 점을 듣고 그것부터 고치겠습니다."
)


def _kinds(prompt: str, **kwargs) -> list[tuple[str, str]]:
    return [(item.kind, item.label) for item in extract(prompt, **kwargs)]


def test_a_number_inside_a_pasted_essay_is_not_a_reading_quota() -> None:
    prompt = ESSAY + "\n\n이거 각 항목마다 700자 이상 900자 미만으로 써주라"

    assert not [kind for kind, _label in _kinds(prompt, must_observe=True) if kind == "count"]


def test_a_pasted_text_with_no_request_at_all_makes_no_quota() -> None:
    """붙여넣기만 한 판(앞 질문의 답으로 자기 글을 준 것)."""
    assert not [kind for kind, _label in _kinds(ESSAY, must_observe=True) if kind == "count"]


def test_a_count_the_person_actually_asked_for_survives_a_long_prompt() -> None:
    asked = [
        ESSAY + " 이 가운데 참고할 공고 3개를 골라줘",                     # 요청 동사에 바로 붙음
        ESSAY + " 그리고 참고할 채용 공고를 최소 4개 읽고 반영해",            # 「최소」
        ESSAY + " 이 과정을 아래 3권에 대해 각각 반복해줘: 가, 나, 다",       # 그 문장이 「…줘」로 끝남
        ESSAY + " 아래 로컬 문서 3개를 각각 직접 읽어라.",                  # 「…어라」
    ]
    for prompt in asked:
        counts = [label for kind, label in _kinds(prompt, must_observe=True) if kind == "count"]
        assert counts, prompt[-40:]
        assert not any("9개" in label for label in counts), "시킨 개수는 본문의 9 가 아니다"


def test_short_requests_are_untouched() -> None:
    assert ("count", "3개 이상 직접 열어 읽기") in _kinds("사람인에서 회계 공고 3개 읽고 알려줘", has_named_source=True)


def test_putting_text_into_a_page_form_is_not_making_a_file() -> None:
    assert wants_an_artifact("그래 들어가서 아까 만든 소개 글 초안 그거 이제 폼 넣어주라") is False
    assert wants_an_artifact("이 초안을 이력서 입력란에 붙여넣어줘") is False


def test_putting_things_into_a_file_is_still_an_artifact() -> None:
    assert wants_an_artifact("조사한 내용을 엑셀에 넣어줘") is True
    assert wants_an_artifact("보고서에 각주 달아줘") is True
    assert wants_an_artifact("이 초안을 폼에 넣고, 워드 문서로도 만들어줘") is True


# ── 다른 사이트의 「임시저장」은 그 사이트의 단추다 (폼 벤치가 찾음) ──────────────


def test_saving_a_draft_on_another_site_is_not_the_blog_action() -> None:
    prompt = "http://127.0.0.2:8765/resume/edit 의 「경력기술서」 칸에 아래 내용을 넣고 임시저장해줘. 제출하기는 누르지 마."

    assert not [label for kind, label in _kinds(prompt, has_named_source=True) if kind == "action"]


def test_saving_a_blog_draft_is_still_the_blog_action() -> None:
    assert ("action", "임시저장") in _kinds("네이버 블로그에 글 쓰고 임시저장해줘", has_named_source=True)
    assert ("action", "임시저장") in _kinds("임시저장해주라")  # 블로그 대화에 이어서 한 말 — 그대로다
    assert ("action", "임시저장") in _kinds("https://blog.naver.com/GoBlogWrite.naver 에서 임시저장해줘", has_named_source=True)
