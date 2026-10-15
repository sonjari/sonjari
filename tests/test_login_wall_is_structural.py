"""사람만 지날 수 있는 문은 **글자가 아니라 구조로** 알아본다.

2026-08-10 크몽 실측. 자비스가 의뢰 등록 화면까지 눌러서 도착했고 로그인 모달에
막혔다. 그런데 스탠바이가 안 걸렸다 — 두 번 두드려 보고 그냥 답을 내고 끝냈다.

원인은 감지 규칙이었다. 모달 문구가 이랬는데:

    로그인 유지 / 아이디·비밀번호 찾기 / 로그인 / SNS 간편 로그인 / 휴대폰 인증 /
    아직 크몽 회원이 아니신가요? / 회원가입

'로그인'이 네 번 나오는데 규칙이 찾던 **'로그인이 필요'** 라는 어구가 없었다.
login_required 로 분류되지 않으니 사람 문이 아니고, 사람 문이 아니니 워커를 놓지도
체크포인트를 남기지도 지켜보지도 않았다. **6단계 전체가 첫 관문에서 죽어 있었다.**

여기에 문구를 하나 더 넣는 것은 사이트 수만큼 두더지를 잡는 일이다. 그래서 무엇을
보는지를 바꾼다 — **자비스가 구조적으로 못 하는 일**만 본다:

    비밀번호 칸이 보인다  →  자비스는 비밀번호를 치지 않는다 (코드에 박힌 결정)
    캡차가 떠 있다        →  자비스는 봇 검사를 통과하지 않는다 (같은 결정)

둘 다 사이트 사정이 아니라 우리 쪽 규칙이라 언어·사이트와 무관하게 성립한다.
그리고 **같은 신호로 열림도 판정한다** — 칸이 사라지면 사람이 지나간 것이다.
막힘과 열림을 한 신호로 보는 것이 이 설계의 전부다.
"""

from __future__ import annotations

from alture_jarvis.attention import classify
from alture_jarvis.human_gate import is_cleared, is_human_gate, wall_code

# 2026-08-10 크몽이 실제로 돌려준 문자열. 지어낸 표본이 아니다.
KMONG_REAL = (
    "browser_popup_blocking:로그인 유지 아이디/비밀번호 찾기 로그인 SNS 간편 로그인 "
    "휴대폰 인증 아직 크몽 회원이 아니신가요? 회원가입"
)


# ── 구조 신호 ────────────────────────────────────────────────────────────────
def test_a_visible_password_box_is_a_human_gate() -> None:
    """옛 체크포인트에는 문맥 필드가 없으므로 기존 판정을 보존한다."""
    assert wall_code({"known": True, "password_fields": 1, "captcha": False}) == "login_required"


def test_a_password_example_inside_a_large_general_form_is_not_a_login_gate() -> None:
    """Selenium 공식 데모처럼 일반 폼의 연습용 password 한 칸은 전체를 막지 않는다."""
    assert wall_code(
        {
            "known": True,
            "password_fields": 1,
            "password_gate": False,
            "captcha": False,
        }
    ) == ""


def test_a_captcha_is_a_human_gate() -> None:
    assert wall_code({"known": True, "password_fields": 0, "captcha": True}) == "bot_check"


def test_a_clean_page_is_not_a_gate() -> None:
    assert wall_code({"known": True, "password_fields": 0, "captcha": False}) == ""


def test_not_knowing_is_not_a_gate() -> None:
    """브라우저가 바빠서 못 봤으면 '문이 없다'가 아니라 '모른다'다.

    모르는데 문이 없다고 하면 자비스는 막힌 화면에서 계속 두드린다.
    """
    assert wall_code({"known": False}) == ""


def test_both_codes_are_things_a_person_must_open() -> None:
    for wall in (
        {"known": True, "password_fields": 2, "captcha": False},
        {"known": True, "password_fields": 0, "captcha": True},
    ):
        assert is_human_gate(wall_code(wall))


# ── 문구 규칙도 크몽을 잡게 고쳤다 (구조 신호의 예비) ────────────────────────
#
# 화면이 없는 실패(예: API 단에서 온 로그인 오류)도 있어서 문구 규칙을 없애지는
# 않는다. 다만 그쪽은 이제 **예비**다.
def test_the_wording_rule_now_catches_the_real_kmong_modal() -> None:
    rule = classify({"ok": False, "error": KMONG_REAL})
    assert rule is not None, "크몽 로그인 모달을 여전히 못 알아본다"
    assert rule.code == "login_required"


def test_a_header_that_merely_says_login_is_not_a_wall() -> None:
    """머리글에 '로그인 회원가입'이 있다고 사람을 부르면, 진짜일 때 아무도 안 본다."""
    assert classify({"ok": False, "error": "browser_action_timeout: 로그인 회원가입 고객센터"}) \
        .code != "login_required"


def test_a_cookie_banner_is_not_a_login_wall() -> None:
    banner = "browser_popup_blocking:쿠키 사용에 동의하시면 로그인 상태가 유지됩니다 동의 거부"
    rule = classify({"ok": False, "error": banner})
    assert rule is None or rule.code != "login_required"


# ── 같은 신호로 열림을 본다 ──────────────────────────────────────────────────
_GATE = {"code": "login_required", "url": "https://kmong.com/"}


def test_the_door_is_open_when_the_password_box_is_gone() -> None:
    """★ 두 번째 구멍이 여기였다.

    주소만 보던 시절엔 크몽처럼 로그인이 모달로 뜨는 SPA 는 사람이 로그인해도
    주소가 그대로라 영영 안 열린 것으로 보였다 — 스탠바이는 걸려도 15분 뒤
    시간이 다 돼서야 깨어난다.
    """
    state = {"known": True, "url": "https://kmong.com/", "password_fields": 0, "captcha": False}
    assert is_cleared(_GATE, state)


def test_the_door_is_still_shut_while_the_password_box_stands() -> None:
    state = {"known": True, "url": "https://kmong.com/", "password_fields": 1, "captcha": False}
    assert not is_cleared(_GATE, state)


def test_a_captcha_still_on_screen_is_still_shut() -> None:
    state = {"known": True, "url": "https://kmong.com/", "password_fields": 0, "captcha": True}
    assert not is_cleared({"code": "bot_check", "url": "https://kmong.com/"}, state)


def test_when_the_browser_is_busy_we_do_not_claim_it_opened() -> None:
    assert not is_cleared(_GATE, {"known": False})


def test_naver_still_uses_the_cookie_because_it_is_certain() -> None:
    """네이버는 쿠키로 '로그인됐다'를 확실히 안다. 확실한 신호를 버리지 않는다."""
    gate = {"code": "login_required", "url": "https://nid.naver.com/nidlogin.login"}
    shut = {"known": True, "url": "https://nid.naver.com/nidlogin.login", "naver_signed_in": False}
    assert not is_cleared(gate, shut)


# ── 문은 어느 창에 있든 문이다 (2026-08-10) ──────────────────────────────────
#
# 로그인 문은 새 창에서 열리는 일이 아주 흔하다(OAuth·결제·본인확인). 현재 창만
# 보면 팝업에 뜬 비밀번호 칸이 안 보이고, 그러면 "문이 없다"고 읽어 사람에게
# 넘기지도 지켜보지도 않는다 — 위시켓에서 자비스가 원래 창만 보고 "아무 일도 안
# 일어났다"고 하던 것과 같은 고장이다. 한 사이트의 문제가 아니다.
class _Frame:
    def __init__(self, passwords: int = 0, captcha: int = 0, payment: int = 0) -> None:
        self.passwords = passwords
        self.captcha = captcha
        self.payment = payment

    def locator(self, selector: str):
        if "password" in selector:
            count = self.passwords
        elif "cc-number" in selector:
            # 2026-09-23 결제 문 — 이 대역은 모르는 선택자를 전부 캡차 수로 답해서, 결제 칸 물음을 따로 받는다.
            count = self.payment
        elif "aria-checked='true'" in selector:
            count = 0
        else:
            count = self.captcha
        return type(
            "L",
            (),
            {
                "count": lambda _self, n=count: n,
                "evaluate_all": lambda _self, _script: False,
            },
        )()


class _Win:
    def __init__(self, url: str, frames: list[_Frame], *, opened_by=None) -> None:
        self.url = url
        self._frames = frames
        self.main_frame = frames[0] if frames else None
        self._opened_by = opened_by

    @property
    def frames(self) -> list[_Frame]:
        return self._frames

    def is_closed(self) -> bool:
        return False

    def opener(self):
        return self._opened_by


class _Ctx:
    def __init__(self, pages: list[_Win]) -> None:
        self.pages = pages


def _wall_worker(tmp_path, pages: list[_Win], current: _Win):
    from alture_jarvis.browser import BrowserWorker
    from alture_jarvis.config import JarvisConfig

    worker = BrowserWorker(
        JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    )
    worker._context = _Ctx(pages)
    worker._page = current
    worker._frames_of = lambda page: page.frames  # type: ignore[assignment]
    return worker


def test_a_password_field_in_another_window_still_counts(tmp_path) -> None:
    """★ 위시켓에서 죽던 자리. 문은 팝업에 있었고 자비스는 원래 창을 보고 있었다."""
    main = _Win("https://auth.wishket.com/login", [_Frame()])
    popup = _Win(
        "https://accounts.google.com/signin", [_Frame(passwords=1)], opened_by=main
    )

    wall = _wall_worker(tmp_path, [main, popup], main)._blocking_wall()

    assert wall["password_fields"] == 1, "다른 창의 문을 못 보면 사람에게 넘기지 못한다"
    assert wall["wall_url"] == "https://accounts.google.com/signin", "어느 창인지 말해줘야 한다"
    assert wall["windows"] == 2


def test_no_wall_anywhere_means_it_is_open(tmp_path) -> None:
    """열림 판정도 같이 넓어진다 — 어느 창에도 없어야 지나간 것이다."""
    main = _Win("https://www.wishket.com/", [_Frame()])
    other = _Win("https://www.wishket.com/project/", [_Frame()])

    wall = _wall_worker(tmp_path, [main, other], main)._blocking_wall()

    assert wall["known"] is True and wall["password_fields"] == 0 and not wall["captcha"]


def test_a_password_input_on_a_non_auth_demo_page_does_not_block(tmp_path) -> None:
    page = _Win("https://www.selenium.dev/selenium/web/web-form.html", [_Frame(passwords=1)])

    wall = _wall_worker(tmp_path, [page], page)._blocking_wall()

    assert wall["password_fields"] == 1
    assert wall["password_gate"] is False
    assert wall_code(wall) == ""


def test_a_captcha_in_another_window_counts_too(tmp_path) -> None:
    main = _Win("https://example.test/", [_Frame()])
    popup = _Win("https://example.test/verify", [_Frame(captcha=1)], opened_by=main)

    wall = _wall_worker(tmp_path, [main, popup], main)._blocking_wall()

    assert wall["captcha"] is True


def test_a_wall_in_an_unrelated_existing_tab_is_ignored(tmp_path) -> None:
    """다른 임무의 탭이 현재 작업을 사람 대기로 잘못 묶으면 안 된다."""
    current = _Win("https://www.google.com/recaptcha/api2/demo", [_Frame()])
    unrelated = _Win("https://search.naver.com/blocked", [_Frame(captcha=1)])

    wall = _wall_worker(tmp_path, [unrelated, current], current)._blocking_wall()

    assert wall["captcha"] is False
    assert wall["windows"] == 1


class _SolvedCaptchaFrame(_Frame):
    def locator(self, selector: str):
        located = super().locator(selector)
        if "aria-checked='true'" in selector:
            return type(
                "L",
                (),
                {"count": lambda _self: 1, "evaluate_all": lambda _self, _script: False},
            )()
        return located


class _HiddenCaptchaFrame(_Frame):
    def locator(self, selector: str):
        if ":visible" in selector:
            return type(
                "L",
                (),
                {"count": lambda _self: 0, "evaluate_all": lambda _self, _script: False},
            )()
        return super().locator(selector)


class _ProviderWrapperResidueFrame(_Frame):
    """성공 뒤 남는 빈 g-recaptcha div. 실제 challenge iframe은 없다."""

    def locator(self, selector: str):
        if "password" in selector or "aria-checked='true'" in selector:
            return super().locator(selector)
        broad_wrapper_would_match = (
            "[class*='captcha']" in selector
            and ":not([class*='recaptcha'])" not in selector
        )
        count = 1 if broad_wrapper_would_match else 0
        return type(
            "L",
            (),
            {
                "count": lambda _self, n=count: n,
                "evaluate_all": lambda _self, _script: False,
            },
        )()


def test_a_human_solved_recaptcha_no_longer_blocks_resume(tmp_path) -> None:
    page = _Win(
        "https://www.google.com/recaptcha/api2/demo",
        [_Frame(captcha=1), _SolvedCaptchaFrame(captcha=1)],
    )

    wall = _wall_worker(tmp_path, [page], page)._blocking_wall()

    assert wall["captcha"] is False
    assert wall["wall_url"] == ""


def test_hidden_captcha_residue_on_the_success_page_is_not_a_gate(tmp_path) -> None:
    page = _Win(
        "https://www.google.com/recaptcha/api2/demo",
        [_HiddenCaptchaFrame(captcha=1)],
    )

    wall = _wall_worker(tmp_path, [page], page)._blocking_wall()

    assert wall["captcha"] is False


def test_visible_empty_recaptcha_wrapper_on_success_is_not_a_gate(tmp_path) -> None:
    page = _Win(
        "https://www.google.com/recaptcha/api2/demo",
        [_ProviderWrapperResidueFrame()],
    )

    wall = _wall_worker(tmp_path, [page], page)._blocking_wall()

    assert wall["captcha"] is False


def test_gate_snapshot_recovers_the_checkpoint_tab_after_a_restart(tmp_path) -> None:
    unrelated = _Win("https://www.naver.com/", [_Frame(captcha=1)])
    solved = _Win(
        "https://www.google.com/recaptcha/api2/demo",
        [_Frame(captcha=1), _SolvedCaptchaFrame(captcha=1)],
    )
    worker = _wall_worker(tmp_path, [unrelated, solved], unrelated)

    state = worker._gate_snapshot(
        "https://www.google.com/recaptcha/api2/demo", "", ["google.com"]
    )

    assert state["url"] == "https://www.google.com/recaptcha/api2/demo"
    assert state["captcha"] is False
    assert state["windows"] == 1


def test_gate_state_attaches_before_recovering_a_checkpoint(tmp_path) -> None:
    worker = _wall_worker(tmp_path, [], _Win("https://unused.test/", [_Frame()]))
    calls: list[str] = []
    worker.start = lambda: calls.append("attach") or {"ok": True}  # type: ignore[method-assign]
    worker._submit = lambda function, _timeout, **_kwargs: function()  # type: ignore[method-assign]
    worker._gate_snapshot = lambda *_args: {  # type: ignore[method-assign]
        "known": True,
        "url": "https://www.google.com/recaptcha/api2/demo",
        "password_fields": 0,
        "captcha": False,
        "wall_url": "",
        "windows": 1,
    }
    worker.naver_session_alive = lambda: {"signed_in": False}  # type: ignore[method-assign]

    state = worker.gate_state(
        {"url": "https://www.google.com/recaptcha/api2/demo", "hosts": ["google.com"]}
    )

    assert calls == ["attach"]
    assert state["known"] is True and state["captcha"] is False


class _TurnstileFrame(_Frame):
    def __init__(self) -> None:
        super().__init__()
        self.seen = ""

    def locator(self, selector: str):
        self.seen = selector
        count = 1 if "turnstile" in selector and "challenges.cloudflare.com" in selector else 0
        return type("L", (), {"count": lambda _self, n=count: n})()


def test_cloudflare_turnstile_is_detected_as_a_human_gate(tmp_path) -> None:
    frame = _TurnstileFrame()
    page = _Win("https://shop.example/challenge", [frame])

    wall = _wall_worker(tmp_path, [page], page)._blocking_wall()

    assert wall["captcha"] is True
    assert "turnstile" in frame.seen
