"""설정 › 서기 · 이어받기 안내 (2026-10-22 대표 — 서기를 실험실에서 꺼내고, 이어받기를 어떻게 시작하는지 알려 준다).

- 서기 폴더를 손으로 치지 않게: 이 PC 의 클로드 코드 프로젝트를 찾아 작업 폴더 이름 · 대화 수 · 마지막 시각으로 준다.
- 시험은 진짜 사용자 폴더(`~/.claude`)를 읽지 않는다 — `home` 을 임시 폴더로 준다.
- 화면의 이어받기 예시 문장은 실제로 이어받기 문(`_WORTH_ASKING`)을 지나야 한다. 안 지나면 안내가 거짓말이 된다.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.scribe import claude_projects, scribe_status
from alture_jarvis.settings import BY_KEY, GROUPS
from alture_jarvis.takeover import _WORTH_ASKING

UI = Path(__file__).resolve().parents[1] / "ui" / "src"


def _log(folder: Path, name: str, cwd: str, mtime: float) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.jsonl"
    rows = [{"type": "queue-operation"}, {"type": "user", "cwd": cwd, "message": {"role": "user", "content": "안녕"}}]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    projects = home / ".claude" / "projects"
    _log(projects / "E----------", "old", "E:\\내 가게", 1_000)
    _log(projects / "E----------", "new", "E:\\내 가게", 5_000)
    _log(projects / "D--side", "a", "D:\\side", 3_000)
    _log(projects / "C--Users-me-AppData-Local-Temp-x", "a", "C:\\Users\\me\\AppData\\Local\\Temp\\x", 4_000)
    (projects / "empty").mkdir()
    return home


def test_projects_are_listed_newest_first_with_the_workdir_people_recognize(tmp_path: Path) -> None:
    found = claude_projects(_home(tmp_path))
    assert [item["name"] for item in found] == ["E----------", "C--Users-me-AppData-Local-Temp-x", "D--side"], "기록 없는 폴더는 뺀다"
    first = found[0]
    assert first["workdir"] == "E:\\내 가게" and first["sessions"] == 2 and first["last_at"] == 5_000
    assert [item["temp"] for item in found] == [False, True, False], "임시 폴더 대화는 표시만(지우지 않는다)"
    assert claude_projects(tmp_path / "nobody") == [], "클로드 코드를 안 쓴 PC 는 빈 목록"


def test_status_marks_chosen_projects_and_keeps_a_chosen_folder_that_is_not_listed(tmp_path: Path) -> None:
    home = _home(tmp_path)
    chosen = home / ".claude" / "projects" / "D--side"
    gone = tmp_path / "gone-project"
    fake = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path / "data", scribe_enabled=True,
                                                  scribe_folders=f"{chosen};{gone}"))
    fake._scribe_folders = lambda: JarvisRuntime._scribe_folders(fake)
    view = JarvisRuntime.scribe_status(fake, home=home)
    picked = {item["name"]: item["chosen"] for item in view["projects"]}
    assert picked["D--side"] is True and picked["E----------"] is False
    tail = view["projects"][-1]
    assert tail["folder"] == str(gone) and tail["chosen"] and tail["missing"], "목록 밖에서 고른 폴더도 보여야 끌 수 있다"
    assert view["enabled"] is True and view["hooks"] == {"installed": False, "events": []}
    assert view["cards"] == 0 and view["last_read_at"] == 0.0


def test_status_counts_open_and_closed_cards_without_calling_a_model(tmp_path: Path) -> None:
    root = tmp_path / "data" / "scribe"
    root.mkdir(parents=True)
    rows = [{"kind": "decided", "text": "가", "line": 1, "session": "s"}, {"kind": "open", "text": "나", "line": 2, "session": "s"}]
    from alture_jarvis.scribe import card_id

    rows.append({"op": "close", "id": card_id(rows[1]), "why": "done"})
    (root / "cards.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    (root / "state.json").write_text("{}", encoding="utf-8")
    view = scribe_status(tmp_path / "data", [])
    assert view["cards"] == 1 and view["closed"] == 1 and view["last_read_at"] > 0


def test_scribe_left_the_labs_and_has_its_own_section() -> None:
    for key in ("scribe_enabled", "scribe_folders"):
        assert BY_KEY[key].group == "scribe" and not BY_KEY[key].lab and BY_KEY[key].live
    assert "scribe" not in {gid for gid, _ in GROUPS}, "왼쪽 목록은 화면의 「사용자 지정 › 서기」가 그린다"
    screen = (UI / "workspace" / "SettingsScreen.tsx").read_text(encoding="utf-8")
    assert 'id: "scribe"' in screen and "<ScribeSection" in screen


def test_takeover_phrases_on_screen_actually_open_the_takeover_door() -> None:
    source = (UI / "workspace" / "TakeoverHowTo.tsx").read_text(encoding="utf-8")
    line = next(row for row in source.splitlines() if "TAKEOVER_PHRASES =" in row)
    phrases = re.findall(r't\("([^"]+)"\)', line)
    en = json.loads((UI / "i18n" / "en.json").read_text(encoding="utf-8"))
    assert len(phrases) == 2
    for phrase in phrases + [en[phrase] for phrase in phrases]:
        assert _WORTH_ASKING.search(phrase), f"안내 문장이 이어받기 문을 못 지난다: {phrase}"
    wizard = (UI / "setup" / "SetupWizard.tsx").read_text(encoding="utf-8")
    assert "<TakeoverHowTo" in wizard, "마법사 「연결」 칸에서 한 번 알려 준다"
    assert '{section === "takeover" && <TakeoverHowTo' in (UI / "workspace" / "SettingsScreen.tsx").read_text(encoding="utf-8")
