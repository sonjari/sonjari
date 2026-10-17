"""마법사 「쓰임」 단계의 「이런 요청에 붙습니다」 낱말은 화면 언어의 표를 따른다 (2026-10-17 영어 마법사 점검).

영어 화면에 「Attached to requests like “문서로」「보고서로」「엑셀로”」가 나왔다 — 낱말은 한국어 표에서, 이음표는 「」「 였다.
영어 요청은 `SKILL_TRIGGERS_EN` 으로 붙으니, 영어 화면에서 보여 줄 약속은 그 표의 낱말이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alture_jarvis import skill_domains, ui_i18n
from alture_jarvis.skills import SKILL_TRIGGERS_EN, SKILL_TRIGGERS_KO


@dataclass
class _Doc:
    headline: str = "가상 한 줄"
    served: bool = True


class _Library:
    skills = {"document-craft": _Doc(), "startup-support-search": _Doc()}


def _words(lang: str, tmp_path: Path) -> dict[str, list[str]]:
    ui_i18n.configure(tmp_path / f"lang_{lang}.json")
    ui_i18n.set_lang(lang)
    try:
        view = skill_domains.catalog(_Library(), [])
    finally:
        ui_i18n.set_lang("ko")
    return {skill["name"]: skill["triggers"] for row in view["domains"] for skill in row["skills"]}


def test_english_screen_shows_the_english_words(tmp_path) -> None:
    words = _words("en", tmp_path)
    assert words["document-craft"] == list(SKILL_TRIGGERS_EN["document-craft"])[:4]
    # 영어 표에 없는 스킬은 빈 목록 — 화면은 「이름으로 지목하면 씁니다」(영어 요청에서 실제로 그렇다).
    assert words["startup-support-search"] == []


def test_korean_screen_keeps_the_korean_words(tmp_path) -> None:
    words = _words("ko", tmp_path)
    assert words["document-craft"] == list(SKILL_TRIGGERS_KO["document-craft"])[:4]
