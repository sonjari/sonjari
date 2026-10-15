"""가이드 스킬 (인수인계 H1-b) — 도구 표가 실제 목록에서 나오고, 남의 스킬은 덮지 않는다."""

from __future__ import annotations

import zipfile
from pathlib import Path

from alture_jarvis.brand import LEGACY_NAMES
from alture_jarvis.delegation import DELEGATION_TOOLS
from alture_jarvis.guide_skill import SKILL_NAME, GuideSkillService, render_skill

TOOLS = [dict(t) for t in DELEGATION_TOOLS] + [
    {"name": "browser_search", "description": "웹 검색\n둘째 줄은 안 나온다"},
    {"name": "local_write_document", "description": "워드 문서 만들기"},
]


def test_the_table_comes_from_the_tool_list() -> None:
    text = render_skill(TOOLS)
    assert text.startswith("---\nname: sonjari-guide\n")
    assert "`browser_search` — 웹 검색" in text and "둘째 줄" not in text
    assert "`sonjari_task`" in text and "통째로 맡긴다" in text
    for legacy in LEGACY_NAMES:
        assert legacy not in text


def test_without_delegation_the_skill_does_not_promise_it() -> None:
    text = render_skill(TOOLS[2:])
    assert "위임 도구가 없다" in text and "`sonjari_task`" not in text
    assert "`repo`" not in text and "저장소의 코드 일을 맡길 때" not in text, "칸은 그 도구에 달려 있다 — 없는 설치에는 적지 않는다"


def test_install_backs_up_our_old_copy_and_refuses_a_foreign_one(tmp_path: Path) -> None:
    service = GuideSkillService(home=tmp_path, documents=tmp_path / "Documents" / "Ontelic", clock=lambda: 7)
    first = service.install_claude_code(TOOLS)
    assert first["ok"] and service.status()["claude_code"]["installed"]
    again = service.install_claude_code(TOOLS)
    assert again["backup"].endswith("SKILL.md.bak-7")

    service.claude_code_path().write_text("사용자가 직접 만든 스킬", encoding="utf-8")
    refused = service.install_claude_code(TOOLS)
    assert refused == {"ok": False, "error": "foreign_skill_exists", "path": str(service.claude_code_path())}
    assert service.remove_claude_code()["ok"] is False
    assert service.claude_code_path().read_text(encoding="utf-8") == "사용자가 직접 만든 스킬"


def test_zip_holds_one_skill_folder(tmp_path: Path) -> None:
    service = GuideSkillService(home=tmp_path, documents=tmp_path / "docs")
    made = service.build_zip(TOOLS)
    with zipfile.ZipFile(made["path"]) as archive:
        assert archive.namelist() == [f"{SKILL_NAME}/SKILL.md"]


def test_the_global_note_points_at_the_skill_file_and_keeps_what_people_wrote(tmp_path: Path) -> None:
    """★ 2026-09-16: 연결만으로는 안 부른다 — Codex 가 온텔릭을 0번 부르고 자기 브라우저로 했다.
    전역 지침은 스킬과 달리 **매번 읽힌다.** 그래서 지침은 짧게 가리키기만 한다."""
    service = GuideSkillService(home=tmp_path, documents=tmp_path / "docs", clock=lambda: 5)
    mine = tmp_path / ".claude" / "CLAUDE.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("# 내 지침\n\n- 한국어로 답한다\n", encoding="utf-8")

    done = service.install_note("claude_code", TOOLS)

    text = mine.read_text(encoding="utf-8")
    assert done["ok"] and "- 한국어로 답한다" in text
    assert "sonjari-guide/SKILL.md" in text.replace("\\", "/")
    assert "말하지 않는다" in text and len(text) < 2000
    assert service.note_status()["claude_code"]["installed"] is True

    # 두 번 넣어도 하나만 — 그리고 뺄 때 사람이 쓴 것은 그대로 남는다.
    service.install_note("claude_code", TOOLS)
    assert mine.read_text(encoding="utf-8").count("<!-- sonjari-guide:start -->") == 1
    service.remove_note("claude_code")
    left = mine.read_text(encoding="utf-8")
    assert "sonjari" not in left and "- 한국어로 답한다" in left


def test_codex_gets_a_copy_of_the_guide_because_it_has_no_skills_folder(tmp_path: Path) -> None:
    service = GuideSkillService(home=tmp_path, documents=tmp_path / "docs")
    done = service.install_note("codex", TOOLS)
    guide = Path(done["guide_path"])
    assert guide.name == "sonjari-guide.md" and "sonjari_task" in guide.read_text(encoding="utf-8")
    assert guide.name in (tmp_path / ".codex" / "AGENTS.md").read_text(encoding="utf-8")


def test_coding_research_is_delegated_and_a_narrow_repo_job_goes_through_the_fields() -> None:
    """09-29 대표: 「있는데도 안 맡긴다」 — 가이드가 코딩 중 조사를 「직접 한다」로 적고 있었다(프론티어는 가이드만큼만 맡긴다).
    10-09: `sonjari_task` 에 repo · check 칸이 생겼다 — 그 전까지는 「저장소를 맡기는 길은 아직 없다」가 맞는 안내였다(09-21 교훈:
    없는 칸을 있다고 쓰지 않는다). 이제는 칸이 있는 만큼만 적는다: 좁은 일 · 새 가지 · 끝은 확인 명령."""
    from alture_jarvis.delegation import TASK_TOOL

    assert {"repo", "check"} <= set(TASK_TOOL["parameters"]["properties"]), "가이드가 말하는 칸이 도구에 실제로 있어야 한다"
    from alture_jarvis.mcp_server import INSTRUCTIONS

    text = render_skill(TOOLS)
    for doc in (text, INSTRUCTIONS):
        assert "코딩 중" in doc and "에러 메시지" in doc and "띄워 둔 앱" in doc
        assert "저장소를 맡기는 길은 아직 없" not in doc
        assert "repo" in doc and "check" in doc and "새 가지" in doc
        assert "처음 보는 API" in doc, "통째로 맡기면 안 되는 쪽도 그대로 적혀 있어야 한다"
        # ★ 10-02 분업 실험: 클로드가 자기가 띄운 localhost 앱은 Playwright 로 직접 확인했다(더 빠르고 결과를 직접 본다).
        #   그 일은 호스트 쪽으로 옮기고, 손자리 쪽에는 호스트 브라우저에 없는 것(사용자 로그인)이 필요한 화면을 둔다.
        assert "로그인" in doc and "빈 브라우저" in doc
    assert "| 로그인이 필요한 사이트에서 보기 | 코드 작성·설명 |" not in text
    # 잰 것만 적는다 — 무엇을 · 어디서 · 몇 판인지가 붙어 있고, 안 잰 칸은 안 쟀다고 적는다.
    assert "1판" in text and "아직 안 쟀다" in text and "stopped_because" in text and "take_home" in text
    assert len(INSTRUCTIONS) <= 1500


def test_code_edits_are_split_read_by_sonjari_written_by_the_host() -> None:
    """★ 2026-10-01 베타 테스터: 「클로드한테 손자리 활용해서 맥스 스크립트 수정해 달라니까 손자리가 인터넷 서칭을 많이 하네」.
    클로드는 그 API 를 아는데 수정 내용까지 통째로 넘겨, 로컬 모델이 처음 보는 API 를 웹에서 공부했다. 읽기·쓰기는 손자리, 짜기는 호스트."""
    from alture_jarvis.mcp_server import INSTRUCTIONS

    text = render_skill(TOOLS)
    for doc in (text, INSTRUCTIONS):
        assert "읽어 오" in doc and "짜" in doc and ("pymxs" in doc or "처음 보는 API" in doc)
    assert "이 PC 의 코드를 고칠 때" in text


def test_an_app_update_refreshes_only_the_guides_we_installed(tmp_path: Path) -> None:
    """★ 10-02: 가이드 문구를 고쳐도 이미 잇기를 한 PC 의 스킬·지침은 옛 문구 그대로였다 — 앱이 켜질 때 맞춘다."""
    from alture_jarvis.guide_skill import _MARK

    service = GuideSkillService(home=tmp_path, documents=tmp_path / "docs", clock=lambda: 9)
    assert service.refresh_installed(TOOLS).get("claude_code_skill") is None
    assert not service.claude_code_path().exists(), "잇지 않은 PC 에는 아무것도 만들지 않는다"
    assert not (tmp_path / ".claude" / "CLAUDE.md").exists()

    service.install_claude_code(TOOLS)
    service.install_note("claude_code", TOOLS)
    skill = service.claude_code_path()
    skill.write_text(f"---\nname: sonjari-guide\n---\n{_MARK}\n옛 문구 — 네 브라우저로 대신하지 않는다\n", encoding="utf-8-sig")
    note = tmp_path / ".claude" / "CLAUDE.md"
    note.write_text("# 내 지침\n사람이 쓴 줄\n\n" + note.read_text(encoding="utf-8-sig").split("# 내 지침", 1)[-1]
                    .replace("빈 브라우저", "옛 문구"), encoding="utf-8-sig")
    done = service.refresh_installed(TOOLS)
    assert done["claude_code_skill"] == str(skill)
    assert "옛 문구" not in skill.read_text(encoding="utf-8-sig") and "빈 브라우저" in skill.read_text(encoding="utf-8-sig")
    text = note.read_text(encoding="utf-8-sig")
    assert "사람이 쓴 줄" in text and "빈 브라우저" in text and "옛 문구" not in text

    skill.write_text("---\nname: sonjari-guide\n---\n사용자가 직접 만든 스킬\n", encoding="utf-8")
    service.refresh_installed(TOOLS)
    assert skill.read_text(encoding="utf-8") == "---\nname: sonjari-guide\n---\n사용자가 직접 만든 스킬\n", "남의 스킬은 덮지 않는다"
