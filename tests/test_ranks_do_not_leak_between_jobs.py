"""지난 판의 검색 순위가 다음 판으로 새면 **딴 사이트를 읽고 여기서 읽었다고 센다.**

## 실측 (2026-08-14, 사람인 판)

    (직전 판) 대학알리미 과제 — browser_search 로 순위 15개를 만들었다
    (다음 판) 사람인 과제 — 레시피로 사람인 검색 결과에 도착했다
       4  browser_open_result rank=38 → 실패 "있는 순위: 1, 2, … 15"   ← 남의 순위다
       5  browser_open_result rank=1  → **academyinfo.go.kr** 로 갔다
       7  browser_extract             → 대학알리미 본문을 읽었다(cc=1432)
      12  browser_extract             → 또 읽었다

**사람인 화면에 서서 대학알리미를 열고 읽었다.** 그리고 그것이 "읽은 출처"로
세어졌다. 광고 브리지 사고와 같은 부류인데, 이쪽 원인은 **우리 상태**다.

## 경계는 화면이 아니라 판이다

"결과를 딴 화면과 지금 화면이 다르면 버린다"로 하면 정상 경로가 깨진다 —
결과 → 상세로 들어간 뒤 `rank 2` 를 여는 것이 바로 그 모양이고 그게 이 도구의
존재 이유다. 그러니 잡이 시작될 때 버린다.

이어받은 판(checkpoint)은 **안 버린다.** 그 순위가 이어서 쓰려던 바로 그것이다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            control_token="t",
            camera_enabled=False,
            vision_enabled=False,
            voice_enabled=False,
            tts_enabled=False,
            camera_control_enabled=False,
        )
    )


def test_forgetting_clears_the_ranks(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    worker._last_results = [
        {"rank": 1, "url": "https://www.academyinfo.go.kr/search/search.do", "title": "대학알리미"}
    ]
    worker._reads_since_search = 3
    worker._searched_before = True

    worker.forget_results()

    assert worker._last_results == []
    assert worker._reads_since_search == 0
    assert worker._searched_before is False


def test_a_stale_rank_would_have_opened_another_site(tmp_path: Path) -> None:
    """왜 이게 위험한지를 시험이 직접 보여 준다.

    버리지 않으면 `_open_result` 가 **남의 주소**를 그대로 연다. 이 단정이 깨지는
    날은 좋은 날이다(그때는 다른 장치가 막고 있다는 뜻).
    """
    worker = _worker(tmp_path)
    worker._last_results = [
        {"rank": 1, "url": "https://www.academyinfo.go.kr/search/search.do", "title": "대학알리미"}
    ]
    stale = next(item for item in worker._last_results if item["rank"] == 1)
    assert "academyinfo" in stale["url"], "이 주소가 사람인 판에서 열렸다"


def test_the_agent_forgets_at_the_start_of_a_fresh_run() -> None:
    """도구를 만들어 놓고 안 부르면 아무것도 안 고쳐진다.

    그리고 **이어받은 판에서는 부르면 안 된다** — 그 순위가 이어서 쓰려던 것이다.
    """
    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py"
    ).read_text(encoding="utf-8")

    assert "self.browser.forget_results()" in source
    # 새 판 갈래(else 뒤, steps 초기화 근처)에만 있어야 한다.
    before, _, after = source.partition("self.browser.forget_results()")
    assert before.rstrip().endswith("pass") or "messages.append" in before[-2000:], (
        "새 판을 준비하는 자리가 아닌 곳에서 부르고 있다"
    )
    assert "steps = []" in after[:400], "판 초기화 자리 옆에 있어야 한다"
