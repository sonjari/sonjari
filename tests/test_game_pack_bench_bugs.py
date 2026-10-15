"""게임 팩 모델 비교 벤치(2026-09-27)에서 나온 우리 쪽 버그 — 철칙: 벤치에서 나온 버그는 고친다."""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import _stuck_report
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.plan import write_prohibition_scope


def _local(tmp_path: Path) -> tuple[Path, LocalComputerTools]:
    project = tmp_path / "Game"
    (project / "Assets" / "Art").mkdir(parents=True)
    (project / "Assets" / "Art" / "hero.psd").write_bytes(b"x")
    (project / "Assets" / "Art" / "hero.png").write_bytes(b"x")
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          local_file_allowed_roots=str(project), local_read_roots=str(project))
    return project, LocalComputerTools(config)


def test_a_pattern_glued_into_the_path_is_split(tmp_path: Path) -> None:
    """35B 텍스처 3회차: path 에 `…\Assets\**\*.psd` 를 통째로 넣어 path_not_found 5번 → 판이 멈췄다."""
    project, local = _local(tmp_path)
    out = local.glob_files({"path": str(project / "Assets") + "\**\*.psd"})
    assert [Path(item["path"]).name for item in out["items"]] == ["hero.psd"]
    assert Path(out["path"]) == (project / "Assets").resolve(), "원장이 어디를 뒤졌는지 적을 수 있게 path 를 싣는다"
    plain = local.glob_files({"path": str(project), "pattern": "**/*.png"})
    assert [Path(item["path"]).name for item in plain["items"]] == ["hero.png"], "보통 모양은 그대로"


def test_a_stuck_local_job_does_not_ask_about_chrome() -> None:
    """로컬 파일 찾기가 막혔는데 「크롬 창에서 이 화면을 맞춰 주세요」라고 했다 — 크롬은 열린 적도 없다."""
    steps = [{"tool": "local_glob", "ok": False, "error": "path_not_found: E:\Game\Assets\**\*.psd"} for _ in range(6)]
    report = _stuck_report(steps)
    assert report is not None and "크롬" not in report["ask"] and "경로" in report["ask"]
    browser = _stuck_report([{"tool": "browser_click", "ok": False, "error": "no_change"} for _ in range(6)])
    assert browser is not None and "크롬" in browser["ask"], "브라우저 판은 예전 그대로"


def test_do_not_fix_is_a_write_prohibition() -> None:
    """「파일은 고치지 마」라고 한 판에서 모델이 프로젝트에 파이썬 파일을 쓰려 했다 — 「고치」가 금지 낱말에 없었다."""
    for said in ("점검해서 알려줘. 파일은 고치지 마.", "빠진 참조 찾아서 알려줘. 고치지는 마.", "아무것도 고치지 마",
                 "고치지 말고 알려줘"):
        assert write_prohibition_scope(said) == "job", said
    # ★ 반대 표본: 대상을 한정한 금지는 판을 묶지 않는다(2026-09-03 SWE 벤치 사고).
    assert write_prohibition_scope("테스트 파일은 절대 수정하지 마 — 구현을 고쳐야 한다.") == "clause"
    assert write_prohibition_scope("테스트 코드는 고치지 마. 구현만 고쳐줘.") == ""
    assert write_prohibition_scope("calc.py 고쳐줘") == ""


def test_unity_guidance_steers_away_from_scanning_image_files() -> None:
    from alture_jarvis.code_runtime import select_code_tool_profile

    guidance = select_code_tool_profile("유니티 프로젝트에서 2048보다 큰 텍스처 점검해줘").guidance
    assert "local_glob" in guidance and "스크립트를 짜지 않는다" in guidance


def test_a_tool_name_put_into_the_command_box_calls_that_tool() -> None:
    """35B 빠진 참조 1회차: `local_run_project_command` 에 `command: "unity_project_info"` — 그 도구를 부르려 한 것이다."""
    from alture_jarvis.agent import _tool_named_in_command

    available = {"local_run_project_command", "unity_project_info", "unity_list_recipes"}
    name, args = _tool_named_in_command(
        "local_run_project_command", {"command": "unity_project_info", "project_path": r"E:\Game"}, available)
    assert name == "unity_project_info" and args == {"project_path": r"E:\Game"}
    # ★ 반대 표본: 진짜 명령, 열려 있지 않은 이름, 명령 도구 자신은 그대로 둔다.
    for command in ("pytest -q", "rm_everything", "local_run_project_command", ["ruff", "check", "."]):
        assert _tool_named_in_command("local_run_project_command", {"command": command}, available)[0] == "local_run_project_command"
    assert _tool_named_in_command("local_read_text_file", {"command": "unity_project_info"}, available)[0] == "local_read_text_file"


def test_windows_paths_in_string_arguments_survive() -> None:
    r"""★ 벤치: `"E:\UnityProjects"` 의 외톨이 `\U` 로 JSON 이 깨져 인자 전체가 `{}` 가 됐다."""
    from alture_jarvis.agent import BrowserAgent

    call = {"function": {"name": "unity_run_recipe",
                         "arguments": r'{"recipe": "texture_audit", "project": "E:\UnityProjects\Game"}'}}
    name, args = BrowserAgent._arguments(call)
    assert name == "unity_run_recipe" and args == {"recipe": "texture_audit", "project": r"E:\UnityProjects\Game"}
    ok = {"function": {"name": "x", "arguments": r'{"path": "C:\\Users\\a", "n": "line\nnext"}'}}
    assert BrowserAgent._arguments(ok)[1] == {"path": r"C:\Users\a", "n": "line\nnext"}, "올바른 JSON 은 그대로"


def test_an_unknown_recipe_is_not_sent_to_the_approval_card(tmp_path) -> None:
    """★ 벤치: `{}` 로 부른 unity_run_recipe 가 「모르는 레시피 → L2」로 승인 카드를 띄우고 판을 세웠다."""
    from alture_jarvis.unity_tools import UnityTools

    tools = UnityTools(JarvisConfig(), object())
    assert tools._risk({}).name == "L1"
    assert tools._risk({"recipe": "texture_audit"}).name == "L1"


def test_recipe_and_param_aliases_are_accepted() -> None:
    """★ 3모델 벤치: 35B·9B 가 `recipe_name`·`recipe_id`·`parameters`(글자 JSON) 로 보내 「모르는 레시피」 세 번 → 파일 뒤지기."""
    from alture_jarvis.unity_tools import UnityTools

    norm = UnityTools._normalized({"recipe_name": "texture_audit", "parameters": '{"max_size": 1024}'})
    assert norm["recipe"] == "texture_audit" and norm["params"] == {"max_size": 1024}
    assert UnityTools._normalized({"recipe_id": "missing_references"})["recipe"] == "missing_references"
    assert UnityTools._normalized({"recipe": "texture_audit", "params": {"limit": 3}})["params"] == {"limit": 3}


def test_a_unity_check_request_requires_a_recipe_run() -> None:
    """★ 3모델 벤치: 4B 가 레시피를 안 돌리고 「텍스처가 없다」를 지어냈다 — 점검 요청은 레시피 실행을 시킨 것으로 센다."""
    from alture_jarvis.plan import extract

    for said in (r"E:\Game 유니티 프로젝트에서 2048보다 큰 텍스처가 있는지 점검해서 알려줘. 파일은 고치지 마.",
                 r"E:\Game 유니티 프로젝트의 프리팹이랑 씬에서 빠진 참조(Missing)가 있는지 찾아서 알려줘."):
        assert ("action", "unity_run_recipe") in [(r.kind, r.target) for r in extract(said)], said
    for said in ("유니티 설치 링크 한번 주라", "유니티가 뭐야", "텍스처 점검 방법 알려줘"):
        assert "unity_run_recipe" not in [r.target for r in extract(said)], said


def test_a_verified_recipe_run_counts_as_reading() -> None:
    """★ 3모델 벤치 18판 중 12판: 레시피로 맞게 읽고도 답 끝에 「❌ 근거가 되는 대상 실제로 읽기 — 0개」가 붙었다."""
    from alture_jarvis.agent import BrowserAgent

    ok = {"tool": "unity_run_recipe", "ok": True,
          "evidence": {"project": r"E:\Game", "recipe": "texture_audit", "verified": True}}
    failed = {"tool": "unity_run_recipe", "ok": True,
              "evidence": {"project": r"E:\Game", "recipe": "missing_references", "verified": False}}
    assert BrowserAgent._sources_actually_read([ok, dict(ok), failed]) == [r"E:\Game::texture_audit"], \
        "검증된 판만, 같은 점검은 한 번만"
