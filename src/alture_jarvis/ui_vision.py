"""Vision-assisted targeting: the model is the eyes, the code is the hands.

Why it is built this way is worth stating once, because the obvious design is
worse. The obvious design hands a screenshot to the model and asks where to
click. That fails twice over on a local vision model: it can read a
screen but cannot produce reliable pixel coordinates, and -- measured, and
written up in the 2026-08-05 handoff (3.1) -- **a click that lands on empty
space still reports success**. Three clicks were spent that way on the gap
between two buttons while the dialog sat there untouched.

So the model never sees a coordinate and never returns one. It is shown a
screenshot in which every operable element already carries a number, plus the
matching list of those numbers, and it answers with one number. That number is
a `ref`, the ref resolves to a Playwright locator, and Playwright applies its
own visibility and actionability checks before anything is pressed. A misread
therefore costs a wrong candidate, which is visible and recoverable -- not a
silent click into nothing.

The fail-closed rule: **0 means "none of these"**, and 0 stops. A picker that
guesses when it is unsure is a picker that eventually presses 확인.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from .browser import BrowserWorker
from .config import JarvisConfig, setting
from .models import RiskLevel
from .ollama import OllamaClient
from .tool_gateway import ToolGateway, ToolSpec

_SYSTEM = (
    "너는 화면에서 목표에 해당하는 요소 하나를 고르는 역할이다. "
    "화면에는 분홍색 번호표가 붙어 있고, 아래 목록의 번호와 같다. "
    "반드시 번호 하나만 숫자로 답해라. 설명·문장·기호를 붙이지 마라. "
    "목표에 맞는 것이 목록에 없으면 0이라고 답해라. "
    "확실하지 않으면 추측하지 말고 0이라고 답해라."
)

# The model is told to answer with a bare number, and mostly does. This also
# accepts "7번", "번호 7", "**7**" -- shapes measured from small local models --
# but deliberately refuses a sentence with several numbers in it, because
# picking the first one there is guessing.
_NUMBER = re.compile(r"\d{1,3}")

_MAX_CANDIDATES = 60

# 이름으로 곧장 찾을 때, 이름이 이보다 길면 안 본다.
#
# 수집기는 이름이 없는 요소에 **둘레 글을 빌려** 채운다("Python 줄의 연필"). 그래서
# 긴 이름에는 온갖 낱말이 우연히 섞여 있다 — 다나와 광고 카드 이름이 예순 자가 넘고
# 그 안에 "가격"이 들어 있다. 진짜 이름표(정렬·탭·버튼)는 짧다.
_NAME_MATCH_MAX_CHARS = 20

# 못 찾았을 때 **내려가며 다시 볼 횟수.** 0 이면 예전처럼 한 화면만 본다.
#
# 둘로 잡은 근거: 검색 결과·상품 목록에서 조작할 것(정렬·필터·더보기)은 대개 첫
# 화면이나 그 바로 아래에 있다. 무한히 내리면 못 찾는 판이 길어지기만 한다 —
# 한 번 더 보는 데 비전 호출 한 번(수 초)이 든다.
_SCROLL_LOOKS = 2

# 한 번에 내릴 픽셀. 한 화면(≈900px)씩 — 겹치지 않게 넘기면 사이에 있는 것을 놓친다.
_SCROLL_STEP_PX = 800

# ── 됐는지 화면으로 판정한다 (2026-08-11) ────────────────────────────────────
#
# 코드로 재는 검증이 자꾸 약했다. 위시켓 기술 태그와 네이버 검색창은 **값이 실제로
# 들어갔는데** verified=False 로 나왔다 — "목록이 닫혔나" 하나만 보고 있었기 때문이다.
# 같은 것을 화면 캡처로는 3초 만에 안다("칸에 Ajax 가 적혀 있고 저장 버튼이 살아났다").
#
# 다만 순서를 지킨다: **비전은 결정론을 뒤집지 않는다.** 결정론이 됐다고 하면 부르지
# 않고(느리다 — 초 단위 대 250ms), 아니라고 하거나 모르겠다고 할 때만 물어본다.
# 그리고 모델은 "네"라고 지어낼 수 있으므로 **무엇을 보고 그렇게 말하는지**를 함께
# 받는다. 근거를 못 대면 판정으로 치지 않는다.
# ★ 모델에게 **판정을 시키지 않는다. 읽기만 시킨다.** (2026-08-11 두 번째 실측)
#
# "이 상태가 맞습니까?"라고 물었더니 자른 이미지(12KB·2.6초)에서도 답이 틀렸고
# 문장이 무너졌다: "'파이썬'이 아니라 '파이썬'이라는 글자가 아닌 '파이썬'과 유사한…".
# 작은 모델에게 판단은 무겁고, 판단은 지어내기 쉽다.
#
# 읽기는 다르다 — 보이는 글자를 옮겨 적는 일은 그림에 답이 있다. 옮겨 적게 하고
# **맞는지는 코드가 정한다.** 오늘 종일 한 그 방식이다(모델이 만들고 코드가 검증).
_VERIFY_SYSTEM = (
    "너는 화면 캡처에 보이는 글자를 그대로 옮겨 적는 역할이다. "
    "판단하거나 설명하지 마라. 보이는 글자만 순서대로 적어라. "
    "글자가 하나도 없으면 (없음) 이라고만 적어라."
)
_DIGITS = re.compile(r"\d[\d,.]*")


def numbers_of(text: str) -> list[str]:
    """글에 나온 숫자들(쉼표 뗌). 폰트 치환·이미지 가격 판정에 쓴다."""
    return [n.replace(",", "").rstrip(".") for n in _DIGITS.findall(text or "") if n.strip(",.")]


def compare_seen_and_dom(seen: str, dom: str) -> dict[str, Any]:
    """그림에서 읽은 숫자와 DOM 글자 숫자를 **코드가** 대조한다. 모델은 읽기만 했다."""
    seen_numbers, dom_numbers = numbers_of(seen), numbers_of(dom)
    if not seen_numbers:
        verdict = "no_numbers_seen"
    elif not dom_numbers:
        verdict = "only_in_picture"        # DOM 에 숫자가 없는데 화면엔 있다 — 그림·캔버스·아이콘 폰트
    elif set(seen_numbers) <= set(dom_numbers):
        verdict = "same"
    else:
        verdict = "differs"                # 폰트 치환 등으로 DOM 글자와 화면 숫자가 다르다
    return {"verdict": verdict, "numbers_seen": seen_numbers[:10], "numbers_dom": dom_numbers[:10]}


def _loose_contains(seen: str, want: str) -> bool:
    """읽어 온 글자에 찾는 말이 들어 있나 — **공백·대소문자만 무시**한다.

    더 느슨하게 하면(자모 분해·유사도) 없는 것을 있다고 하기 시작한다. 검증에서
    관대함은 미덕이 아니다.
    """
    squeeze = lambda text: "".join(str(text or "").split()).casefold()
    return bool(want) and squeeze(want) in squeeze(seen)


def _verify_enabled() -> bool:
    """기본은 켜짐. 끄려면 JARVIS_UI_VERIFY=0.

    처음엔 꺼 두었다 — 화면 전체를 주고 **판정을 시켰더니** 178초에 오답이었다.
    두 가지를 바꾸고 켠다: 그 자리만 잘라서 보여주고(441KB → 12KB), 모델에게는
    **읽기만** 시킨다(판정은 코드가). 실측 1.5~2.0초, 양방향 정확.
    """
    return setting("JARVIS_UI_VERIFY", "1").lower() not in {"0", "false", "no"}


_VERDICT = {
    "예": True,
    "yes": True,
    "아니오": False,
    "아니요": False,
    "no": False,
}


class UiVision:
    """Choose an on-screen target by looking, then act through the ref."""

    def __init__(
        self, config: JarvisConfig, worker: BrowserWorker, client: OllamaClient
    ) -> None:
        self.config = config
        self.worker = worker
        self.client = client
        self._definitions = self._build_definitions()

    # ---- tools ----------------------------------------------------------
    @staticmethod
    def _function(
        name: str, description: str, properties: dict[str, Any], required: list[str] | None = None
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                },
            },
        }

    def _build_definitions(self) -> list[dict[str, Any]]:
        return [
            self._function(
                "ui_find_target",
                "화면을 보고 목표에 해당하는 요소를 찾아 ref를 돌려준다. 누르지는 않는다. "
                "snapshot 목록만으로 어느 것이 목표인지 판단이 안 설 때 쓴다. "
                "단, 검토된 사이트 검색 절차가 있는 화면에서 검색창을 찾는 용도로는 거절된다 — "
                "그때는 browser_site_search를 쓰면 안전한 절차로 자동 연결된다.",
                {"goal": {"type": "string", "description": "예: 글쓰기 버튼, 검색 입력란"}},
                ["goal"],
            ),
            self._function(
                "ui_verify",
                "화면의 그 자리를 **읽어서** 기대한 글자가 있는지 본다. 누르지 않는다. "
                "browser_click·browser_pick_suggestion 이 verified=false 를 돌려줬는데 "
                "정말 안 된 건지 확인할 때 쓴다. ref 를 주면 그 칸만 잘라 보므로 훨씬 "
                "빠르고 정확하다. 판정은 코드가 하고 모델은 읽기만 한다.",
                {
                    "claim": {"type": "string", "description": "확인할 상태. 예: 기술명 칸에 Ajax 가 적혀 있다"},
                    "ref": {
                        "type": "string",
                        "description": "그 칸의 ref. 주면 그 자리만 잘라 보므로 훨씬 빠르고 정확하다",
                    },
                    "expect": {
                        "type": "string",
                        "description": "화면에 있어야 할 글자. 이것으로 코드가 판정한다 (예: Ajax)",
                    },
                },
                ["claim"],
            ),
            self._function(
                "ui_read_value",
                "화면의 **그 칸을 잘라 그림으로 읽는다**(가격·수량 같은 값). 누르지 않는다. 사이트가 숫자를 이미지·캔버스·"
                "글꼴 치환으로 숨겨서 본문/스냅샷 글자와 화면이 다를 때 쓴다. ref(스냅샷) 또는 box{x,y,width,height}"
                "(targets·probe 의 상자)를 준다. 모델은 읽기만 하고, DOM 글자와 숫자가 같은지는 코드가 판정한다.",
                {
                    "ref": {"type": "string"},
                    "box": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                                             "width": {"type": "number"}, "height": {"type": "number"}}},
                    "what": {"type": "string", "description": "무엇을 읽나. 예: 판매가"},
                },
            ),
            self._function(
                "ui_click_target",
                "화면을 보고 목표에 해당하는 요소를 찾아 누른다. 찾지 못하면 누르지 않고 멈춘다. "
                "전송·결제·삭제처럼 되돌릴 수 없는 동작은 보호 규칙에 따라 차단된다.",
                {"goal": {"type": "string"}},
                ["goal"],
            ),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self._definitions}

    def read_value(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """칸을 잘라 **그림으로** 읽고, DOM 글자와 숫자를 코드가 대조한다(2026-09-18 「그림·폰트로 숨긴 값」).

        `ui_verify` 와 같은 규율이다: 잘라서 보고(전체 화면은 축소돼 못 읽는다), 모델은 옮겨 적기만, 판정은 코드.
        """
        ref = str(arguments.get("ref") or "")
        box = arguments.get("box") if isinstance(arguments.get("box"), dict) else None
        if not ref and not box:
            raise ValueError("ref_or_box_required")
        shot = self.worker.execute("browser_screenshot", {"ref": ref, "pad": 6} if ref else {"box": box, "pad": 6})
        image = self._encode(str(shot.get("path") or ""))
        if not image:
            return {"verdict": "unknown", "reason": "화면을 캡처하지 못했습니다", "screenshot": shot.get("path", "")}
        reply = self.client.chat_message(
            "이 그림에 보이는 글자와 숫자를 그대로 옮겨 적어라.",
            system=_VERIFY_SYSTEM,
            images=[image],
            temperature=0.0,
            think=False,
            num_predict=60,
        )
        seen = str(reply.get("content") or "").strip()
        dom = ""
        if ref:
            try:
                dom = str(self.worker.execute("browser_read", {"selector": f'[data-jarvis-ref="{ref}"]', "max_chars": 500}).get("text") or "")
            except Exception:
                dom = ""
        compared = compare_seen_and_dom(seen, dom)
        verdict = compared["verdict"]
        notes = {
            "only_in_picture": "이 값은 **화면 그림에만** 있다(DOM 글자에 숫자가 없다) — 사이트가 이미지·캔버스로 그렸다. seen 의 값을 쓰되 그림에서 읽었다고 밝혀라.",
            "differs": "화면 숫자와 DOM 글자 숫자가 **다르다** — 글꼴 치환일 수 있다. 사람이 보는 것은 화면이다. 둘 다 말하고 화면 값을 앞에 둬라.",
            "same": "화면과 DOM 글자의 숫자가 같다 — 본문 값을 그대로 써도 된다.",
            "no_numbers_seen": "그림에서 숫자를 못 읽었다. 칸을 더 넓게 잡거나 본문 값을 써라.",
        }
        return {
            "what": str(arguments.get("what") or ""),
            "seen": seen[:200],
            "dom_text": dom[:200],
            **compared,
            "screenshot": shot.get("path", ""),
            "instruction": "[도구가 보낸 안내] " + notes[verdict],
        }

    def register(self, gateway: ToolGateway) -> None:
        handlers = {"ui_find_target": self.find, "ui_verify": self.verify, "ui_click_target": self.click,
                    "ui_read_value": self.read_value}
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            # ★ `ui_verify` 는 한 번 껐다가 다시 켠 도구다 (2026-08-11).
            #
            # 화면 전체(441KB)를 주고 **판정을 시켰더니** 웜 상태에서 178초에
            # 오답이었다. 축소된 그림에서 글자를 못 읽었고, 문장은 같은 말을
            # 반복하며 무너졌다. 그래서 처음엔 꺼 두었다.
            #
            # 두 가지를 바꾸니 쓸 만해졌다:
            #   ① 그 자리만 잘라서 본다      441KB → 12KB
            #   ② 모델은 **읽기만** 한다      판정은 코드가 (오늘 종일 한 그 방식)
            # 실측 1.5~2.0초 · 있는 것/없는 것 양방향 정확. 그래서 켠다.
            # 끄려면 JARVIS_UI_VERIFY=0.
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    # Finding is a read. Clicking something a model picked from a
                    # picture is not, so it sits at the same level as filling a
                    # field -- the irreversible ones are stopped further down by
                    # the browser's own risky-action gate.
                    # 보는 것은 L0, 누르는 것만 L1 이다.
                    risk_level=RiskLevel.L1 if name == "ui_click_target" else RiskLevel.L0,
                    handler=handlers[name],
                    enabled=self.config.browser_enabled and (
                        name != "ui_verify" or _verify_enabled()
                    ),
                )
            )

    # ---- the pick --------------------------------------------------------
    def find(self, arguments: dict[str, Any]) -> dict[str, Any]:
        goal = str(arguments.get("goal") or "").strip()
        if not goal:
            raise ValueError("goal_required")
        # ★ 레시피가 있는데 검색창을 그림으로 다시 찾지 않는다 (2026-08-17 실측).
        #
        # 자연어 사람인 시험에서 시스템 프롬프트와 도구 설명에 site_run 우선이라고
        # 써 두었는데도 Gemma는 ui_find_target → snapshot → find → ui_find_target...
        # 으로 10걸음을 손운전했다. 검색어는 모델이 사용자 문장에서 이미 알고 있다.
        # 여기서 억지로 뽑아 실행하면 다른 값을 검색할 수 있으므로, 검토된 길의 존재만
        # 알리고 ref 생성을 거절한다. 모델은 검색어를 그대로 browser_site_search에 준다.
        search_goal = re.search(
            r"검색\s*(창|입력|칸|버튼|어|필드)|search\s*(box|input|field|button)",
            goal,
            re.IGNORECASE,
        )
        route_lookup = getattr(self.worker, "reviewed_search_recipe", None)
        route = str(route_lookup() or "") if search_goal and callable(route_lookup) else ""
        if route:
            raise RuntimeError(
                "reviewed_site_search_required — 이 사이트에는 사람이 검토한 검색 절차가 "
                f"이미 있다({route}). 검색창 ref를 그림으로 찾지 말고 지금 "
                "browser_site_search(query=사용자가 요청한 검색어)를 불러라. 그 호출이 "
                "검토된 L0 절차로 자동 연결된다."
            )
        answer = self._find(arguments, goal)
        return self._note_if_asked_again(goal, answer)

    # 화면마다 "무엇을 찾아 무엇을 받았나". 되묻기를 알아보는 데만 쓴다.
    _recent_finds: dict[str, list[tuple[str, str]]] = {}

    def _note_if_asked_again(self, goal: str, answer: dict[str, Any]) -> dict[str, Any]:
        """같은 화면에서 **같은 답을 또 받았으면** 그 사실을 알려 준다.

        ## 왜 필요한가 (2026-08-15 실측)

        되풀이 차단을 풀어 주니(보는 것은 되풀이가 아니므로 맞는 수정이다) 이번엔
        **되묻기**가 드러났다. 사람인 16걸음 판에서 10걸음이 이 도구였다:

            2 검색창        -> j6      6 (스냅샷)
            4 검색어 입력란  -> j6      7 검색어 입력창 -> j6
            5 검색어 입력창  -> j6      8 input        -> j6
                                      9 검색창 입력란  -> j6

        **여섯 가지 표현으로 물어 여섯 번 같은 답을 받았고, 한 번도 안 채웠다.**
        차단 장치가 이걸 못 잡는 이유는 분명하다 — `goal` 이 매번 달라서 지문이 갈린다.
        막아서 풀 문제가 아니라 **알려 줘서** 풀 문제다.

        이 도구가 답을 못 준 적이 없다는 것이 요점이다. 모델은 확신이 없어서
        되물은 것이고, 확신은 같은 답을 한 번 더 받는다고 생기지 않는다.
        그래서 **다음에 무엇을 하면 되는지**를 이름까지 대서 말해 준다.
        """
        ref = str(answer.get("ref") or "")
        if not ref:
            return answer
        # ★ 주소를 물으려고 왕복을 하나 더 하지 않는다. 방금 그린 화면
        # (`browser_annotate`)이 이미 주소를 갖고 있다 — 효율을 말하면서 왕복을
        # 늘리면 앞뒤가 안 맞고, 시험이 그걸 잡았다(호출 순서가 어긋났다).
        page = str(getattr(self, "_last_seen_url", "") or "")
        seen = self._recent_finds.setdefault(page.split("#")[0], [])
        same = [g for g, r in seen if r == ref]
        seen.append((goal, ref))
        del seen[:-8]
        if len(same) >= 1:
            answer = {
                **answer,
                "asked_before": len(same) + 1,
                "instruction": (
                    f"★ 이 화면에서 같은 것을 벌써 {len(same) + 1}번 찾았고 **답은 매번 {ref} 로 같다**"
                    f"(앞서 물은 말: {', '.join(same[-3:])}). 표현을 바꿔 또 찾아도 같은 답이 나온다. "
                    f"지금 할 일은 찾는 것이 아니라 **쓰는 것**이다 — 채울 칸이면 "
                    f"browser_fill(ref={ref}), 누를 것이면 browser_click(ref={ref}) 을 지금 불러라. "
                    "그게 실패하면 그때 실패 메시지가 다음 수를 알려 준다. "
                    + str(answer.get("instruction") or "")
                ).strip(),
            }
        return answer

    def _find(self, arguments: dict[str, Any], goal: str) -> dict[str, Any]:
        # ★ 화면은 한 장이 아니다 — **없다고 말하기 전에 내려 본다** (2026-08-13).
        #
        # 실측(오늘 잡 142 건): `browser_scroll` 을 쓴 잡이 **9 건(6%)**, `load_more`
        # 는 2 건이다. 사실상 안 내려 본다. 그런데 이 도구의 후보는 **지금 화면에
        # 든 것**뿐이라(그림에 번호를 그리니까), 접힌 아래쪽에 있는 것은 언제나
        # "없습니다"가 된다.
        #
        # 프롬프트에 "스크롤해라"라고 적어 두는 것은 이미 해 봤고 안 먹었다(위 실측).
        # 사람은 한 화면 보고 "이 페이지엔 없네요"라고 하지 않는다. 도구가 한다.
        looked = 0
        while True:
            annotated = self.worker.execute("browser_annotate", {"limit": _MAX_CANDIDATES})
            # 되묻기를 알아보려면 "어느 화면에서 물었나"가 필요하다. 방금 그린 것이
            # 그 화면이므로 여기서 받아 둔다(따로 물으면 왕복이 하나 는다).
            self._last_seen_url = str((annotated or {}).get("url") or "")
            result = self._pick(goal, annotated, scrolled=looked)
            if result is not None:
                return result
            if looked >= _SCROLL_LOOKS:
                candidates = list(annotated.get("candidates") or [])
                raise RuntimeError(
                    f"ui_target_not_found:{goal} — 화면을 {looked + 1}번(내려가며) 봤는데 "
                    f"마지막 화면 후보 {len(candidates)}개 중에 없습니다. 다른 낱말로 다시 "
                    "찾거나, browser_snapshot 으로 전체를 보세요."
                )
            looked += 1
            self.worker.execute("browser_scroll", {"amount": _SCROLL_STEP_PX})

    def _pick(
        self, goal: str, annotated: dict[str, Any], *, scrolled: int
    ) -> dict[str, Any] | None:
        """이 화면에서 고른다. **못 찾았으면 None** — 부르는 쪽이 내려서 다시 부른다.

        못 찾음을 예외가 아니라 None 으로 돌려주는 것이 요점이다. 예외로 만들면
        "아래를 더 봐야 한다"와 "정말 없다"가 같은 모양이 되고, 그러면 내려 볼 수가 없다.
        """
        candidates = list(annotated.get("candidates") or [])

        # ★ 비전에 묻기 전에 **코드가 먼저 이름으로 찾아본다** (2026-08-13).
        #
        # 그림에 번호를 그릴 수 있는 개수에는 한계가 있어(비전이 못 읽는다) 후보는
        # 화면에 든 것 중 앞에서부터 60 개다. 다나와 검색결과처럼 머리말·배너·광고가
        # 화면을 가득 채우는 곳에서는 그 60 개가 정렬 바에 닿지 않는다 — 실측에서
        # 자비스는 "낮은가격순"이라는 **이름이 정확히 일치하는 요소를 두고** 광고
        # 상품 링크를 골랐다.
        #
        # 이 저장소가 이미 정리해 둔 규칙이 있다: **비전은 읽게 하고 판정은 코드가.**
        # 이름이 딱 하나 맞으면 그건 판정이 아니라 조회다. 둘 이상이면 애매한
        # 것이므로 원래대로 그림을 보고 고른다.
        exact = self._by_name(goal, annotated.get("elements") or [])
        method = "name_match"
        if exact is None and scrolled == 0:
            # ★ 받은 목록에 없으면 **페이지 전체에서** 이름으로 한 번 찾는다 (2026-10-07 폼 벤치 넷째 판).
            #   그림 도구가 내주는 목록은 400개까지다. 요소 1,062개인 이력서 화면에서 이름이 정확히 「자기소개서 1 내용」인
            #   칸(1,056번째)이 목록에 없었고, 그림에 물으니 화면에 보이는 유일한 글상자(경력기술서)를 골랐다 — 모델은 거기에
            #   썼고 「자기소개서에 넣었습니다」라고 답했다(세 판 중 두 판). 이름이 딱 하나 맞으면 조회다. 그림은 그다음이다.
            exact = self._by_name_anywhere(goal)
            method = "name_match_whole_page"
        if exact is not None:
            return {
                "goal": goal,
                "screenshot": annotated.get("path", ""),
                "candidate_count": len(candidates),
                "raw": "",
                "chosen": exact,
                "ref": str(exact.get("ref") or ""),
                "status": "found",
                # 어떻게 찾았는지를 남긴다. 눈금이 "비전이 잘 골랐다"와 "코드가
                # 찾았다"를 구별하지 못하면 비전의 실력을 잘못 재게 된다.
                "method": method,
                "scrolled": scrolled,
            }

        if not candidates:
            # 지금 화면에 조작할 것이 없다. 아래에는 있을 수 있으니 내려 보게 한다.
            return None

        # ★ 그림이 없으면 **비전에 묻지 않는다** (2026-08-14).
        #
        # 무거운 페이지에서 스크린샷이 타임아웃 난다(쿠팡 상세 실측: 20초 ×2).
        # 이제 그래도 목록은 오지만, 그림 없이 "번호로 답해라"라고 물으면 모델은
        # 목록 글자만 보고 찍는다 — 그건 판정이 아니라 추측이고, 이 도구가 막으려는
        # 바로 그것이다. 이름으로 못 찾았고 그림도 없으면 **못 찾은 것**이다.
        image = self._encode(str(annotated.get("path") or ""))
        if not image:
            return None

        prompt = self._prompt(goal, candidates)
        reply = self.client.chat_message(
            prompt,
            system=_SYSTEM,
            images=[image],
            temperature=0.0,
            # gemma4 is a thinking model: without this the whole num_predict
            # budget goes into message.thinking and content comes back empty.
            think=False,
        )
        raw = str(reply.get("content") or "").strip()
        number = self._parse(raw)
        result: dict[str, Any] = {
            "goal": goal,
            "screenshot": annotated.get("path", ""),
            "candidate_count": len(candidates),
            "raw": raw[:200],
            "scrolled": scrolled,
        }
        if number is None:
            result["chosen"] = None
            result["status"] = "unclear"
            result["reason"] = "모델이 번호로 답하지 않았습니다"
            return result
        if number == 0:
            # ★ **못 찾은 것은 성공이 아니다.**
            #
            # 예전에는 `status: not_found` 를 담은 dict 를 그냥 돌려줬다. 게이트웨이는
            # 예외가 없으면 `ok=True` 로 적으므로, **못 찾은 호출이 성공으로 기록됐다.**
            # 2026-08-13 실측: 55 회 중 53 회가 ok=True 였고, 그 안에 다나와 정렬을 못
            # 찾은 7 회가 통째로 들어 있었다 — L2 조사 성공률 98.8% 가 그만큼 부풀어
            # 있었다는 뜻이다.
            #
            # 모델은 예전에도 이유를 받아 봤다(도구 결과는 그대로 전달된다). 잘못된
            # 것은 **장부**였다. 이 저장소가 이미 두 번 겪은 모양이다 — 도구가 예외를
            # 안 냈다고 성공으로 세는 것(사고: 블로그 임시저장, 생존 검사).
            #
            # ★ 다만 여기서 **예외를 던지지 않는다.** 부르는 쪽이 내려서 다시 본 뒤,
            # 그래도 없을 때 던진다. 아래를 안 보고 "없다"고 하는 것이 오늘 실측에서
            # 가장 흔한 실패였다.
            return None
        ref = f"j{number}"
        chosen = next((item for item in candidates if item.get("ref") == ref), None)
        if chosen is None:
            # A number outside the list is a misread, not a target. Resolving it
            # to "the nearest one" would be the same guess the fail-closed rule
            # exists to prevent.
            result["chosen"] = None
            result["status"] = "out_of_range"
            result["reason"] = f"{number}번은 후보 목록에 없습니다"
            return result
        result["chosen"] = chosen
        result["ref"] = ref
        result["status"] = "found"
        return result

    def _by_name_anywhere(self, goal: str) -> dict[str, Any] | None:
        """페이지 전체(화면 밖 포함)에서 이름이 딱 하나 맞는 요소. 찾기 도구가 훑는다 — 번호는 스냅샷과 같은 것을 쓴다."""
        try:
            found = self.worker.execute("browser_find", {"query": goal, "limit": 50})
        except Exception:  # noqa: BLE001 — 이름 조회가 안 되면 예전대로 그림으로 간다
            return None
        matches = found.get("matches") if isinstance(found, dict) else None
        return self._by_name(goal, [item for item in (matches or []) if isinstance(item, dict)])

    @staticmethod
    def _by_name(goal: str, elements: list[dict[str, Any]]) -> dict[str, Any] | None:
        """이름이 **딱 하나** 맞는 요소. 애매하면 None(그때는 그림을 본다).

        조건을 좁게 잡는 것이 요점이다:
          · 이름이 짧아야 한다 — 긴 이름은 둘레 글을 빌려 온 것이라(수집기가 그렇게
            채운다) 우연히 낱말이 들어 있을 뿐이다. 다나와 광고 카드 이름이 예순 자다.
          · 붙여 비교한다 — "낮은가격순"과 "낮은 가격순"은 사람에게 같은 말이다.
          · 후보가 둘 이상이면 **고르지 않는다.** 그건 판정이고, 판정은 그림 몫이다.
        """
        squeeze = lambda text: "".join(str(text or "").split())  # noqa: E731
        target = squeeze(goal)
        if len(target) < 2:
            return None
        hits: list[dict[str, Any]] = []
        for item in elements:
            name = squeeze(item.get("name"))
            if not name or len(name) > _NAME_MATCH_MAX_CHARS:
                continue
            if name == target or name in target or target in name:
                hits.append(item)
        if len(hits) != 1:
            return None
        return hits[0]

    def verify(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """화면을 보고 **됐는지 아닌지**를 답한다. 누르지 않는다.

        코드로 재는 검증이 약할 때 쓴다. `browser_click`·`browser_pick_suggestion`
        이 verified=false 를 돌려줬는데 사람 눈에는 된 것 같을 때가 그렇다 —
        실제로 위시켓 기술 태그와 네이버 검색창이 **값은 들어갔는데** false 였다.

        판정은 셋이다: 됐다 / 안 됐다 / **모르겠다.** 셋째가 중요하다. 가려져 있거나
        화면 밖이면 모르는 것이고, 모르는 것을 됐다고 적으면 그게 제일 나쁜 보고다.
        """
        claim = str(arguments.get("claim") or "").strip()
        if not claim:
            raise ValueError("claim_required")
        # ★ 그 자리만 잘라서 본다. 화면 전체를 주면 축소돼 글자를 못 읽는다
        # (실측: 441KB 전체화면 178초 · 오답). ref 가 없으면 어쩔 수 없이 전체다.
        ref = str(arguments.get("ref") or "")
        shot = self.worker.execute("browser_screenshot", {"ref": ref} if ref else {})
        image = self._encode(str(shot.get("path") or ""))
        if not image:
            return {
                "claim": claim,
                "verdict": "unknown",
                "reason": "화면을 캡처하지 못했습니다",
                "screenshot": shot.get("path", ""),
            }
        reply = self.client.chat_message(
            "이 그림에 보이는 글자를 그대로 옮겨 적어라.",
            system=_VERIFY_SYSTEM,
            images=[image],
            temperature=0.0,
            # gemma4 는 thinking 모델이라 이걸 안 끄면 답이 통째로 빈다.
            think=False,
            # ★ 길이를 묶는다. 안 묶었더니 같은 말을 반복하며 무너졌다. 옮겨 적는
            # 일은 짧게 끝나므로 길게 둘 이유가 없고, 길수록 지어낸다.
            num_predict=80,
        )
        seen_text = str(reply.get("content") or "").strip()
        # ★ 판정은 **코드가** 한다. 모델은 읽기만 했다.
        want = str(arguments.get("expect") or "").strip()
        if want:
            verdict = "yes" if _loose_contains(seen_text, want) else "no"
        else:
            verdict = "unknown"
        return {
            "claim": claim,
            "expect": want,
            "verdict": verdict,
            "saw": seen_text[:300],
            "screenshot": shot.get("path", ""),
            "instruction": (
                f"화면에서 읽은 글자에 ‘{want}’ 가 있다."
                if verdict == "yes"
                else f"화면에서 읽은 글자에 ‘{want}’ 가 없다. saw 를 보고 판단해라."
                if verdict == "no"
                else "무엇을 확인할지(expect)를 주지 않아 판정하지 않았다. 읽은 글자만 saw 에 있다."
            ),
        }

    def click(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # ★ 조회와 클릭은 실패의 뜻이 다르다.
        #
        # `find` 는 **찾는 것이 일**이라, 못 찾았으면 그 일을 못 한 것이다(장부에
        # 실패로 남아야 L2 가 부풀지 않는다). 반면 `click` 은 **누르는 것이 일**이고,
        # 못 찾았을 때 아무것도 안 누른 것은 **제대로 한 것**이다 — 비슷한 걸
        # 아무거나 누르는 것보다 낫다.
        #
        # 그래서 여기서 받아 낸다. 예외로 올려 보내면 상위 루프가 재시도하며 같은
        # 화면을 계속 다시 본다.
        try:
            found = self.find(arguments)
        except RuntimeError as exc:
            if not str(exc).startswith("ui_target_not_found:"):
                raise
            return {
                "goal": str(arguments.get("goal") or ""),
                "chosen": None,
                "status": "not_found",
                "reason": "화면에서 목표를 찾지 못해 아무것도 누르지 않았습니다",
            }
        if found.get("status") != "found":
            return found
        clicked = self.worker.execute("browser_click", {"ref": found["ref"]})
        found["clicked"] = clicked
        found["status"] = "clicked"
        return found

    # ---- helpers ---------------------------------------------------------
    def _prompt(self, goal: str, candidates: list[dict[str, Any]]) -> str:
        lines = []
        for item in candidates:
            number = str(item.get("ref") or "j0")[1:]
            name = str(item.get("name") or "").strip() or "(이름 없음)"
            role = str(item.get("role") or "")
            frame = str(item.get("frame") or "")
            suffix = f" · {frame}" if frame and frame != "main" else ""
            lines.append(f"{number}. [{role}] {name}{suffix}")
        return (
            f"목표: {goal}\n\n"
            "화면에 붙은 번호와 같은 후보 목록이다:\n"
            + "\n".join(lines)
            + "\n\n번호 하나만 답해라. 목록에 없으면 0."
        )

    @staticmethod
    def _encode(path: str) -> str:
        if not path:
            return ""
        try:
            return base64.b64encode(Path(path).read_bytes()).decode("ascii")
        except Exception:
            return ""

    @staticmethod
    def _parse(raw: str) -> int | None:
        numbers = _NUMBER.findall(raw)
        if len(numbers) != 1:
            # Zero numbers means it answered in prose. More than one means it is
            # reasoning out loud, and taking the first would be picking for it.
            return None
        try:
            return int(numbers[0])
        except ValueError:
            return None
