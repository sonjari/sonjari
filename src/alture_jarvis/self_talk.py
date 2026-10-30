"""손자리가 **자기 설정을 대화로** 알려 주고 · 묻고 · 바꾼다 (2026-10-20 대표).

## 왜

대표(10-20): 그림 읽기가 꺼진 PC 에서 「이 제품 찾아서 분석해 줘」가 그림을 못 읽고 끝났다. 「손자리가 설정을 보고 있다가
'그림 읽기를 켜면 됩니다, 바꿔 드릴까요?' 하고 — **카드가 뜨는 게 아니라 대화로** — 바꿔 주면 좋겠다 · 클로드처럼」.

## 무엇을 (모델에게 맡기지 않는다 — 이어받기 `takeover.intercept` 와 같은 자리 · 같은 방식)

- 「뭐가 바뀌었어?」 → 패키지 안 글(`whats_new`)로 답한다.
- 「지금 설정 보여줘」 · 「무슨 모델 써?」 → 지금 값으로 답한다.
- 「그림 읽기 켜 줘 / 꺼 줘」 → 바로 바꾸고, 무엇이 바뀌었는지와 되돌리는 말을 적는다(사람이 직접 시킨 것이다).
- 손자리가 그림을 못 읽고 끝난 판이면 답 끝에 「켜 드릴까요?」를 붙이고(`offer_eyes`) **다음 말 한 번 동안만** 기다린다.
  그 말이 「응」이면 켜고, 「아니」면 그대로, 다른 말이면 제안을 버린다(질문이 엇갈려 「응」이 엉뚱한 것을 승인하지 않게).
- 「되돌려」 → 이 대화에서 바로 앞에 바꾼 것을 되돌린다.

## 지키는 것

- 「응」은 **사람이 친 말**에서만 받는다. 이 모듈은 채팅 입구에서 사람의 말만 본다 — 웹 · 파일 · 도구 결과의 글은 여기 오지 않는다.
- 대화로 바꿀 수 있는 것은 지금 **그림 읽기 하나**다(되돌릴 수 있고 이 PC 안에서 끝난다). 보안 · 권한 · 허용 폴더 · 밖으로 보내는
  연결 · 「클로드에게 넘기기」(구독 한도를 쓴다) · 새 모델 받기는 사람이 설정 화면에서 한다.
- 알아보는 말은 **짧고 분명한 문장**만 본다. 「네이버 뭐가 바뀌었어?」 같은 일 부탁을 가로채면 그 일이 사라진다.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import whats_new

#: 제안은 다음 말 한 번 · 그리고 이 시간 안에만 유효하다.
OFFER_TTL_SEC = 30 * 60
#: 「되돌려」가 닿는 시간.
UNDO_TTL_SEC = 2 * 60 * 60

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", str(text or "")).strip().lower()


def _short(text: str, limit: int) -> bool:
    return 0 < len(_norm(text)) <= limit


_END = r"[\s.!~?…ㅎㅋ]*$"
_YES = re.compile(
    r"^(응+|어+엉*|엉+|웅+|네+|넵|넹|예|ㅇㅇ+|ㅇㅋ|오케이|ok(ay)?|yes|yep|yeah|sure|좋아(요)?|그래(요)?|"
    r"그렇게 해(줘|주세요|요)?|바꿔(줘|주세요)?|켜(줘|주세요)?|해(줘|주세요)?|부탁(해|해요|합니다)?)"
    r"(\s*(바꿔|켜|해)(줘|주세요)?)?" + _END
)
_NO = re.compile(r"^(아니(요|야)?|아뇨|ㄴㄴ|괜찮아(요)?|됐어(요)?|안 ?해도 ?돼|no|nope|그대로 ?둬(줘)?)" + _END)
_UNDO = re.compile(r"^(되돌려(줘|주세요)?|원래대로(\s*(해|돌려)(줘|주세요)?)?|다시 원래대로|undo|revert|switch (it )?back)" + _END)

_EYES_ON = re.compile(r"(그림\s*(읽기|보기)\s*(를|좀)?\s*(켜|켜줘|켜 ?줘|켜 ?주세요|켜라|켜봐))|(turn on picture reading|turn picture reading on)")
_EYES_OFF = re.compile(r"(그림\s*(읽기|보기)\s*(를|좀)?\s*(꺼|꺼줘|꺼 ?줘|꺼 ?주세요|꺼라|꺼봐))|(turn off picture reading|turn picture reading off)")

_DEMO_START = re.compile(
    r"^(배우기\s*시작|지금부터\s*(내가\s*하는\s*(거|것|걸)\s*(를|을)?\s*)?(잘\s*)?(보고\s*)?배워(줘|봐)?|"
    # 이름은 띄어쓰기나 쌍점 뒤에만 — 「배우기 시작하는 법 알려줘」(붙여 쓴 일 부탁)를 가로채지 않는다.
    r"(이거|이렇게)?\s*보여\s*줄게|start learning|watch (me|what i do))(?:(?:\s*[:：\-]\s*|\s+)(?P<label>.+))?" + _END
)
_DEMO_STOP = re.compile(r"^(다\s*했어(요)?|다\s*했다|끝(났어|났어요|이야)?|배우기\s*(끝|그만)|여기까지|done|finished|stop learning)" + _END)
_DEMO_CANCEL = re.compile(r"^(배우기\s*취소|취소(해|해줘)?|cancel( learning)?)" + _END)
# 슬래시 문 (2026-10-28 대표): 앱 대화창에서 `/레시피` 한 단어 — 문장 맞추기가 아니라 **정해진 명령**이다. 뒤에 이름을 붙일 수 있다
#   (`/레시피 쿠팡 장바구니`). 「/레시피를」 같은 일반 문장은 빈칸이나 끝이 아니라서 걸리지 않는다.
_SLASH_RECIPE = re.compile(r"^/(?:레시피|recipe)(?:\s+(?P<label>.+?))?\s*$", re.IGNORECASE)
# 배운 걸음을 저장하기 전 거치는 말들(한 번 해 보기 → 저장 · 버리기 · 다시 보여 주기). 모두 짧은 말만 본다.
_REPLAY_WORDS = re.compile(r"^(한 ?번 ?해 ?(볼게요?|봐(줘)?|보세요|봅시다)|해 ?봐(줘)?|(다시 )?돌려 ?봐(줘)?|try it( once)?|try once|run it( once)?)" + _END)
_SAVE_WORDS = re.compile(r"^(((그냥|그래도|검증 ?없이)\s*)?저장(해(줘|주세요)?|할게(요)?)?|save( it)?( anyway)?)" + _END)
_DISCARD_WORDS = re.compile(r"^(버려(줘)?|버리기|지워(줘)?|삭제(해줘)?|discard( it)?|throw (it )?away)" + _END)
_RETEACH_WORDS = re.compile(r"^(다시 ?보여 ?(줄게(요)?|주기|드릴게요?)|다시 ?(할게(요)?|배워)|show (me )?again)" + _END)

_WHATS_NEW_EXACT = re.compile(r"^(뭐가?|무엇이|뭐뭐) ?(바뀌었|달라졌|새로 생겼)(어|어요|나|니|지|는지)?" + _END)
_WHATS_NEW = re.compile(
    r"((업데이트|새 ?버전|이번 ?(판|버전)|손자리|sonjari|너).{0,12}(뭐|무엇|무슨|어떤).{0,6}(바뀌|달라|새로|추가))|"
    r"(업데이트 ?(내용|된 ?(거|것|기능)|한 ?(거|것)))|(새(로운)? ?기능.{0,6}(뭐|알려|있어|보여))|(what'?s new|what changed)"
)
_SETTINGS = re.compile(
    r"((손자리|너|네|니|sonjari)\s*(의\s*)?(지금\s*)?설정)|(^(지금|현재)?\s*(내\s*)?설정\s*(좀\s*)?(보여|알려|어때|어떻게))|"
    r"((무슨|어떤)\s*모델\s*(을|로)?\s*(써|쓰|돌))|(그림\s*읽기\s*(켜져|꺼져|되어|돼)\s*(있|있어|있나|있니))|"
    r"(show (me )?(your|my) settings|which model are you)"
)


def is_yes(text: str) -> bool:
    return _short(text, 16) and bool(_YES.match(_norm(text)))


def is_no(text: str) -> bool:
    return _short(text, 16) and bool(_NO.match(_norm(text)))


def is_undo(text: str) -> bool:
    return _short(text, 20) and bool(_UNDO.match(_norm(text)))


def eyes_command(text: str) -> bool | None:
    """「그림 읽기 켜 줘」 → True · 「꺼 줘」 → False · 아니면 None. 짧은 문장만 — 긴 일 부탁 속 낱말은 가로채지 않는다."""
    if not _short(text, 30):
        return None
    value = _norm(text)
    if _EYES_OFF.search(value):
        return False
    if _EYES_ON.search(value):
        return True
    return None


def asks_whats_new(text: str) -> bool:
    if not _short(text, 40):
        return False
    value = _norm(text)
    return bool(_WHATS_NEW_EXACT.match(value) or _WHATS_NEW.search(value))


def asks_settings(text: str) -> bool:
    return _short(text, 40) and bool(_SETTINGS.search(_norm(text)))


def _ctx_label(ctx: Any) -> str:
    try:
        value = int(ctx)
    except (TypeError, ValueError):
        return ""
    return f"{value // 1024}K" if value >= 1024 else str(value)


def eyes_offer_text(pages: int, saves_gb: float, ctx: Any, lang: str = "ko") -> str:
    """그림을 못 읽고 끝난 판의 답 끝에 붙는 질문 — 모델이 쓰지 않는다."""
    label = _ctx_label(ctx)
    if lang == "en":
        cost = (f" It loads about {saves_gb:.1f} GB more onto the graphics card, so the context ({label} now) may get smaller."
                if saves_gb else "")
        return (f"\n\n---\nPicture reading is off, so I couldn't read the pictures on {pages} page(s).{cost} "
                "Want me to turn picture reading on? (yes / no)")
    cost = (f" 켜면 그래픽카드에 약 {saves_gb:.1f}GB 가 더 올라가서 창(지금 {label})이 줄 수 있습니다."
            if saves_gb else "")
    return (f"\n\n---\n그림 읽기가 꺼져 있어서 페이지 {pages}곳의 그림을 읽지 못했습니다.{cost} "
            "그림 읽기를 켜 드릴까요? (응 / 아니)")


@dataclass
class SelfContext:
    """대화 답에 필요한 지금 값 · 바꾸는 손. 런타임이 채운다 — 이 모듈은 설정 파일을 직접 만지지 않는다."""

    version: Callable[[], str]
    lang: Callable[[], str]
    current_eyes: Callable[[], dict[str, Any]]
    apply_eyes: Callable[[bool], dict[str, Any]]
    summary: Callable[[], dict[str, Any]]
    # 배운 레시피(2026-10-20 확장 설계 P1 · T5). 없으면(시험 · 레시피 엔진이 꺼진 PC) 레시피 제안에 답하지 않는다.
    save_recipe: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    forget_recipe: Callable[[str], dict[str, Any]] | None = None
    decline_recipe: Callable[[str], None] | None = None
    # 사람 시연 「배우기」(T8). start → {"ok", "error"} · stop(label) → {"recipe", "read_out", "secrets_skipped"} 또는 {"refused"}.
    start_demo: Callable[[], dict[str, Any]] | None = None
    stop_demo: Callable[[str], dict[str, Any]] | None = None
    # 배운 걸음을 저장하기 **전에** 그대로 한 번 돌려 본다(2026-10-28). recipe → {"ok", "total", "failed_at", "reason", "rows"}.
    # 없으면(시험 · 크롬이 꺼진 PC) 예전처럼 곧바로 「저장할까요?」를 묻는다.
    replay_demo: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    # 화면에 알릴 사건(「배우는 중」 칸) — 이름 · 내용. 없어도 대화는 그대로 간다.
    notify: Callable[[str, dict[str, Any]], None] | None = None


@dataclass
class _SessionState:
    offer: str = ""
    offered_at: float = 0.0
    # 제안에 딸린 것(레시피 제안이면 저장할 레시피 그대로). 「응」이 **그때 보여 준 것**을 저장하게 — 다시 만들지 않는다.
    payload: dict[str, Any] = field(default_factory=dict)
    # 「배우기」 중이면 사람이 붙인 이름(「배우기 시작: 다나와 최저가」의 뒤쪽). None 이면 기록 중이 아니다.
    demo_label: str | None = None
    # 막 배운 걸음이 저장 · 버림을 기다리는 중 — {"stage": review|verified|failed, "recipe", "label", "at"}. 엉뚱한 다음 말에도 안 사라진다
    #   (방금 가르친 것을 딴소리 한 번에 잃으면 안 된다). 시간(`UNDO_TTL_SEC`)이 지나거나 사람이 고르면 닫힌다.
    demo_pending: dict[str, Any] = field(default_factory=dict)
    last_change: dict[str, Any] = field(default_factory=dict)


class SelfTalk:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, _SessionState] = {}

    def _state(self, session_id: str) -> _SessionState:
        return self._sessions.setdefault(str(session_id or ""), _SessionState())

    # ── 제안 ─────────────────────────────────────────────────────────────
    def offer_eyes(self, session_id: str) -> None:
        with self._lock:
            state = self._state(session_id)
            state.offer, state.offered_at = "eyes_on", self._clock()

    def offer_recipe(self, session_id: str, recipe: dict[str, Any]) -> None:
        """「이 일을 레시피로 저장해 둘까요?」 — 다음 말 한 번 동안만 산다(그림 읽기 제안과 같은 규칙)."""
        with self._lock:
            state = self._state(session_id)
            state.offer, state.offered_at, state.payload = "save_recipe", self._clock(), dict(recipe)

    def offer_demo(self, session_id: str, host: str) -> None:
        """막힌 판 끝의 「보여 주시겠어요?」 — 「응」이면 그때 배우기를 시작한다(그 전엔 아무것도 기록하지 않는다)."""
        with self._lock:
            state = self._state(session_id)
            state.offer, state.offered_at, state.payload = "show_me", self._clock(), {"host": host}

    def demo_session(self) -> str:
        """지금 **배우는 중**인 대화의 번호(없으면 빈 글). 손자리 크롬 띠의 「다 했어」 단추가 그 대화로 말을 보내는 데 쓴다."""
        with self._lock:
            return next((key for key, state in self._sessions.items() if state.demo_label is not None), "")

    def demo_label(self, session_id: str) -> str:
        with self._lock:
            return str(self._sessions.get(str(session_id or ""), _SessionState()).demo_label or "")

    def pending_offer(self, session_id: str) -> str:
        with self._lock:
            state = self._sessions.get(str(session_id or ""))
            if state is None or not state.offer or self._clock() - state.offered_at > OFFER_TTL_SEC:
                return ""
            return state.offer

    # ── 입구 ─────────────────────────────────────────────────────────────
    def intercept(self, prompt: str, session_id: str, ctx: SelfContext) -> dict[str, Any] | None:
        """사람의 말이 손자리 자신에 대한 것이면 답(`{"answer", "kind", ...}`)을, 아니면 None.

        제안은 **다음 말 한 번** 동안만 산다 — 어떤 말이 오든 여기서 지운다(응이면 쓰고, 아니면 버린다).
        """
        lang = (ctx.lang() or "ko") if callable(ctx.lang) else "ko"
        with self._lock:
            state = self._state(session_id)
            offer = state.offer if (state.offer and self._clock() - state.offered_at <= OFFER_TTL_SEC) else ""
            payload = dict(state.payload) if offer else {}
            state.offer, state.offered_at, state.payload = "", 0.0, {}
            last = dict(state.last_change) if state.last_change and self._clock() - float(state.last_change.get("at") or 0) <= UNDO_TTL_SEC else {}
        with self._lock:
            demo_label = self._state(session_id).demo_label
        if demo_label is not None and ctx.stop_demo is not None:
            if _short(prompt, 20) and _DEMO_CANCEL.match(_norm(prompt)):
                return self._stop_demo(session_id, ctx, lang, keep=False)
            if _short(prompt, 20) and _DEMO_STOP.match(_norm(prompt)):
                return self._stop_demo(session_id, ctx, lang, keep=True)
        # ★ 슬래시 문: 모델을 부르지 않고 **결정론으로** 받는다. 문장 맞추기(`_DEMO_START`)는 그대로 두고, 이 문은 따로다.
        if _short(prompt, 80):
            slash = _SLASH_RECIPE.match(" ".join(str(prompt).split()))
            if slash:
                return self._slash_recipe((slash.group("label") or "").strip(), session_id, ctx, lang)
        if ctx.start_demo is not None and _short(prompt, 80):
            started = _DEMO_START.match(_norm(prompt))
            if started:
                return self._start_demo(started.group("label") or "", session_id, ctx, lang)
        if _short(prompt, 24):
            waiting = self._demo_pending_reply(prompt, session_id, ctx, lang)
            if waiting is not None:
                return waiting
        else:
            with self._lock:  # 긴 말이 끼었다 — 기다림은 두되 맨 「응」은 더 받지 않는다
                current = self._state(session_id).demo_pending
                if current:
                    current["armed"] = False
        if offer == "eyes_on" and is_yes(prompt):
            return self._switch_eyes(True, session_id, ctx, lang, asked_by="offer")
        if offer == "show_me" and payload and ctx.start_demo is not None and is_yes(prompt):
            host = str(payload.get("host") or "")
            return self._start_demo(f"{host} 에서 막혔던 일" if host else "", session_id, ctx, lang)
        if offer == "save_recipe" and payload and ctx.save_recipe is not None and is_yes(prompt):
            return self._save_recipe(payload, session_id, ctx, lang)
        if offer == "save_recipe" and payload and is_no(prompt):
            if ctx.decline_recipe is not None and not str(payload.get("name") or "").endswith("_demo"):
                try:
                    ctx.decline_recipe(str(payload.get("name") or ""))
                except Exception:  # noqa: BLE001 — 기억 못 해도 답은 한다
                    pass
            text = ("Okay, I won't save it, and I won't ask again for this site." if lang == "en"
                    else "알겠습니다. 저장하지 않고, 이 사이트는 다시 묻지 않겠습니다.")
            return {"answer": text, "kind": "recipe_declined"}
        if offer and is_no(prompt):
            text = "알겠습니다. 그대로 두겠습니다." if lang != "en" else "Okay, I'll leave it as it is."
            return {"answer": text, "kind": "offer_declined"}
        if last and is_undo(prompt) and last.get("what") == "recipe":
            return self._forget_recipe(str(last.get("name") or ""), session_id, ctx, lang)
        if last and is_undo(prompt):
            return self._switch_eyes(bool(last.get("before")), session_id, ctx, lang, asked_by="undo")
        command = eyes_command(prompt)
        if command is not None:
            return self._switch_eyes(command, session_id, ctx, lang, asked_by="command")
        if asks_whats_new(prompt):
            answer = whats_new.chat_answer(ctx.version(), lang)
            if answer:
                return {"answer": answer, "kind": "whats_new"}
            return None
        if asks_settings(prompt):
            return {"answer": self._settings_answer(ctx, lang), "kind": "settings"}
        return None

    # ── 답 ───────────────────────────────────────────────────────────────
    def _settings_answer(self, ctx: SelfContext, lang: str) -> str:
        info = ctx.summary() or {}
        eyes = info.get("reads_pictures")
        if lang == "en":
            lines = ["Here are my current settings."]
            if info.get("version"):
                lines.append(f"- Version: {info['version']}")
            if info.get("model"):
                lines.append(f"- Chat model: {info['model']}")
            if eyes is not None:
                lines.append(f"- Picture reading: {'on' if eyes else 'off'}" + ("" if eyes or not info.get("can_switch") else " (say \"turn picture reading on\" to switch)"))
            if info.get("num_ctx"):
                lines.append(f"- Context: {_ctx_label(info['num_ctx'])}")
            if info.get("permission"):
                lines.append(f"- Permission mode: {info['permission']}")
            lines.append("Other settings are in Settings. I only change picture reading from the chat.")
            return "\n".join(lines)
        lines = ["지금 설정입니다."]
        if info.get("version"):
            lines.append(f"- 판: {info['version']}")
        if info.get("model"):
            lines.append(f"- 대화 모델: {info['model']}")
        if eyes is not None:
            lines.append(f"- 그림 읽기: {'켜짐' if eyes else '꺼짐'}" + ("" if eyes or not info.get("can_switch") else " (「그림 읽기 켜 줘」라고 하시면 켭니다)"))
        if info.get("num_ctx"):
            lines.append(f"- 창(한 번에 보는 글의 양): {_ctx_label(info['num_ctx'])}")
        if info.get("permission"):
            lines.append(f"- 권한 단계: {info['permission']}")
        lines.append("나머지는 설정 화면에서 보고 바꿀 수 있습니다. 대화로 바꿔 드리는 것은 지금 그림 읽기 하나입니다.")
        return "\n".join(lines)

    def _save_recipe(self, recipe: dict[str, Any], session_id: str, ctx: SelfContext, lang: str) -> dict[str, Any]:
        en = lang == "en"
        try:
            result = ctx.save_recipe(recipe) or {}  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 — 실패도 사람에게 말한다
            result = {"saved": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
        if not result.get("saved"):
            reason = str(result.get("error") or "")
            text = (f"I tried to save it but couldn't ({reason}). Nothing changed." if en
                    else f"저장하려 했지만 되지 않았습니다({reason}). 바뀐 것은 없습니다.")
            return {"answer": text, "kind": "recipe_save_failed", "error": reason}
        name = str(result.get("name") or recipe.get("name") or "")
        with self._lock:
            self._state(session_id).last_change = {"what": "recipe", "name": name, "at": self._clock()}
        hosts = str(recipe.get("_where") or ", ".join(recipe.get("hosts") or []))
        if name.endswith("_demo"):
            verified = (recipe.get("verification") or {}).get("state") == "verified"
            if en:
                text = (f"Saved as {'a verified recipe' if verified else 'unverified'}. Next time you ask for this on {hosts}, "
                        "I'll run these steps as they are and check each one. Say \"undo\" to remove it.")
            else:
                text = (f"{'검증된 레시피로' if verified else '미검증으로'} 저장했습니다. 다음에 {hosts} 에서 이 일을 시키시면 이 걸음을 그대로 "
                        f"돌리고 걸음마다 확인합니다{'' if verified else '(아직 한 번도 돌려 확인하지 않았습니다)'}. 지우려면 「되돌려」라고 하세요.")
        elif en:
            text = (f"Saved. Next time I search on {hosts}, I'll open this address directly and show the check under the answer. "
                    "Say \"undo\" to remove it.")
        else:
            text = (f"저장했습니다. 다음에 {hosts} 에서 찾을 때는 이 주소로 바로 열고, 답 아래에 확인 결과를 한 줄로 남깁니다. "
                    "지우려면 「되돌려」라고 하세요.")
        return {"answer": text, "kind": "recipe_saved", "name": name, "path": str(result.get("path") or "")}

    # ── 사람 시연 「배우기」 ────────────────────────────────────────────────────────
    @staticmethod
    def _buttons(*pairs: tuple[str, str]) -> list[dict[str, str]]:
        """답 아래 단추 — 누르면 `say` 를 사람이 친 말처럼 같은 문으로 보낸다(화면은 말을 해석하지 않는다)."""
        return [{"label": label, "say": say} for label, say in pairs]

    @staticmethod
    def _notify(ctx: SelfContext, event: str, payload: dict[str, Any]) -> None:
        if ctx.notify is None:
            return
        try:
            ctx.notify(event, payload)
        except Exception:  # noqa: BLE001 — 화면 알림이 틀어져도 대화는 간다
            pass

    def _slash_recipe(self, label: str, session_id: str, ctx: SelfContext, lang: str) -> dict[str, Any]:
        if ctx.start_demo is None:
            text = ("I can't learn right now — the Sonjari browser isn't available on this PC." if lang == "en"
                    else "지금은 배우기를 쓸 수 없습니다. 이 PC 에서 손자리 크롬을 쓸 수 없는 상태입니다.")
            return {"answer": text, "kind": "demo_unavailable"}
        return self._start_demo(label, session_id, ctx, lang)

    def _start_demo(self, label: str, session_id: str, ctx: SelfContext, lang: str) -> dict[str, Any]:
        en = lang == "en"
        with self._lock:
            busy = next((key for key, state in self._sessions.items() if state.demo_label is not None), None)
        if busy is not None:
            # 기록기는 하나다 — 또 시작하면 지금까지 적은 걸음이 지워진다. 시작하지 않고 지금 상태를 말한다.
            same = busy == str(session_id or "")
            if en:
                text = ("I'm already learning — when you're done say \"done\", or \"cancel\" to throw it away." if same
                        else "I'm already learning in another conversation. Finish or cancel it there first.")
            else:
                text = ("이미 배우는 중입니다. 다 하셨으면 「다 했어」, 그만두시려면 「배우기 취소」라고 해 주세요." if same
                        else "다른 대화에서 이미 배우는 중입니다. 거기서 마치거나 취소한 뒤에 시작해 주세요.")
            buttons = self._buttons(("Done", "done") if en else ("다 했어", "다 했어"),
                                    ("Cancel", "cancel learning") if en else ("취소", "배우기 취소")) if same else []
            return {"answer": text, "kind": "demo_already", "buttons": buttons}
        with self._lock:
            self._state(session_id).demo_pending = {}
        try:
            result = ctx.start_demo() or {}  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
        if not result.get("ok"):
            reason = str(result.get("error") or "")
            text = (f"I couldn't start learning ({reason}). Open the Sonjari browser and try again." if en
                    else f"배우기를 시작하지 못했습니다({reason}). 손자리 크롬을 연 뒤 다시 말씀해 주세요.")
            return {"answer": text, "kind": "demo_start_failed", "error": reason}
        clean = " ".join(label.split())[:60]
        with self._lock:
            self._state(session_id).demo_label = clean
        self._notify(ctx, "demo_started", {"label": clean, "url": str(result.get("url") or "")})
        if en:
            text = ("Okay — do it once in the **Sonjari browser** I just brought to the front (the window with the red \"learning\" bar). "
                    "Your everyday Chrome isn't watched. The step count on the bar goes up as you click and type, and the steps pile up "
                    "in the \"Learning\" box next to this chat. When you're done, press **Done** on the bar or say \"done\" here. "
                    "I don't record passwords or file fields.")
        else:
            text = ("좋습니다. 방금 앞으로 띄운 **손자리 크롬**(위에 빨간 「배우는 중」 띠가 있는 창)에서 한 번 해 보여 주세요. "
                    "평소 쓰시는 크롬은 보지 않습니다. 누르거나 칠 때마다 띠의 걸음 수가 올라가고, 이 대화창 옆 「배우는 중」 칸에도 한 걸음씩 쌓입니다. "
                    "다 하시면 띠의 **[다 했어]** 를 누르거나 여기에 「다 했어」라고 해 주세요. 비밀번호 · 파일 칸은 적지 않습니다.")
        return {"answer": text, "kind": "demo_started",
                "buttons": self._buttons(("Done", "done") if en else ("다 했어", "다 했어"),
                                         ("Cancel", "cancel learning") if en else ("취소", "배우기 취소"))}

    def _stop_demo(self, session_id: str, ctx: SelfContext, lang: str, *, keep: bool) -> dict[str, Any]:
        en = lang == "en"
        with self._lock:
            state = self._state(session_id)
            label, state.demo_label = state.demo_label or "", None
        try:
            result = ctx.stop_demo(label) or {}  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            result = {"refused": f"{type(exc).__name__}: {exc}"[:160]}
        if not keep:
            self._notify(ctx, "demo_ended", {"outcome": "cancelled"})
            text = "Stopped learning and threw it away." if en else "배우기를 멈추고 적은 것을 버렸습니다."
            return {"answer": text, "kind": "demo_cancelled"}
        if result.get("refused") or not result.get("recipe"):
            self._notify(ctx, "demo_ended", {"outcome": "refused"})
            reason = str(result.get("refused") or "기록된 걸음이 없습니다")
            with self._lock:  # 「다시 보여 주기」 단추가 같은 이름으로 다시 시작할 수 있게 이름만 들고 있는다
                self._state(session_id).demo_pending = {"stage": "refused", "label": label, "at": self._clock(), "armed": True}
            text = (f"I couldn't turn that into a recipe: {reason}. Type /recipe to try again." if en
                    else f"보여 주신 것을 레시피로 옮기지 못했습니다 — {reason}. 다시 하시려면 `/레시피` 라고 해 주세요.")
            return {"answer": text, "kind": "demo_refused", "reason": reason,
                    "buttons": self._buttons(("Show again", "show again") if en else ("다시 보여 주기", "다시 보여 줄게"))}
        recipe = dict(result["recipe"])
        self._notify(ctx, "demo_ended", {"outcome": "stopped"})
        skipped = int(result.get("secrets_skipped") or 0)
        note = ""
        if skipped:
            note = (f"\n(I skipped {skipped} password/file field(s) — you'll fill those yourself.)" if en
                    else f"\n(비밀번호 · 파일 칸 {skipped}곳은 적지 않았습니다 — 그 칸은 직접 채우셔야 합니다.)")
        if ctx.replay_demo is None:
            # 되돌려 볼 손이 없는 문맥 — 예전처럼 곧바로 저장을 묻는다.
            with self._lock:
                state = self._state(session_id)
                state.offer, state.offered_at, state.payload = "save_recipe", self._clock(), recipe
            if en:
                text = (str(result.get("read_out") or "") + note
                        + "\n\nSave it? Next time I'll run these steps as they are and check each one. (yes / no)")
            else:
                text = (str(result.get("read_out") or "") + note
                        + "\n\n저장할까요? 다음에 이 일을 시키시면 이 걸음을 그대로 돌리고 걸음마다 확인합니다. (응 / 아니)")
            return {"answer": text, "kind": "demo_ready", "name": recipe.get("name")}
        with self._lock:
            self._state(session_id).demo_pending = {"stage": "review", "recipe": recipe, "label": label, "at": self._clock(), "armed": True}
        if en:
            text = ("This is what I learned.\n" + str(result.get("read_out") or "") + note
                    + "\n\nWant me to try it once before saving? The Sonjari browser will click and type these steps as they are "
                      "and check each one — I only call it \"verified\" if every check passes.")
        else:
            text = ("이렇게 배웠습니다.\n" + str(result.get("read_out") or "") + note
                    + "\n\n저장하기 전에 한 번 그대로 해 볼까요? 손자리 크롬이 위 걸음을 그대로 누르고 입력하면서 걸음마다 확인합니다. "
                      "확인이 모두 맞아야 「검증된 레시피」라고 부릅니다.")
        return {"answer": text, "kind": "demo_ready", "name": recipe.get("name"), "stage": "review",
                "buttons": self._buttons(("Try it once", "try it once") if en else ("한 번 해 볼게요", "한 번 해 볼게요"),
                                         ("Save without checking", "save anyway") if en else ("검증 없이 저장", "검증 없이 저장"),
                                         ("Discard", "discard") if en else ("버리기", "버려"))}

    def _demo_pending_reply(self, prompt: str, session_id: str, ctx: SelfContext, lang: str) -> dict[str, Any] | None:
        """방금 배운 걸음이 기다리는 동안의 말 — 해 보기 · 저장 · 버리기 · 다시 보여 주기. 다른 말이면 None(기다림은 그대로)."""
        with self._lock:
            pending = dict(self._state(session_id).demo_pending)
        if not pending or self._clock() - float(pending.get("at") or 0) > UNDO_TTL_SEC:
            return None
        stage, value = str(pending.get("stage") or ""), _norm(prompt)
        # ★ 맨 「응」 · 「아니」는 **바로 앞 말이 이 질문이었을 때만** 받는다(`armed`). 엉뚱한 대화 끝의 「응」이 손자리 크롬을 눌러 돌려 보는 일이
        #   없게 — 해 보기 · 저장 · 버리기를 또렷이 말하는 것(「한 번 해 볼게요」 · 「저장」 · 「버려」)은 언제든 받는다.
        armed = bool(pending.get("armed"))
        replay = bool(_REPLAY_WORDS.match(value))
        save = bool(_SAVE_WORDS.match(value))
        discard = bool(_DISCARD_WORDS.match(value)) or (armed and is_no(prompt))
        reteach = bool(_RETEACH_WORDS.match(value))
        yes = armed and is_yes(prompt)
        if reteach:
            with self._lock:
                self._state(session_id).demo_pending = {}
            return self._start_demo(str(pending.get("label") or ""), session_id, ctx, lang)
        if discard:
            with self._lock:
                self._state(session_id).demo_pending = {}
            text = "Okay, I threw it away." if lang == "en" else "알겠습니다. 배운 것을 버렸습니다."
            return {"answer": text, "kind": "demo_discarded"}
        if stage == "review":
            if replay or yes:
                return self._replay_demo(pending, session_id, ctx, lang)
            if save:
                return self._save_pending(pending, session_id, ctx, lang)
        if stage == "verified" and (yes or save):
            return self._save_pending(pending, session_id, ctx, lang)
        if stage == "failed":
            if save and not yes:
                return self._save_pending(pending, session_id, ctx, lang)
            if yes:
                if lang == "en":
                    text = "It didn't pass the check, so I won't take a plain \"yes\" — pick one: show again, save anyway, or discard."
                else:
                    text = "확인이 맞지 않아서 그냥 「응」으로는 받지 않습니다. 다시 보여 주기 · 그래도 저장 · 버리기 가운데 골라 주세요."
                return {"answer": text, "kind": "demo_choice", "buttons": self._failed_buttons(lang)}
        with self._lock:  # 다른 말이 끼었다 — 기다림은 두되 맨 「응」은 더 받지 않는다
            current = self._state(session_id).demo_pending
            if current:
                current["armed"] = False
        return None

    def _failed_buttons(self, lang: str) -> list[dict[str, str]]:
        return self._buttons(*(
            [("Show again", "show again"), ("Save anyway", "save anyway"), ("Discard", "discard")] if lang == "en"
            else [("다시 보여 주기", "다시 보여 줄게"), ("그래도 저장", "그래도 저장"), ("버리기", "버려")]))

    def _replay_demo(self, pending: dict[str, Any], session_id: str, ctx: SelfContext, lang: str) -> dict[str, Any]:
        en = lang == "en"
        recipe = dict(pending.get("recipe") or {})
        try:
            result = ctx.replay_demo(recipe) or {}  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 — 못 돌린 것도 「틀림」으로 말한다
            result = {"ok": False, "total": 0, "failed_at": 1, "reason": f"{type(exc).__name__}: {exc}"[:160], "rows": []}
        checked = int(result.get("total") or 0)
        if result.get("ok"):
            recipe["verification"] = {"state": "verified", "checked_at": self._clock(), "steps": checked}
            with self._lock:
                self._state(session_id).demo_pending = {**pending, "stage": "verified", "recipe": recipe, "at": self._clock(), "armed": True}
            if en:
                text = f"Verified — I ran all {checked} steps as they are and every check passed.\n\nSave it as a verified recipe?"
            else:
                text = f"검증됐습니다 — 걸음 {checked}개를 그대로 돌렸고 확인이 모두 맞았습니다.\n\n검증된 레시피로 저장할까요?"
            return {"answer": text, "kind": "demo_verified", "stage": "verified",
                    "buttons": self._buttons(*([("Save", "save"), ("Discard", "discard")] if en else [("저장", "저장"), ("버리기", "버려")]))}
        failed_at = int(result.get("failed_at") or 1)
        reason = str(result.get("reason") or ("a check did not pass" if en else "확인이 맞지 않았습니다"))
        recipe["verification"] = {"state": "unverified", "checked_at": self._clock(), "steps": checked,
                                  "failed_at": failed_at, "reason": reason[:160]}
        with self._lock:
            self._state(session_id).demo_pending = {**pending, "stage": "failed", "recipe": recipe, "at": self._clock(), "armed": True}
        if en:
            text = (f"It went wrong at step {failed_at}: {reason}\n(Steps 1-{max(failed_at - 1, 0)} were fine.)\n\n"
                    "Show me again, save it anyway (it stays marked unverified), or discard it?")
        else:
            text = (f"{failed_at}번째 걸음에서 틀렸습니다 — {reason}\n(앞 {max(failed_at - 1, 0)}걸음은 맞았습니다.)\n\n"
                    "다시 보여 주시겠어요, 그래도 저장할까요(「미검증」으로 남습니다), 아니면 버릴까요?")
        return {"answer": text, "kind": "demo_failed", "stage": "failed", "failed_at": failed_at,
                "buttons": self._failed_buttons(lang)}

    def _save_pending(self, pending: dict[str, Any], session_id: str, ctx: SelfContext, lang: str) -> dict[str, Any]:
        recipe = dict(pending.get("recipe") or {})
        recipe.setdefault("verification", {"state": "unverified", "checked_at": 0, "steps": 0, "reason": "not_tried"})
        recipe.setdefault("usage", {"runs": 0, "succeeded": 0})
        with self._lock:
            self._state(session_id).demo_pending = {}
        if ctx.save_recipe is None:
            text = "I can't save recipes on this PC right now." if lang == "en" else "지금은 이 PC 에 레시피를 저장할 수 없습니다."
            return {"answer": text, "kind": "recipe_save_failed", "error": "no_store"}
        return self._save_recipe(recipe, session_id, ctx, lang)

    def _forget_recipe(self, name: str, session_id: str, ctx: SelfContext, lang: str) -> dict[str, Any]:
        en = lang == "en"
        if ctx.forget_recipe is None or not name:
            text = "There's nothing to undo." if en else "되돌릴 것이 없습니다."
            return {"answer": text, "kind": "recipe_undo_none"}
        try:
            result = ctx.forget_recipe(name) or {}
        except Exception as exc:  # noqa: BLE001
            result = {"removed": False, "error": f"{type(exc).__name__}"}
        with self._lock:
            self._state(session_id).last_change = {}
        if result.get("removed"):
            text = "Removed the recipe. Next time I'll search the usual way." if en else "레시피를 지웠습니다. 다음부터는 원래대로 찾습니다."
            return {"answer": text, "kind": "recipe_forgotten", "name": name}
        text = "The recipe was already gone." if en else "레시피가 이미 없었습니다."
        return {"answer": text, "kind": "recipe_undo_none", "name": name}

    def _switch_eyes(self, on: bool, session_id: str, ctx: SelfContext, lang: str, *, asked_by: str) -> dict[str, Any]:
        en = lang == "en"
        try:
            now = ctx.current_eyes() or {}
        except Exception:  # noqa: BLE001 — 못 읽으면 바꾸지 않는다
            now = {}
        if not now:
            text = ("I couldn't read the current model, so I didn't change anything. You can switch it in Settings > Model."
                    if en else "지금 모델을 읽지 못해 바꾸지 않았습니다. 설정 › 모델에서 바꿀 수 있습니다.")
            return {"answer": text, "kind": "eyes_unknown"}
        if bool(now.get("reads_pictures")) == on:
            text = (f"Picture reading is already {'on' if on else 'off'}." if en
                    else f"그림 읽기는 이미 {'켜져' if on else '꺼져'} 있습니다.")
            return {"answer": text, "kind": "eyes_already"}
        if not now.get("can_switch"):
            text = ("This model can't switch picture reading on and off. To read pictures, pick a model that reads pictures in Settings > Model."
                    if en else "지금 모델은 그림 읽기를 따로 켜고 끌 수 없습니다. 그림을 읽으려면 설정 › 모델에서 그림을 읽는 모델을 골라 주세요.")
            return {"answer": text, "kind": "eyes_not_switchable"}
        try:
            result = ctx.apply_eyes(on) or {}
        except Exception as exc:  # noqa: BLE001 — 실패도 사람에게 말한다
            result = {"ok": False, "error": f"{type(exc).__name__}"}
        if not result.get("ok"):
            reason = str(result.get("error") or "")
            text = (f"I tried but couldn't switch it ({reason}). The previous setting is kept." if en
                    else f"바꿔 보았지만 되지 않았습니다({reason}). 원래 설정 그대로입니다.")
            return {"answer": text, "kind": "eyes_failed", "error": reason}
        new_ctx = (result.get("selection") or {}).get("num_ctx")
        with self._lock:
            self._state(session_id).last_change = {"what": "eyes", "before": not on, "at": self._clock()}
        if en:
            text = (f"Picture reading is now {'on' if on else 'off'}"
                    + (f" (context {_ctx_label(new_ctx)})" if new_ctx else "") + ". "
                    + ("Ask me the same thing again and I'll read the pictures this time. " if on and asked_by == "offer" else "")
                    + "Say \"undo\" to switch back.")
        else:
            text = (f"그림 읽기를 {'켰습니다' if on else '껐습니다'}"
                    + (f"(창 {_ctx_label(new_ctx)})" if new_ctx else "") + ". "
                    + ("아까 일을 다시 맡겨 주시면 이번엔 그림까지 읽습니다. " if on and asked_by == "offer" else "")
                    + "되돌리려면 「되돌려」라고 하세요.")
        return {"answer": text, "kind": "eyes_switched", "on": on, "num_ctx": new_ctx, "asked_by": asked_by}


def unread_picture_pages(steps: list[dict[str, Any]]) -> int:
    """이 판에서 **그림 본문이 있는데 읽지 못한** 페이지 수 — 브라우저 결과의 칸(`image_body` · `images_read`)으로만 센다."""
    seen: set[str] = set()
    for step in steps or []:
        if not step.get("ok"):
            continue
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        if evidence.get("image_body") and not evidence.get("images_read"):
            seen.add(str(evidence.get("url") or step.get("step") or len(seen)))
    return len(seen)


def recipe_offer_text(read_out_text: str, lang: str = "ko") -> str:
    """잘 끝난 판의 답 끝에 붙는 레시피 제안 — 읽어 주기(무엇을 하고 무엇을 확인하나)를 그대로 보인다. 모델이 쓰지 않는다."""
    if lang == "en":
        return ("\n\n---\nWant me to save this as a recipe? Next time I'll open the search directly and check each step.\n"
                + read_out_text + "\n(yes / no)")
    return ("\n\n---\n이 일을 레시피로 저장해 둘까요? 다음엔 검색 화면을 바로 열고, 걸음마다 확인합니다.\n"
            + read_out_text + "\n(응 / 아니)")
