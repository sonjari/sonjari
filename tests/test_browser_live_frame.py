"""자비스가 보는 화면을 사람도 본다 — 그 경로가 지켜야 할 것들 (R2).

여기서 못 박는 것은 **그림이 예쁜지가 아니라 안전한지**다.

  1. 화면을 보는 것이 크롬을 여는 계기가 되면 안 된다(폴링 한 번이 몰래 창을 띄운다)
  2. 앞 동작에 줄 서지 않는다 — 브라우저 일꾼은 하나뿐이라, 줄 서면 자비스가 멈춘다
  3. 못 찍었으면 **왜**를 말한다. 503 만 오면 화면은 "브라우저가 없다"밖에 못 하는데
     실제 이유는 안 떠 있음·붙기 실패·앞 동작에 물림으로 다 다르고 사람이 할 일도 다르다
  4. 캐시 금지 — 1.5초마다 같은 주소를 부르므로 한 장이 붙들리면 화면이 멈춘 것처럼 보인다
"""

from __future__ import annotations

import time
from urllib.parse import unquote

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig


def _config(tmp_path) -> JarvisConfig:
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )


def test_frame_never_starts_the_browser(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    started: list[str] = []
    runtime.browser._ensure_started = lambda: started.append("boom")  # type: ignore[method-assign]

    with TestClient(app) as client:
        response = client.get("/v1/browser/frame.jpg")

    assert response.status_code == 503
    assert started == [], "화면을 본 것만으로 브라우저가 떴다"
    assert unquote(response.headers["X-Jarvis-Frame-Reason"]) == "browser_not_started"
    assert response.headers["X-Jarvis-Frame-Fresh"] == "0"


def test_frame_says_why_it_could_not_look(tmp_path) -> None:
    """앞 동작에 물려 못 찍은 것과 브라우저가 꺼진 것은 사람이 할 일이 다르다."""
    app = create_app(_config(tmp_path), start_services=False)
    browser = app.state.jarvis.browser
    browser._connected = True

    def busy() -> dict:
        raise RuntimeError("browser_busy_active — 브라우저가 앞 동작(browser_open)을 12초째 실행 중입니다.")

    browser._capture_live_frame = busy  # type: ignore[method-assign]

    with TestClient(app) as client:
        response = client.get("/v1/browser/frame.jpg")

    assert response.status_code == 503
    assert "browser_busy_active" in unquote(response.headers["X-Jarvis-Frame-Reason"])


def test_a_captured_frame_carries_where_it_was(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    browser = app.state.jarvis.browser
    browser._connected = True
    browser._capture_live_frame = lambda: {  # type: ignore[method-assign]
        "jpeg": b"\xff\xd8\xff\xdb-fake-jpeg",
        "url": "https://www.kmong.com/search?q=RAG",
        # 한글 제목은 흔하다. 헤더는 latin-1 이라 그대로 실으면 응답이 통째로 깨진다.
        "title": "크몽 · RAG 검색 결과",
        "at": time.time(),
    }

    with TestClient(app) as client:
        response = client.get("/v1/browser/frame.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8\xff")
    assert response.headers["X-Jarvis-Frame-Url"] == "https://www.kmong.com/search?q=RAG"
    assert unquote(response.headers["X-Jarvis-Frame-Title"]) == "크몽 · RAG 검색 결과"
    assert response.headers["X-Jarvis-Frame-Fresh"] == "1"
    # 웹뷰가 한 장을 붙들면 화면이 멈춘 것처럼 보인다. 그게 제일 알아채기 어렵다.
    assert "no-store" in response.headers["Cache-Control"]


def test_a_stale_frame_is_served_but_marked_stale(tmp_path) -> None:
    """바쁘면 마지막 장을 준다 — 다만 **낡았다고 말하고** 준다.

    화면을 비우는 것보다 낫지만, 낡은 것을 새것처럼 주면 그게 제일 나쁘다:
    자비스는 이미 다른 페이지에 가 있는데 사람은 옛 화면을 보며 판단하게 된다.
    """
    app = create_app(_config(tmp_path), start_services=False)
    browser = app.state.jarvis.browser
    browser._connected = True
    browser._last_frame = {
        "jpeg": b"\xff\xd8\xff\xdb-old", "url": "https://old.example", "title": "",
        "at": time.time() - 30,
    }

    def busy() -> dict:
        raise RuntimeError("browser_busy_stuck — 앞 동작에 12초째 물려 있습니다")

    browser._capture_live_frame = busy  # type: ignore[method-assign]

    with TestClient(app) as client:
        response = client.get("/v1/browser/frame.jpg")

    assert response.status_code == 200
    assert response.headers["X-Jarvis-Frame-Fresh"] == "0"
    assert float(response.headers["X-Jarvis-Frame-Age"]) >= 29
    assert "browser_busy_stuck" in unquote(response.headers["X-Jarvis-Frame-Reason"])


def test_repeat_calls_do_not_re_capture(tmp_path) -> None:
    """창 여럿이 같이 보고 있어도 캡처는 간격 안에서 한 번만 일어난다."""
    app = create_app(_config(tmp_path), start_services=False)
    browser = app.state.jarvis.browser
    browser._connected = True
    captures: list[float] = []

    def capture() -> dict:
        captures.append(time.time())
        return {"jpeg": b"\xff\xd8\xff\xdb-x", "url": "https://example", "title": "", "at": time.time()}

    browser._capture_live_frame = capture  # type: ignore[method-assign]

    with TestClient(app) as client:
        for _ in range(4):
            assert client.get("/v1/browser/frame.jpg").status_code == 200

    assert len(captures) == 1, f"같은 순간에 {len(captures)}번 찍었다"


def test_a_busy_pump_does_not_freeze_the_view(tmp_path) -> None:
    """심장박동과 부딪혔다고 화면이 멈추면 안 된다 (2026-08-19 라이브에서 잡았다).

    펌프는 250ms 돌고 250ms 쉬므로 브라우저 일꾼을 **절반쯤 붙들고 있다.** 그리고
    `_submit` 의 0.75초 양보는 `background=False` 인 호출에만 주는데, 이 캡처는 스스로
    background 라(에이전트가 내 캡처를 기다려 주게 하려고) 그 양보를 못 받는다.

    실측: 배포 직후 34초 동안 계속 `browser_busy_active(browser_pump)` 였고, 화면에는
    낡은 장이 계속 걸려 있었다. 이유를 안 읽으면 "갱신이 멈췄다"로만 보인다.
    """
    app = create_app(_config(tmp_path), start_services=False)
    browser = app.state.jarvis.browser
    browser._connected = True
    tries: list[int] = []

    def busy_then_ready() -> dict:
        tries.append(1)
        if len(tries) < 3:
            raise RuntimeError("browser_busy_active — 브라우저가 앞 동작(browser_pump)을 0초째 실행 중입니다.")
        return {"jpeg": b"\xff\xd8\xff\xdb-ok", "url": "https://www.naver.com/", "title": "NAVER", "at": time.time()}

    browser._capture_live_frame = busy_then_ready  # type: ignore[method-assign]

    with TestClient(app) as client:
        response = client.get("/v1/browser/frame.jpg")

    assert response.status_code == 200
    assert response.headers["X-Jarvis-Frame-Fresh"] == "1", "펌프에 밀려 낡은 장만 돌려줬다"
    assert len(tries) == 3


def test_it_does_not_keep_retrying_what_will_not_clear(tmp_path) -> None:
    """물렸거나(stuck) 회로가 열린 것은 기다린다고 안 풀린다 — 바로 사실을 말한다."""
    app = create_app(_config(tmp_path), start_services=False)
    browser = app.state.jarvis.browser
    browser._connected = True
    tries: list[int] = []

    def stuck() -> dict:
        tries.append(1)
        raise RuntimeError("browser_busy_stuck — 앞 동작에 12초째 물려 있습니다")

    browser._capture_live_frame = stuck  # type: ignore[method-assign]

    with TestClient(app) as client:
        assert client.get("/v1/browser/frame.jpg").status_code == 503

    assert len(tries) == 1, f"안 풀릴 것을 {len(tries)}번 다시 시도했다"
