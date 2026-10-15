"""낱말 **안에** 든 글자는 출처가 아니다 — 「입문서」의 「문서」 (2026-09-29 밤, AWS 첫 실행).

## 무슨 일이 있었나

크롬 없는 깨끗한 윈도우(AWS)에서 대표가 친 첫 과제:

    YES24에서 파이썬 입문서 3권의 쪽수와 가격을 비교해서 문서로 만들어줘

대조표에 **「로컬 자료 3개 이상 직접 열어 읽기」** 가 떴다. 웹 조사인데 로컬이다.

`plan._scoped_count_targets` 는 「3권」 앞 180자에서 가장 가까운 출처 낱말을 찾는다. 로컬 낱말표에
「문서」가 있고, 「입**문서**」 안에 「문서」가 들어 있다(`rfind` 는 낱말 경계를 안 본다). 「YES24」는
점이 없어 웹 주소 낱말표에도 안 걸렸다. 그래서 가장 가까운 출처가 「입문서」의 「문서」가 됐다.

같은 모양: 설명**서**·교과**서**는 괜찮지만 공**문서**·입**문서**·보고**서** 중 앞의 둘이 걸린다.
「파일」도 프로**파일**에서 같은 일이 난다.

## 고친 것

출처 낱말은 **낱말의 머리**에서만 센다 — 바로 앞 글자가 한글이면 다른 낱말의 속이다.
「내 문서」·「문서 3개」·「로컬 파일」은 그대로 걸린다.
"""
from __future__ import annotations

from alture_jarvis.plan import _scoped_count_targets, extract as extract_plan

PROMPT = "YES24에서 파이썬 입문서 3권의 쪽수와 가격을 비교해서 문서로 만들어줘"


def test_the_night_prompt_is_not_a_local_read() -> None:
    plan = extract_plan(PROMPT, has_named_source=True)
    labels = [req.label for req in plan if req.kind == "count"]
    assert not any("로컬" in label for label in labels), labels


def test_a_word_inside_a_word_does_not_pick_the_scope() -> None:
    assert ("local", 3) not in _scoped_count_targets("파이썬 입문서 3권을 비교해줘")
    assert ("local", 3) not in _scoped_count_targets("크롬 프로파일 3개를 비교해줘")


def test_real_local_words_still_count() -> None:
    assert ("local", 3) in _scoped_count_targets("내 문서 3개를 읽고 정리해줘")
    assert ("local", 3) in _scoped_count_targets("로컬 파일 3개를 읽고 정리해줘")
    assert ("local", 3) in _scoped_count_targets("문서 3개를 열어 비교해줘")


def test_web_and_local_in_one_request_stay_apart() -> None:
    found = dict(_scoped_count_targets("로컬 문서 2개와 웹 자료 3개를 비교해줘"))
    assert found == {"local": 2, "web": 3}
