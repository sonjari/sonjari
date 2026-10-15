"""우리 숙제를 손자리에게 맡긴 판에서 나온 둘 (2026-10-09 새벽).

① 과제 글이 버그를 설명하며 따옴표로 옮겨 적은 예시 문장(「앞 판이 『…에서 공고 3개 열어 읽어줘』였으면」)에서
   「3개 이상 직접 열어 읽기」와 「…에서 하기」가 섰다. 코드 버그를 고치는 판이 「아직 읽은 본문 없음」으로 재촉받았다.
   개수와 사이트 이름은 따옴표 밖에서만 찾는다. 운영 요청 1,811개에 대 보니 달라지는 것은 그 과제 글 하나였다.
   (처음 규칙은 요청 전체를 낫표로 감싸 보낸 요청의 요구를 전부 지워서, 글의 대부분을 감싼 따옴표는 건드리지 않게 조였다.)

② 코드 판에서 모델이 짧은 경로(`src/pkg/mod.py`)로 고치려 하자, 로컬 도구가 그 경로를 손자리가 설치된 폴더 기준으로 풀어
   작업 폴더가 아닌 곳을 가리켰다(권한 문이 막았다). 짧은 경로는 그 판의 작업 폴더 기준으로 푼다.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from alture_jarvis import plan
from alture_jarvis.agent import BrowserAgent, anchor_relative_paths
from alture_jarvis.plan import _without_quoted_sentences

_SITES = {"사람인": ("saramin.co.kr",)}


def _kinds(prompt: str) -> list[tuple[str, str]]:
    return [(r.kind, r.label) for r in plan.extract(prompt, has_named_source=True, must_observe=True, known_sites=_SITES)]


# ── ① 따옴표로 옮겨 적은 문장 ──────────────────────────────────────────────────


def test_an_example_sentence_in_quotes_makes_no_requirement() -> None:
    task = ("이 저장소에 버그가 있다. 원인을 찾아 설명해줘. 예를 들면 앞 판이 「사람인에서 공고 3개 열어 읽어줘」였으면 "
            "그 요구가 새 요청에 다시 살아난다. 「파이썬 책 2권 추천해줘」 같은 말에서도 그렇다.")
    kinds = _kinds(task)
    assert not [k for k in kinds if k[0] in ("count", "count_action", "site")], kinds


@pytest.mark.parametrize("quotes", ["「{}」", "『{}』", "\"{}\"", "'{}'", "“{}”"])
def test_every_kind_of_quote_is_a_mention(quotes: str) -> None:
    task = "아래 문장이 왜 잘못 읽히는지 설명해줘: " + quotes.format("사람인에서 공고 3개 열어 읽어줘") + " 이게 예시다."
    assert not [k for k in _kinds(task) if k[0] in ("count", "site")]


def test_the_same_sentence_outside_quotes_is_still_a_request() -> None:
    kinds = _kinds("사람인에서 공고 3개 열어 읽어줘")
    assert ("site", "사람인에서 하기") in kinds
    assert any(kind == "count" for kind, _label in kinds)


def test_a_single_quoted_name_is_still_a_name() -> None:
    """낱말 하나를 따옴표로 감싼 것은 이름을 짚은 것이다."""
    kinds = _kinds("'사람인'에서 'RAG' 로 검색해서 공고 3개 열어 읽어줘")
    assert ("site", "사람인에서 하기") in kinds
    assert any(kind == "count" for kind, _label in kinds)


def test_a_request_wrapped_whole_in_quotes_is_still_the_request() -> None:
    """요청을 통째로 낫표에 넣어 보내는 사람이 있다 — 글의 대부분을 감싼 따옴표는 인용이 아니다."""
    kinds = _kinds("「사람인에서 지금 모집 중인 회계 공고 3개를 찾아 회사명과 마감일을 알려줘」")
    assert ("site", "사람인에서 하기") in kinds
    assert any(kind == "count" for kind, _label in kinds)


def test_blanking_keeps_the_length_and_the_quote_marks() -> None:
    text = "앞 판이 「가 나 다」였다. '한낱말' 은 그대로."
    blanked = _without_quoted_sentences(text)
    assert len(blanked) == len(text)
    assert "「" in blanked and "」" in blanked and "가 나 다" not in blanked
    assert "'한낱말'" in blanked


# ── ② 짧은 경로는 작업 폴더 기준 ───────────────────────────────────────────────

_ROOT = str(Path("C:/work/copy/repo"))


def test_a_short_path_lands_inside_the_job_workspace() -> None:
    changed = anchor_relative_paths({"path": "src/pkg/mod.py", "old": "a", "new": "b"}, _ROOT)
    assert changed == {"path": str(Path(_ROOT) / "src/pkg/mod.py"), "old": "a", "new": "b"}


def test_a_full_path_a_home_path_and_an_env_path_are_left_alone() -> None:
    for value in (str(Path("C:/other/place/file.py")), "~/notes.txt", "%USERPROFILE%/a.txt", "$HOME/a.txt", "https://site.example/x", ""):
        assert anchor_relative_paths({"path": value}, _ROOT) is None, value


def test_lists_and_the_working_directory_are_anchored_too() -> None:
    changed = anchor_relative_paths({"paths": ["a.py", str(Path("C:/x/b.py"))], "cwd": ".", "command": "pytest -q tests/x.py"}, _ROOT)
    assert changed is not None
    assert changed["paths"] == [str(Path(_ROOT) / "a.py"), str(Path("C:/x/b.py"))]
    assert changed["cwd"] == str(Path(_ROOT) / ".")
    assert changed["command"] == "pytest -q tests/x.py"  # 명령 글은 경로 칸이 아니다


def test_it_is_wired_into_code_jobs_only() -> None:
    source = inspect.getsource(BrowserAgent.run)
    at = source.index("anchor_relative_paths(arguments, required_local_root)")
    guard = source.rfind("if model_role == \"code\" and required_local_root and name.startswith(\"local_\"):", 0, at)
    assert 0 <= guard and at - guard < 200


# ── ③ 쓰기 금지도 따옴표 밖에서만 (2026-10-09 새벽 — 판 hw3) ────────────────────────
#
# 「쓰기 금지를 잘못 읽는 버그를 고쳐라」는 과제 글이 그 버그의 예시를 따옴표로 옮겨 적자, 예시가 시킨 말로 읽혀 판 전체가
# 읽기 전용이 됐다. 손자리는 원인을 다 읽고도 명령 하나 못 돌렸다. 운영 요청 1,816개에 대 보니 달라지는 것은 그 과제 글 하나였다.


def test_a_quoted_prohibition_does_not_lock_the_job() -> None:
    task = ("이 저장소의 판정 규칙을 고쳐줘. 지금은 「조사만 해줘. 파일은 만들지 마」 같은 말과 "
            "「문서를 만들되 표는 넣지 말고 글로만 써줘」를 같은 것으로 읽는다. 고친 뒤 시험을 돌려 확인해.")
    assert plan.write_prohibition_scope(task) == ""


def test_the_same_prohibition_outside_quotes_still_locks_it() -> None:
    assert plan.write_prohibition_scope("이 폴더를 조사만 해줘. 파일은 만들지 마") == "job"


def test_a_prohibition_said_outside_quotes_survives_the_examples_around_it() -> None:
    task = ("「파일은 만들지 마」 같은 말을 잘못 읽는 버그를 고쳐줘. 테스트 파일은 수정하지 마 — 구현을 고쳐라.")
    assert plan.write_prohibition_scope(task) == "clause"


def test_a_request_wrapped_whole_in_quotes_keeps_its_prohibition() -> None:
    assert plan.write_prohibition_scope("「이 폴더를 조사만 해줘. 파일은 만들지 마」") == "job"
