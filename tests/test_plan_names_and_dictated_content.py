"""이름만 묻는 말과 **넣을 내용**을 준 말은 읽기 요구가 아니다 (2026-09-30 실측 두 판).

1. 「strategy 폴더에 있는 파일 이름을 세 개만 알려 줘」 → 「로컬 자료 3개 이상 직접 열어 읽기」. 이름만 볼 일에 파일을
   열었고, 폴더에 파일이 하나뿐이라 부분 완료로 끝났다.
2. 「robometafit.com 주소를 담은 QR 코드 PNG 를 만들어」 → 「근거가 되는 대상 실제로 읽기」. 주소는 QR 에 넣을 내용이지
   읽을 출처가 아니다. 읽을 게 없으니 영원히 미달이다(09-23 「메모.txt 에 …라고 적어」와 같은 병).

양방향: 본문을 보라거나 사이트에 들어가 읽으라는 말이 있으면 읽기 요구는 그대로 남아야 한다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import named_sources
from alture_jarvis.plan import extract


def _labels(prompt: str) -> list[str]:
    return [r.label for r in extract(prompt, has_named_source=bool(named_sources(prompt)), must_observe=True)]


def test_asking_for_file_names_is_not_a_reading_quota() -> None:
    labels = _labels(r"C:\work\monorepo\tools\alture-jarvis\docs\strategy 폴더에 있는 파일 이름을 세 개만 알려 줘. 파일은 만들지 말고 답으로만.")
    assert not any("열어 읽기" in label or "실제로 읽기" in label for label in labels), labels


def test_content_to_encode_is_not_a_source_to_read() -> None:
    labels = _labels("robometafit.com 주소를 담은 QR 코드 PNG 이미지를 만들어서 바탕화면에 qr_robometafit.png 로 저장해 줘.")
    assert labels == ["실제 산출물 파일 만들기"], labels


@pytest.mark.parametrize("prompt", [
    r"E:\docs 폴더의 파일 세 개를 열어서 각각 요약해 줘.",
    r"E:\docs 폴더 파일 이름 세 개 알려 주고 그 내용을 읽고 요약해 줘.",
])
def test_reading_the_files_still_needs_reading(prompt: str) -> None:
    assert any("열어 읽기" in label for label in _labels(prompt))


def test_going_to_the_site_to_read_still_needs_reading() -> None:
    labels = _labels("robometafit.com 에 들어가서 요금제를 읽고 QR 코드로 만들어 줘.")
    assert "근거가 되는 대상 실제로 읽기" in labels, labels


def test_web_research_counts_are_left_alone() -> None:
    labels = _labels("교보문고에서 파이썬 책 3권의 이름과 가격을 찾아 엑셀로 정리해 줘.")
    assert "3개 이상 직접 열어 읽기" in labels, labels


@pytest.mark.parametrize("prompt", [
    "robometafit.com 주소를 담은 QR 코드 PNG 이미지를 만들어서 바탕화면에 qr_robometafit.png 로 저장해 줘.",
    "QR코드 만들어 줘",
    "바코드 이미지 만들어 줘",
    "쿠폰 코드 목록을 엑셀로 만들어 줘",
])
def test_a_qr_or_bar_code_is_not_program_code(prompt: str) -> None:
    """★ QR 판이 코딩 과제로 분류돼 `coding_verification_missing` 으로 죽었다 — 「코드」는 부호일 때가 있다."""
    from alture_jarvis.plan import wants_code

    assert wants_code(prompt) is False


@pytest.mark.parametrize("prompt", [
    "파이썬 코드 짜서 QR 만들어 줘",
    "로그인 페이지 코드 고쳐 줘",
    "QR 코드를 생성하는 파이썬 스크립트 만들어 줘",
])
def test_program_code_is_still_code(prompt: str) -> None:
    from alture_jarvis.plan import wants_code

    assert wants_code(prompt) is True
