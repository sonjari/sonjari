"""만든 화면을 **눈으로** 본다 — 화면에 안 보이는 별도 크롬으로 통째로 찍어 모델에게 보여 준다 (2026-10-11).

## 왜

손자리는 화면을 못 찍었다. 손자리의 크롬은 사람의 화면을 가리지 않으려고 뒤에서 도는데, 뒤에 있는 탭은 그림으로 찍히지
않는다(판 43c92b51 — 세 번 시도해 세 번 실패). 찍혀도 그 그림은 사람이 볼 증거로만 저장되고 모델에게 가지 않았다.
그래서 디자인 스킬이 「화면을 찍어 확인하라」고 해도 따를 길이 없었고, 화면을 못 본 모델은 좌표 숫자로 짐작했다(틀렸다).

계산 검사(`layout_probe`)는 「글자가 덮였다 · 삐져나갔다 · 그림이 깨졌다」처럼 참·거짓이 분명한 것만 잰다.
못생긴 것 · 어색한 것 · 흐린 글자는 눈으로 볼 일이다.

## 어떻게

- **따로 찍는다**: 같은 크롬 실행 파일을 화면 없이(headless) · 그래픽카드 없이(`--disable-gpu`) 따로 띄워 그 주소를 새로 열고
  위에서 아래까지 통째로 찍는다. 사람이 쓰는 창과 손자리의 일하는 탭은 건드리지 않는다. 이 PC 는 같이 쓰는 PC 다.
- **통째로 보여 준다**: 화면 한 칸만 찍어 보여 줬더니 멀쩡한 페이지 6번 중 6번을 「아래가 잘렸다」고 했다(스크롤하면 나오는
  부분이다). 통째로 찍으면 그 헛짚기가 사라졌다. 조각으로 자르지 않는 까닭도 같다 — 자른 자리가 결함으로 보인다.
- **흔들리지 않게**: 온도 0. 같은 그림에 같은 말이 나온다.

## 넣기 전에 잰 것 (운영 모델 27B · 통째 그림 · 온도 0)

- 결함 있는 페이지(첫 화면의 글자가 막에 덮여 뿌옇다): 「큰 제목과 문구가 배경과 대비가 낮아 흐릿하다」 — 맞음.
- 멀쩡한 페이지 둘: 「이상 없음」.
- 조금 어색한 페이지 하나(맨 아래 섹션만 세로 막대와 제목이 떨어져 있다): 「제목이 빠졌다」 — **자리는 맞고 설명은 틀렸다.**
- 화면 한 칸만 보여 줬을 때: 결함 3번 중 2번 · 멀쩡한 것 6번 중 6번 헛짚음.
찍기 1.8초 · 보기 1~4초. 네 페이지뿐이다.

## 규율

- 눈으로 본 것은 **인상**이다 — 자리는 맞아도 설명이 틀릴 수 있다. 그래서 「틀릴 수 있다, 고치기 전에 확인하라」를 붙여서 준다.
  참·거짓이 분명한 것은 계산 검사가 말한다. 둘이 다르면 계산 쪽이 맞다.
- 따로 띄운 크롬은 **그 주소를 새로 열었을 때의 첫 모습**을 본다. 일하는 탭에서 눌러 연 창 · 담아 둔 장바구니는 거기 없다.
- 이 PC 안 페이지에서만 본다. 보다 틀어지면 아무 말도 안 한다.
"""

from __future__ import annotations

import io
import re
from typing import Any

#: 찍는 폭과, 통째로 찍되 넘지 않을 높이(아주 긴 페이지는 위에서 이만큼만 본다 — 줄여 보내면 글자가 뭉개진다).
SHOT_WIDTH = 1280
SHOT_MAX_HEIGHT = 3200
#: 모델에게 보내는 그림의 폭. 재 본 값이다(이 폭에서 흐린 글자를 알아봤다).
EYE_WIDTH = 1000
EYE_JPEG_QUALITY = 80
#: 화면에 비추는 작은 그림의 폭(`browser._IMAGE_LOOK_WIDTH` 와 같은 쓰임).
LOOK_ANSWER_TOKENS = 220
SHOT_TIMEOUT_MS = 15_000

LOOK_PROMPT = (
    "이 웹페이지 화면을 보고, 눈에 띄게 잘못돼 보이는 곳(글자가 흐리거나 안 보임 · 겹침 · 깨짐 · 잘림)이 있으면 "
    "어디가 어떻게 그런지 한두 문장으로 말해라. 없으면 「이상 없음」이라고만 답해라."
)

_NOTHING = re.compile(r"^[\s「『\"'(\[]*(?:이상\s*없(?:음|다|습니다)|문제\s*없(?:음|다|습니다)|no (?:issues?|problems?)|looks? (?:good|fine))", re.IGNORECASE)


def saw_nothing(said: str) -> bool:
    """모델이 「이상 없음」이라고 했는가 — 빈 답도 할 말이 없는 것으로 친다."""
    text = str(said or "").strip()
    return not text or bool(_NOTHING.match(text))


def shrink_for_eyes(png: bytes) -> tuple[bytes, int, int]:
    """찍은 그림을 모델에게 보낼 크기로 줄인다 → (JPEG, 폭, 높이). 못 줄이면 (b"", 0, 0)."""
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(png)).convert("RGB")
        width, height = image.size
        if width > EYE_WIDTH:
            height = max(1, int(height * EYE_WIDTH / width))
            width = EYE_WIDTH
            image = image.resize((width, height))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=EYE_JPEG_QUALITY)
        return buffer.getvalue(), width, height
    except Exception:  # noqa: BLE001
        return b"", 0, 0


def render_apart(playwright: Any, chrome_path: str, url: str) -> bytes:
    """그 주소를 **따로 띄운 화면 없는 크롬**으로 열어 위에서 아래까지 찍는다 → PNG. 실패하면 빈 바이트.

    그래픽카드를 쓰지 않게 띄운다 — 시험용 브라우저가 화면용 그래픽카드에 붙어 사람의 게임을 죽인 적이 있다(10-07).
    찍고 나면 닫는다. 쿠키도 창도 남기지 않는다.
    """
    browser = None
    try:
        launch: dict[str, Any] = {"headless": True, "args": ["--disable-gpu", "--hide-scrollbars", "--mute-audio"]}
        if chrome_path:
            launch["executable_path"] = chrome_path
        browser = playwright.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": SHOT_WIDTH, "height": 900})
        page.goto(url, wait_until="load", timeout=SHOT_TIMEOUT_MS)
        page.wait_for_timeout(400)
        height = int(page.evaluate(
            "Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)"
        ) or 0)
        height = max(200, min(SHOT_MAX_HEIGHT, height))
        return page.screenshot(
            clip={"x": 0, "y": 0, "width": SHOT_WIDTH, "height": height}, full_page=True,
            animations="disabled", timeout=SHOT_TIMEOUT_MS,
        )
    except Exception:  # noqa: BLE001 — 찍다 틀어져도 페이지 열기는 성공이다
        return b""
    finally:
        try:
            if browser is not None:
                browser.close()
        except Exception:  # noqa: BLE001
            pass


def look_note(said: str) -> str:
    """눈으로 본 것을 모델이 읽을 한 덩어리로 — 인상이라는 딱지를 붙인다. 「이상 없음」이면 빈 글."""
    if saw_nothing(said):
        return ""
    text = " ".join(str(said).split())[:400]
    return (
        "👁 화면을 찍어 눈으로 본 인상(그림을 보고 한 말이라 **자리는 맞아도 설명이 틀릴 수 있다** — 고치기 전에 그 자리를 "
        f"browser_read 나 코드로 확인하라. 이 주소를 새로 열었을 때의 첫 모습이다): {text}"
    )
