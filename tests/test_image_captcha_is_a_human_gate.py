"""글자 그림 캡차도 사람 문이다 (2026-10-01 네이버 서치어드바이저).

손자리가 네이버 서치어드바이저 소유확인을 누르자 캡차 대화상자가 떴다. 클릭 도구는 「덮는 화면이
떴습니다: …자동등록을 방지하기 위해 보안절차를…」까지 읽었는데, 사람 문 판정(`wall_code`)은
조용했다. 그래서 손자리가 확인 버튼을 두 번 더 누르고 `browser_dismiss_dialog` 로 **캡차 창을
닫았고**, 「done(일부)」로 끝냈다. 로그인 화면에선 바로 멈춰 넘겼는데 캡차에선 못 넘긴 것이다.

원인은 구조였다. 네이버 캡차는 Vuetify 대화상자이고, class·id 어디에도 captcha 가 없으며, 그림이
`<img>` 가 아니라 배경 그림(`style="background-image:url(https://captcha.nid.naver.com/…)"`)이다
(서치어드바이저 번들 `_v2/c9855e9.js` 의 CaptchaDialog, v-img). 이 시험은 그 모양을 실제
크로미움에 그려 판정 선택자가 잡는지, 그리고 「캡차」라는 글이 실린 멀쩡한 페이지는 안 잡는지 본다.

자식 프로세스에서 재는 이유는 tests/result_list_bench.py 머리말(이벤트 루프 오염).
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"

# 서치어드바이저가 실제로 그리는 모양(Vuetify 2 v-dialog + v-img)을 줄였다.
NAVER_DIALOG = """
<div class="v-dialog__content v-dialog__content--active" style="z-index:202">
  <div class="v-dialog v-dialog--active v-dialog--persistent" style="max-width:420px">
    <div class="v-card v-sheet">
      <div class="v-card__title">보안 절차</div>
      <div class="v-card__text">네이버 서치어드바이저는 프로그램을 이용한 자동등록을 방지하기 위해
        보안절차를 거치고 있습니다. 아래 이미지에 보이는 글자 및 숫자를 입력해주세요.
        <div class="d-flex mt-5">
          <div class="v-image v-responsive flex-grow-0 theme--light" style="width:200px;height:90px">
            <div class="v-image__image v-image__image--contain"
                 style="background-image:url(&quot;https://captcha.nid.naver.com/nhncaptchav4.gif?key=abc&amp;r=7&quot;);background-position:left bottom;width:200px;height:90px"></div>
          </div>
        </div>
        <div class="v-input"><input type="text" id="input-91"></div>
      </div>
    </div>
  </div>
</div>
"""

# 멈추면 안 되는 페이지: 캡차를 **설명하는** 글, 평범한 그림, 숨은(닫힌) 캡차 잔해.
ARTICLE = """
<article><h1>captcha 가 뭔가요? 보안문자(CAPTCHA) 설명</h1>
  <p>자동등록방지를 위해 보안절차를 거칩니다 — 이건 설명 글입니다.</p>
  <img src="/images/cat.png" width="200" height="120" alt="captcha 설명용 고양이">
  <a href="https://example.com/what-is-captcha">더 읽기</a>
</article>
"""
CLOSED_DIALOG = NAVER_DIALOG.replace('class="v-dialog__content', 'style="display:none" class="v-dialog__content')

_CHILD = textwrap.dedent(
    r"""
    import json, sys
    sys.path.insert(0, sys.argv[1])
    from playwright.sync_api import sync_playwright
    from alture_jarvis.browser import _VISIBLE_CAPTCHA_SELECTOR
    pages = json.loads(sys.argv[2])
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        # 바깥 요청은 전부 끊는다(캡차 그림 주소를 실제로 부르지 않는다).
        page.route("**/*", lambda route: route.abort() if route.request.url.startswith("http") else route.continue_())
        for name, html in pages.items():
            page.set_content(f"<html><body>{html}</body></html>")
            out[name] = page.locator(_VISIBLE_CAPTCHA_SELECTOR).count()
        b.close()
    print(json.dumps(out))
    """
)


@pytest.fixture(scope="module")
def counts() -> dict:
    pages = {"naver": NAVER_DIALOG, "article": ARTICLE, "closed": CLOSED_DIALOG}
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(_SRC), json.dumps(pages)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if proc.returncode != 0:
        if "Executable doesn't exist" in proc.stderr or "playwright install" in proc.stderr:
            pytest.skip("크로미움이 설치돼 있지 않다: " + proc.stderr.strip().splitlines()[-1])
        raise AssertionError(proc.stderr[-2000:])
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_naver_picture_captcha_in_a_dialog_is_seen(counts: dict) -> None:
    assert counts["naver"] >= 1


def test_a_page_that_only_talks_about_captcha_is_not_a_gate(counts: dict) -> None:
    assert counts["article"] == 0


def test_a_closed_captcha_dialog_is_not_a_gate(counts: dict) -> None:
    # 사람이 풀고 나면 대화상자가 닫힌다. 숨은 잔해를 문으로 치면 지켜보기가 영영 안 깨어난다.
    assert counts["closed"] == 0


def test_the_gate_is_called_a_bot_check() -> None:
    from alture_jarvis.human_gate import wall_code

    assert wall_code({"known": True, "captcha": True}) == "bot_check"
