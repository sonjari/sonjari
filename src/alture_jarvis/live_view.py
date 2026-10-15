"""브라우저 무대 — 화면 밖 크롬을 온텔릭 창 **안에서** 보고 만진다 (2026-09-24 부산).

## 왜

크롬 창을 사람 화면에 띄우는 길은 다 번쩍임·앞창 뺏기로 끝났다(09-18 ~ 09-24 여섯 판). 다른 에이전트도 못 풀었다 —
크롬 DevTools MCP 는 「읽기만 해도 포커스를 뺏는다」 이슈를 「계획 없음」으로 닫았고, Claude in Chrome 도 같은 이슈가 열려 있다.
그래서 **창을 띄우지 않는다.** 크롬은 늘 화면 밖에 두고, 사람은 온텔릭 안의 살아 있는 화면으로 보고, 그 화면을 누르면 그대로 넘겨받는다.

## 어떻게

- 브라우저 일꾼(Playwright 전용 스레드)과 **따로** 크롬 탭에 CDP 웹소켓으로 붙는다. 그래서 일꾼이 바빠도 화면이 안 멈춘다
  (예전 1.5초 스크린샷은 일꾼 줄에 서서 `browser_busy` 로 자주 밀렸다).
- `Page.startScreencast` — 크롬이 그릴 때마다 JPEG 한 장을 민다. 보는 사람이 있을 때만 켠다(6초 동안 아무도 안 당기면 끈다).
- 사람의 마우스·키·글자는 `Input.dispatch*`·`Input.insertText` 로 그 탭에 그대로 넣는다(한글은 조합이 끝난 글자를 넣는다).
- 넘겨받는 동안 온텔릭은 **브라우저 도구를 멈춘다**(`BrowserWorker.execute` 가 기다린다). 2분 손을 안 대면 저절로 돌려준다.
- 넘겨받는 동안의 화면은 온텔릭 창으로만 간다 — 모델·기록으로 안 넘어간다(ChatGPT 에이전트의 「넘겨받는 동안 캡처 안 함」과 같은 약속).

## 3차 (2026-09-26) — 평소 쓰던 브라우저처럼

- 주소·제목·로딩·뒤로/앞으로 상태(`nav_state`)와 이동(`navigate`) — 주소창·버튼이 이걸 쓴다.
- 탭 목록·전환·새 탭. 온텔릭이 일하는 탭을 표시한다.
- 크롬이 페이지 **밖**에 띄우는 것 셋을 가로채 무대에서 대신 그린다 — 스크린캐스트에 안 찍히고 화면 밖 창에 떠서 보이지도 않는다:
  고르기 상자(누르는 순간 목록을 읽어 돌려준다) · 확인/취소 알림창(`Page.javascriptDialogOpening`) · 파일 고르기(`Page.fileChooserOpened`).
- 규칙은 하나다: 사람이 무대 안의 **무엇이든** 누르면(화면·주소창·버튼·탭) 그 순간 넘겨받기.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

LOG = logging.getLogger(__name__)

#: 이 시간 동안 아무도 화면을 안 당기면 스트림을 끈다 — 안 보는 화면을 그리지 않는다.
WATCH_IDLE_SEC = 6.0
#: 넘겨받은 사람이 이만큼 손을 안 대면 온텔릭에게 돌려준다.
CONTROL_IDLE_SEC = 120.0
#: 스트림을 켰는데 이만큼 한 장도 안 오면 **뒤쪽 탭**이다(숨은 탭은 그리지 않는다) — 화면은 예전 스크린샷 길로 돌아간다.
NO_FRAME_SEC = 2.5
#: 무대에 맞출 때 크롬 폭의 하한. 좁히면 사이트가 태블릿·모바일 배치로 바뀌어 레시피·셀렉터가 어긋난다 —
#: 선명함보다 온텔릭이 **같은 페이지를 보는 것**이 먼저다. 비율만 무대에 맞춘다.
FIT_MIN_WIDTH = 1280

_MODIFIER_BITS = {"alt": 1, "ctrl": 2, "meta": 4, "shift": 8}
#: 글자가 아닌 키 — `rawKeyDown` 으로 보낸다. Enter 는 폼 제출이 되도록 글자 "\r" 을 싣는다(퍼피티어와 같은 규칙).
_KEY_TEXT = {"Enter": "\r"}
#: 편집 단축키는 명령으로 보낸다 — 키만 보내면 크롬이 편집 명령으로 안 바꾼다.
_SHORTCUT_COMMANDS = {"a": "selectAll", "c": "copy", "x": "cut", "z": "undo", "y": "redo"}


class LiveView:
    """온텔릭 크롬 한 탭의 살아 있는 화면과 조작 창구."""

    def __init__(self, worker: Any) -> None:
        self.worker = worker
        self._cond = threading.Condition()
        self._frame: dict[str, Any] | None = None
        self._seq = 0
        self._watch_until = 0.0
        self._thread: threading.Thread | None = None
        self._ws: Any = None
        self._target_id = ""
        self._stream_started_at = 0.0
        self._last_frame_at = 0.0
        self._msg_id = 0
        self._id_lock = threading.Lock()
        #: 입력은 한 번에 하나씩 — API 가 요청마다 다른 스레드에서 부르므로, 잠그지 않으면 떼기가 누르기보다 먼저 들어갈 수 있다.
        self._input_lock = threading.Lock()
        self._replies: dict[int, dict[str, Any]] = {}
        self._reply_cond = threading.Condition()
        self._control_active = False
        self._control_since = 0.0
        self._control_last_input = 0.0
        self._control_reason = ""
        self._fit_wanted: tuple[int, int] | None = None
        self._fit_done: tuple[int, int] | None = None
        self._status = "idle"
        # 3차: 브라우저 틀이 보여 줄 상태
        self._nav: dict[str, Any] = {"url": "", "title": "", "loading": False, "can_back": False, "can_forward": False}
        self._history: dict[str, Any] = {"index": -1, "entries": []}
        self._history_dirty = True
        self._main_frame = ""
        self._tabs: list[dict[str, Any]] = []
        #: 사람이 고른 탭. 비면 온텔릭이 일하는 탭을 본다. 돌려주면 비운다.
        self._view_override = ""
        #: 사람이 넘겨받은 동안 뜬 알림창·파일 고르기 — 무대가 대신 그린다.
        self._dialog: dict[str, Any] | None = None
        self._file_chooser: dict[str, Any] | None = None

    # ── 보는 쪽 ─────────────────────────────────────────────────────────────
    def frame(self, after: int = 0, wait: float = 1.0) -> dict[str, Any] | None:
        """`after` 보다 새 장을 **기다렸다가** 준다(롱 폴). 없으면 None — 그때 화면은 그대로 둔다."""
        self._watch()
        deadline = time.time() + max(0.0, min(float(wait), 5.0))
        with self._cond:
            while True:
                current = self._frame
                # ★ 받는 쪽이 **우리보다 앞선 번호**를 들고 오면 우리가 다시 떴다는 뜻이다(2026-09-29 실사용). 번호는 프로세스마다
                #   0 부터 세는데, 창은 재시작 전 번호(수만)를 그대로 들고 「이것보다 새 것」을 달라고 했다 — 우리는 새 장이 없다고만
                #   답했고, 큰 화면은 재시작 직전 마지막 장(12일 전 YTN 기사)을 붙든 채 30분 넘게 멈춰 보였다(작은 창은 스크린샷 길이라 멀쩡).
                #   받는 쪽이 앞설 수는 없다 — 그때는 지금 장을 바로 준다.
                if current is not None and (int(current["seq"]) > int(after) or int(after) > self._seq):
                    return dict(current)
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)

    def status(self) -> dict[str, Any]:
        frame = self._frame or {}
        return {
            "status": self._status,
            "streaming": self._ws is not None,
            "seq": int(frame.get("seq") or 0),
            "width": int(frame.get("width") or 0),
            "height": int(frame.get("height") or 0),
            "control": self.control_state(),
            "fit": list(self._fit_done or ()),
        }

    def nav_state(self) -> dict[str, Any]:
        """브라우저 틀이 그릴 것: 주소·제목·로딩·뒤로/앞으로·탭·(넘겨받은 동안) 알림창·파일 고르기."""
        self._watch()
        controlling = self.human_in_control()
        return {
            **self._nav,
            "tabs": list(self._tabs),
            "viewing": self._target_id,
            "dialog": dict(self._dialog) if (self._dialog and controlling) else None,
            "file_chooser": dict(self._file_chooser) if (self._file_chooser and controlling) else None,
            "control": controlling,
        }

    def _watch(self) -> None:
        self._watch_until = time.time() + WATCH_IDLE_SEC
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="ontelic-live-view")
            self._thread.start()

    # ── 넘겨받기 ─────────────────────────────────────────────────────────────
    def human_in_control(self) -> bool:
        if self._control_active and time.time() - self._control_last_input > CONTROL_IDLE_SEC:
            self.release_control("idle")
        return self._control_active

    def control_state(self) -> dict[str, Any]:
        active = self.human_in_control()
        return {
            "active": active,
            "since": self._control_since if active else 0.0,
            "idle_release_in": max(0.0, CONTROL_IDLE_SEC - (time.time() - self._control_last_input)) if active else 0.0,
            "last_release": self._control_reason,
        }

    def take_control(self) -> dict[str, Any]:
        """사람이 화면을 눌렀다 — 지금부터 온텔릭의 브라우저 도구는 기다린다."""
        now = time.time()
        if not self._control_active:
            self._control_active = True
            self._control_since = now
            self._control_reason = ""
            # 페이지가 「창이 앞에 있다」고 믿게 한다 — 화면 밖 창이라 포커스가 없으면 입력칸 커서·자동완성이 안 뜬다.
            self._send("Emulation.setFocusEmulationEnabled", {"enabled": True}, wait=False)
        self._control_last_input = now
        self._watch()
        return {"ok": True, **self.control_state()}

    def release_control(self, reason: str = "button") -> dict[str, Any]:
        if self._control_active:
            self._control_active = False
            self._control_reason = reason
            self._send("Emulation.setFocusEmulationEnabled", {"enabled": False}, wait=False)
            # 사람이 답하지 않은 알림창을 남기면 페이지가 멈추고 온텔릭의 다음 걸음이 매달린다 — 취소로 닫는다.
            if self._dialog is not None:
                self._send("Page.handleJavaScriptDialog", {"accept": False}, wait=False)
                self._dialog = None
            self._file_chooser = None
            if self._view_override:
                # 사람이 다른 탭을 봤다 — 크롬 안에서도 온텔릭의 탭을 앞으로 되돌린다. 안 그러면 그 탭은 뒤에 남아 창 크기를 못 따라가고
                # (앞 탭만 크기가 바뀐다), 무대 좌표가 어긋났다(2026-09-26 E2E: 창 1000 인데 그 탭은 752 그대로).
                agent = next((item for item in self._tabs if item.get("agent")), None)
                if agent is not None:
                    self._send("Target.activateTarget", {"targetId": str(agent["id"])}, wait=False)
            self._view_override = ""  # 사람이 보던 탭이 아니라 온텔릭이 일하는 탭으로 돌아간다
            held = round(time.time() - self._control_since, 1)
            note = getattr(self.worker, "_human_took_over", None)
            if isinstance(note, dict):
                note["released_at"] = time.time()
            elif held >= 1.0:
                # ★ 온텔릭이 **생각하는 사이에** 넘겨받았다 돌려주면 도구는 기다린 적이 없어 알림이 안 붙는다 — 그러면 바뀐 화면을
                #   모른 채 옛 번호를 누른다. 돌려주는 쪽에서 적어 두고, 다음 도구 결과가 싣는다(`_with_takeover_note`).
                try:
                    self.worker._human_took_over = {"waited_sec": held, "released_at": time.time()}
                except Exception:  # noqa: BLE001
                    pass
        return {"ok": True, **self.control_state()}

    def input(self, event: dict[str, Any]) -> dict[str, Any]:
        """사람의 입력 한 개를 크롬 탭에 넣는다. 넘겨받기를 안 했으면 이 입력이 곧 넘겨받기다."""
        with self._input_lock:
            return self._input(event)

    def _input(self, event: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(event, dict):
            return {"ok": False, "error": "bad_event"}
        if not self._control_active:
            self.take_control()
        self._control_last_input = time.time()
        # 연결이 잠깐 끊겨 다시 붙는 중이면 기다린다 — 예전엔 끊긴 사이의 입력이 「성공」으로 돌아가고 조용히 사라졌다.
        if self._ws is None:
            self._watch()
            deadline = time.time() + 2.0
            while self._ws is None and time.time() < deadline:
                time.sleep(0.05)
            if self._ws is None:
                return {"ok": False, "error": "not_connected"}
        frame = self._frame or {}
        width = float(frame.get("css_width") or frame.get("width") or 0)
        height = float(frame.get("css_height") or frame.get("height") or 0)
        # ★ 화면이 **자기가 보고 있던 그림**의 크기를 같이 보내면 그걸로 잰다. 창 크기가 바뀌는 사이에는 화면의 그림(옛 크기)과
        #   마지막 장(새 크기)이 달라서, 0..1 좌표를 새 크기로 곱하면 누른 자리가 어긋났다(E2E 에서 고르기 상자를 헛눌렀다).
        try:
            seen_w, seen_h = float(event.get("fw") or 0), float(event.get("fh") or 0)
        except (TypeError, ValueError):
            seen_w = seen_h = 0.0
        if seen_w > 0 and seen_h > 0:
            width, height = seen_w, seen_h
        kind = str(event.get("kind") or "")
        modifiers = _modifiers(event)
        try:
            if kind in {"mouse", "wheel"}:
                if width <= 0 or height <= 0:
                    return {"ok": False, "error": "no_frame_yet"}
                x = max(0.0, min(1.0, float(event.get("x") or 0))) * width
                y = max(0.0, min(1.0, float(event.get("y") or 0))) * height
                if kind == "wheel":
                    params = {"type": "mouseWheel", "x": x, "y": y, "modifiers": modifiers,
                              "deltaX": float(event.get("dx") or 0), "deltaY": float(event.get("dy") or 0)}
                else:
                    if str(event.get("type")) == "down" and str(event.get("button") or "left") == "left" and not modifiers:
                        picked = self._select_at(x, y)
                        if picked is not None:
                            # 고르기 상자는 크롬이 페이지 밖 창으로 목록을 띄운다(스트림에 안 찍힘) — 누르지 않고 목록을 돌려준다.
                            return {"ok": True, "select": picked}
                    kind_map = {"down": "mousePressed", "up": "mouseReleased", "move": "mouseMoved"}
                    params = {"type": kind_map.get(str(event.get("type")), "mouseMoved"), "x": x, "y": y,
                              "modifiers": modifiers, "button": str(event.get("button") or "none"),
                              "clickCount": int(event.get("clickCount") or 0)}
                    if params["type"] == "mouseMoved" and params["button"] == "none":
                        params.pop("clickCount")
                self._send("Input.dispatchMouseEvent", params, wait=False)
                return {"ok": True}
            if kind == "text":
                text = str(event.get("text") or "")[:2000]
                if text:
                    self._send("Input.insertText", {"text": text}, wait=False)
                return {"ok": True}
            if kind == "key":
                self._send("Input.dispatchKeyEvent", _key_params(event, modifiers), wait=False)
                return {"ok": True}
            if kind == "select":
                return self._select_pick(int(event.get("index") or 0))
        except Exception as exc:  # noqa: BLE001 — 입력 하나가 서버를 죽이면 안 된다
            return {"ok": False, "error": str(exc)[:200]}
        return {"ok": False, "error": f"unknown_kind:{kind}"}

    # ── 브라우저 틀: 이동·탭 ─────────────────────────────────────────────────
    def navigate(self, action: str, url: str = "") -> dict[str, Any]:
        """뒤로·앞으로·새로고침·멈춤·주소 이동. 누르는 것이 곧 넘겨받기다."""
        self.take_control()
        action = str(action or "")
        if action in {"back", "forward"}:
            history = self._refresh_history() or self._history
            index = int(history.get("index", -1)) + (-1 if action == "back" else 1)
            entries = list(history.get("entries") or [])
            if not 0 <= index < len(entries):
                return {"ok": False, "error": f"no_{action}"}
            self._send("Page.navigateToHistoryEntry", {"entryId": entries[index]["id"]}, wait=False)
        elif action == "reload":
            self._send("Page.reload", {}, wait=False)
        elif action == "stop":
            self._send("Page.stopLoading", {}, wait=False)
        elif action == "go":
            target = normalize_address(url)
            if not target:
                return {"ok": False, "error": "empty_address"}
            self._send("Page.navigate", {"url": target}, wait=False)
            self._nav["url"] = target
        else:
            return {"ok": False, "error": f"unknown_action:{action}"}
        self._nav["loading"] = action in {"go", "reload", "back", "forward"}
        self._history_dirty = True
        return {"ok": True}

    def switch_tab(self, target_id: str) -> dict[str, Any]:
        """사람이 다른 탭을 눌렀다 — 그 탭을 크롬 안에서 앞으로 두고(숨은 탭은 안 그린다) 무대가 그 탭을 본다."""
        self.take_control()
        known = {str(item.get("id")) for item in self._tabs}
        if str(target_id) not in known:
            return {"ok": False, "error": "unknown_tab"}
        self._send("Target.activateTarget", {"targetId": str(target_id)}, wait=False)
        self._view_override = str(target_id)
        return {"ok": True}

    def new_tab(self, url: str = "") -> dict[str, Any]:
        self.take_control()
        created = self._send("Target.createTarget", {"url": normalize_address(url) or "about:blank"})
        target = str((created or {}).get("targetId") or "")
        if not target:
            return {"ok": False, "error": "create_failed"}
        self._view_override = target
        return {"ok": True, "tab": target}

    def answer_dialog(self, accept: bool, text: str = "") -> dict[str, Any]:
        """사람이 무대에 그린 알림창에 답했다."""
        if self._dialog is None:
            return {"ok": False, "error": "no_dialog"}
        self.take_control()
        params: dict[str, Any] = {"accept": bool(accept)}
        if accept and self._dialog.get("type") == "prompt":
            params["promptText"] = str(text or "")[:2000]
        self._send("Page.handleJavaScriptDialog", params, wait=False)
        self._dialog = None
        return {"ok": True}

    def set_files(self, paths: list[str]) -> dict[str, Any]:
        """사람이 온텔릭의 파일 고르기 창으로 고른 파일을 그 입력칸에 넣는다. 빈 목록이면 취소."""
        chooser = self._file_chooser
        if chooser is None:
            return {"ok": False, "error": "no_file_chooser"}
        self.take_control()
        self._file_chooser = None
        files = [str(item) for item in (paths or []) if str(item).strip()][:20]
        if not files:
            return {"ok": True, "cancelled": True}
        if chooser.get("mode") != "selectMultiple":
            files = files[:1]
        reply = self._send("DOM.setFileInputFiles", {"files": files, "backendNodeId": chooser.get("backend_node_id")})
        return {"ok": reply is not None, "count": len(files)}

    def _select_at(self, x: float, y: float) -> dict[str, Any] | None:
        """(x, y) 가 고르기 상자면 목록을 읽어 준다. iframe 안·여러 개 고르기는 건드리지 않는다(진짜 크롬으로)."""
        script = (
            "(() => { const el = document.elementFromPoint(%f, %f);"
            " const s = el && el.closest ? el.closest('select') : null;"
            " if (!s || s.disabled || s.multiple || s.size > 1) return null;"
            " window.__ontelicSelect = s; const r = s.getBoundingClientRect();"
            " return JSON.stringify({options: Array.from(s.options).slice(0, 300).map(o => ({text: o.text, disabled: o.disabled})),"
            " selected: s.selectedIndex, rect: {x: r.left, y: r.top, w: r.width, h: r.height}}); })()"
        ) % (x, y)
        reply = self._send("Runtime.evaluate", {"expression": script, "returnByValue": True}, timeout=1.5)
        value = ((reply or {}).get("result") or {}).get("value")
        if not value:
            return None
        try:
            picked = json.loads(value)
        except (TypeError, ValueError):
            return None
        frame = self._frame or {}
        width = float(frame.get("css_width") or 1) or 1.0
        height = float(frame.get("css_height") or 1) or 1.0
        rect = picked.get("rect") or {}
        # 무대는 0..1 좌표를 쓴다 — 목록을 상자 바로 아래에 그리려고 비율로 바꿔 준다.
        picked["rect"] = {"x": float(rect.get("x") or 0) / width, "y": float(rect.get("y") or 0) / height,
                          "w": float(rect.get("w") or 0) / width, "h": float(rect.get("h") or 0) / height}
        return picked

    def _select_pick(self, index: int) -> dict[str, Any]:
        script = (
            "(() => { const s = window.__ontelicSelect; if (!s || !s.isConnected) return false;"
            " if (%d < 0 || %d >= s.options.length || s.options[%d].disabled) return false;"
            " s.selectedIndex = %d; s.dispatchEvent(new Event('input', {bubbles: true}));"
            " s.dispatchEvent(new Event('change', {bubbles: true})); return true; })()"
        ) % (index, index, index, index)
        reply = self._send("Runtime.evaluate", {"expression": script, "returnByValue": True}, timeout=1.5)
        ok = bool(((reply or {}).get("result") or {}).get("value"))
        return {"ok": ok} if ok else {"ok": False, "error": "select_gone"}

    def _refresh_history(self) -> dict[str, Any] | None:
        reply = self._send("Page.getNavigationHistory", {}, timeout=1.5)
        if not reply or "entries" not in reply:
            return None
        entries = [{"id": item.get("id"), "url": item.get("url"), "title": item.get("title")} for item in reply["entries"]]
        index = int(reply.get("currentIndex", -1))
        self._history = {"index": index, "entries": entries}
        self._nav["can_back"] = index > 0
        self._nav["can_forward"] = 0 <= index < len(entries) - 1
        if 0 <= index < len(entries):
            self._nav["url"] = str(entries[index].get("url") or self._nav["url"])
            self._nav["title"] = str(entries[index].get("title") or self._nav["title"])
        self._history_dirty = False
        return self._history

    # ── 무대 크기 ───────────────────────────────────────────────────────────
    def fit(self, width: int, height: int) -> dict[str, Any]:
        """무대(온텔릭 안 화면 칸) 비율에 크롬 창을 맞춘다. 폭은 `FIT_MIN_WIDTH` 아래로 안 내린다."""
        try:
            width, height = int(width), int(height)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_size"}
        if width < 200 or height < 150:
            return {"ok": False, "error": "too_small"}
        target_w = max(FIT_MIN_WIDTH, min(2400, width))
        target_h = int(round(target_w * height / width))
        target_h = max(600, min(1600, target_h))
        self._fit_wanted = (target_w, target_h)
        self._watch()
        return {"ok": True, "wanted": [target_w, target_h]}

    def _apply_fit(self) -> None:
        wanted = self._fit_wanted
        if not wanted or wanted == self._fit_done or not self._target_id or self._ws is None:
            return
        # 사람이 불러서 화면 안에 둔 창은 사람의 것이다 — 크기를 바꾸지 않는다.
        from .browser import BrowserWorker

        if BrowserWorker._human_shown:
            return
        window = self._send("Browser.getWindowForTarget", {"targetId": self._target_id})
        if not window or "windowId" not in window:
            return
        bounds = dict(window.get("bounds") or {})
        if str(bounds.get("windowState") or "normal") != "normal":
            return
        chrome = self._send("Runtime.evaluate", {
            "expression": "JSON.stringify([outerWidth-innerWidth, outerHeight-innerHeight])",
            "returnByValue": True,
        })
        try:
            dx, dy = json.loads(str(((chrome or {}).get("result") or {}).get("value") or "[0,0]"))
        except (ValueError, TypeError):
            dx, dy = 0, 0
        dx, dy = max(0, min(int(dx), 60)), max(0, min(int(dy), 200))
        want_w, want_h = wanted
        if not (abs(int(bounds.get("width") or 0) - (want_w + dx)) < 8 and abs(int(bounds.get("height") or 0) - (want_h + dy)) < 8):
            self._send("Browser.setWindowBounds", {
                "windowId": window["windowId"],
                "bounds": {"width": want_w + dx, "height": want_h + dy},
            })
            time.sleep(0.3)
        self._fit_background_tab(want_w, want_h)
        self._fit_done = wanted

    def _fit_background_tab(self, want_w: int, want_h: int) -> None:
        """창을 맞춰도 **뒤 탭**은 안쪽 크기를 안 따라온다 — 그 탭에만 같은 크기를 지정한다 (2026-09-26 E2E).

        주차 중 온텔릭은 새 탭을 뒤 탭(`createTarget background:true`)으로 연다 — 앞창을 뺏지 않으려고. 크롬은 창 크기가 바뀌면
        앞 탭만 따라 바꾼다. 그래서 벤치 뒤 무대의 탭은 창(1280)과 달리 안쪽이 1920×922 로 남아, 그림 아래가 검은 띠였고
        위 좌표 버그(세로 가운데 셈)까지 드러났다. 창과 **같은 값**을 지정하므로 페이지가 보는 크기는 앞 탭일 때와 같다.
        """
        measured = self._send("Runtime.evaluate", {
            "expression": "JSON.stringify([innerWidth, innerHeight])",
            "returnByValue": True,
        })
        try:
            inner_w, inner_h = json.loads(str(((measured or {}).get("result") or {}).get("value") or "[0,0]"))
        except (ValueError, TypeError):
            return
        if abs(int(inner_w) - want_w) < 8 and abs(int(inner_h) - want_h) < 8:
            return
        self._send("Emulation.setDeviceMetricsOverride", {
            "width": want_w, "height": want_h, "deviceScaleFactor": 0, "mobile": False,
        })

    # ── 스트림 스레드 ─────────────────────────────────────────────────────────
    def _run(self) -> None:
        checked_at = 0.0
        while True:
            try:
                watching = time.time() < self._watch_until or self._control_active
                if not watching:
                    self._close("idle")
                    if time.time() > self._watch_until + 60:
                        return  # 오래 아무도 안 봤다 — 다음에 보면 다시 선다
                    time.sleep(0.25)
                    continue
                if time.time() - checked_at > 1.0:
                    checked_at = time.time()
                    target = self._pick_target()
                    if target is None:
                        self._close("no_page")
                        self._status = "no_page"
                        time.sleep(0.5)
                        continue
                    if target["id"] != self._target_id or self._ws is None:
                        self._open(target)
                    try:
                        self._apply_fit()
                    except Exception:  # noqa: BLE001 — 창 맞춤 실패가 스트림을 죽이면 안 된다(닫고 다시 열고 또 실패하는 고리)
                        LOG.debug("live view fit failed", exc_info=True)
                        self._fit_done = self._fit_wanted
                    if self._history_dirty and self._ws is not None:
                        self._refresh_history()
                    if (self._ws is not None and self._last_frame_at < self._stream_started_at
                            and time.time() - self._stream_started_at > NO_FRAME_SEC):
                        self._status = "no_frames"  # 뒤쪽 탭 — 화면은 예전 스크린샷 길을 쓴다
                self._pump(0.25)
            except Exception as exc:  # noqa: BLE001 — 끊기면 다시 붙는다
                # 같은 오류는 한 번만 남긴다 — 삼키기만 하면 「화면이 안 움직인다」의 원인을 영영 못 본다(2026-09-26 E2E).
                signature = f"{type(exc).__name__}:{str(exc)[:120]}"
                if signature != getattr(self, "_last_error", ""):
                    self._last_error = signature
                    LOG.warning("live view stream error: %s", signature, exc_info=True)
                self._close("error")
                time.sleep(0.5)

    def _port(self) -> int:
        worker = self.worker
        return int(getattr(worker, "_cdp_port_in_use", None) or getattr(worker.config, "browser_cdp_port", 9222) or 9222)

    def _pick_target(self) -> dict[str, Any] | None:
        """온텔릭이 지금 일하는 탭. 일꾼의 탭 주소로 찾는다(일꾼 스레드에 줄 서지 않으려고 목록은 HTTP 로 받는다)."""
        if not getattr(self.worker, "_connected", False):
            return None
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._port()}/json/list", timeout=1.5) as response:  # noqa: S310
                targets = json.loads(response.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
        pages = [item for item in targets if item.get("type") == "page" and not str(item.get("url") or "").startswith("devtools://")]
        if not pages:
            self._tabs = []
            return None
        wanted = ""
        page = getattr(self.worker, "_page", None)
        try:
            wanted = str(getattr(page, "url", "") or "")
        except Exception:  # noqa: BLE001
            wanted = ""
        agent = next((item for item in pages if wanted and str(item.get("url") or "") == wanted), None)
        if agent is None:
            wanted_bare = wanted.split("#", 1)[0]
            agent = next((item for item in pages if wanted_bare and str(item.get("url") or "").split("#", 1)[0] == wanted_bare), None)
        self._tabs = [{"id": str(item.get("id")), "title": str(item.get("title") or "")[:120], "url": str(item.get("url") or "")[:500],
                       "agent": agent is not None and item.get("id") == agent.get("id")} for item in pages[:12]]
        if self._view_override:
            chosen = next((item for item in pages if str(item.get("id")) == self._view_override), None)
            if chosen is not None:
                return chosen
            self._view_override = ""
        if agent is not None:
            return agent
        current = next((item for item in pages if item.get("id") == self._target_id), None)
        return current or pages[0]

    def _open(self, target: dict[str, Any]) -> None:
        from websockets.sync.client import connect

        self._close("switch")
        url = str(target.get("webSocketDebuggerUrl") or f"ws://127.0.0.1:{self._port()}/devtools/page/{target['id']}")
        # ★ keepalive 끔 (2026-09-26 E2E). 화면 장이 몰려 받는 줄이 차면 핑 답(pong)을 제때 못 읽어 20초 뒤 연결이 끊겼다
        #   (`keepalive ping timeout`) — 그 틈에 사람이 친 아이디가 사라졌다. 로컬 크롬 연결이고, 끊김은 받기 오류로 이미 안다.
        self._ws = connect(url, max_size=32 * 1024 * 1024, open_timeout=3, compression=None, ping_interval=None)
        self._target_id = str(target["id"])
        self._stream_started_at = time.time()
        self._status = "streaming"
        self._fit_done = None
        self._dialog = None
        self._file_chooser = None
        self._history_dirty = True
        self._main_frame = ""
        self._send("Page.enable", {}, wait=False)
        # 파일 고르기를 가로챈다 — 안 그러면 크롬이 화면 밖 창에 윈도우 파일 창을 띄워 아무도 못 본다.
        self._send("Page.setInterceptFileChooserDialog", {"enabled": True}, wait=False)
        self._send("Page.startScreencast", {"format": "jpeg", "quality": 72, "maxWidth": 2560, "maxHeight": 1600,
                                            "everyNthFrame": 1}, wait=False)
        if self._control_active:
            self._send("Emulation.setFocusEmulationEnabled", {"enabled": True}, wait=False)

    def _close(self, why: str) -> None:
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass
        self._status = why

    def _pump(self, timeout: float) -> None:
        ws = self._ws
        if ws is None:
            time.sleep(timeout)
            return
        try:
            raw = ws.recv(timeout=timeout)
        except TimeoutError:
            return
        message = json.loads(raw)
        if "id" in message:
            with self._reply_cond:
                self._replies[int(message["id"])] = message
                self._reply_cond.notify_all()
            return
        method = str(message.get("method") or "")
        if method and method != "Page.screencastFrame":
            self._on_page_event(method, message.get("params") or {})
            return
        if message.get("method") == "Page.screencastFrame":
            params = message.get("params") or {}
            self._send("Page.screencastFrameAck", {"sessionId": params.get("sessionId")}, wait=False)
            meta = params.get("metadata") or {}
            data = base64.b64decode(params.get("data") or "")
            page = getattr(self.worker, "_page", None)
            try:
                url = str(getattr(page, "url", "") or "")
            except Exception:  # noqa: BLE001
                url = ""
            with self._cond:
                self._seq += 1
                self._frame = {
                    "seq": self._seq,
                    "jpeg": data,
                    "at": time.time(),
                    # 입력 좌표는 CSS 픽셀이다 — 그림 픽셀이 아니라 메타데이터의 기기 폭·높이로 바꾼다.
                    "css_width": float(meta.get("deviceWidth") or 0),
                    "css_height": float(meta.get("deviceHeight") or 0),
                    "width": float(meta.get("deviceWidth") or 0),
                    "height": float(meta.get("deviceHeight") or 0),
                    "url": url,
                    "target": self._target_id,
                }
                self._last_frame_at = time.time()
                self._status = "streaming"
                self._cond.notify_all()

    def _on_page_event(self, method: str, params: dict[str, Any]) -> None:
        if method == "Page.frameNavigated":
            frame = params.get("frame") or {}
            if not frame.get("parentId"):
                self._main_frame = str(frame.get("id") or self._main_frame)
                self._nav["url"] = str(frame.get("url") or self._nav["url"])
                self._history_dirty = True
        elif method == "Page.navigatedWithinDocument":
            if not self._main_frame or params.get("frameId") == self._main_frame:
                self._nav["url"] = str(params.get("url") or self._nav["url"])
                self._history_dirty = True
        elif method == "Page.frameStartedLoading":
            if not self._main_frame or params.get("frameId") == self._main_frame:
                self._nav["loading"] = True
        elif method in {"Page.frameStoppedLoading", "Page.loadEventFired"}:
            if method == "Page.loadEventFired" or not self._main_frame or params.get("frameId") == self._main_frame:
                self._nav["loading"] = False
                self._history_dirty = True
        elif method == "Page.javascriptDialogOpening":
            self._dialog = {"type": str(params.get("type") or "alert"), "message": str(params.get("message") or "")[:1000],
                            "default": str(params.get("defaultPrompt") or "")[:500], "at": time.time()}
        elif method == "Page.javascriptDialogClosed":
            self._dialog = None
        elif method == "Page.fileChooserOpened":
            self._file_chooser = {"mode": str(params.get("mode") or "selectSingle"),
                                  "backend_node_id": params.get("backendNodeId"), "at": time.time()}

    def _send(self, method: str, params: dict[str, Any] | None = None, *, wait: bool = True,
              timeout: float = 3.0) -> dict[str, Any] | None:
        ws = self._ws
        if ws is None:
            return None
        with self._id_lock:
            self._msg_id += 1
            message_id = self._msg_id
        try:
            ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        except Exception:  # noqa: BLE001
            return None
        if not wait:
            return None
        # 답은 스트림 스레드가 받는다. 그 스레드 자신이 부른 것이면 여기서 직접 받는다.
        deadline = time.time() + timeout
        on_stream = threading.current_thread() is self._thread
        with self._reply_cond:
            while True:
                reply = self._replies.pop(message_id, None)
                if reply is not None:
                    return reply.get("result") if isinstance(reply.get("result"), dict) else {}
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                if on_stream:
                    self._reply_cond.release()
                    try:
                        self._pump(min(0.2, remaining))
                    finally:
                        self._reply_cond.acquire()
                else:
                    self._reply_cond.wait(remaining)


def _modifiers(event: dict[str, Any]) -> int:
    value = 0
    for name, bit in _MODIFIER_BITS.items():
        if event.get(name):
            value |= bit
    return value


def _key_params(event: dict[str, Any], modifiers: int) -> dict[str, Any]:
    key = str(event.get("key") or "")
    down = str(event.get("type") or "down") == "down"
    params: dict[str, Any] = {
        "key": key,
        "code": str(event.get("code") or ""),
        "windowsVirtualKeyCode": int(event.get("keyCode") or 0),
        "nativeVirtualKeyCode": int(event.get("keyCode") or 0),
        "modifiers": modifiers,
    }
    if not down:
        params["type"] = "keyUp"
        return params
    text = _KEY_TEXT.get(key, "")
    params["type"] = "keyDown" if text else "rawKeyDown"
    if text:
        params["text"] = text
        params["unmodifiedText"] = text
    if modifiers & (_MODIFIER_BITS["ctrl"] | _MODIFIER_BITS["meta"]):
        command = _SHORTCUT_COMMANDS.get(key.lower())
        if command:
            params["commands"] = [command]
    return params


_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
#: 주소창에서 열어도 되는 것. `javascript:`·`file:`·`chrome:` 은 검색어로 본다 — 주소창이 스크립트 실행 문이 되면 안 된다.
_SAFE_SCHEMES = ("http://", "https://", "about:blank")


def normalize_address(text: str) -> str:
    """주소창에 친 것 → 열 주소. 주소 모양이 아니면 네이버 검색(아버님이 「부산 날씨」라고 쳐도 되게)."""
    value = str(text or "").strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered.startswith(_SAFE_SCHEMES):
        return value
    if not _SCHEME.match(value) and " " not in value and ("." in value or lowered.startswith("localhost")):
        return "https://" + value
    return "https://search.naver.com/search.naver?query=" + urllib.parse.quote(value)
