"""「A **말고** 다른 파일은 고치지 마」에서 A 는 지킬 파일이 아니라 **고칠 파일**이다 (2026-10-15).

10-15 02:58 맡긴 코드 일(551f1fa5): 「ollama.py 의 runner_stopped 를 넓혀 줘 … ollama.py 말고 다른 파일은 고치지 말고」를 하네스가
「ollama.py 는 고치지 마」로 뽑았다(`protected_write_targets` → names=['ollama.py']). 손자리는 「이 세션에 ollama.py 는 읽기만 하라는
지시가 걸려 있다」며 고칠 코드만 답에 적고 멈췄다. 모델이 거꾸로 읽은 게 아니라 **하네스가 거꾸로 뽑았다.**

지키는 약속:
- 파일 이름 바로 뒤에 「말고 · 빼고 · 외에 · 제외하고」가 오고 그 뒤에 「다른 · 나머지」가 오면, 그 이름은 지킬 파일에서 뺀다.
- 그렇게 빼고 남는 이름도 시험 파일 지목도 없으면 지킬 대상이 없다(빈 dict) — 「다른 파일」은 이름이 없어 막을 수 없다.
- 이름을 그대로 댄 금지(「test_report.py 와 orders.csv 는 고치지 마」)와 「테스트 파일은 고치지 마」는 지금 그대로다.
"""

from __future__ import annotations

from alture_jarvis.plan import protected_write_targets


def test_the_named_exception_is_the_file_to_edit() -> None:
    prompt = ("tests/test_x.py 의 시험이 통과하도록 src/alture_jarvis/ollama.py 의 runner_stopped 판단을 넓혀 줘. "
              "ollama.py 말고 다른 파일은 고치지 말고, 바꾼 자리에 한국어 주석을 달아.")
    assert protected_write_targets(prompt) == {}


def test_other_spellings_of_the_exception() -> None:
    for said in ("config.py 빼고 나머지 파일은 건드리지 마", "main.py 외에 다른 파일은 수정하지 마",
                 "app.py 를 제외하고 다른 파일은 고치지 마"):
        assert protected_write_targets(said) == {}, said


def test_an_exception_with_a_real_protected_file_keeps_the_real_one() -> None:
    found = protected_write_targets("ollama.py 말고 다른 파일은 고치지 말고, 특히 conftest.py 는 절대 고치지 마")
    assert found.get("names") == ["conftest.py"]


def test_plain_prohibitions_are_unchanged() -> None:
    assert protected_write_targets("test_report.py 와 orders.csv 는 고치지 마")["names"] == ["test_report.py", "orders.csv"]
    assert protected_write_targets("테스트 파일은 고치지 마")["tests"] is True
