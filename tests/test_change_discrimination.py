"""기대가 빗나갔을 때 "안 눌렸다"와 "다른 게 일어났다"를 가른다.

2026-08-05 실측: 커리어넷에서 메뉴를 눌렀더니 `url_changes` 가 빗나갔는데 화면은
분명히 바뀌어 있었다 — 조작 가능한 요소가 73개에서 75개로 늘고 하위 메뉴가 열렸다.
`unknown` 하나로 뭉뚱그리면 그것과 "정말 아무 일도 없었다"가 같은 얼굴이 된다.

다음 수가 완전히 다르다:
  changed_otherwise -> 눌렸다. 기대를 잘못 걸었을 뿐이니 화면을 다시 읽고 이어간다.
  unchanged         -> 막혔다. 사람이 봐야 한다.

둘 다 **재시도는 아니다**. 눌렸는데 확인만 못 했을 수 있고, 그러면 두 번 눌린다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.attention import classify
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"
        )
    )


def _signals(**overrides: Any) -> dict[str, Any]:
    base = {"url": "https://a.test/", "title": "가", "operable": 73, "text_len": 100, "text_hash": "aaa", "dialog": ""}
    base.update(overrides)
    return base


def test_a_menu_that_opened_reads_as_a_change(tmp_path: Path) -> None:
    """커리어넷에서 실제로 일어난 일: 주소는 그대로, 요소는 73->75."""
    notes = _worker(tmp_path)._explain_change(
        _signals(), _signals(operable=75, text_hash="bbb", text_len=140)
    )

    assert any("73개에서 75개" in note for note in notes)
    assert any("화면 글이 바뀌었습니다" in note for note in notes)


def test_a_dead_click_reads_as_nothing(tmp_path: Path) -> None:
    assert _worker(tmp_path)._explain_change(_signals(), _signals()) == []


def test_a_popup_is_called_out_by_name(tmp_path: Path) -> None:
    # 눌렀는데 아무 일도 안 일어난 것처럼 보이는 가장 흔한 이유다.
    notes = _worker(tmp_path)._explain_change(_signals(), _signals(dialog="정말 삭제하시겠습니까?"))

    assert notes == ["덮는 화면이 떴습니다: 정말 삭제하시겠습니까?"]


def test_a_mega_menu_does_not_flood_the_note(tmp_path: Path) -> None:
    """워크넷 실측: 메뉴 전체가 잡혀 200자가 한 줄로 들어왔다. 그러면 무엇이 떴는지
    사람도 모델도 못 읽는다."""
    notes = _worker(tmp_path)._explain_change(_signals(), _signals(dialog="채용정보 " * 60))

    assert len(notes[0]) < 120


def test_navigation_is_named_with_the_new_address(tmp_path: Path) -> None:
    notes = _worker(tmp_path)._explain_change(_signals(), _signals(url="https://b.test/"))

    assert "https://b.test/" in notes[0]


# ── 이 판정이 사람을 부를지 말지까지 바꾼다 ──────────────────────────────────
def test_something_else_happening_does_not_wake_a_person() -> None:
    """에이전트가 화면을 다시 읽고 이어갈 수 있는 상황이다. 이런 것까지 울리면
    진짜일 때 아무도 안 본다."""
    observation = {
        "ok": True,
        "result": {
            "action": "clicked",
            "verified": False,
            "verification": {"status": "changed_otherwise", "changes": ["조작 가능한 요소가 73개에서 75개로 바뀌었습니다"]},
        },
    }

    assert classify(observation) is None


def test_nothing_happening_does_wake_a_person() -> None:
    observation = {
        "ok": True,
        "result": {
            "action": "clicked",
            "verified": False,
            "verification": {"status": "unchanged", "changes": []},
        },
    }

    rule = classify(observation)
    assert rule is not None and rule.code == "change_not_verified"


def test_an_old_style_result_without_a_status_still_wakes_a_person() -> None:
    """판정 정보가 없으면 모르는 것이다. 모를 때는 사람 쪽으로 기운다."""
    rule = classify({"ok": True, "result": {"action": "clicked", "verified": False}})

    assert rule is not None and rule.code == "change_not_verified"
