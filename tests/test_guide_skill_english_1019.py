"""가이드 스킬 영어판 (2026-10-19).

영어 사용자가 클로드 코드에 손자리를 붙이면 가이드가 한국어였다. 클로드는 그 가이드를 읽고 손자리에게 일을 **한국어로**
넘겼다(10-19 실측) — 사용자는 영어로 시켰는데 답도 한국어 쪽으로 끌렸다. 그래서 화면 언어가 영어면 가이드도 영어로 깐다.
"""

from __future__ import annotations

import re
from pathlib import Path

from alture_jarvis.delegation import DELEGATION_TOOLS
from alture_jarvis.guide_skill import _GROUPS, _GROUPS_EN, _MARK, SKILL_NAME, GuideSkillService, render_skill

TOOLS = [dict(t) for t in DELEGATION_TOOLS] + [
    {"name": "browser_search", "description": "웹 검색\n둘째 줄은 안 나온다"},
    {"name": "local_write_document", "description": "Make a Word document"},
    {"name": "something_else", "description": "기타 도구"},
]
HANGUL = re.compile("[가-힣]")
#: conftest 가 이 모듈에서는 `refresh_installed` 를 가짜로 바꾼다(실제 사용자 폴더를 지키려고 — 이름이 `test_guide_skill`
#: 로 끝나는 모듈만 예외). 수집 때(픽스처 전) 원본을 잡아 두고, 임시 홈만 쓰는 시험 (e) 안에서만 되돌린다.
_REAL_REFRESH = GuideSkillService.refresh_installed
#: 두 판이 같이 담아야 하는 필드·도구 이름 — 번역하면 호스트가 없는 칸을 부른다.
FIELDS = ("repo", "check", "needs", "unsupported_numbers", "resume", "model_hint", "branch", "take_home",
          "sources", "files", "needs_approval", "stopped_because", "sonjari_task", "sonjari_task_status", "sonjari_guide")


def _fields_in(text: str) -> set[str]:
    return {name for name in FIELDS if re.search(rf"`{re.escape(name)}[`.]|`{re.escape(name)}`", text)}


def test_english_has_no_hangul_at_all() -> None:
    """(a) 한 글자도 없다. 「손자리」 표기도 쓰지 않는다 — 영어판은 `NAME`(Sonjari)만으로 충분하다.
    도구 설명이 한국어면 그 설명은 빼고 이름만 둔다(설명 전체는 MCP 도구 목록에 있다)."""
    for tools in (TOOLS, TOOLS[2:]):
        text = render_skill(tools, "en")
        assert HANGUL.findall(text) == [], HANGUL.findall(text)[:20]
    text = render_skill(TOOLS, "en")
    assert "- `browser_search`\n" in text, "한국어 설명은 빼고 이름만"
    assert "- `local_write_document` — Make a Word document" in text, "영어 설명은 그대로"
    assert "### Hand off a whole task (" in text and "### Browser (low-level) (1)" in text
    assert "### Files and documents on this PC (1)" in text and "### Other (1)" in text


def test_both_editions_carry_the_same_field_names() -> None:
    """(b) 필드·도구 이름은 번역하지 않는다 — 같은 집합."""
    ko, en = render_skill(TOOLS), render_skill(TOOLS, "en")
    assert _fields_in(ko) == _fields_in(en)
    # needs 는 위임 도구 칸이라 표에만 나올 수 있다 — 적어도 이 목록의 대부분이 두 판에 다 있어야 한다.
    assert {"repo", "check", "unsupported_numbers", "resume", "model_hint", "branch", "take_home"} <= _fields_in(en)
    assert {prefix for prefix, _ in _GROUPS} == set(_GROUPS_EN), "묶음 앞머리는 두 판이 같다"
    # 숫자·날짜도 같다(사실 주장을 더하거나 빼지 않는다).
    # (「270초」의 「초」는 낱말 글자라 \b 가 안 맞는다 — 앞뒤가 숫자가 아닌 것으로 본다.)
    numbers = re.compile(r"\$\d+\.\d+|\d{4}-\d{2}-\d{2}|\b\d+(?:GB|B)\b|(?<!\d)270(?!\d)")
    assert sorted(set(numbers.findall(ko))) == sorted(set(numbers.findall(en)))


def test_english_tells_the_host_to_write_in_the_users_language() -> None:
    """(c) 영어판 「과제를 적는 법」에 언어 줄 — 한국어판에도 같은 뜻."""
    en = render_skill(TOOLS, "en")
    assert "Write the task in the language the user is using with you." in en
    assert "과제는 사용자가 너와 쓰는 언어로 적는다" in render_skill(TOOLS)
    # 같은 이름·같은 표시 — 설치된 파일을 알아보는 표시는 언어와 상관없다.
    assert en.startswith(f"---\nname: {SKILL_NAME}\ndescription: How to use") and _MARK in en


def test_default_is_still_korean() -> None:
    """(d) 언어를 안 주면 예전과 같은 한국어 본문. 모르는 언어도 한국어."""
    text = render_skill(TOOLS)
    assert text == render_skill(TOOLS, "ko") == render_skill(TOOLS, "fr")
    assert "## 순서" in text and "## When you hit a wall" not in text
    assert "### 기타 (1)" in text


def test_service_follows_the_language_callback(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """(e) 화면 언어를 바꾸면 다음 갱신에서 설치된 가이드가 그 언어로 다시 써진다 — 코덱스 사본도."""
    monkeypatch.setattr(GuideSkillService, "refresh_installed", _REAL_REFRESH)
    lang = ["en"]
    service = GuideSkillService(home=tmp_path, documents=tmp_path / "docs", clock=lambda: 3, lang=lambda: lang[0])
    service.install_claude_code(TOOLS)
    service.install_note("codex", TOOLS)
    skill = service.claude_code_path()
    codex = tmp_path / ".codex" / f"{SKILL_NAME}.md"
    assert not HANGUL.search(skill.read_text(encoding="utf-8-sig"))
    assert not HANGUL.search(codex.read_text(encoding="utf-8-sig"))

    lang[0] = "ko"
    done = service.refresh_installed(TOOLS)
    assert done.get("claude_code_skill") == str(skill)
    assert skill.read_text(encoding="utf-8-sig") == render_skill(TOOLS)
    assert codex.read_text(encoding="utf-8-sig") == render_skill(TOOLS)

    lang[0] = "en"
    service.refresh_installed(TOOLS)
    assert skill.read_text(encoding="utf-8-sig") == render_skill(TOOLS, "en")
    assert service.refresh_installed(TOOLS).get("claude_code_skill") is None, "같으면 다시 쓰지 않는다"

    # 콜백이 없으면 예전처럼 한국어 — 콜백이 터져도 한국어.
    plain = GuideSkillService(home=tmp_path / "b", documents=tmp_path / "b" / "docs")
    plain.install_claude_code(TOOLS)
    assert plain.claude_code_path().read_text(encoding="utf-8-sig") == render_skill(TOOLS)
    broken = GuideSkillService(home=tmp_path / "c", documents=tmp_path / "c" / "docs", lang=lambda: 1 / 0)
    broken.install_claude_code(TOOLS)
    assert broken.claude_code_path().read_text(encoding="utf-8-sig") == render_skill(TOOLS)


# ── 전역 지침 블록(`render_note`) — 매번 읽히는 파일이라 여기가 한국어면 같은 사고가 난다 ─────────────────────


def test_the_english_note_has_no_hangul_and_the_same_marks(tmp_path: Path) -> None:
    from alture_jarvis.guide_skill import _NOTE_END, _NOTE_START, render_note

    guide = tmp_path / ".claude" / "skills" / SKILL_NAME / "SKILL.md"
    pack = tmp_path / ".claude" / "skills" / "sonjari-game" / "SKILL.md"
    en = render_note(guide, [("Game pack", pack)], "en")
    ko = render_note(guide, [("Game pack", pack)])
    assert HANGUL.findall(en) == [], HANGUL.findall(en)[:20]
    assert en.startswith(_NOTE_START) and en.endswith(_NOTE_END) and ko.startswith(_NOTE_START) and ko.endswith(_NOTE_END)
    assert str(guide) in en and str(pack) in en and "do not say" in en
    assert ko == render_note(guide, [("Game pack", pack)], "ko") == render_note(guide, [("Game pack", pack)], "fr")
    assert "말하지 않는다" in ko and "do not say" not in ko
    assert len(en) < 2000


def test_the_note_follows_the_language_and_keeps_what_people_wrote(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """언어를 바꾸면 다음 갱신에서 지침 블록이 그 언어로 갈아 끼워진다 — 하나만 남고, 사람이 쓴 줄은 그대로."""
    monkeypatch.setattr(GuideSkillService, "refresh_installed", _REAL_REFRESH)
    lang = ["ko"]
    service = GuideSkillService(home=tmp_path, documents=tmp_path / "docs", clock=lambda: 4, lang=lambda: lang[0])
    note = tmp_path / ".claude" / "CLAUDE.md"
    note.parent.mkdir(parents=True)
    note.write_text("# 내 지침\n\n- 사람이 쓴 줄\n", encoding="utf-8")
    service.install_note("claude_code", TOOLS)
    assert "말하지 않는다" in note.read_text(encoding="utf-8-sig")

    lang[0] = "en"
    service.refresh_installed(TOOLS)
    text = note.read_text(encoding="utf-8-sig")
    assert "do not say" in text and "말하지 않는다" not in text and "- 사람이 쓴 줄" in text
    assert text.count("<!-- sonjari-guide:start -->") == 1
    assert "do not say" in service.manual_note(), "Cursor 에 붙여 넣을 글도 같은 언어"

    lang[0] = "ko"
    service.refresh_installed(TOOLS)
    text = note.read_text(encoding="utf-8-sig")
    assert "말하지 않는다" in text and "do not say" not in text and text.count("<!-- sonjari-guide:start -->") == 1
