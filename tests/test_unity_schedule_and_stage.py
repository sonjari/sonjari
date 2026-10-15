"""게임 팩 정기 점검과 유니티 무대 (2026-09-27).

정기 점검: 모델 없이 정해 둔 시각에 돌고, 첫 판은 기준만, 늘었을 때만 부르고, 에디터가 열려 있으면 미룬다.
무대: 그림이 바뀔 때만 새 장, 최소화면 그렇다고 말하고, 창을 앞으로 가져오는 것은 「직접 하기」 뿐.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis.unity_schedule import RecipeSchedule, watch_numbers
from alture_jarvis.unity_stage import UnityStage


class FakeUnity:
    packs = None

    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.calls: list[dict[str, Any]] = []

    def enabled(self) -> bool:
        return True

    def recipes(self) -> dict[str, dict[str, Any]]:
        return {
            "missing_references": {"title": "빠진 참조 찾기", "risk": "L1", "params": {},
                                   "watch": {"missing_references": "끊긴 참조", "missing_scripts": "빠진 스크립트"}},
            "fixer": {"title": "고치기", "risk": "L2", "params": {}},
        }

    def _params(self, recipe: dict[str, Any], given: dict[str, Any]) -> dict[str, Any]:
        return dict(given)

    def _project(self, arguments: dict[str, Any], *, write: bool) -> Path:
        return Path(str(arguments["project"]))

    def run_recipe(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(arguments)
        return {"verified": True, "elapsed_sec": 12.0, "result": self.results.pop(0), "result_file": "r.json"}


class Attention:
    def __init__(self) -> None:
        self.notices: list[dict[str, Any]] = []

    def announce(self, **notice: Any) -> None:
        self.notices.append(notice)


def _schedule(tmp_path: Path, results: list[dict[str, Any]], clock: list[datetime], editor_open: list[bool]):
    unity = FakeUnity(results)
    attention = Attention()
    service = RecipeSchedule(SimpleNamespace(data_dir=tmp_path), unity, attention=attention,
                             now=lambda: clock[0], project_open=lambda _p: editor_open[0])
    return service, unity, attention


def test_watch_numbers_reads_plain_and_aggregated_fields() -> None:
    result = {"flagged_total": 3, "ok": True, "scenes": [{"triangles": 10}, {"triangles": 40, "realtime_lights": 2}]}
    assert watch_numbers(result, {"flagged_total": "", "max:scenes.triangles": "", "sum:scenes.realtime_lights": "", "gone": ""}) == {
        "flagged_total": 3.0, "max:scenes.triangles": 40.0, "sum:scenes.realtime_lights": 2.0}


def test_it_runs_at_the_set_time_once_a_day_and_only_calls_when_worse(tmp_path: Path) -> None:
    clock = [datetime(2026, 9, 28, 2, 59)]
    editor_open = [False]
    results = [{"missing_references": 2, "missing_scripts": 0}, {"missing_references": 5, "missing_scripts": 0}]
    service, unity, attention = _schedule(tmp_path, results, clock, editor_open)
    item = service.add({"recipe": "missing_references", "project": "E:/P", "at": "03:00"})

    assert service.tick() == [] and unity.calls == [], "시각 전에는 안 돈다"
    clock[0] = datetime(2026, 9, 28, 3, 0)
    first = service.tick()
    assert first[0]["verified"] and unity.calls[0]["recipe"] == "missing_references"
    assert attention.notices == [], "첫 판은 기준만 잡고 조용히 있는다"
    clock[0] = datetime(2026, 9, 28, 9, 0)
    assert service.tick() == [], "하루에 한 번"

    clock[0] = datetime(2026, 9, 29, 3, 1)
    second = service.tick()[0]
    assert second["worse"] == {"missing_references": [2.0, 5.0]}
    assert len(attention.notices) == 1 and "끊긴 참조 2→5" in attention.notices[0]["message"]
    listed = service.listing()[0]
    assert listed["id"] == item["id"] and listed["last"]["numbers"]["missing_references"] == 5.0


def test_an_open_editor_defers_the_run_instead_of_closing_it(tmp_path: Path) -> None:
    clock = [datetime(2026, 9, 28, 3, 0)]
    editor_open = [True]
    service, unity, _ = _schedule(tmp_path, [{"missing_references": 1, "missing_scripts": 0}], clock, editor_open)
    service.add({"recipe": "missing_references", "project": "E:/P", "at": "03:00"})
    out = service.tick()[0]
    assert out["deferred"] and unity.calls == [] and "에디터가 열려 있어 미룸" in service.listing()[0]["deferred"]
    editor_open[0] = False
    clock[0] = datetime(2026, 9, 28, 10, 0)
    assert service.tick()[0]["verified"], "그날 안에 닫히면 그때 돈다"


def test_weekday_schedules_skip_weekends_and_writers_are_refused(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 3, 4, 0)]  # 토요일
    service, unity, _ = _schedule(tmp_path, [], clock, [False])
    service.add({"recipe": "missing_references", "project": "E:/P", "at": "03:00", "days": "weekday"})
    assert service.tick() == [] and unity.calls == []
    with pytest.raises(ValueError, match="schedule_read_only"):
        service.add({"recipe": "fixer", "project": "E:/P"})
    with pytest.raises(ValueError, match="schedule_time"):
        service.add({"recipe": "missing_references", "project": "E:/P", "at": "25:00"})


def test_schedules_are_not_model_tools() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "unity_tools.py").read_text(encoding="utf-8")
    assert "unity_schedule" not in source.split("def ollama_tools", 1)[1], "스스로 도는 일감은 사람만 만든다(설정 화면)"


# ── 무대 ────────────────────────────────────────────────────────────────


def test_the_stage_only_makes_new_frames_when_the_picture_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    window = {"hwnd": 7, "title": "Game - Main - Unity 6.6", "width": 1920, "height": 1080, "minimized": False}
    pictures = [b"A", b"A", b"B"]
    fronted: list[int] = []
    clock = [0.0]
    stage = UnityStage(find=lambda: [window], grab=lambda hwnd: (pictures.pop(0), 1600, 900),
                       front=lambda hwnd: fronted.append(hwnd) or True, clock=lambda: clock[0])
    monkeypatch.setattr("alture_jarvis.unity_stage.time.sleep", lambda _s: clock.__setitem__(0, clock[0] + 0.25))
    first = stage.frame(after=0, wait=0)
    assert first and first["seq"] == 1
    clock[0] += 1
    assert stage.frame(after=1, wait=0) is None, "그림이 같으면 새 장이 아니다"
    clock[0] += 1
    assert stage.frame(after=1, wait=0)["seq"] == 2
    assert fronted == [], "비추기는 창을 앞으로 가져오지 않는다"
    assert stage.take_over()["ok"] and fronted == [7], "「직접 하기」만 창을 앞으로"


def test_a_minimized_editor_is_named_not_shown_black() -> None:
    window = {"hwnd": 7, "title": "Game - Unity", "width": 160, "height": 28, "minimized": True}
    grabbed: list[int] = []
    stage = UnityStage(find=lambda: [window], grab=lambda hwnd: grabbed.append(hwnd) or (b"x", 1, 1), front=lambda h: True)
    assert stage.frame(after=0, wait=0) is None and stage.problem == "minimized" and grabbed == []
    assert stage.status()["status"] == "minimized"
    assert UnityStage(find=lambda: [], grab=lambda h: (b"", 0, 0), front=lambda h: True).status()["status"] == "no_editor"
