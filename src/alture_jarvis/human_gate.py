"""사람만 열 수 있는 문 — 넘기고, 지켜보고, 열리면 이어받는다.

자비스가 막히는 방식 중에는 아무리 애써도 못 푸는 것이 있다: 로그인, 봇 확인.
비밀번호를 다루지 않고 캡차를 풀지 않는다는 것은 한계가 아니라 **결정**이다
(사용자가 네이버 계정 저장을 거절하신 것과 같은 선).

그러면 그 앞에서 무엇을 해야 하나. 지금까지는 실패를 관찰값으로 돌려주고 모델이
계속 두드리게 뒀다 — 실측에서 그 결과는 검색으로 되돌아가 헛도는 것이었다.

★ 여기서 자비스만 할 수 있는 것이 있다. 마누스는 클라우드 VM 안에 있고 GPT 는
내부 브라우저 안에 있어서, **막혔을 때 사람이 손을 뻗어 넣을 수가 없다.** 자비스는
사용자 눈앞의 진짜 크롬에서 돈다. 사용자가 그 창에 직접 로그인하실 수 있다.

그래서 규칙은 이렇다:

    막히면 → 무엇을 해주셔야 하는지 정확히 말하고 → **워커를 놓고**
    → 싸게 지켜보다가 → 열리면 스스로 이어간다

워커를 놓는 것이 중요하다. 잡은 직렬로 돌기 때문에(JobRunner 스레드 하나) 기다리는
잡이 워커를 쥐고 있으면 그동안 다른 요청이 전부 멈춘다.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from .site_atlas import registrable

# 사람이 아니면 못 여는 문. attention.py 의 분류 코드와 같은 이름을 쓴다 —
# 이름이 갈리면 한쪽만 고치고 다른 쪽은 조용히 안 걸린다.
HUMAN_GATE_CODES = frozenset({"bot_check", "login_required", "payment_required"})

# ★ 결제 정보 칸 (2026-09-23 제품 요청: 「결제 수단이 없는데 결제하려고 헤맨다 — 시간만 쓰고 UX 최악」).
#   온텔릭은 카드 번호·결제 비밀번호를 **절대 넣지 않는다**(비밀번호와 같은 결정). 그러니 결제 칸이 뜬 화면은
#   아무리 두드려도 못 지나가는 문이다 — 비밀번호 칸처럼 구조로 알아보고 사람에게 넘긴다. 문구·언어를 보지 않는다.
#   카드 칸은 HTML 표준 자동완성 표식(`cc-number`·`cc-csc`·`cc-exp`)과 흔한 이름 조각으로 본다.
PAYMENT_FIELD_SELECTOR = (
    "input[autocomplete*='cc-number' i], input[autocomplete*='cc-csc' i], input[autocomplete*='cc-exp' i], "
    "input[name*='cardnumber' i], input[name*='card_number' i], input[name*='cardno' i], input[name*='card_no' i], "
    "input[id*='cardnumber' i], input[id*='card_number' i], input[id*='cardno' i]"
)
#   결제 대행사 창. 상품 페이지의 작은 「간편결제 구매」 단추(iframe)는 문이 아니다 — 브라우저 쪽에서 **결제창 크기**
#   (가로 250·세로 200 이상)일 때만 문으로 친다. 스트라이프 카드 칸은 작아도 카드 칸이라 이름으로 따로 본다.
PAYMENT_FRAME_HOSTS = (
    "tosspayments", "pay.toss.im", "inicis", "kcp.co.kr", "nicepay", "danal", "portone", "iamport",
    "paypal.com/checkoutnow", "checkout.stripe.com", "kakaopay.com", "pay.naver.com/o/", "payco.com/pay",
)
PAYMENT_CARD_FRAME_MARKERS = ("elements-inner-card", "elements-inner-payment")

# 로그인·인증 화면임을 알아보는 조각들. 사람이 이걸 통과하면 주소가 바뀐다.
_GATE_URL_MARKERS = ("/login", "/signin", "/sign_in", "nid.naver.com", "/sorry/", "captcha", "challenge")

# 구조로 확인할 수 있는 CAPTCHA 공급자와 표준 표식. 푸는 셀렉터가 아니라 **멈출**
# 셀렉터다. 한 사이트 이름을 browser.py에 계속 보태지 않고 이 계약 한 곳에 둔다.
CAPTCHA_SELECTOR = (
    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], "
    "iframe[src*='challenges.cloudflare.com'], "
    # Google demo의 성공 화면에는 iframe 없이 빈 ``g-recaptcha`` wrapper만
    # 남는다. 공급자 widget은 위 iframe으로 판정하고, 범용 class/id 규칙에서는
    # 그 껍데기를 제외해야 사람이 푼 뒤 watcher가 깨어난다.
    "[class*='captcha']:not([class*='recaptcha']):not([class*='hcaptcha']), "
    "[id*='captcha']:not([id*='recaptcha']):not([id*='hcaptcha']), "
    "[class*='turnstile'], "
    "[data-sitekey][data-callback], "
    # ★ 글자 그림 캡차 (2026-10-01 네이버 서치어드바이저 소유확인).
    #   네이버는 캡차를 Vuetify 대화상자에 띄우는데 class·id 어디에도 captcha 가 없고, 그림은
    #   `<img>` 가 아니라 **배경 그림**(style="background-image:url(https://captcha.nid.naver.com/
    #   nhncaptchav4.gif?…)")이다. 위 규칙을 전부 빠져나가 손자리가 확인 버튼을 두 번 더 누르고
    #   그 대화상자를 「닫아」 버렸다. 문구가 아니라 **그림이 어디서 오는가**로 본다 — 캡차 그림은
    #   공급자 주소에 captcha 가 들어간다. 공급자 위젯(reCAPTCHA·hCaptcha)은 위 iframe 규칙의 몫이다.
    "img[src*='captcha' i]:not([src*='recaptcha' i]):not([src*='hcaptcha' i]), "
    "[style*='captcha' i]:not([style*='recaptcha' i]):not([style*='hcaptcha' i]), "
    "input[name*='captcha' i]:not([name*='recaptcha' i]):not([name*='hcaptcha' i])"
)


def is_human_gate(code: str) -> bool:
    return code in HUMAN_GATE_CODES


def wall_code(wall: dict[str, Any]) -> str:
    """지금 화면이 **사람만 지날 수 있는 문**인가. 아니면 빈 문자열.

    ★ 근본 신호. 사이트가 뭐라고 쓰는지 보지 않는다.

    2026-08-10 크몽에서 문구 방식이 깨졌다: 로그인 모달에 '로그인'이 네 번 나오는데
    규칙이 찾던 '로그인이 필요'가 없어서 못 알아봤고, 사람 문으로 분류되지 않아
    6단계(넘기고·지켜보고·이어받기) 전체가 첫 관문에서 죽었다. 문구를 하나 더
    넣어 봐야 다음 사이트에서 또 깨진다.

    그래서 **자비스가 구조적으로 못 하는 일**만 본다:

        인증 폼의 비밀번호 칸 →  자비스는 비밀번호를 치지 않는다
        캡차가 떠 있다        →  자비스는 봇 검사를 통과하지 않는다

    둘 다 사이트 사정이 아니라 우리 쪽 결정이라 언어·사이트와 무관하게 성립한다.
    """
    if not wall.get("known"):
        return ""
    if wall.get("captcha"):
        return "bot_check"
    if wall.get("payment"):
        return "payment_required"
    password_gate = wall.get("password_gate")
    # `password_gate`가 없는 옛 체크포인트·호출자는 예전 계약으로 읽는다. 새 브라우저
    # snapshot은 반드시 True/False를 주므로 일반 폼의 password 한 칸을 구별한다.
    if bool(password_gate) or (
        password_gate is None and int(wall.get("password_fields") or 0) > 0
    ):
        return "login_required"
    return ""


def host_of(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower()


# ★ 이 PC 개발 주소의 **시험 계정** (2026-10-02 분업 실험).
#
#   클로드 코드가 할 일 앱을 만들고 「localhost:3000 에서 아이디 "demo_user", 비밀번호 "demo1234" 로 가입해 보고
#   확인해라」를 맡겼다. 손자리는 비밀번호 칸을 보고 「로그인이 필요해요」 카드를 띄워 사람에게 넘겼다 —
#   클로드가 방금 만든 시험 앱의, 클로드가 방금 정한 시험 계정인데. 대표: 「이건 애초에 잘못됐다」.
#
#   비밀번호를 안 치는 결정은 **남의 계정을 지키려는 것**이다. 아래 셋이 다 맞으면 지킬 계정이 없다:
#     ① 화면이 이 PC 개발 주소다(localhost·127.0.0.1·[::1]·*.localhost·*.test) — 밖으로 안 나간다
#     ② 맡긴 글이 비밀번호를 말하고, 이 PC 개발 주소를 가리킨다
#     ③ 칠 값이 맡긴 글 안에 **글자 그대로** 있다 — 손자리가 기억·저장소에서 꺼낸 값이 아니다
#   결제 칸·보안 문자는 여기서 풀지 않는다(그건 계정이 아니라 돈과 봇 검사다).
_LOCAL_DEV_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_LOCAL_DEV_SUFFIXES = (".localhost", ".test")
_CREDENTIAL_WORDS = re.compile(r"비밀\s*번호|비번|패스워드|password|passwd|\bpw\b", re.IGNORECASE)
_LOCAL_DEV_MENTION = re.compile(
    r"\blocalhost\b|\b127\.0\.0\.1\b|\[::1\]|\b[\w-]+\.localhost\b|\b[\w-]+\.test\b", re.IGNORECASE
)
LOCAL_TEST_SECRET_MIN_LEN = 4


def is_local_dev_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in _LOCAL_DEV_HOSTS or host.endswith(_LOCAL_DEV_SUFFIXES)


def local_test_login_prompt(prompt: str) -> str:
    """맡긴 글이 이 PC 개발 주소의 시험 계정을 담고 있으면 그 글, 아니면 빈 문자열."""
    text = str(prompt or "")
    if _CREDENTIAL_WORDS.search(text) and _LOCAL_DEV_MENTION.search(text):
        return text
    return ""


def allows_local_test_secret(url: str, prompt: str, value: str) -> bool:
    """이 비밀번호 칸에 이 값을 손자리가 넣어도 되는가 — 위 ①②③이 전부 맞을 때만."""
    secret = str(value or "")
    if len(secret.strip()) < LOCAL_TEST_SECRET_MIN_LEN or not is_local_dev_url(url):
        return False
    text = local_test_login_prompt(prompt)
    return bool(text) and secret in text


def local_test_login_gate(code: str, url: str, prompt: str) -> bool:
    """이 로그인 문은 사람에게 넘기지 말고 맡긴 시험 계정으로 지나갈 문인가."""
    return code == "login_required" and is_local_dev_url(url) and bool(local_test_login_prompt(prompt))


LOCAL_TEST_LOGIN_NOTE = (
    "[시스템] 이 로그인·가입 칸은 이 PC 개발 주소(사용자의 시험 앱)에 있고, 맡긴 글에 시험 계정이 적혀 있다. "
    "사람에게 넘기지 말고 맡긴 글에 적힌 값 **그대로** browser_fill 로 채워 진행하라. 값을 바꾸거나 지어내지 마라 — "
    "맡긴 글에 없는 값은 비밀번호 칸이 받지 않는다. 결제 칸·보안 문자가 나오면 그때는 사람에게 넘긴다."
)


def gate_evidence(code: str, url: str, state: dict[str, Any]) -> dict[str, Any]:
    """문을 다른 작업·사이트의 깨끗한 탭과 혼동하지 않을 작은 지문."""
    urls = [str(url or ""), str(state.get("url") or ""), str(state.get("wall_url") or "")]
    hosts = sorted(
        {
            site
            for item in urls
            if (site := registrable(host_of(item)))
        }
    )
    material = {
        "code": str(code or ""),
        "urls": [item.split("#", 1)[0][:500] for item in urls if item],
        "hosts": hosts,
        "password_fields": state.get("password_fields"),
        "password_gate": state.get("password_gate"),
        "captcha": state.get("captcha"),
    }
    return {
        "hosts": hosts,
        "wall_url": str(state.get("wall_url") or "")[:500],
        "fingerprint": hashlib.sha256(
            json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "detected": {
            "password_fields": state.get("password_fields"),
            "password_gate": state.get("password_gate"),
            "captcha": state.get("captcha"),
            "windows": state.get("windows"),
        },
    }


# 사람 문이 아닌 막힘. **이것도 장부에 적는다.**
#
# 처음엔 로그인·봇 확인만 셌다. 그런데 레시피가 제일 급한 곳은 거기가 아니었다 —
# 크몽 공고 본문은 로그인을 요구하지도, 봇 확인을 띄우지도 않는다. 그냥 안 읽힌다.
# 그래서 "3번 막히면 레시피"라는 규칙이 정작 그 사이트에는 영영 걸리지 않았다.
# 장부가 사람 문 앞에만 있었기 때문에, 레시피가 자기 입력을 못 받고 있었다.
CONTENT_FRICTION_CODE = "content_unreadable"

# 같은 사이트에서 이만큼 막히면 레시피를 만들 때가 된 것이다.
#
# 한 번은 사고다. 두 번은 우연일 수 있다. **세 번이면 그 사이트는 앞으로도 계속
# 막는다** — 그때가 사람을 한 번 더 부르는 대신 절차를 굳힐 시점이다.
RECIPE_SUGGEST_AFTER = 3


def suggest_recipe(host: str, hits: int, *, code: str = "") -> str:
    """레시피를 만들 때가 됐다고 알리는 말. 아직이면 빈 문자열.

    ★ 이 말을 **막힌 그 순간에** 하는 것이 핵심이다. 나중에 목록을 보고 고르라고
    하면 아무도 안 본다. 지금 사용자가 그 화면 앞에 계시고, 방금 직접 뚫으셨다 —
    셀렉터를 확인하기에 이보다 나은 순간이 없다.

    막힌 종류에 따라 말이 달라야 한다. 사람 문은 사용자가 방금 여신 참이라 화면이
    그대로 있지만, 못 읽은 페이지는 **무엇이 안 읽혔는지**를 짚어 드려야 어디를 볼지
    아신다. 같은 문구를 두 경우에 쓰면 한쪽은 반드시 어긋난다.
    """
    if hits < RECIPE_SUGGEST_AFTER:
        return ""
    # ★ 예전에는 여기서 "레시피 만들자고 말씀해 주세요"라고 했다. 그런데 그때
    # 자비스에게는 만들 손이 없었다 — 도구가 보기(site_list)와 실행(site_run)
    # 둘뿐이었다. 시켜도 못 하는 것을 시켜 달라고 한 셈이다.
    #
    # 이제 `site_draft_recipe` 로 **초안까지는 자기가 쓴다.** 그러니 부탁이 아니라
    # 제안이어야 한다: 써 둘까요, 그리고 확정은 사용자가.
    if code == CONTENT_FRICTION_CODE:
        return (
            f"\n\n💡 {host} 의 본문을 끝내 못 읽은 게 이번이 **{hits}번째**입니다. "
            "여긴 로그인이나 봇 확인이 아니라 페이지 구조 문제라, 절차를 레시피로 "
            "굳혀 두면 다음부터는 그냥 읽힙니다. **제가 지금 화면에서 확인한 것으로 "
            '초안을 써 둘까요?** "레시피 초안 써줘"라고 하시면 됩니다 — '
            "쓰기만 하고, 실제로 쓸지는 보시고 정하시면 됩니다."
        )
    return (
        f"\n\n💡 {host} 에서 막힌 게 이번이 **{hits}번째**입니다. "
        "이 사이트 절차를 레시피로 굳혀 두면 다음부터는 안 막힙니다. "
        "**지금 화면이 열려 있을 때 제가 초안을 써 두는 것이 가장 정확합니다** — "
        '"레시피 초안 써줘"라고 하시면 확인된 셀렉터만 골라 적어 두고, '
        "실제로 쓸지는 보시고 정하시면 됩니다."
    )


def describe(code: str, url: str, done: int, total: int, *, stage: bool = False) -> str:
    """사용자에게 드릴 말. **무엇을·어디서·지금 어디까지**가 다 들어가야 한다.

    예전 문구는 "봇 확인 화면이 떴습니다. 확인해 주세요"였다. 무엇을 해야 하는지,
    어디를 봐야 하는지, 하고 나면 어떻게 되는지가 없다. 그러면 사람은 창을 찾다
    포기하고, 자비스는 영영 못 이어간다.
    """
    # ★ 2026-09-18: 크롬은 평소 뒤에 떠 있고, 넘길 때도 **앞으로 올리지 않는다**(사람의 작업 흐름을 안 끊는다 — 사용자 요청).
    #   대신 작업 표시줄 크롬 아이콘이 깜빡이니 「그걸 눌러 주세요」라고 말하고, 못 찾으시면 누를 버튼을 알려 드린다.
    # ★ 2026-09-26 브라우저 무대: 크롬이 화면 밖에 있으면(`stage`) 사람이 할 곳은 **온텔릭 창 안의 브라우저 화면**이다.
    #   작업 표시줄 아이콘을 누르면 진짜 크롬이 화면에 나오긴 하지만, 그건 무대가 안 될 때의 뒷문이다.
    door = ("Sonjari 창의 브라우저 화면을 눌러 직접" if stage
            else "작업 표시줄에서 깜빡이는 크롬 아이콘을 눌러")
    where = f"\n\n그 화면 주소: {url[:200]}" if url else ""
    progress = f"\n\n여기까지 했습니다: {done}/{total}단계." if total else ""
    if code == "login_required":
        what = (
            f"**로그인이 필요해요.** {door} 평소처럼 로그인해 주세요. "
            "'로그인 상태 유지'를 켜 두시면 다음부터는 안 물어봐요."
        )
    elif code == "payment_required":
        # 결제는 되돌릴 수 없는 일이라 이 문을 사람이 지나가도 **마지막 결제 누르기는 여전히 승인 카드**를 거친다.
        what = (
            "**결제 정보를 넣는 화면이에요.** 카드 번호·결제 비밀번호는 제가 넣지 않아요 — "
            f"{door} 결제 수단을 넣거나 골라 주세요. "
            "결제 수단이 없으면 등록부터 해 주셔야 해요. 실제 결제는 끝까지 제가 누르지 않고 먼저 여쭤볼게요."
        )
    else:
        what = (
            "**사람인지 확인하는 화면이 떴어요**(체크 표시나 그림 고르기). 이건 제가 대신 누르지 않아요 — "
            f"{door} 확인해 주세요."
        )
    tail = (" 누르시는 동안 저는 기다려요. 그 화면으로 안 되면 「크롬 창 보기」를 눌러 주세요." if stage
            else " 크롬 창이 안 보이면 Sonjari 화면의 「크롬 창 보기」를 눌러 주세요.")
    return (what + where + progress
            + "\n\n다 하시면 제가 알아서 이어서 할게요. 따로 말씀 안 하셔도 돼요." + tail)


def is_cleared(gate: dict[str, Any], state: dict[str, Any]) -> bool:
    """문이 열렸는가.

    두 가지 신호를 본다. 둘 다 **페이지에 말을 걸지 않고** 알 수 있는 것들이다:

      1. 네이버 로그인 쿠키가 생겼다 (네이버 계열일 때 확실한 신호)
      2. 막혔던 그 주소를 떠났다 (로그인에 성공하면 사이트가 다른 곳으로 보낸다)

    ★ 모르면 열렸다고 하지 않는다. 잘못 열렸다고 판단해 재개하면 자비스는 아직
    막혀 있는 화면에서 다시 헛돈다 — 기다리는 것보다 나쁘다.
    """
    if not state.get("known"):
        return False
    code = str(gate.get("code") or "")
    blocked_url = str(gate.get("url") or "")
    now_url = str(state.get("url") or "")

    # 네이버 쿠키는 현재 탭이 어디든 로그인 완료를 직접 증명한다.
    if code == "login_required" and "naver.com" in blocked_url and state.get("naver_signed_in"):
        return True

    # 지켜보는 동안 사람이 다른 사이트를 보고 있을 수 있다. 그 깨끗한 탭 하나로
    # 위시켓·크몽 등 대기 중인 모든 문을 열었다고 하면 안 된다. 막힐 때 본 본창과
    # OAuth 팝업의 registrable host 중 하나에 여전히 서 있을 때만 판정한다.
    expected_hosts = {str(item) for item in (gate.get("hosts") or []) if str(item)}
    if expected_hosts:
        observed_hosts = {
            site
            for candidate in (now_url, str(state.get("wall_url") or ""))
            if (site := registrable(host_of(candidate)))
        }
        if not (expected_hosts & observed_hosts):
            return False

    # ★ 막을 때 쓴 신호로 열림도 판정한다. 문이 사라졌으면 사람이 지나간 것이다.
    #
    # 주소만 보던 것이 두 번째 구멍이었다. 크몽처럼 로그인이 **모달**로 뜨는 SPA 는
    # 로그인해도 주소가 그대로라, 스탠바이는 걸려도 영영 안 깨어난다 — 15분 뒤
    # 시간이 다 돼서야 가진 것으로 답하게 된다.
    #
    # 비밀번호 칸이 사라졌다고 반드시 로그인에 성공한 것은 아니다(그냥 닫았을 수도
    # 있다). 그래도 이어가는 편이 낫다: 아직 막혀 있으면 그 문 앞에서 다시 서면
    # 되고, 그건 되돌릴 수 있는 실수다. 영영 매달려 있는 것이 더 나쁘다.
    if wall_code(state) == "":
        if (state.get("password_fields") is not None or state.get("captcha") is not None
                or state.get("payment") is not None):
            return True

    if code == "login_required" and "naver.com" in blocked_url:
        return bool(state.get("naver_signed_in"))

    if not blocked_url or not now_url:
        return False
    if now_url == blocked_url:
        return False
    # 주소가 바뀌었어도 여전히 로그인·확인 화면이면 아직이다.
    lowered = now_url.lower()
    return not any(marker in lowered for marker in _GATE_URL_MARKERS)
