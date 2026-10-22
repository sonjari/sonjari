"""서기 훅 제품화 (2026-10-22 · 간판 3번) — 서기를 켜면 클로드 코드 설정에 훅 셋, 끄면 우리 것만 뺀다.

지키는 것: 사용자가 단 훅은 그대로 · 바뀐 게 없으면 쓰지 않음(백업이 쌓이지 않게) · 쓸 때는 백업 · JSON 이 아니면 손대지 않음 ·
스토어 판은 실행 별칭 `-m` · `pythonw` 는 출력이 없으니 `python` · 시험은 진짜 사용자 설정을 못 건드림(`start()` 전엔 안 함).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from alture_jarvis import claude_hooks, msix, scribe_hooks


def _config(tmp_path: Path, **extra) -> SimpleNamespace:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return SimpleNamespace(**{"data_dir": data, "host": "127.0.0.1", "port": 8091, "scribe_style_file": "", **extra})


def _settings(home: Path) -> dict:
    return json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))


def _ours(data: dict) -> list[tuple[str, str | None, str]]:
    return [(event, group.get("matcher"), hook["command"]) for event, groups in data.get("hooks", {}).items()
            for group in groups for hook in group["hooks"] if "claude_hooks" in hook["command"]]


def test_turning_on_adds_three_hooks_and_keeps_the_users_own(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    mine = {"hooks": {"SessionStart": [{"matcher": "compact", "hooks": [{"type": "command", "command": "python my_hook.py"}]}],
                      "Stop": [{"hooks": [{"type": "command", "command": "python stop.py"}]}]}, "theme": "dark"}
    (home / ".claude" / "settings.json").write_text(json.dumps(mine), encoding="utf-8")
    result = scribe_hooks.apply(_config(tmp_path), True, home=home, clock=lambda: 0.0)
    assert result["ok"] and result["changed"] and Path(result["backup"]).exists()
    data = _settings(home)
    ours = _ours(data)
    assert {(e, m) for e, m, _ in ours} == {("SessionStart", "compact"), ("SessionStart", "startup"), ("PostCompact", None)}
    assert any("my_hook.py" in h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"]), "사용자 훅은 그대로"
    assert data["hooks"]["Stop"] and data["theme"] == "dark"
    after = next(c for e, m, c in ours if m == "compact")
    assert "after-compact" in after and "--base-url http://127.0.0.1:8091" in after and "control.token" in after
    assert "save-compact" in next(c for e, m, c in ours if e == "PostCompact")

    again = scribe_hooks.apply(_config(tmp_path), True, home=home, clock=lambda: 1.0)
    assert again == {"ok": True, "changed": False, "path": str(home / ".claude" / "settings.json")}, "같으면 안 쓴다"

    off = scribe_hooks.apply(_config(tmp_path), False, home=home, clock=lambda: 2.0)
    assert off["changed"] and _ours(_settings(home)) == []
    assert _settings(home)["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "python my_hook.py"
    assert scribe_hooks.status(home) == {"installed": False, "events": []}


def test_a_broken_settings_file_is_left_alone(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text("{ 이건 JSON 아님", encoding="utf-8")
    assert scribe_hooks.apply(_config(tmp_path), True, home=home)["error"] == "config_not_json"
    assert (home / ".claude" / "settings.json").read_text(encoding="utf-8") == "{ 이건 JSON 아님"


def test_store_build_calls_the_alias_and_dev_build_calls_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dev = scribe_hooks.hook_commands(_config(tmp_path))
    assert "claude_hooks.py" in dev[0][2] and "-m alture_jarvis" not in dev[0][2]
    monkeypatch.setattr(msix, "is_packaged", lambda: True)
    monkeypatch.setattr(scribe_hooks, "msix_alias_path", lambda: Path("C:/Users/x/AppData/Local/Microsoft/WindowsApps/sonjari.exe"))
    store = scribe_hooks.hook_commands(_config(tmp_path))
    assert store[0][2].startswith('"C:/Users/x/AppData/Local/Microsoft/WindowsApps/sonjari.exe" -m alture_jarvis.claude_hooks')
    assert '--alias "C:/Users/x/AppData/Local/Microsoft/WindowsApps/sonjari.exe"' in store[0][2]


def test_pythonw_is_swapped_for_python_because_hooks_must_print(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    (tmp_path / "python.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert scribe_hooks._python().name == "python.exe"


def test_style_file_is_passed_only_when_set(tmp_path: Path) -> None:
    assert "--style-file" not in scribe_hooks.hook_commands(_config(tmp_path))[0][2]
    with_style = scribe_hooks.hook_commands(_config(tmp_path, scribe_style_file="C:/me/style.md"))
    assert '--style-file "C:/me/style.md"' in with_style[0][2]


STORY = {"enabled": True, "count": 2, "index": "- 색인 속도 (10-22) 줄 30 · 20",
         "card": "## 정한 것\n- 예전 결정  (10-21 09:00 · 줄 10 · 「옛 인용」)\n- 새 결정  (10-22 10:00 · 줄 20 · 「새 인용」)"}


def test_after_compact_puts_index_and_newest_cards_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_hooks, "_story", lambda *_: dict(STORY))
    out = claude_hooks.after_compact({"session_id": "s1", "source": "compact", "transcript_path": "C:/t/s1.jsonl"},
                                     {"base-url": "http://127.0.0.1:8091", "token-file": "x"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "주제 색인" in text and "색인 속도" in text and "open-line" in text
    assert text.index("새 결정") < text.index("예전 결정"), "칸마다 최신 카드부터"
    assert "옛 인용" not in text and "(10-22 10:00 · 줄 20)" in text, "인용은 빼고 줄 번호만"
    assert out["systemMessage"].startswith("대화가 접혔습니다. 서기 카드를 다시 넣었습니다 — 정한 것 2")


def test_startup_shows_the_previous_conversations_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "old.jsonl").write_text("{}\n", encoding="utf-8")
    (folder / "new.jsonl").write_text("{}\n", encoding="utf-8")
    seen: list[str] = []
    monkeypatch.setattr(claude_hooks, "_story", lambda base, token, session: seen.append(session) or dict(STORY))
    out = claude_hooks.after_compact({"session_id": "new", "source": "startup", "transcript_path": str(folder / "new.jsonl")},
                                     {"alias": "C:/a/sonjari.exe"})
    assert seen == ["old"] and "바로 앞 대화의 주제 색인(old)" in out["hookSpecificOutput"]["additionalContext"]
    assert '"C:/a/sonjari.exe" -m alture_jarvis.claude_hooks open-line' in out["hookSpecificOutput"]["additionalContext"]
    assert "정한 것" not in out["hookSpecificOutput"]["additionalContext"], "새 세션엔 색인만(카드는 안 넣음)"


def test_sonjari_off_means_no_cards_and_a_plain_reason(tmp_path: Path) -> None:
    out = claude_hooks.after_compact({"session_id": "s1", "source": "compact"}, {"token-file": str(tmp_path / "none")})
    assert "못 넣었습니다(손자리 열쇠 파일이 없음)" in out["systemMessage"]


def test_save_compact_keeps_summary_and_cards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_hooks, "_story", lambda *_: dict(STORY))
    out = claude_hooks.save_compact({"session_id": "s1", "trigger": "auto", "compact_summary": "요약 글"},
                                    {"log-dir": str(tmp_path / "log")})
    saved = json.loads(next((tmp_path / "log" / "s1").glob("*.json")).read_text(encoding="utf-8"))
    assert saved["summary"] == "요약 글" and "새 결정" in saved["cards"] and saved["trigger"] == "auto"
    assert "1번째" in out["systemMessage"]


def test_the_hook_file_runs_on_its_own_with_only_the_standard_library(tmp_path: Path) -> None:
    log = tmp_path / "s.jsonl"
    rows = [{"type": "user", "message": {"role": "user", "content": f"말 {i}"}} for i in range(5)]
    log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    script = Path(claude_hooks.__file__)
    done = subprocess.run([sys.executable, "-I", str(script), "open-line", str(log), "2", "1"], capture_output=True,
                          text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0 and "▶ [2] 사람: 말 2" in done.stdout and "[1]" in done.stdout and "[3]" in done.stdout
    quiet = subprocess.run([sys.executable, "-I", str(script), "after-compact", "--token-file", str(tmp_path / "x")],
                           input="{}", capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert quiet.returncode == 0, "손자리가 없어도 훅은 넘어지지 않는다"


def test_tests_cannot_touch_the_real_settings_before_start(tmp_path: Path) -> None:
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.runtime import JarvisRuntime

    runtime = JarvisRuntime(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                                         scribe_enabled=True))
    assert runtime._sync_scribe_hooks() == {"skipped": "앱이 시작되지 않음"}
