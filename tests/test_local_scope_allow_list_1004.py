"""「로컬」은 뒤에 파일을 담는 것이 올 때만 출처다 · 출처 이름표가 틀려도 읽은 것은 센다 (2026-10-04 허깅페이스 판 5749ff16).

「허깅페이스에서 … 로컬용 GGUF 텍스트 생성 모델 … 5개」가 「로컬 자료 5개 이상 직접 열어 읽기」가 됐다. 웹 페이지를 열일곱 장 읽는
내내 「0개 읽음」이었고 끝은 부분 완료였다. 「로컬」 오독은 09-29(입문서) · 09-30(로컬 AI 제품) 에 이어 세 번째다 — 그때마다
금지 낱말을 하나씩 늘렸다. 종류는 끝이 없고 출처는 몇 개뿐이라 허용 목록으로 뒤집고, 틀려도 손해가 없게 판정 쪽도 막는다.
"""
from __future__ import annotations

import pytest

from alture_jarvis import plan
from alture_jarvis.plan import Requirement


def _scopes(prompt: str) -> list[tuple[str, str]]:
    found = plan.extract(prompt, has_named_source=True)
    return [(item.label, item.source_scope) for item in found if item.kind == "count"]


# --- 계획: 「로컬 X」의 X 가 출처일 때만 ---------------------------------------

@pytest.mark.parametrize("prompt", [
    "허깅페이스(huggingface.co)에서 최근 올라온 로컬용 GGUF 텍스트 생성 모델 가운데 근거를 확인할 수 있는 모델 5개를 찾아 엑셀로 정리해줘",
    "로컬에서 돌리는 코딩 모델 3개를 레딧에서 찾아 읽고 정리해줘",
    "레딧에서 로컬 추론 서버 4개를 찾아 읽고 비교해줘",
    "깃허브에서 로컬 우선 메모 앱 3개를 찾아 읽고 표로 만들어줘",
])
def test_local_as_a_kind_of_thing_is_not_a_local_source(prompt: str) -> None:
    assert all(scope != "local" for _label, scope in _scopes(prompt)), _scopes(prompt)
    assert all("로컬 자료" not in label for label, _scope in _scopes(prompt))


@pytest.mark.parametrize("prompt", [
    "로컬 문서 3개와 웹 자료 3개를 읽고 비교해줘",
    "내 문서 폴더의 계약서 파일 2개를 읽고 차이를 정리해줘",
    "로컬에 있는 보고서 3개를 읽고 요약해줘",
    "로컬 파일 4개를 읽고 공통점을 정리해줘",
])
def test_a_real_local_source_still_reads_as_local(prompt: str) -> None:
    assert ("local" in {scope for _label, scope in _scopes(prompt)}), _scopes(prompt)


def test_the_same_holds_in_english() -> None:
    kind = plan.extract("Read up on 5 local LLM runners on reddit.com and compare them", has_named_source=True)
    place = plan.extract("Read 3 local files in my Documents folder and compare them", has_named_source=False)

    assert all(item.source_scope != "local" for item in kind)
    assert any(item.source_scope == "local" for item in place)


# --- 판정: 이름표와 다른 쪽으로만 읽었으면 읽은 쪽으로 센다 ------------------------

_WEB = [f"https://huggingface.co/org/model-{index}" for index in range(5)]


def _local(target: int) -> Requirement:
    return Requirement("count", f"로컬 자료 {target}개 이상 직접 열어 읽기", target, grounding_required=True, source_scope="local")


def _web(target: int) -> Requirement:
    return Requirement("count", f"웹 자료 {target}개 이상 직접 열어 읽기", target, grounding_required=True, source_scope="web")


def test_a_mislabelled_scope_does_not_leave_the_job_unmet() -> None:
    (_req, ok, saw), = plan.check([_local(5)], sources=_WEB, steps=[])

    assert ok is True
    assert saw.startswith("5개 읽음") and "웹에서 읽은 것을 셈" in saw


def test_nothing_read_is_still_nothing() -> None:
    (_req, ok, saw), = plan.check([_local(5)], sources=[], steps=[])

    assert ok is False and saw.startswith("0개 읽음")


def test_when_both_scopes_were_asked_the_label_keeps_its_meaning() -> None:
    """로컬 3 + 웹 3 을 시켰는데 웹만 읽었으면 로컬 쪽은 미달이다 — 이때는 이름표가 뜻을 가진다."""
    results = plan.check([_local(3), _web(3)], sources=_WEB, steps=[])
    by_scope = {req.source_scope: (ok, saw) for req, ok, saw in results}

    assert by_scope["web"][0] is True
    assert by_scope["local"][0] is False and by_scope["local"][1].startswith("0개 읽음")


def test_reads_on_the_labelled_side_are_counted_as_before() -> None:
    mixed = ["C:/docs/a.pdf", "C:/docs/b.pdf", *_WEB]
    (_req, ok, saw), = plan.check([_local(3)], sources=mixed, steps=[])

    assert ok is False and saw.startswith("2개 읽음") and "셈" not in saw
