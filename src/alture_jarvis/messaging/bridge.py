"""메신저에서 받은 말을 **이미 돌고 있는 손자리 본체**(HTTP)에 맡기고, 진행과 답을 메신저로 돌려준다 (2026-10-17).

## 본체와 말하는 법 — MCP 다리(`mcp_server._delegate`)와 같은 문을 쓴다

    맡기기   POST /v1/chat               (토큰)  → {"id": …}
    물어보기 GET  /v1/jobs/{id}          (토큰 없이 — 바깥으로 나가는 판으로 정제된 사본이 온다, `outbound.outbound_job_view`)
    진행     GET  /v1/jobs/{id}/live     (토큰)  → 「지금 하는 일」
    승인 내용 GET /v1/approvals?status=pending (토큰) — **읽기만.** 승인 문(POST /v1/approvals/…)은 이 다리에서 부르지 않는다.
    멈추기   POST /v1/jobs/{id}/cancel   (토큰)

## ★ origin 을 `mcp` 로 보내는 까닭 (2026-10-17)

`ChatRequest.origin` 은 `chat · voice · workspace · mcp` 만 받는다 — `discord` 를 보내면 422 다. 그리고 `mcp` 가 지금
붙어 있는 성질이 디스코드에 맞다:
- 화면(이미 깔린 exe)이 「밖에서 맡긴 일」로 알아보고 제 방 · 출처 이름(`caller="Discord"`)을 두른다. 새 값은 exe 를 다시
  구워야 화면이 안다.
- 나가는 답을 정제한다(주민번호 · 카드 · 비밀 키 가림, `outbound.refine`). 디스코드로 가는 답은 PC 밖으로 나간다.
- 대신 줄에서 PC 앞 사람의 일이 먼저 나간다(`jobs._delegated_payload`). PC 앞 사람이 먼저인 것이 맞다고 보고 그대로 둔다.
새 origin 이 필요해지면(예: 줄 순서를 사람처럼) 본체 · 화면을 같이 고칠 때 바꾼다.

## 이 모듈이 하지 않는 것

- 토큰 단위 흘려 보내기(스트리밍) — 진행 메시지 하나를 「지금 하는 일」로 고쳐 쓴다.
- 승인 · 질문 카드에 답하기 — `discord_approvals="app_only"`. PC 앱에서 기다린다고만 알린다.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from ..memory import without_our_tail
from ..model_aliases import split_prefix
from .base import PC_SAME, REDACTOR, BasePlatformAdapter, MessageEvent, SessionMap, parse_command, say

log = logging.getLogger("sonjari.messaging")

__all__ = ["SonjariBackend", "BackendError", "TaskRunner", "ApprovalButtonBinder", "resolve_backend", "CALLER"]

#: 화면 · 영수증에 찍히는 맡긴 쪽 이름.
CALLER = "Discord"
TERMINAL = {"completed", "failed", "cancelled"}
POLL_SEC = 2.0
#: 디스코드의 「입력 중…」은 약 10초 간다 — 그보다 조금 짧게 다시 보낸다.
TYPING_EVERY_SEC = 9.0
#: 본체가 이만큼 연달아 답하지 않으면 그 판을 놓는다(2초 × 45 ≈ 1.5분). 본체 재시작 정도는 견딘다.
MAX_OFFLINE_POLLS = 45
#: 한 판에 올리는 파일 수 상한 — 폴더 하나를 통째로 만든 판이 채널을 덮지 않게.
MAX_FILES = 10


#: 대표사진을 디스코드로 보낼 때 잘라 내는 위 띠 — 로그인한 사이트가 이름 · 프로필을 그리는 자리(2026-10-18 대표 결정).
SHOWCASE_TOP_BAND_PX = 120


def _without_top_band(source: Path, band: int = SHOWCASE_TOP_BAND_PX) -> Path:
    """위 띠를 잘라 낸 사본을 같은 폴더에 만든다(원본은 그대로 — PC 앱은 원본을 보여 준다)."""
    from PIL import Image

    target = source.with_name(f"{source.stem}.discord{source.suffix or '.jpg'}")
    with Image.open(source) as image:
        width, height = image.size
        top = min(band, max(0, height // 4))  # 아주 작은 사진은 4분의 1까지만 자른다
        image.crop((0, top, width, height)).convert("RGB").save(target, "JPEG", quality=80)
    return target


class BackendError(Exception):
    """kind: offline(안 떠 있음) · unauthorized(토큰 불일치) · rejected(받지 않음) · not_found(그 일이 없음)."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def resolve_backend() -> tuple[str, str, Path]:
    """(본체 주소, 연결 토큰, 데이터 폴더). MCP 다리 · 측정 꾸러미와 **같은 차례**로 찾는다.

    `JARVIS_BASE_URL` · `JARVIS_TOKEN_FILE`(설정 보관소) → 설정의 기본 자리. 패키지(MSIX)로 깐 손자리는 토큰이
    앱 전용 칸에 있어 밖의 프로세스가 여는 실제 경로로 푼다(`msix.external_path`).
    """
    from .. import config as config_module
    from .. import msix
    from ..config import JarvisConfig, setting

    # ★ 소스로 깐 손자리(`<루트>/src/alture_jarvis`)는 본체가 `scripts/task_entry.py` 에서 런타임 루트를 정하고 뜬다. 다리는 그 길을
    #   안 지나서 기본 자리(스토어판 데이터 폴더)를 보고 「연결 토큰: 없음」이 됐다 (2026-10-17 첫 점검). 본체와 같은 루트를 쓴다 —
    #   그 루트에 본체가 만든 연결 토큰이 있을 때만(스토어판은 패키지 안에 data 가 없어 여기 안 걸린다).
    source_root = Path(__file__).resolve().parents[3]
    if not setting("JARVIS_RUNTIME_ROOT") and (source_root / "data" / "control.token").is_file():
        config_module.keep_private("JARVIS_RUNTIME_ROOT", str(source_root))
        try:
            config_module.load_env_file(source_root / ".env")
        except Exception:  # noqa: BLE001 - .env 를 못 읽어도 기본 주소로 붙는다(본체 task_entry 와 같은 태도).
            pass

    config = JarvisConfig.from_env()
    host = str(getattr(config, "host", "127.0.0.1") or "127.0.0.1")
    host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    base_url = setting("JARVIS_BASE_URL") or f"http://{host}:{int(config.port)}"
    data_dir = msix.external_path(Path(config.data_dir))
    token_path = Path(setting("JARVIS_TOKEN_FILE") or msix.external_path(Path(config.data_dir) / "control.token"))
    try:
        token = token_path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        token = ""
    REDACTOR.register(token)
    return base_url.rstrip("/"), token, Path(data_dir)


class SonjariBackend:
    """본체 HTTP 문 다섯 개. 승인을 **내리는** 문은 일부러 없다."""

    def __init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None,
                 timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        REDACTOR.register(token)
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-JARVIS-TOKEN": self.token}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, f"{self.base_url}{path}",
                                                  headers=self._headers if auth else None, **kwargs)
        except httpx.RequestError as exc:
            raise BackendError("offline", type(exc).__name__) from exc
        if response.status_code == 401:
            raise BackendError("unauthorized")
        if response.status_code == 404:
            raise BackendError("not_found")
        return response

    async def health(self) -> bool:
        try:
            return (await self._call("GET", "/health", auth=False)).status_code == 200
        except BackendError:
            return False

    async def model_aliases(self) -> dict[str, Any] | None:
        """본체의 모델 별명 표 `{"pc_model", "aliases": [{alias, tag, note, loaded}]}`. 못 받으면 None."""
        try:
            response = await self._call("GET", "/v1/models/aliases")
        except BackendError:
            return None
        if response.status_code != 200:
            return None
        data = response.json()
        return data if isinstance(data, dict) and isinstance(data.get("aliases"), list) else None

    async def request_access(self, event: MessageEvent) -> dict[str, Any] | None:
        """허용 목록 밖 사람이 말을 걸었다 — 본체에 「허용 요청」을 남긴다. {"notify": 안내를 보낼까, ...}. 못 남기면 None."""
        body = {"user_id": event.user_id, "display_name": event.user_name, "username": event.user_handle,
                "text": event.text[:200]}
        try:
            response = await self._call("POST", "/v1/discord/requests", json=body)
        except BackendError:
            return None
        return response.json() if response.status_code == 200 else None

    async def submit(self, prompt: str, session_id: str, *, caller: str = CALLER, model_alias: str = "") -> str:
        body = {
            "prompt": prompt[:12000],
            # 화면의 대화 목록에 보일 짧은 말 — 「어디서 온 일인가」가 먼저 보이게.
            "display_prompt": f"{caller} · {prompt.strip()[:60]}",
            "origin": "mcp",
            "caller": caller,
            "session_id": session_id,
            # 원격에서 시킨 일이다 — PC 화면에 워드 · 엑셀 창을 띄우지 않고, PC 스피커로 답을 읽지도 않는다.
            "open_results": False,
            "delivery": "screen",
        }
        if model_alias:
            # 판 하나만 그 모델로 — 본체가 별명 표로 태그를 푼다(태그를 직접 넘기는 길은 없다).
            body["model_alias"] = model_alias
        response = await self._call("POST", "/v1/chat", json=body)
        if response.status_code >= 400:
            raise BackendError("rejected", REDACTOR.redact(response.text[:300]))
        job_id = str((response.json() or {}).get("id") or "")
        if not job_id:
            raise BackendError("rejected", "no_job_id")
        return job_id

    async def job(self, job_id: str) -> dict[str, Any]:
        # 토큰 없이 읽는다 — 바깥으로 나가는 판으로 정제된 사본이 온다(mcp_server 와 같은 읽기).
        response = await self._call("GET", f"/v1/jobs/{job_id}", auth=False)
        if response.status_code >= 400:
            # 5xx 는 본체가 잠깐 못 답한 것으로 본다 — 연결이 끊긴 것과 같이 몇 번 더 묻는다(`MAX_OFFLINE_POLLS`).
            raise BackendError("offline", f"http_{response.status_code}")
        return response.json()

    async def live(self, job_id: str) -> dict[str, Any] | None:
        try:
            response = await self._call("GET", f"/v1/jobs/{job_id}/live")
        except BackendError:
            return None
        return response.json() if response.status_code == 200 else None

    async def pending_approval(self, job_id: str) -> dict[str, Any] | None:
        """이 일이 기다리는 카드 — 질문 카드면 그 질문을 디스코드에 옮기려고 **읽기만** 한다."""
        try:
            response = await self._call("GET", "/v1/approvals", params={"status": "pending", "limit": 20})
        except BackendError:
            return None
        if response.status_code != 200:
            return None
        return next((row for row in response.json() or [] if str(row.get("job_id") or "") == job_id), None)

    async def cancel(self, job_id: str) -> bool:
        try:
            response = await self._call("POST", f"/v1/jobs/{job_id}/cancel")
        except BackendError:
            return False
        return response.status_code == 200


# ── 승인 버튼 자리 (기본 꺼짐) ─────────────────────────────────────────────────

class ApprovalButtonBinder:
    """★ 버튼 하나 = 승인 하나 (2026-10-17, 아직 쓰지 않는 자리).

    Hermes #135905: 승인 버튼이 **그 버튼을 그릴 때의 승인**이 아니라 「지금 걸려 있는 승인」을 눌러, 앞서 뜬 버튼이
    나중 승인을 통과시켰다. 그래서 버튼마다 제 무작위 표를 만들고 표 → (승인 nonce, 일, 누른 사람)을 여기에만 둔다.
    - 승인 nonce 자체는 디스코드에 안 싣는다(custom_id 는 디스코드 서버를 지난다). 표만 싣는다.
    - 한 번 쓰면 짝(승인/거절) 둘 다 지운다 · 시킨 사람만 누를 수 있다 · `ttl_sec` 뒤엔 무효.
    """

    PREFIX = "sonjari-approval"

    def __init__(self, ttl_sec: float = 300.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_sec
        self._clock = clock
        self._tickets: dict[str, dict[str, Any]] = {}

    def bind(self, approval_nonce: str, job_id: str, user_id: str) -> tuple[str, str]:
        expires = self._clock() + self._ttl
        approve, deny = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
        for ticket, decision, sibling in ((approve, True, deny), (deny, False, approve)):
            self._tickets[ticket] = {"nonce": approval_nonce, "job_id": job_id, "user_id": str(user_id),
                                     "approve": decision, "sibling": sibling, "expires": expires}
        return f"{self.PREFIX}:{approve}", f"{self.PREFIX}:{deny}"

    def resolve(self, custom_id: str, user_id: str) -> tuple[str, bool] | None:
        prefix, _, ticket = str(custom_id or "").partition(":")
        entry = self._tickets.get(ticket) if prefix == self.PREFIX else None
        if entry is None or entry["user_id"] != str(user_id):
            return None
        self._tickets.pop(ticket, None)
        self._tickets.pop(entry["sibling"], None)
        if self._clock() > entry["expires"]:
            return None
        return entry["nonce"], bool(entry["approve"])


# ── 한 판 돌리기 ───────────────────────────────────────────────────────────────

@dataclass
class _Waits:
    approval: bool = False
    person: bool = False


class TaskRunner:
    """들어온 말 하나 → 명령이면 처리, 아니면 본체에 맡기고 끝까지 따라간다."""

    def __init__(self, adapter: BasePlatformAdapter, backend: SonjariBackend, sessions: SessionMap, *,
                 approvals: str = "app_only", poll_sec: float = POLL_SEC, typing_every: float = TYPING_EVERY_SEC,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Any] = asyncio.sleep,
                 max_offline_polls: int = MAX_OFFLINE_POLLS, default_model: Callable[[], str] | None = None) -> None:
        self.adapter = adapter
        #: 디스코드 기본 모델 별명을 **그때그때** 읽는다(설정 화면에서 바꾸면 다리를 다시 켜지 않아도 다음 판부터).
        self._default_model = default_model or (lambda: "")
        self.backend = backend
        self.sessions = sessions
        if approvals != "app_only":
            log.warning("discord_approvals=%s 는 아직 연결하지 않았습니다 — app_only 로 돕니다(승인은 PC 앱에서만).", approvals)
        self.approvals = "app_only"
        self.poll_sec = poll_sec
        self.typing_every = typing_every
        self._clock = clock
        self._sleep = sleep
        self._max_offline = max_offline_polls
        #: 대화마다 마지막으로 쓴 언어 — `/stop` 처럼 말이 없는 명령에 그 언어로 답한다.
        self._langs: dict[str, str] = {}
        #: 본체가 꺼져 허용 요청을 못 남길 때만 쓰는 「하루 한 번 안내」 기억.
        self._local_notices: dict[str, float] = {}

    async def handle(self, event: MessageEvent) -> None:
        command = parse_command(event.text)
        if command:
            if not event.text.strip().split(maxsplit=1)[1:]:
                event.lang = self._langs.get(event.session_key, event.lang)
            reply = await self.command_reply(command, event)
            await self.adapter.send(event.chat_id, reply, reply_to=event.message_id or None)
            return
        if not event.text.strip():
            return
        if self.sessions.active(event.session_key):
            await self.adapter.send(event.chat_id, say("busy", event.lang), reply_to=event.message_id or None)
            return
        await self.run_task(event)

    async def command_reply(self, command: str, event: MessageEvent) -> str:
        """`/new` · `/stop` · `/status` 의 답 글. 디스코드 슬래시 명령도 이 함수로 온다."""
        lang = event.lang
        if command == "new":
            self.sessions.reset(event.session_key)
            return say("new", lang)
        active = self._active_for(event)
        if command == "stop":
            if not active:
                return say("stop_none", lang)
            return say("stop_ok" if await self.backend.cancel(active["job_id"]) else "stop_failed", lang)
        if command == "status":
            if not active:
                return say("status_idle", lang)
            try:
                job = await self.backend.job(active["job_id"])
            except BackendError as exc:
                return say("offline" if exc.kind == "offline" else "status_idle", lang)
            label = await self._label(job, active["job_id"], lang)
            minutes = max(0, int((time.time() - float(active.get("since") or time.time())) // 60))
            return say("status_running", lang, label=label, minutes=minutes)
        return ""

    def _active_for(self, event: MessageEvent) -> dict[str, Any] | None:
        active = self.sessions.active(event.session_key)
        if active is None and event.chat_type == "channel":
            found = self.sessions.active_for_user(event.user_id)
            active = found[1] if found else None
        return active

    # ── 허용 요청 (2026-10-18) ───────────────────────────────────────────────

    async def access_request(self, event: MessageEvent) -> None:
        """허용 목록 밖 사람의 말 — **일은 시작하지 않는다.** 본체에 요청을 남기고, 하루 한 번만 「주인이 허용하면 답한다」."""
        result = await self.backend.request_access(event)
        if result is None:
            now = time.time()
            notify = now - self._local_notices.get(event.user_id, 0.0) >= 24 * 3600
            if notify:
                self._local_notices[event.user_id] = now
        else:
            notify = bool(result.get("notify"))
        if notify:
            await self.adapter.send(event.chat_id, say("access_pending", event.lang), reply_to=event.message_id or None)

    # ── 모델 고르기 (2026-10-18) ──────────────────────────────────────────────

    def _chosen_model(self, event: MessageEvent) -> str:
        """`/모델` 로 이 대화에 고른 별명 → 없으면 디스코드 기본 모델. 스레드는 바깥 채널에서 고른 것도 본다."""
        for key in (event.session_key, event.origin_chat_id):
            chosen = self.sessions.model(key) if key else ""
            if chosen:
                return "" if chosen == PC_SAME else chosen
        try:
            return str(self._default_model() or "")
        except Exception:  # noqa: BLE001 — 설정을 못 읽으면 PC 와 같게
            return ""

    async def _pick_model(self, event: MessageEvent) -> tuple[str, str, dict[str, Any] | None]:
        """(이 판의 별명, 맡길 글, 그 별명의 표 행). 「@별명 할 일」이 먼저, 그다음 대화에 고른 모델."""
        text = event.text
        table = await self.backend.model_aliases()
        rows = list((table or {}).get("aliases") or [])
        names = [str(row.get("alias") or "") for row in rows if row.get("alias")]
        alias, rest = split_prefix(text, names)
        if alias:
            text = rest
        else:
            alias = self._chosen_model(event)
        row = next((r for r in rows if str(r.get("alias") or "").casefold() == alias.casefold()), None) if alias else None
        # 표에서 지워진 별명이 대화 · 설정에 남아 있으면 PC 모델로 돈다(판을 죽이지 않는다).
        return (str(row.get("alias")) if row else ""), text, row

    def model_choices(self, current: str, rows: list[dict[str, Any]], lang: str = "ko") -> list[tuple[str, str]]:
        """`/모델` 자동 완성 — (보이는 이름, 값). 「PC 와 같음」이 맨 앞."""
        wanted = str(current or "").strip().casefold()
        out = [(say("model_pc_choice", lang), PC_SAME)]
        for row in rows:
            alias = str(row.get("alias") or "")
            label = f"{alias} · {row.get('tag') or ''}" + (f" — {row['note']}" if row.get("note") else "")
            out.append((label[:100], alias))
        return [item for item in out if not wanted or wanted in item[0].casefold()][:25]

    async def model_command(self, value: str, event: MessageEvent) -> str:
        """`/모델 <별명>` — 이 대화의 모델을 계속 그것으로. 디스코드 슬래시 명령이 부른다."""
        lang = event.lang
        choice = str(value or "").strip()
        if choice in {PC_SAME, say("model_pc_choice", "ko"), say("model_pc_choice", "en")}:
            self.sessions.set_model(event.session_key, PC_SAME)
            return say("model_pc", lang)
        table = await self.backend.model_aliases()
        if table is None:
            return say("model_none", lang)
        rows = list(table.get("aliases") or [])
        row = next((r for r in rows if str(r.get("alias") or "").casefold() == choice.casefold()), None)
        if row is None:
            names = ", ".join(str(r.get("alias")) for r in rows) or "-"
            return say("model_unknown", lang, alias=choice[:40], names=names)
        self.sessions.set_model(event.session_key, str(row["alias"]))
        return say("model_set", lang, alias=row["alias"], tag=row.get("tag") or "")

    async def run_task(self, event: MessageEvent) -> dict[str, Any] | None:
        """맡기고 → 따라가고 → 답 · 파일 · 반응. 끝난 판의 요약(`delegation.summarize_job`)을 돌려준다."""
        lang, key = event.lang, event.session_key
        self._langs[key] = lang
        alias, text, row = await self._pick_model(event)
        if not text.strip():
            await self.adapter.send(event.chat_id, say("model_prefix_empty", lang, alias=alias or "-"),
                                    reply_to=event.message_id or None)
            return None
        # ★ 고른 모델이 지금 안 올라가 있으면 진행 메시지에 미리 알린다 — 첫 답이 20초쯤 늦는 까닭을 사람이 알게.
        note = say("model_loading", lang, alias=alias) if row is not None and row.get("loaded") is False else ""
        await self.adapter.on_processing_start(event)
        try:
            job_id = await self.backend.submit(text, self.sessions.session_id(key), model_alias=alias)
        except BackendError as exc:
            text = say("rejected", lang, error=exc.detail) if exc.kind == "rejected" else say(
                "unauthorized" if exc.kind == "unauthorized" else "offline", lang)
            await self.adapter.send(event.chat_id, text, reply_to=event.message_id or None)
            await self.adapter.on_processing_complete(event, False)
            return None
        self.sessions.set_active(key, job_id, event.user_id)
        progress = await self.adapter.send(event.chat_id, "⏳ " + (note or say("accepted", lang)),
                                           reply_to=event.message_id or None)
        progress_id = progress.message_id if progress.success else None
        ok: bool | None = False
        summary: dict[str, Any] | None = None
        try:
            job = await self._follow(event, job_id, progress_id, note=note)
            if job is None:
                await self.adapter.send(event.chat_id, say("lost", lang))
                return None
            from ..delegation import summarize_job

            summary = summarize_job(job)
            raw = str(job.get("status") or "")
            ok = None if raw == "cancelled" else raw == "completed"
            if progress_id:
                label = say({"completed": "done_label", "cancelled": "cancelled_label"}.get(raw, "failed_label"), lang)
                steps = int(summary.get("steps") or 0)
                mark = {"completed": "✅", "cancelled": "⏹"}.get(raw, "❌")
                await self.adapter.edit_message(event.chat_id, progress_id,
                                                f"{mark} {label}" + (f" · {say('step', lang, n=steps)}" if steps else ""))
            await self._deliver(event, job, summary)
            return summary
        finally:
            self.sessions.clear_active(key, job_id)
            await self.adapter.on_processing_complete(event, ok)

    async def _follow(self, event: MessageEvent, job_id: str, progress_id: str | None, *,
                      note: str = "") -> dict[str, Any] | None:
        """끝날 때까지 물어본다. 입력 중 표시 · 진행 메시지 고쳐 쓰기 · 기다림 알림. 연결을 잃으면 None."""
        lang = event.lang
        waits = _Waits()
        last_label: str | None = None
        last_typing = float("-inf")
        offline = 0
        while True:
            now = self._clock()
            if now - last_typing >= self.typing_every:
                await self.adapter.send_typing(event.chat_id)
                last_typing = now
            try:
                job = await self.backend.job(job_id)
                offline = 0
            except BackendError as exc:
                if exc.kind == "not_found":
                    return None
                offline += 1
                if offline >= self._max_offline:
                    return None
                await self._sleep(self.poll_sec)
                continue
            status = str(job.get("status") or "")
            if status in TERMINAL:
                return job
            if status == "waiting_approval":
                if not waits.approval:
                    waits.approval = True
                    await self.adapter.send(event.chat_id, await self._approval_text(job_id, lang))
            elif status == "waiting_continuation":
                if not waits.person:
                    waits.person = True
                    await self.adapter.send(event.chat_id, say("waiting_person", lang))
            else:
                # 기다림이 풀렸다 — 다음 기다림은 다시 알린다(승인이 두 번 걸리는 판).
                waits = _Waits()
            label = await self._label(job, job_id, lang)
            if note and label in (say("working", lang), say("queued", lang)):
                label = note   # 모델을 올리는 동안은 「지금 하는 일」이 아직 없다 — 올리는 중이라는 말을 그대로 둔다
            elif note and label != say("waiting_short", lang):
                note = ""      # 첫 걸음이 보이면 그 뒤로는 평소처럼
            if progress_id and label != last_label:
                await self.adapter.edit_message(event.chat_id, progress_id, f"⏳ {label}")
                last_label = label
            await self._sleep(self.poll_sec)

    async def _approval_text(self, job_id: str, lang: str) -> str:
        """「PC 앱에서 승인을 기다린다」. 질문 카드면 질문만 옮긴다 — 선택은 PC 앱에서."""
        text = say("waiting_approval", lang)
        pending = await self.backend.pending_approval(job_id)
        target = (pending or {}).get("target") if (pending or {}).get("tool_name") == "ask_user" else None
        if isinstance(target, dict) and target.get("question"):
            text += "\n" + say("waiting_question", lang, question=REDACTOR.redact(str(target["question"]))[:500])
        return text

    async def _label(self, job: dict[str, Any], job_id: str, lang: str) -> str:
        status = str(job.get("status") or "")
        if status == "queued":
            return say("queued", lang)
        if status in ("waiting_approval", "waiting_continuation"):
            return say("waiting_short", lang)
        live = await self.backend.live(job_id) or {}
        doing = str(live.get("doing") or "").strip()
        if not doing:
            steps = ((job.get("result") or {}).get("agent_trace") or {}).get("steps") or []
            doing = str((steps[-1] or {}).get("tool") or "") if steps and isinstance(steps[-1], dict) else ""
        try:
            step = int(live.get("step") or 0)
        except (TypeError, ValueError):
            step = 0
        label = doing or say("working", lang)
        return (label + (f" · {say('step', lang, n=step)}" if step else ""))[:300]

    async def _deliver(self, event: MessageEvent, job: dict[str, Any], summary: dict[str, Any]) -> None:
        lang = event.lang
        raw = str(job.get("status") or "")
        if raw == "completed":
            body = str(summary.get("answer") or "").strip() or say("empty_answer", lang)
        elif raw == "cancelled":
            body = say("cancelled", lang)
        else:
            body = say("failed", lang, error=str(summary.get("error") or job.get("error") or "")[:300] or "-")
        # ★ 디스코드에는 하네스 경고 · 대조표 · 영수증을 싣지 않는다 (2026-10-18 대표). 「하이」 답 밑에 「⚠ 이번 답은 도구를
        #   쓰지 않고 쓴 답입니다」와 「출처 0곳 · Discord 에게 보냄 · 정제 0」이 붙었다. 경고는 답 본문이 아니라 PC 앱의 옆 판에서
        #   본다(10-13 결정) — 디스코드에는 옆 판이 없으니 싣지 않는다. 확인할 거리는 PC 앱 기록에 그대로 남는다.
        if raw == "completed":
            body = without_our_tail(body) or body
        text = REDACTOR.redact(body)
        for chunk in self.adapter.split_message(text, lang):
            await self.adapter.send(event.chat_id, chunk)
        started = float(job.get("started_at") or job.get("created_at") or 0)
        for path in list(summary.get("files") or [])[:MAX_FILES]:
            await self._attach(event, str(path), started)
        if raw == "completed":
            await self._attach_showcase(event, job, started)

    async def _attach_showcase(self, event: MessageEvent, job: dict[str, Any], started_at: float) -> None:
        """답이 실제로 기댄 페이지 사진(대표사진)을 많아야 두 장 붙인다 (2026-10-18 대표 결정).

        사진은 바깥 사본(`outbound.showcase_for_outside`)이 이미 거른 것만 온다 — 개인 연락처 · 로그인 · 결제 화면은 빠져 있다.
        ★ 그래도 로그인한 크롬이라 페이지 맨 위 띠에 「○○님」 같은 이름이 찍힐 수 있다 — 보내기 전에 위 120픽셀을 잘라 낸다.
        """
        shots = list(((job.get("result") or {}).get("showcase")) or [])[:2]
        for shot in shots:
            source = Path(str((shot or {}).get("path") or ""))
            try:
                if not source.is_file() or (started_at and source.stat().st_mtime < started_at - 120):
                    continue
                cropped = _without_top_band(source)
            except Exception as exc:  # noqa: BLE001 — 사진은 덤이다. 못 붙여도 답은 이미 갔다.
                log.warning("대표사진을 준비하지 못했습니다: %s", REDACTOR.redact(exc))
                continue
            caption = say("showcase_caption", event.lang, title=str(shot.get("title") or "")[:120],
                          url=str(shot.get("url") or "")[:300])
            result = await self.adapter.send_document(event.chat_id, str(cropped), caption=REDACTOR.redact(caption),
                                                      file_name=cropped.name)
            if not result.success:
                log.warning("대표사진 올리기 실패: %s", REDACTOR.redact(result.error or ""))

    async def _attach(self, event: MessageEvent, path: str, started_at: float) -> None:
        """결과 파일을 디스코드에 그대로 올린다 — 올리기 **전에** 크기를 잰다(한도를 넘으면 올리지 않고 알린다)."""
        lang = event.lang
        file = Path(path)
        name = file.name or path
        try:
            stat = file.stat()
        except OSError:
            await self.adapter.send(event.chat_id, say("file_missing", lang, name=name))
            return
        if not file.is_file():
            return
        # ★ 이 판이 만든(또는 고친) 파일만 — 판보다 한참 오래된 파일이 결과 목록에 끼면 올리지 않는다.
        #   결과 목록은 쓰기 걸음에서 오지만, 걸음 기록을 그대로 믿고 PC 의 아무 파일이나 밖으로 내보내지 않는다.
        if started_at and stat.st_mtime < started_at - 120:
            log.warning("판보다 오래된 파일이라 올리지 않았습니다: %s", name)
            return
        limit = self.adapter.max_upload_bytes
        if stat.st_size > limit:
            await self.adapter.send(event.chat_id, say("file_too_big", lang, name=name, size_mb=stat.st_size / 1048576,
                                                       limit_mb=limit / 1048576))
            return
        result = await self.adapter.send_document(event.chat_id, str(file), file_name=name)
        if not result.success:
            await self.adapter.send(event.chat_id, say("file_failed", lang, name=name))
