"""3D 무대 알림(`gen3d_stage`) — 실행기가 단계를 바꿀 때마다 화면에 알리고, 그 알림이 어느 판으로 가는지 (2026-11-14).

양방향:
- 해야 할 것: 단계 · 끝을 알린다 · 앱 판에서 부르면 그 판으로 · 클로드가 MCP 로 바로 부르면 `gen3d:<번호>` 로 ·
  단계 안 비율은 화면 칸(part · parts)으로 · 넣은 그림 사본은 내준다.
- 하면 안 되는 것: 남은 시간을 싣는다 · 실행기 칸 이름(sub · started_at)을 그대로 흘린다 · 원본 그림 경로를 알림에 싣는다 ·
  판 폴더 밖 · 영수증 밖 이름을 내준다 · 알림이 실패하면 3D 만들기가 멈춘다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from test_gen3d_1114 import _Config, _Packs, _runner, _wait

from alture_jarvis.gen3d_tools import Gen3DTools


def _tools(tmp_path: Path) -> tuple[Gen3DTools, list[tuple[str, dict[str, Any]]]]:
    tools = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    runner = _runner(tmp_path)
    tools._runner = runner
    runner.on_change = tools._emit
    sent: list[tuple[str, dict[str, Any]]] = []
    tools.publish = lambda event, payload: sent.append((event, payload))
    return tools, sent


def _wait_done_event(sent: list[tuple[str, dict[str, Any]]], gen_id: str) -> None:
    """상태가 done 이 된 뒤 마지막 알림이 나가기까지 틈이 있다 — 알림이 실제로 올 때까지 기다린다."""
    import time

    for _ in range(300):
        if any(p.get("gen_id") == gen_id and p.get("state") in {"done", "failed"} for _, p in sent):
            return
        time.sleep(0.02)
    raise AssertionError("done 알림이 안 왔다")


def _image(tmp_path: Path) -> Path:
    image = tmp_path / "private_folder" / "ship.png"
    image.parent.mkdir()
    image.write_bytes(b"\x89PNG fake")
    return image


def test_stages_and_the_end_are_announced_to_the_calling_job(tmp_path: Path) -> None:
    tools, sent = _tools(tmp_path)
    out = tools.gen_3d({"image_path": str(_image(tmp_path)), "__job_id": "job_abc"})
    assert out["ok"]
    _wait(tools.runner, out["job_id"])
    _wait_done_event(sent, out["job_id"])
    events = [payload for name, payload in sent if name == "gen3d_stage"]
    assert events, "알림이 하나도 없다"
    # 판 주인이 정해진 뒤의 알림은 전부 그 판으로 간다
    owned = [e for e in events if e["job_id"] == "job_abc"]
    assert owned and owned[-1]["state"] == "done"
    assert owned[-1]["receipt"]["measured"]["faces"] > 0
    # 단계가 1 → 7 로 나아가는 것이 알림에 보인다(실측 로그 그대로 흘림)
    indexes = [e["stage"]["index"] for e in events if e.get("stage")]
    assert indexes and indexes == sorted(indexes)


def test_a_direct_mcp_call_has_no_job_so_it_goes_to_a_gen3d_lane(tmp_path: Path) -> None:
    tools, sent = _tools(tmp_path)
    out = tools.gen_3d({"image_path": str(_image(tmp_path))})  # MCP /v1/tools/execute — __job_id 없음
    _wait(tools.runner, out["job_id"])
    _wait_done_event(sent, out["job_id"])
    lanes = {payload["job_id"] for _, payload in sent}
    assert lanes == {f"gen3d:{out['job_id']}"}


def test_the_screen_gets_part_and_parts_never_the_remaining_time_or_runner_fields(tmp_path: Path) -> None:
    tools, sent = _tools(tmp_path)
    out = tools.gen_3d({"image_path": str(_image(tmp_path)), "__job_id": "job_abc"})
    _wait(tools.runner, out["job_id"])
    stages = [payload["stage"] for _, payload in sent if payload.get("stage")]
    assert stages
    for stage in stages:
        assert "sub" not in stage and "started_at" not in stage
        assert not any("left" in str(value) or "remain" in str(key) for key, value in stage.items())
        if "part" in stage:
            assert 0 <= stage["part"] <= stage["parts"]
    # 원본 그림 경로(사용자 폴더)는 알림 어디에도 없다 — 판 폴더 안 사본 이름만
    blob = repr(sent)
    assert "private_folder" not in blob
    assert all(payload.get("image") in (None, "input.png") for _, payload in sent)


def test_the_input_copy_is_served_but_nothing_else_outside_the_receipt(tmp_path: Path) -> None:
    tools, _ = _tools(tmp_path)
    out = tools.gen_3d({"image_path": str(_image(tmp_path))})
    _wait(tools.runner, out["job_id"])
    served = tools.runner.file_for(out["job_id"], "input.png")
    assert served is not None and served.read_bytes() == b"\x89PNG fake"
    assert tools.runner.file_for(out["job_id"], "run.log") is None
    assert tools.runner.file_for(out["job_id"], "job.json") is None
    assert tools.runner.file_for(out["job_id"], "../input.png") is None


def test_a_broken_screen_does_not_stop_the_3d_run(tmp_path: Path) -> None:
    tools, _ = _tools(tmp_path)

    def broken(event: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("화면이 죽었다")

    tools.publish = broken
    out = tools.gen_3d({"image_path": str(_image(tmp_path)), "__job_id": "job_abc"})
    assert _wait(tools.runner, out["job_id"])["state"] == "done"
