"""게임 팩이 맥에서 유니티를 찾는다(2026-11-08) — 윈도우 경로만 알아 맥에서 「에디터 없음」이 나던 빈칸."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alture_jarvis import unity_tools


def test_editor_exe_shape_per_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(unity_tools, "_MAC", True)
    assert unity_tools._editor_exe(tmp_path / "6000.6.3f1") == tmp_path / "6000.6.3f1" / "Unity.app" / "Contents" / "MacOS" / "Unity"
    monkeypatch.setattr(unity_tools, "_MAC", False)
    assert unity_tools._editor_exe(tmp_path / "6000.6.3f1") == tmp_path / "6000.6.3f1" / "Editor" / "Unity.exe"


def test_mac_hub_roots_include_default_and_secondary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(unity_tools, "_MAC", True)
    monkeypatch.setattr(unity_tools.Path, "home", classmethod(lambda cls: tmp_path))
    settings = tmp_path / "Library" / "Application Support" / "UnityHub"
    settings.mkdir(parents=True)
    (settings / "secondaryInstallPath.json").write_text('"/Volumes/Big/Unity"', encoding="utf-8")
    roots = unity_tools._hub_install_roots()
    assert Path("/Applications/Unity/Hub/Editor") in roots
    assert Path("/Volumes/Big/Unity") in roots


def test_mac_open_check_reads_process_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = tmp_path / "BugGuard"
    other = tmp_path / "BugGuard2"
    for path in (project, other):
        (path / "Temp").mkdir(parents=True)
        (path / "Temp" / "UnityLockfile").write_text("", encoding="utf-8")
    lines = [
        "/usr/bin/python3 x.py",
        f"/Applications/Unity/Hub/Editor/6000.6.3f1/Unity.app/Contents/MacOS/Unity -projectpath {project} -useHub",
    ]
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="\n".join(lines), stderr=""),
    )
    assert unity_tools._editor_open_by_process(project) is True
    assert unity_tools._editor_open_by_process(other) is False, "이름이 앞부분만 같은 다른 프로젝트를 열린 것으로 보지 않는다"


def test_mac_open_check_unknown_counts_as_open(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*a, **k):
        raise OSError("ps 없음")

    monkeypatch.setattr(subprocess, "run", boom)
    assert unity_tools._editor_open_by_process(tmp_path) is True


def test_unity_editor_rules_stay_inside_one_sentence() -> None:
    """11-08 게임 시험 1단계: 조사 글의 「…만들고」 · 「GameObjects」 · 「파일을 만들어 줘」가 다른 문장인데 「에디터에서 바꾸기」로 섰다."""
    from alture_jarvis import plan

    def editor(text: str) -> set[str]:
        return {r.target for r in plan.extract(text) if r.kind == "action" and r.target.startswith("unity_editor")}

    research = (
        "유니티 6로 협동 게임을 이 맥에서 만들고, 노트북도 참가하게 하려 한다. 공식 문서를 읽고 정리한 .md 파일을 만들어 줘.\n"
        "① 네트워크 도구 후보 표(Netcode for GameObjects, Mirror 등): 유니티 6 지원 여부와 판."
    )
    assert editor(research) == set()
    assert "unity_editor_change" in editor("유니티 에디터에서 아까 만든 큐브 지워 줘")
    assert "unity_editor_change" in editor("유니티 씬에 스피어 하나 만들어 줘.")
    assert "unity_editor_look" in editor("에디터 콘솔에 에러 있나 확인해 줘")


def test_same_version_twice_picks_the_one_with_more_build_support(monkeypatch, tmp_path) -> None:
    """2-2: `6000.6.3f1`(맥 빌드만) · `6000.6.3f1-arm64`(윈도우 모듈까지) — 판이 같으면 빌드 지원이 많은 쪽."""
    from types import SimpleNamespace

    monkeypatch.setattr(unity_tools, "_MAC", True)
    root = tmp_path / "Editor"
    for name, engines in (("6000.6.3f1", ["MacStandaloneSupport"]),
                          ("6000.6.3f1-arm64", ["MacStandaloneSupport", "WindowsStandaloneSupport"])):
        exe = root / name / "Unity.app" / "Contents" / "MacOS" / "Unity"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")
        for engine in engines:
            (root / name / "PlaybackEngines" / engine).mkdir(parents=True)
    tools = object.__new__(unity_tools.UnityTools)
    tools.config = SimpleNamespace(unity_editor_roots=str(root))
    monkeypatch.setattr(unity_tools, "_hub_install_roots", lambda: [])
    editors = tools.installed_editors()
    assert "6000.6.3f1-arm64" in str(editors["6000.6.3f1"])


def test_design_brief_does_not_demand_a_recipe_run() -> None:
    """11-08 저녁 3단계(하네스 탓 8): 설계만 시킨 글이 「레시피로 실제 점검하기」를 세웠다 — 다른 문장의 「씬 · 프리팹」 과 「확인」."""
    from alture_jarvis import plan

    def unity(text: str) -> set[str]:
        return {r.target for r in plan.extract(text) if r.kind == "action" and r.target.startswith("unity_")}

    brief = ("유니티 6로 만들 게임의 설계 문서를 .md 로 써 줘.\n"
             "4. 유니티 프로젝트 구조(폴더 · 씬 · 프리팹 · 스크립트 목록)\n"
             "5. 에셋은 CC0 만 — 받을 곳과 라이선스 확인 방법")
    assert unity(brief) == set()
    assert "unity_run_recipe" in unity("유니티 프로젝트의 빠진 참조를 점검해 줘")
    assert "unity_editor_undo" in unity("유니티 에디터에서 방금 한 거 되돌려 줘")
