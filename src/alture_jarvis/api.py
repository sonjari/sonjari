from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .config import JarvisConfig
from .outbound import outbound_job_view
from . import peer_guard
from . import ui_i18n
from .models import RiskLevel
from .runtime import JarvisRuntime
from .packs import PackError
from .unity_tools import is_unity_project


class ChatAttachment(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    mime_type: str = Field(default="application/octet-stream", max_length=120)
    data_base64: str = Field(default="", max_length=48_000_000)
    # 화면이 만든 작은 미리보기(data URL). 대화 기록에 남아 보낸 말 안에 그림으로 뜬다 — 원본은 기록에 안 남는다.
    thumbnail: str = Field(default="", max_length=400_000)
    width: int = Field(default=0, ge=0, le=100_000)
    height: int = Field(default=0, ge=0, le=100_000)


class UnityProjectRequest(BaseModel):
    path: str = Field(min_length=3, max_length=1024)


class SteerRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    # 모델이 읽을 인계문과 사람이 대화에서 볼 문장을 분리한다. 평소 채팅은 비워
    # 두며, Cowork 이어오기처럼 구조화된 내부 맥락이 길 때만 사용한다.
    display_prompt: str = Field(default="", max_length=500)
    # 이어오기 캡슐에서 사람이 고른 방향. 비어 있으면 평소 채팅이다. 있으면 계획 층이
    # 긴 인계문이 아니라 `display_prompt` + 방향 계약에서 요구를 뽑고, review·tasks 는
    # 읽기 전용으로 돈다(`takeover.handoff_contract`).
    handoff_direction: Literal["", "continue", "review", "tasks", "custom"] = ""
    # 빈 값 = "사용자가 지금 보고 있는 대화". 예전에는 화면마다 자기 기본값을 들고
    # 있어서(작은 HUD 는 "office-main") 같은 자비스가 두 개의 기억을 갖고 있었다.
    session_id: str = Field(default="", max_length=80)
    delivery: Literal["auto", "voice", "hybrid", "screen"] = "auto"
    speak: bool | None = Field(default=None, deprecated=True)
    # "workspace" marks a full-screen WorkspaceApp chat: the small HUD window
    # subscribes to the same broadcast socket and must not pop open for it.
    # `mcp` = 바깥 AI(Claude·Codex·Cursor)가 MCP 로 맡긴 일. 화면이 **자기가 안 만든 일**을 알아보고
    # 생각·진행을 그대로 보여 주기 위해 있다 — 이게 없으면 맡긴 일은 화면에서 통째로 안 보였다(2026-09-16).
    origin: Literal["chat", "voice", "workspace", "mcp"] = "chat"
    agent_mode: Literal["auto", "off", "browser"] = "auto"
    # 전체화면의 Cowork/Code는 모양만 다른 탭이 아니다. Code는 저장소를 먼저
    # 관찰하고 코드 역할 모델로 실행해야 하므로 요청 계약에 명시한다.
    workspace_mode: Literal["cowork", "code"] = "cowork"
    code_workspace: str = Field(default="", max_length=1000)
    # ★ 부르는 쪽이 **플레이북을 지목**한다 (2026-09-09).
    #
    #   낱말표는 하루에 세 번 샜다 — 「공고」 하나로 채용 스킬이 프리랜서 판에
    #   붙었고, 「경쟁 분석」은 트리거에 없어 안 붙었다. 클로드는 `skill_list` 로
    #   95종을 보고 고를 수 있고, 젬마도 고를 수 있다(실측 10판, 진짜 오답 0).
    #   지목이 있으면 그것을 쓰고, 없으면 지금처럼 추측한다.
    #
    #   모르는 이름은 조용히 무시한다 — 이름이 틀렸다고 판을 죽이지 않는다.
    skill: str = Field(default="", max_length=80)
    # 입력창의 「추론」 칩(2026-09-28). 비면 설정 「생각 깊이」를 따른다. auto = 보통으로 시작해 막히면 깊게.
    reasoning: Literal["", "auto", "fast", "normal", "deep"] = ""
    # 출처 도장의 「찾아보고 다시 답하기」(2026-09-30). 참이면 갈래를 추측하지 않고 에이전트로 가서,
    # 실제로 본 걸음이 있어야 답한다(`runtime.answer_grounding` 주석).
    observe: bool = False
    # 바깥 AI 가 맡긴 일이면 그 호스트 이름(MCP clientInfo) — 화면이 출처 색 이음선과 이름을 두른다(2026-09-30).
    caller: str = Field(default="", max_length=80)
    # ★ 바깥 AI 가 **코드 일**을 맡길 때의 칸 둘 (2026-10-09). 저장소(또는 그 안의 폴더)와, 끝을 가르는 확인 명령.
    #   서버가 그 저장소의 새 가지를 만들어 거기서 일하게 하고(`delegated_branch.prepare`), 과제 글에서 요구를 뽑는 대신
    #   그 명령으로 끝을 가른다. 폴더는 **이미 허락된 자리**여야 한다 — 바깥 AI 가 넘긴 경로로 범위를 넓히지 않는다.
    delegated_repo: str = Field(default="", max_length=1000)
    delegated_check: str = Field(default="", max_length=1000)
    # ★ 바깥 AI 가 밝힌 「돌려받아야 할 것」(2026-10-15 · 전략안 §55-32) — 끝난 판의 요약이 항목마다 채웠는지 확인하고,
    #   밝힌 연락처는 정제에서 뺀다(`outbound`). 잡에 그대로 남는다(payload).
    needs: list[str] = Field(default_factory=list, max_length=12)
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=6)
    # ★ 판이 끝나면 만든 파일을 **띄울지** (2026-09-13 사용자 요청).
    #
    #   벤치가 한 번 돌 때마다 워드·엑셀 창이 열다섯 개씩 떴다. 사람이 쓰는 PC 에서
    #   그러면 일을 못 한다. 벤치는 파일이 **만들어졌는지**만 알면 되고, 그건
    #   결과의 경로와 채움 채점기로 이미 코드가 확인한다. 사람이 시킨 일은 지금처럼
    #   띄운다(기본 참) — 벤치가 끄고 들어온다.
    open_results: bool = True
    # ★ 판 하나만 다른 모델로 (2026-10-18 · 디스코드 「@빠른」 · `/모델`). **별명**만 받는다 — 본체가 별명 표
    #   (`model_aliases.py`)로 태그를 푼다. 바깥이 아무 태그나 넘겨 모델을 올리게 하는 길은 열지 않는다.
    model_alias: str = Field(default="", max_length=12)


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default="office-main", min_length=1, max_length=80)
    source: str = "naver_web"
    max_results: int = Field(default=5, ge=1, le=20)
    delivery: Literal["auto", "voice", "hybrid", "screen"] = "auto"
    speak: bool | None = Field(default=None, deprecated=True)


class VisionRequest(BaseModel):
    prompt: str = "이 사무실 화면에서 보이는 상황을 간단히 설명해줘."
    focus: str = "사용자가 요청한 현재 사무실 장면"
    session_id: str = Field(default="office-main", min_length=1, max_length=80)
    delivery: Literal["auto", "voice", "hybrid", "screen"] = "auto"
    speak: bool | None = Field(default=None, deprecated=True)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    play: bool = True


class ToolRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class NewPersonRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class ApprovalDecision(BaseModel):
    approve: bool
    #: 질문 카드(`ask_user`)에서 고른 선택지 또는 직접 적은 말. 승인 카드에는 없다.
    answer: str | None = Field(default=None, max_length=2000)


class ForgetFactRequest(BaseModel):
    """★ 모듈 수준에 둔다 (2026-09-16 밤 실측).

    `create_app` **안에서** 선언했더니 `from __future__ import annotations` 때문에 FastAPI 가 타입을
    못 풀어 본문 대신 `?request=` 쿼리로 읽었다. 그래서 「기억에 직접 넣기」·「잊기」가 **모든 요청을
    422 로 거절**했다 — 사람이 기억을 고치는 유일한 문이 조용히 닫혀 있었다.
    """

    fact_id: int = Field(ge=1)


class LearnFactRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    subject: str = Field(min_length=1, max_length=120)
    fact: str = Field(min_length=1, max_length=200)


class ContinuationDecision(BaseModel):
    action: Literal["extend_3m", "continue_task", "finish"]


class GenericJobRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "L0"


class ScheduleRequest(BaseModel):
    title: str = Field(default="예약 작업", min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=12000)
    run_at: str | float | None = None
    delay_minutes: float | None = Field(default=None, gt=0, le=525600)
    session_id: str = Field(default="office-main", min_length=1, max_length=80)
    # ★ 2026-08-21: 스케줄러와 `schedule_create` 도구는 이 둘을 진작 받고 있었는데
    #   **이 모델만 안 따라왔다.** 그래서 HTTP 로는 반복 예약도, 메일 배달도 만들
    #   수가 없었다 — 기능은 있는데 문이 하나 잠겨 있던 셈이다.
    #
    #   같은 모양을 이 저장소가 여러 번 겪었다(도구는 만들었는데 카탈로그에 없음,
    #   갈래가 없음, 분류표에 없음). **새 인자를 만들면 그것을 받는 문을 전부 세어라.**
    repeat_every: str = Field(default="none", max_length=16)
    deliver_to: str | list[str] = Field(default="")


class PresenceRequest(BaseModel):
    # 전체화면 워크스페이스가 지금 보고 있는 대화. 빈 값이면 "화면은 떠 있지만 아직
    # 어느 대화인지 모른다"는 뜻이라, 음성 답변은 지금까지처럼 팝업으로 간다.
    session_id: str = Field(default="", max_length=80)
    # 어느 **모드**로 보고 있는가. 말로 시킨 것도 같은 모드로 가야 한다 — 이게 없어서
    # Code 탭에서 말한 판이 cowork 로 돌았다(2026-08-28 실측: 말한 판 3/3 타임아웃,
    # 같은 탭에서 타이핑한 판 3/3 완료).
    workspace_mode: Literal["", "cowork", "code"] = ""
    code_workspace: str = Field(default="", max_length=1000)


class PttRequest(BaseModel):
    # 비워 둘 수 있다. F9 단축키는 본문 없이 부르고, 그때는 워크스페이스가 마지막으로
    # 알려준 대화를 이어 쓴다.
    session_id: str = Field(default="", max_length=80)


def create_app(config: JarvisConfig | None = None, *, start_services: bool = True) -> FastAPI:
    runtime = JarvisRuntime(config)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if start_services:
            runtime.start()
        yield
        if start_services:
            runtime.stop()

    app = FastAPI(
        title="Sonjari Local Backend",
        version="0.1.0",
        lifespan=lifespan,
    )
    # The packaged Tauri WebView uses a local custom-protocol origin. JSON
    # mutations carry X-JARVIS-TOKEN and therefore require a browser CORS
    # preflight even though the API itself only listens on loopback.
    # ── 누가 닿을 수 있나 ────────────────────────────────────────────────────
    #
    # 이 API 로 들어오면 도구를 실행하고, 브라우저를 몰고, 메일을 보낸다.
    # 그래서 바인딩을 넓히더라도(위성 갱신 때문에 넓혀야 한다) **주소로 한 번 더**
    # 거른다. 방화벽은 사람이 지우고 윈도우가 초기화하지만, 이건 코드에 박혀 있다.
    #
    # 인증이 아니다 — 인증은 토큰이 한다. 이건 **여는 범위**다. 둘 다 있어야 한다.
    extra_allowed = tuple(
        part.strip()
        for part in str(getattr(runtime.config, "api_extra_allowed_cidrs", "") or "").split(",")
        if part.strip()
    )
    if extra_allowed:
        # 뜰 때 한 번 읽어 본다. 오타면 여기서 죽는 편이, 갱신하려다 막히는 것보다 낫다.
        peer_guard.parse_networks(extra_allowed)

    @app.middleware("http")
    async def only_from_home(request: Request, call_next):  # type: ignore[no-untyped-def]
        client = request.client.host if request.client else ""
        if not peer_guard.is_allowed(client, extra_allowed):
            return JSONResponse({"detail": peer_guard.refusal(client)}, status_code=403)
        return await call_next(request)

    # ── 화면 언어 (2026-10-02 영어판 2단계) ─────────────────────────────────
    # 백엔드는 한국어로 만들고 저장한다. 화면이 영어면 **나가는 순간** 사전으로 바꾼다(ui_i18n). JSON 만 —
    # 파일·그림·스트림은 그대로 지나간다.
    ui_i18n.configure(Path(runtime.config.data_dir) / "ui_language.json")

    @app.middleware("http")
    async def ui_language_out(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        if ui_i18n.lang() != "en" or not response.headers.get("content-type", "").startswith("application/json"):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
        headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
        try:
            data = json.loads(body)
        except ValueError:
            return Response(content=body, status_code=response.status_code, headers=headers)
        return JSONResponse(ui_i18n.translate_payload(data), status_code=response.status_code, headers=headers)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://tauri.localhost",
            "https://tauri.localhost",
            "tauri://localhost",
            "http://127.0.0.1:1420",
            "http://localhost:1420",
        ],
        allow_credentials=False,
        # ★ 2026-09-18: PATCH·DELETE 가 빠져 포장 앱에서 설정 저장·사람 잊기가 통째로 죽어 있었다
        #   (사전 확인에서 막혀 요청이 안 나감 — 서버 로그에도 안 남음). 라우트 메서드는 시험이 전부 찌른다.
        # ★ 2026-10-18: PUT 을 더했다(`/v1/models/aliases` · `/v1/discord/settings`). 빠지면 포장 앱에서 사전 확인에 막힌다.
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-JARVIS-TOKEN"],
        # ★ 이걸 안 적으면 화면이 **자기 앞에 온 헤더를 못 읽는다.** CORS 는 기본으로
        # 몇 가지 표준 헤더만 통과시키고 나머지는 브라우저가 가린다 — 응답은 멀쩡히
        # 도착했는데 자바스크립트에서는 null 이다. 라이브 화면(R2)이 "왜 못 찍었나"를
        # 여기로 나르므로, 빠지면 빈 화면이 이유를 말할 수 없게 된다.
        expose_headers=[
            "X-Jarvis-Frame-Url", "X-Jarvis-Frame-Title", "X-Jarvis-Frame-Age",
            "X-Jarvis-Frame-Fresh", "X-Jarvis-Frame-Reason",
            # ★ 브라우저 무대(2026-09-24). 빠지면 화면이 스트림 상태·넘겨받기를 **못 읽어** 늘 예전 스크린샷으로 떨어진다 —
            #   포장 앱은 화면(tauri.localhost)과 백엔드(127.0.0.1)가 달라 여기 적힌 헤더만 보인다. 시험이 목록을 대조한다.
            "X-Live-Status", "X-Live-Control", "X-Live-Release-In", "X-Live-Seq",
            "X-Live-Width", "X-Live-Height", "X-Live-Url",
            # 유니티 무대(2026-09-27). 빠지니 최소화된 창을 「받는 중…」으로 영원히 기다렸다(같은 함정, 개발 화면에서 실측).
            "X-Stage-Problem", "X-Stage-Seq", "X-Stage-Width", "X-Stage-Height", "X-Stage-Title",
        ],
    )
    app.state.jarvis = runtime

    def require_token(x_jarvis_token: str = Header(default="")) -> None:
        if not runtime.config.control_token or x_jarvis_token != runtime.config.control_token:
            raise HTTPException(status_code=401, detail="invalid_control_token")

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "service": "alture-jarvis",
            "version": "0.1.0",
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health")
    def health() -> dict[str, Any]:
        return runtime.health()

    @app.get("/v1/config")
    def public_config() -> dict[str, Any]:
        return runtime.config.public_dict()

    @app.get("/v1/state")
    def state() -> dict[str, Any]:
        # Reconcile first: this is what the HUD polls to resync after a dropped
        # socket, so it must never report a busy state no job can leave.
        runtime.reconcile_state()
        snapshot = runtime.state.snapshot()
        return {
            "state": snapshot.state.value,
            "changed_at": snapshot.changed_at,
            "reason": snapshot.reason,
            "event_sequence": runtime.events.sequence,
            # 지금 말하면 답이 어디로 나오는지. 값이 있으면 전체화면, 비어 있으면 팝업.
            # 이걸 밖에서 볼 수 없으면 "답이 엉뚱한 데서 떴다"를 진단할 방법이 없다 —
            # 화면 두 개가 같은 방송을 듣고 각자 판단하던 것이 이번 증상의 뿌리였다.
            "workspace_session": runtime.workspace_session(),
        }

    @app.get("/v1/presentation/policy")
    def presentation_policy() -> dict[str, Any]:
        policy = runtime.presentation
        return {
            "default": "auto",
            "modes": ["voice", "hybrid", "screen"],
            "short_max_chars": policy.short_max_chars,
            "short_max_sentences": policy.short_max_sentences,
            "short_max_speech_sec": policy.short_max_speech_sec,
            "visual_triggers": [
                "analysis_or_research",
                "code",
                "table",
                "links",
                "multiple_sources",
                "long_list",
                "character_length",
                "sentence_count",
                "speech_duration",
            ],
        }

    @app.get("/v1/events")
    def events(after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        return [event.to_dict() for event in runtime.events.get_since(after, limit)]

    @app.get("/v1/jobs")
    def jobs(limit: int = 50, status: str = "", view: str = "full") -> list[dict[str, Any]]:
        # `view=summary` 는 목록용 — 답변 전문과 도구 걸음을 빼고 한 줄에 그릴 것만
        # 준다(`JobStore.list_job_summaries` 주석에 실측 근거). 기본값은 그대로
        # `full` 이라 이미 이 경로를 쓰는 벤치·스크립트는 아무것도 달라지지 않는다.
        if view == "summary":
            return runtime.store.list_job_summaries(limit, status)
        return runtime.store.list_jobs(limit, status)

    @app.get("/v1/jobs/{job_id}")
    def job(job_id: str, x_jarvis_token: str = Header(default="")) -> dict[str, Any]:
        found = runtime.store.get_job(job_id)
        if found is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        # ★ 바깥 AI 가 맡긴 일의 답은 **토큰 없이 읽으면 정제해서** 준다(2026-10-15 · `outbound.outbound_job_view`).
        #   MCP 연결 프로세스는 이 문을 토큰 없이 읽는다 — 옛 프로세스가 정제를 몰라도 여기서 걸린다. 화면은 토큰을 들고 읽어 원문을 본다.
        if not (runtime.config.control_token and x_jarvis_token == runtime.config.control_token):
            return outbound_job_view(found)
        return found

    # ── 그 걸음이 실제로 본 것 (2026-08-19) ──────────────────────────────────
    # 이벤트로 나가는 장부는 200자에서 잘린다(`agent._step_evidence`). 그건 옳은
    # 판단이지만 — 걸음마다 8,000자를 웹소켓으로 쏠 수는 없다 — 그 결과 화면은
    # 파일을 읽어도 **어느 파일인지조차** 몰랐다. 그래서 원문은 물어볼 때만 준다.
    #
    # 내용에 파일 본문이 그대로 실리므로 **토큰을 받는다.** 목록도 마찬가지다.
    # 지금 무엇을 하는 중인가 — MCP 호스트가 사용자에게 전할 진행(`live_progress.py`). 남은 시간 예측은 싣지 않는다.
    @app.get("/v1/jobs/{job_id}/live", dependencies=[Depends(require_token)])
    def job_live(job_id: str) -> dict[str, Any]:
        return runtime.live.snapshot(job_id)

    @app.get("/v1/jobs/{job_id}/steps", dependencies=[Depends(require_token)])
    def job_steps(job_id: str) -> dict[str, Any]:
        rows = runtime.observations.list_steps(job_id)
        return {"job_id": job_id, "count": len(rows), "items": rows}

    @app.get("/v1/jobs/{job_id}/steps/{step}", dependencies=[Depends(require_token)])
    def job_step(job_id: str, step: int) -> dict[str, Any]:
        found = runtime.observations.get(job_id, step)
        if found is None:
            # 잡이 오래돼 버려졌는지, 그 걸음이 없는지를 화면이 구별할 수 있어야
            # "안 보여 준다"와 "볼 것이 없다"를 다르게 말할 수 있다.
            known = runtime.observations.list_steps(job_id)
            raise HTTPException(
                status_code=404,
                detail="step_not_found" if known else "job_observations_expired",
            )
        return found

    # ── 그 작업이 만든 것 (R4) ───────────────────────────────────────────────
    # `outputs/` 에는 파일이 쌓이는데 목록 경로가 없었다. 자비스가 무언가를 만들어도
    # 사람이 손에 쥘 방법이 없었다 — 답변에 적힌 경로를 보고 탐색기를 직접 열어야 했다.
    @app.get("/v1/outputs", dependencies=[Depends(require_token)])
    def job_outputs(job_id: str) -> dict[str, Any]:
        try:
            return runtime.job_outputs(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/outputs/file", dependencies=[Depends(require_token)])
    def job_output_file(job_id: str, path: str) -> Response:
        # 경로를 인자로 받는다. 그러니 **장부에 있는가**와 **산출물 폴더 안인가**를
        # 둘 다 본다(`runtime.job_output_file`). 하나만 보면 각각 뚫린다.
        try:
            target = runtime.job_output_file(job_id, path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        suffix = target.suffix.lower()
        media = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf",
        }.get(suffix, "application/octet-stream")
        return Response(content=target.read_bytes(), media_type=media)

    # ★ 답이 기댄 페이지의 사진(대표사진 · 2026-10-18 대표 결정) — 손자리 앱 답 아래 출처 카드가 쓴다.
    #   사진은 `outputs/shots/<job>/` 에 있어 「만든 것」 장부(`/v1/outputs/file`)에 안 실린다(만든 것이 아니라 읽은 것이다).
    #   화면 CSP 가 `img-src 'self' data: blob:` 라 PC 경로를 `<img>` 로 못 연다 — 토큰을 들고 바이트를 받아 blob 으로 건다.
    #   경로는 **인자로 안 받는다**: 그 판 result.showcase 의 index 번째만, 그것도 그 판의 사진 자리(`showcase.shot_dir`) 안의
    #   jpg 만 준다. 기록이 고쳐졌거나 옛 판이 엉뚱한 경로를 들고 있어도 그 자리 밖은 안 나간다(경로 순회 막기).
    @app.get("/v1/jobs/{job_id}/showcase/{index}", dependencies=[Depends(require_token)])
    def job_showcase_shot(job_id: str, index: int) -> Response:
        from .showcase import shot_dir

        found = runtime.store.get_job(job_id)
        if found is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        shots = (found.get("result") or {}).get("showcase") if isinstance(found.get("result"), dict) else None
        if not isinstance(shots, list) or not 0 <= index < len(shots) or not isinstance(shots[index], dict):
            raise HTTPException(status_code=404, detail="showcase_not_found")
        raw = str(shots[index].get("path") or "")
        try:
            home = shot_dir(runtime.config.output_dir, job_id).resolve()
            target = Path(raw).resolve() if raw else None
        except (OSError, ValueError):
            target = None
        if (
            target is None
            or Path(job_id).name != job_id
            or not target.is_relative_to(home)
            or target.suffix.lower() not in {".jpg", ".jpeg"}
        ):
            raise HTTPException(status_code=404, detail="showcase_outside_shots")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="showcase_missing")
        # 끝난 판의 사진은 안 바뀐다 — 대화를 다시 열 때 또 받지 않게 이 창 안에서는 잡아 둔다.
        return Response(content=target.read_bytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})

    # ★ 만든 파일을 **이 PC 의 기본 앱**으로 연다 (2026-09-17). 화면의 blob 새 창은 데스크톱 앱에서 막혔다.
    #   이 PC 에서 온 요청만 연다 — 위성·다른 기기가 부르면 **그 사람 화면이 아니라 이 PC** 에 창이 뜬다.
    # 「크롬 창 보기」 버튼 — **사람이 눌렀을 때만** 뒤에 떠 있는 창을 앞으로(2026-09-18). 온텔릭 스스로는 앞으로 안 올린다.
    @app.post("/v1/browser/show", dependencies=[Depends(require_token)])
    def browser_show(request: Request) -> dict[str, Any]:
        client = request.client.host if request.client else ""
        if client not in {"127.0.0.1", "::1", "localhost"}:
            return {"ok": False, "error": "not_this_pc"}
        return runtime.browser.present_for_human(activate=True)

    @app.post("/v1/outputs/open", dependencies=[Depends(require_token)])
    def job_output_open(body: dict[str, Any], request: Request) -> dict[str, Any]:
        client = request.client.host if request.client else ""
        if client not in {"127.0.0.1", "::1", "localhost"}:
            return {"ok": False, "error": "not_this_pc"}
        try:
            return runtime.open_job_output(str(body.get("job_id") or ""), str(body.get("path") or ""),
                                           reveal=bool(body.get("reveal")))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            return {"ok": False, "error": f"open_failed: {exc}"[:200]}

    # ★ 만든 문서를 **화면 안에서** 확인한다 (2026-09-01).
    #
    #   위의 `/file` 은 바이트를 준다. 그런데 hwpx·docx·xlsx 는 브라우저가 못
    #   그려서, 받아서 창에 띄우면 다운로드가 될 뿐이다 — 사용자가 본 그 화면이다
    #   ("미리보기도 안되고 아무것도 안되는데"). 여기서는 **글**을 준다.
    @app.get("/v1/outputs/preview", dependencies=[Depends(require_token)])
    def job_output_preview(job_id: str, path: str) -> dict[str, Any]:
        try:
            return runtime.job_output_preview(job_id, path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # ── 배운 것 (2026-08-24, P5) ─────────────────────────────────────────────
    #
    # ★ **사람이 볼 수 없는 기억은 고칠 수도 없다.**
    #
    # 자동 추출이 도는 순간부터 틀린 사실이 쌓인다. 틀린 사실은 영구적으로
    # 틀리고, 그것이 시스템 프롬프트에 매 턴 실려 간다. 그래서 목록과 지우기가
    # **추출과 같은 날** 있어야 한다.

    # (요청 모델 두 개는 모듈 위로 옮겼다 — `ForgetFactRequest` 주석 참고.)

    @app.get("/v1/memory/facts", dependencies=[Depends(require_token)])
    def list_facts() -> dict[str, Any]:
        """무엇을 배웠는지. **출처와 함께** 준다 — 근거 없이는 판단이 안 선다."""
        rows = runtime.memory.facts_with_sources(limit=300)
        block = runtime.memory.learned_block()
        return {
            "count": len(rows),
            "items": rows,
            # 이 중 무엇이 **매 턴 실려 가는지**도 알려 준다. 서랍에 있는 것과
            # 실제로 모델이 보는 것은 다르다(상한이 있다).
            "always_on_chars": len(block),
            "always_on_cap": runtime.memory.LEARNED_MAX_CHARS,
        }

    @app.post("/v1/memory/facts/forget", dependencies=[Depends(require_token)])
    def forget_fact(request: ForgetFactRequest) -> dict[str, Any]:
        """틀린 사실을 **덮는다.** 지우지 않는다 — 왜 바뀌었는지가 남아야 한다."""
        runtime.memory.supersede_fact(request.fact_id)
        runtime.events.publish("fact_forgotten", {"fact_id": request.fact_id})
        return {"ok": True, "forgotten": request.fact_id}

    @app.post("/v1/memory/facts", dependencies=[Depends(require_token)])
    def learn_fact(request: LearnFactRequest) -> dict[str, Any]:
        """사람이 직접 넣는다. 출처는 사람이다(`origin="manual"`)."""
        try:
            fact_id = runtime.memory.add_fact(
                kind=request.kind, subject=request.subject, fact=request.fact,
                source_message_id=0, origin="manual",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "fact_id": fact_id}

    # ── 위성 갱신 (2026-08-24) ───────────────────────────────────────────────
    #
    # 본체는 앞의 둘을 **내어 주고**, 위성은 뒤의 둘을 **부른다.** 같은 서버에
    # 넷이 다 있고 역할로 갈린다 — 두 벌로 나누면 반드시 어긋난다.
    #
    # 전부 토큰이 필요하다. 위성은 이미 본체 토큰을 갖고 있으므로 새 비밀이
    # 늘지 않는다(비밀이 하나 늘면 어긋날 자리가 하나 는다).

    @app.get("/v1/update/manifest", dependencies=[Depends(require_token)])
    def update_manifest() -> dict[str, Any]:
        return runtime.update_manifest()

    @app.get("/v1/update/payload", dependencies=[Depends(require_token)])
    def update_payload() -> Response:
        # ★ 매번 새로 만든다. 캐시하면 「본체는 새 코드인데 zip 은 어제 것」이
        #   되고, 위성에서는 **받고도 안 바뀌는** 모양으로 나타난다.
        try:
            path = runtime.update_payload_path()
        except RuntimeError as exc:
            if str(exc) == "private_update_disabled":
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise
        return Response(
            content=path.read_bytes(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="jarvis-update.zip"'},
        )

    @app.post("/v1/update/check", dependencies=[Depends(require_token)])
    def update_check() -> dict[str, Any]:
        """(위성) 받을 게 있나 물어만 본다. 아무것도 안 바꾼다."""
        return runtime.update_check()

    @app.post("/v1/update/apply", dependencies=[Depends(require_token)])
    def update_apply() -> dict[str, Any]:
        """(위성) 사람이 눌렀다. 받아서 확인하고 교체 스크립트를 띄운다.

        ★ 이 호출의 응답은 「시작했다」이지 「됐다」가 아니다. 이 프로세스가
          곧 죽기 때문에 여기서 성공을 말할 수가 없다. 성공은 재기동 뒤
          `/health` 의 `build` 로만 확인한다.
        """
        try:
            return runtime.update_apply()
        except Exception as exc:
            if str(exc) == "private_update_disabled":
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    # ── 되돌리기 (R4) ────────────────────────────────────────────────────────
    # `undo_list` · `undo_action` 도구는 **이미 있었다.** 모델만 부를 수 있었고
    # 화면에는 버튼이 없었다 — 사람이 "방금 거 취소해줘"라고 말로 해야 했다.
    @app.get("/v1/undo", dependencies=[Depends(require_token)])
    def list_undo() -> dict[str, Any]:
        rows = runtime.store.list_undo_offers()
        return {
            "count": len(rows),
            "items": [
                {
                    "undo_id": row["undo_id"],
                    "tool": row["tool"],
                    "job_id": row["job_id"],
                    "label": row["label"],
                    # 자비스가 못 되돌리는 것도 목록에 남는다. 그때는 사람이 할 일을
                    # `manual_hint` 가 말한다 — 버튼을 숨기면 그 말도 같이 사라진다.
                    "automatic": row["automatic"],
                    "manual_hint": row["manual_hint"],
                    "what": row["handle"],
                    "created_at": row["created_at"],
                    "expires_at": row["expires_at"],
                }
                for row in rows
            ],
        }

    @app.post("/v1/undo/{undo_id}", dependencies=[Depends(require_token)])
    def run_undo(undo_id: str) -> dict[str, Any]:
        # 승인을 다시 묻지 않는다. 되돌리기는 **원래 상태로 가는 방향**이고,
        # 무거운 되돌리기는 안 쓰인다(`ToolGateway.undo` 주석과 같은 판단).
        return runtime.gateway.undo(undo_id)

    @app.get("/v1/memory/{session_id}", dependencies=[Depends(require_token)])
    def memory(session_id: str) -> dict[str, Any]:
        return runtime.memory.inspect(session_id)

    @app.get("/v1/conversations", dependencies=[Depends(require_token)])
    def conversations(limit: int = 50) -> list[dict[str, Any]]:
        return runtime.memory.list_sessions(limit=limit)

    @app.delete("/v1/conversations/{session_id}", dependencies=[Depends(require_token)])
    def delete_conversation(session_id: str) -> dict[str, Any]:
        """대화 하나를 지운다(목록에서 사라진다). 사실 서랍은 그대로 둔다 — `MemoryStore.delete_session`."""
        removed = runtime.memory.delete_session(session_id)
        return {"ok": True, "session_id": session_id, "removed": removed}

    @app.get(
        "/v1/conversations/{session_id}/messages",
        dependencies=[Depends(require_token)],
    )
    def conversation_messages(session_id: str, limit: int = 200) -> dict[str, Any]:
        memory = runtime.memory.inspect(session_id)
        return {
            "session_id": memory["session_id"],
            "summary": memory["summary"],
            "has_summary": bool(memory["summary"]),
            "searchable_memory_count": memory["searchable_memory_count"],
            "context_window": runtime.config.ollama_num_ctx,
            "retrieval_enabled": runtime.config.memory_retrieval_enabled,
            "messages": runtime.memory.history(session_id, limit=limit),
        }

    @app.post("/v1/jobs", dependencies=[Depends(require_token)])
    def create_job(request: GenericJobRequest) -> dict[str, Any]:
        return runtime.enqueue(
            request.kind,
            request.title,
            request.payload,
            RiskLevel.parse(request.risk_level),
        )

    @app.get("/v1/ui-language", dependencies=[Depends(require_token)])
    def ui_language_get() -> dict[str, Any]:
        return {"lang": ui_i18n.lang()}

    @app.post("/v1/ui-language", dependencies=[Depends(require_token)])
    def ui_language_set(body: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"lang": ui_i18n.set_lang(str(body.get("lang") or ""))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/schedules", dependencies=[Depends(require_token)])
    def schedules(limit: int = 50, status: str = "") -> dict[str, Any]:
        return runtime.scheduler.list({"limit": limit, "status": status})

    @app.post("/v1/schedules", dependencies=[Depends(require_token)])
    def create_schedule(request: ScheduleRequest) -> dict[str, Any]:
        try:
            return runtime.scheduler.create(request.model_dump())
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/schedules/{schedule_id}/cancel", dependencies=[Depends(require_token)])
    def cancel_schedule(schedule_id: str) -> dict[str, Any]:
        try:
            return runtime.scheduler.cancel({"schedule_id": schedule_id})
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
    def cancel_job(job_id: str) -> dict[str, Any]:
        if not runtime.store.cancel(job_id):
            raise HTTPException(status_code=409, detail="job_not_cancellable")
        runtime.events.publish("job_cancelled", {"job_id": job_id})
        return {"ok": True, "job_id": job_id}

    @app.post("/v1/jobs/{job_id}/steer", dependencies=[Depends(require_token)])
    def steer_job(job_id: str, request: SteerRequest) -> dict[str, Any]:
        """돌고 있는 작업에 사람의 말을 덧붙인다 — 다음 걸음 앞에서 모델이 읽는다(2026-09-26).
        안 돌고 있으면 409 — 화면은 그 말을 새 작업으로 보낸다."""
        outcome = runtime.steer_job(job_id, request.text)
        if not outcome.get("ok"):
            raise HTTPException(status_code=409, detail=str(outcome.get("reason") or "job_not_running"))
        return outcome

    # ── 분야 팩 (0판, 2026-09-27 · 전략안 §50) ─────────────────────────────
    # 켜고 끄는 것은 **사람이 화면에서 누른 것**이 동의다(권한을 먼저 보여 준다). 모델에게 주는 도구가 아니다.
    def _packs_view(listing: dict[str, Any]) -> dict[str, Any]:
        # 직접 넣은 팩의 스킬 가운데 못 받은 것(이름이 겹침)도 「읽지 못한 팩」에 같이 보인다 — 조용히 빠지지 않게.
        return {**listing, "problems": [*listing.get("problems", []), *getattr(runtime.skills, "pack_problems", [])]}

    @app.get("/v1/packs", dependencies=[Depends(require_token)])
    def packs_list() -> dict[str, Any]:
        return _packs_view(runtime.packs.listing())

    # 사람이 스킬팩 폴더에 폴더를 넣거나 뺀 뒤 누른다(2026-10-11). 경로를 받지 않는다 — 읽는 자리는 정해져 있다.
    @app.post("/v1/packs/rescan", dependencies=[Depends(require_token)])
    def packs_rescan() -> dict[str, Any]:
        return _packs_view(runtime.packs.rescan())

    @app.post("/v1/packs/{pack_id}/{action}", dependencies=[Depends(require_token)])
    def packs_toggle(pack_id: str, action: str) -> dict[str, Any]:
        if action not in {"enable", "disable"}:
            raise HTTPException(status_code=404, detail="unknown_action")
        try:
            return runtime.packs.set_enabled(pack_id, action == "enable")
        except PackError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/packs/game/unity", dependencies=[Depends(require_token)])
    def unity_setup() -> dict[str, Any]:
        return runtime.unity_tools.setup_status()

    @app.post("/v1/packs/game/unity/project", dependencies=[Depends(require_token)])
    def unity_pick_project(request: UnityProjectRequest) -> dict[str, Any]:
        """사람이 **직접 고른** 유니티 프로젝트 폴더를 허락하고 기억한다(설정 › 권한의 「승인해 준 폴더」와 같은 장부)."""
        path = Path(request.path).expanduser()
        if not is_unity_project(path):
            raise HTTPException(status_code=400, detail="not_a_unity_project — ProjectSettings/ProjectVersion.txt 와 Assets 가 있는 폴더를 골라 주세요")
        try:
            runtime.local_computer.grant_path_by_person(str(path), "write")
        except (PermissionError, ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runtime.unity_tools.remember_project(path.resolve(strict=False))
        return runtime.unity_tools.setup_status()

    @app.post("/v1/packs/game/unity/hub", dependencies=[Depends(require_token)])
    def unity_open_hub() -> dict[str, Any]:
        return runtime.unity_tools.open_hub()

    # 클로드·코덱스가 짜서 돌려 본 **초안**. 레시피로 올리는 것은 사람만 — 이 화면의 단추가 그 자리다.
    @app.get("/v1/packs/game/unity/drafts", dependencies=[Depends(require_token)])
    def unity_drafts() -> dict[str, Any]:
        return {
            "drafts": runtime.unity_tools.drafts(), "recipes": sorted(runtime.unity_tools.recipes()),
            # 화면의 「바로 시킬 수 있는 점검」 — 이름 대신 제목·쉬운 한 줄·그대로 말하면 되는 문장.
            "recipe_cards": runtime.unity_tools.recipe_cards(),
        }

    @app.post("/v1/packs/game/unity/drafts/{name}/{action}", dependencies=[Depends(require_token)])
    def unity_draft_action(name: str, action: str) -> dict[str, Any]:
        try:
            if action == "promote":
                return runtime.unity_tools.promote_draft(name)
            if action == "discard":
                return runtime.unity_tools.discard_draft(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=404, detail="unknown_action")

    # ── 게임 팩 2단계: 열린 에디터 · 무대 · 정기 실행 (2026-09-27) ─────────────────────
    # 전부 **사람이 누르는** 문이다. 프로젝트에 다리를 잇고 풀기, 사용 기록을 원본에 같이 보내기, 정기 실행 만들기 —
    # 모델에게 주는 도구가 아니다(스스로 도는 일감·프로젝트 설정 변경은 사람의 동의).
    def _game_pack_on() -> None:
        if not runtime.packs.is_enabled("game"):
            raise HTTPException(status_code=409, detail="pack_disabled — 설정 › 팩에서 게임 팩을 먼저 켜 주세요")

    def _allowed_project(raw: Any) -> Path:
        try:
            return runtime.unity_tools._project({"project": str(raw or "")}, write=True)  # noqa: SLF001
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/packs/game/unity/editor", dependencies=[Depends(require_token)])
    def unity_editor_view() -> dict[str, Any]:
        _game_pack_on()
        return runtime.unity_tools.editor_view(stage=runtime.unity_stage)

    @app.post("/v1/packs/game/unity/editor/{action}", dependencies=[Depends(require_token)])
    def unity_editor_action(action: str, body: dict[str, Any]) -> dict[str, Any]:
        _game_pack_on()
        bridge = runtime.unity_tools.editor
        if action == "share":
            return bridge.set_share(bool(body.get("on")))
        if action in {"install", "uninstall"}:
            project = _allowed_project(body.get("project"))
            try:
                return bridge.install(project) if action == "install" else bridge.uninstall(project)
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc
        raise HTTPException(status_code=404, detail="unknown_action")

    # 유니티 창의 그림. 브라우저 무대처럼 **토큰이 있어야** 하고, 모델·기록으로 넘어가지 않는다.
    @app.get("/v1/packs/game/unity/stage", dependencies=[Depends(require_token)])
    def unity_stage_frame(after: int = 0, wait: float = 1.0, project: str = "") -> Response:
        _game_pack_on()
        frame = runtime.unity_stage.frame(after=after, wait=wait, project_hint=project)
        headers = {"Cache-Control": "no-store, max-age=0", "X-Stage-Problem": runtime.unity_stage.problem}
        if frame is None:
            return Response(status_code=204, headers=headers)
        headers.update({"X-Stage-Seq": str(frame["seq"]), "X-Stage-Width": str(frame["width"]),
                        "X-Stage-Height": str(frame["height"]), "X-Stage-Title": quote(str(frame.get("title") or "")[:300])})
        return Response(content=frame["jpeg"], media_type="image/jpeg", headers=headers)

    @app.post("/v1/packs/game/unity/stage/takeover", dependencies=[Depends(require_token)])
    def unity_stage_takeover(body: dict[str, Any]) -> dict[str, Any]:
        """「직접 하기」 — 사람이 누른 것만 유니티 창을 앞으로 가져온다."""
        _game_pack_on()
        return runtime.unity_stage.take_over(str(body.get("project") or ""))

    @app.get("/v1/packs/game/unity/schedules", dependencies=[Depends(require_token)])
    def unity_schedules() -> dict[str, Any]:
        return {"schedules": runtime.unity_schedule.listing()}

    @app.post("/v1/packs/game/unity/schedules", dependencies=[Depends(require_token)])
    def unity_schedule_add(body: dict[str, Any]) -> dict[str, Any]:
        _game_pack_on()
        try:
            return runtime.unity_schedule.add(body)
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/packs/game/unity/schedules/{schedule_id}/{action}", dependencies=[Depends(require_token)])
    def unity_schedule_action(schedule_id: str, action: str) -> dict[str, Any]:
        try:
            if action == "run":
                _game_pack_on()
                # 레시피는 수십 초 걸린다 — 화면을 붙잡지 않게 뒤에서 돌리고 목록을 다시 읽게 한다.
                threading.Thread(target=runtime.unity_schedule.run, args=(schedule_id,), daemon=True,
                                 name="ontelic-unity-schedule-now").start()
                return {"ok": True, "started": schedule_id}
            if action in {"enable", "disable"}:
                return runtime.unity_schedule.set_enabled(schedule_id, action == "enable")
            if action == "remove":
                return runtime.unity_schedule.remove(schedule_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=404, detail="unknown_action")

    @app.post("/v1/chat", dependencies=[Depends(require_token)])
    def chat(request: ChatRequest) -> dict[str, Any]:
        payload = request.model_dump()
        alias = request.model_alias.strip()
        if alias:
            tag = runtime.model_aliases.resolve(alias)
            if not tag:
                raise HTTPException(status_code=400, detail={"code": "unknown_model_alias", "alias": alias})
            payload["model_override"] = tag   # `runtime._chat_job` 이 이 판 동안만 `pin_model` 로 묶는다
        # 프로젝트 탐색은 대화 기억과 묶인다. 잡이 실행될 때가 아니라 접수 순간의
        # 대화를 확정해야, 사용자가 그 사이 다른 대화로 옮겨도 엉뚱한 저장소를 잇지 않는다.
        payload["session_id"] = runtime.resolve_session_id(payload.get("session_id", ""))
        if request.delegated_repo.strip() or request.delegated_check.strip():
            if request.origin != "mcp":
                raise HTTPException(status_code=400, detail={"code": "delegated_fields_need_a_delegated_job"})
            try:
                branch = runtime.prepare_delegated_code(request.delegated_repo.strip(), request.delegated_check.strip())
            except (ValueError, PermissionError, FileNotFoundError, NotADirectoryError) as exc:
                # 왜 못 받았는지를 맡긴 쪽이 읽고 고칠 수 있게 그대로 돌려준다(폴더가 허락 밖 · 저장소가 아님 · 그 명령은 못 돌림).
                raise HTTPException(status_code=400, detail={"code": "delegated_repo_refused", "reason": str(exc)[:600]}) from exc
            for key in ("delegated_repo", "delegated_check"):
                payload.pop(key, None)
            payload.update({
                "workspace_mode": "code", "code_workspace": branch["workspace"], "delegated": branch,
                "workspace_discovery": {"status": "resolved", "workspace": branch["workspace"], "confidence": 1.0,
                                        "source": "delegated_branch", "candidates": []},
            })
            return runtime.enqueue("chat", (request.display_prompt or request.prompt)[:80], payload)
        if request.workspace_mode == "code":
            workspace = request.code_workspace.strip()
            discovery: dict[str, Any] | None = None
            if not workspace:
                found = runtime.project_discovery.discover(
                    request.prompt, session_id=payload["session_id"]
                )
                discovery = found.to_dict()
                if found.status != "resolved":
                    raise HTTPException(
                        status_code=409,
                        detail={"code": "code_workspace_ambiguous", **discovery},
                    )
                workspace = found.workspace
            elif request.origin != "mcp":
                # ★ 사람이 **직접 고른** 폴더는 허락으로 받는다 (`admit_code_workspace` 주석).
                #   바깥 AI(MCP)가 넘긴 경로는 이 문으로 안 받는다 — 폴더를 넓히는 결정은 사람 몫이다.
                try:
                    runtime.local_computer.admit_code_workspace(workspace)
                except (ValueError, PermissionError, FileNotFoundError) as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            try:
                root = runtime.local_computer.resolve_allowed_path(
                    workspace, must_exist=True
                )
            except (ValueError, PermissionError, FileNotFoundError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not root.is_dir():
                raise HTTPException(status_code=400, detail="code_workspace_must_be_directory")
            # 모델이 UI 문자열을 재해석하지 않게 검증·정규화된 절대경로만 잡에 넣는다.
            payload["code_workspace"] = str(root)
            payload["workspace_discovery"] = discovery or {
                "status": "resolved", "workspace": str(root),
                "confidence": 1.0, "source": "explicit", "candidates": [],
            }
            runtime.project_discovery.remember(payload["session_id"], str(root))
        return runtime.enqueue("chat", (request.display_prompt or request.prompt)[:80], payload)

    @app.get("/v1/code/workspaces/discover", dependencies=[Depends(require_token)])
    def discover_code_workspace(query: str = "", session_id: str = "") -> dict[str, Any]:
        """UI와 평가기가 자동 선정의 후보·근거를 같은 계약으로 확인한다."""
        resolved_session = runtime.resolve_session_id(session_id)
        return runtime.project_discovery.discover(
            query, session_id=resolved_session
        ).to_dict()

    @app.post("/v1/thinking/translate", dependencies=[Depends(require_token)])
    def thinking_translate(body: dict[str, Any]) -> dict[str, Any]:
        """판이 끝난 생각 원문을 한국어로 (인수인계 H3). **일하는 중이면 거절한다** — 번역 때문에 일이 늦어지면 고장이다."""
        from .thinking_ko import translate_after

        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="text_required")
        if runtime.store.has_live_work():
            raise HTTPException(status_code=409, detail="busy")
        role = "code" if str(body.get("mode") or "") == "code" else "chat"

        def ask(prompt: str) -> str:
            return str(runtime.ollama.chat_message(prompt, role=role, think=False, temperature=0.1).get("content") or "")

        return {"ok": True, "text": translate_after(text, ask)}

    @app.post("/v1/research", dependencies=[Depends(require_token)])
    def research(request: ResearchRequest) -> dict[str, Any]:
        return runtime.enqueue("research", request.query[:80], request.model_dump())

    @app.post("/v1/vision/describe", dependencies=[Depends(require_token)])
    def describe(request: VisionRequest) -> dict[str, Any]:
        return runtime.enqueue("vision_describe", "카메라 장면 분석", request.model_dump())

    @app.get("/v1/vision/status")
    def vision_status() -> dict[str, Any]:
        return runtime.vision.status()

    @app.get("/v1/browser/status")
    def browser_status() -> dict[str, Any]:
        return runtime.browser.status()

    # 자비스가 보는 화면 한 장 (R2). **읽기 전용이고, 브라우저를 띄우지 않는다.**
    #
    # 화면이 당겨 간다 — 미는 쪽이 되면 아무도 안 볼 때도 프레임을 만들게 된다.
    # 캐시를 막는 이유: 1.5초마다 같은 주소를 부르므로 웹뷰가 한 장을 붙들면
    # 화면이 그대로 멈춘 것처럼 보인다(그리고 그게 제일 알아채기 어려운 고장이다).
    #
    # 못 찍었을 때 **왜 못 찍었는지**를 헤더로 같이 보낸다. 503 만 오면 화면은
    # "브라우저가 없다"밖에 말할 수 없는데, 실제 이유는 안 떠 있음·붙기 실패·앞
    # 동작에 물림·회로 열림으로 다 다르고 사람이 할 일도 다르다.
    @app.get("/v1/browser/frame.jpg")
    def browser_frame() -> Response:
        frame = runtime.browser.live_frame()
        headers = {
            "Cache-Control": "no-store, max-age=0",
            "X-Jarvis-Frame-Url": str(frame.get("url") or "")[:900],
            "X-Jarvis-Frame-Age": f"{max(0.0, time.time() - float(frame.get('at') or 0)):.2f}",
            "X-Jarvis-Frame-Fresh": "1" if frame.get("fresh") else "0",
        }
        # 제목은 한글이 흔하다. 헤더는 latin-1 이라 그대로 실으면 응답이 깨진다.
        title = str(frame.get("title") or "")[:200]
        if title:
            headers["X-Jarvis-Frame-Title"] = quote(title)
        # 이유는 **그림이 있을 때도** 보낸다. 낡은 장을 주는 경우가 그렇다 —
        # 200 이 왔다고 새 화면이라는 뜻은 아니고, 왜 못 갱신했는지는 사람이 알아야 한다.
        reason = str(frame.get("reason") or "")[:300]
        if reason:
            headers["X-Jarvis-Frame-Reason"] = quote(reason)
        jpeg = frame.get("jpeg") or b""
        if not jpeg:
            headers.setdefault("X-Jarvis-Frame-Reason", quote("no_frame"))
            return Response(status_code=503, headers=headers)
        return Response(content=jpeg, media_type="image/jpeg", headers=headers)

    @app.post("/v1/browser/start", dependencies=[Depends(require_token)])
    def browser_start() -> dict[str, Any]:
        return runtime.browser.start()

    # ── 브라우저 무대 (2026-09-24) — 화면 밖 크롬을 온텔릭 창 안에서 보고 만진다(`live_view.py`) ──────────────
    # 스크린샷(frame.jpg)과 달리 **토큰이 있어야** 한다. 사람이 넘겨받은 화면(로그인 중)이 흐르는 길이다.
    @app.get("/v1/browser/live", dependencies=[Depends(require_token)])
    def browser_live(after: int = 0, wait: float = 1.0) -> Response:
        view = runtime.browser.live_view
        frame = view.frame(after=after, wait=wait)
        state = view.status()
        headers = {
            "Cache-Control": "no-store, max-age=0",
            "X-Live-Status": str(state.get("status") or ""),
            "X-Live-Control": "1" if state["control"]["active"] else "0",
            "X-Live-Release-In": f"{float(state['control'].get('idle_release_in') or 0):.0f}",
        }
        if frame is None:
            return Response(status_code=204, headers=headers)
        headers.update({
            "X-Live-Seq": str(frame["seq"]),
            "X-Live-Width": f"{float(frame.get('css_width') or 0):.0f}",
            "X-Live-Height": f"{float(frame.get('css_height') or 0):.0f}",
            "X-Live-Url": quote(str(frame.get("url") or "")[:900]),
        })
        return Response(content=frame["jpeg"], media_type="image/jpeg", headers=headers)

    @app.get("/v1/browser/live/status", dependencies=[Depends(require_token)])
    def browser_live_status() -> dict[str, Any]:
        return runtime.browser.live_view.status()

    @app.post("/v1/browser/live/input", dependencies=[Depends(require_token)])
    def browser_live_input(body: dict[str, Any]) -> dict[str, Any]:
        events = body.get("events") if isinstance(body.get("events"), list) else [body]
        results = [runtime.browser.live_view.input(item) for item in events[:64]]
        failed = [item for item in results if not item.get("ok")]
        picked = next((item["select"] for item in results if item.get("select")), None)
        return {"ok": not failed, "count": len(results), "errors": [item.get("error") for item in failed][:5],
                **({"select": picked} if picked else {})}

    # 3차(2026-09-26): 브라우저 틀 — 주소·탭·알림창·파일 고르기
    @app.get("/v1/browser/live/state", dependencies=[Depends(require_token)])
    def browser_live_state() -> dict[str, Any]:
        return runtime.browser.live_view.nav_state()

    @app.post("/v1/browser/live/nav", dependencies=[Depends(require_token)])
    def browser_live_nav(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.browser.live_view.navigate(str(body.get("action") or ""), str(body.get("url") or "")[:2000])

    @app.post("/v1/browser/live/tab", dependencies=[Depends(require_token)])
    def browser_live_tab(body: dict[str, Any]) -> dict[str, Any]:
        view = runtime.browser.live_view
        if str(body.get("action") or "") == "new":
            return view.new_tab(str(body.get("url") or "")[:2000])
        return view.switch_tab(str(body.get("id") or ""))

    @app.post("/v1/browser/live/dialog", dependencies=[Depends(require_token)])
    def browser_live_dialog(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.browser.live_view.answer_dialog(bool(body.get("accept")), str(body.get("text") or ""))

    @app.post("/v1/browser/live/files", dependencies=[Depends(require_token)])
    def browser_live_files(body: dict[str, Any]) -> dict[str, Any]:
        # 경로는 사람이 **온텔릭 파일 고르기 창**(Tauri `pick_upload_files`)에서 고른 것만 온다 — 화면이 경로를 지어내지 않는다.
        paths = body.get("paths") if isinstance(body.get("paths"), list) else []
        return runtime.browser.live_view.set_files([str(item) for item in paths])

    @app.post("/v1/browser/live/control", dependencies=[Depends(require_token)])
    def browser_live_control(body: dict[str, Any]) -> dict[str, Any]:
        view = runtime.browser.live_view
        if str(body.get("action") or "") == "take":
            return view.take_control()
        return view.release_control(str(body.get("reason") or "button")[:40])

    @app.post("/v1/browser/live/fit", dependencies=[Depends(require_token)])
    def browser_live_fit(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.browser.live_view.fit(body.get("width"), body.get("height"))

    @app.get("/v1/google/status", dependencies=[Depends(require_token)])
    def google_status(verify: bool = False) -> dict[str, Any]:
        return runtime.google.status(verify=verify)

    @app.post("/v1/google/oauth/start", dependencies=[Depends(require_token)])
    def google_oauth_start() -> dict[str, Any]:
        try:
            return runtime.google.start_oauth()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/google/picker/start", dependencies=[Depends(require_token)])
    def google_picker_start() -> dict[str, Any]:
        """드라이브에서 파일 고르기 (인수인계 H4) — 기본 브라우저에서 Google 이 고르는 화면을 띄운다."""
        try:
            return runtime.google.start_picker()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/google/picker/files", dependencies=[Depends(require_token)])
    def google_picker_files() -> dict[str, Any]:
        return {"files": runtime.google.picked_files()}

    @app.get("/v1/computer/status", dependencies=[Depends(require_token)])
    def computer_status() -> dict[str, Any]:
        return runtime.local_computer.status()

    @app.get("/v1/vision/snapshot.jpg")
    def vision_snapshot() -> Response:
        frame = runtime.vision.latest_jpeg()
        if not frame:
            raise HTTPException(status_code=503, detail="camera_frame_unavailable")
        return Response(content=frame, media_type="image/jpeg")

    @app.post("/v1/ui/presence", dependencies=[Depends(require_token)])
    def workspace_presence(request: PresenceRequest) -> dict[str, Any]:
        # 화면이 살아 있다는 것과 무엇을 보고 있는지를 주기적으로 알린다. 음성으로 시킨
        # 답이 전체화면에 붙을지 작은 팝업으로 뜰지가 이 한 줄에서 갈린다.
        return runtime.note_workspace_presence(
            request.session_id, request.workspace_mode, request.code_workspace
        )

    @app.post("/v1/voice/ptt/toggle", dependencies=[Depends(require_token)])
    def ptt_toggle(request: PttRequest | None = None) -> dict[str, Any]:
        # Preferred over start/stop: the runtime decides which one this press
        # means, so the caller can never disagree with the state machine.
        #
        # `session_id` is optional so the F9 hotkey (which sends no body) keeps
        # working; it inherits whichever conversation the workspace last named.
        return runtime.ptt_toggle(request.session_id if request else "")

    @app.get("/v1/voice/level", dependencies=[Depends(require_token)])
    def voice_level() -> dict[str, Any]:
        """듣는 동안 화면이 짧게 물어보는 소리 크기(0~1) — 「내 말을 듣고 있구나」 파형의 재료(2026-09-30)."""
        return runtime.recorder.level()

    @app.post("/v1/voice/ptt/start", dependencies=[Depends(require_token)])
    def ptt_start(request: PttRequest | None = None) -> dict[str, Any]:
        return runtime.ptt_start(request.session_id if request else "")

    @app.post("/v1/voice/ptt/stop", dependencies=[Depends(require_token)])
    def ptt_stop() -> dict[str, Any]:
        return runtime.ptt_stop()

    @app.post("/v1/tts", dependencies=[Depends(require_token)])
    def tts(request: TTSRequest) -> dict[str, Any]:
        return runtime.enqueue("tts", "F1 음성 합성", request.model_dump())

    @app.get("/v1/tools")
    def tools() -> list[dict[str, Any]]:
        return runtime.gateway.list_tools()

    # ── 할 수 있는 일 (R5) ───────────────────────────────────────────────────
    #
    # 도구 102개(L0 35 · L1 53 · L2 14)와 사이트 레시피와 아는 사이트가 전부 코드
    # 안에만 있었다. **쓸 수 있다는 걸 모르면 없는 기능과 같다.**
    #
    # 셋을 한 번에 주는 이유: 화면이 세 번 왕복할 이유가 없고, 세 목록은 같은 질문
    # ("자비스는 무엇을 할 수 있나")의 세 면이라 따로 낡으면 안 된다.
    # ── 첫 실행: 진단 · 모델 추천 · 받기 · 적용 (전략안 §43, P1·P2) ────────────────
    from .model_setup import SetupService

    setup_service = SetupService(
        runtime.config,
        publish=runtime.events.publish,
        patch_settings=runtime.settings.patch,
    )

    @app.get("/v1/setup/profile", dependencies=[Depends(require_token)])
    def setup_profile(fresh: bool = False) -> dict[str, Any]:
        return setup_service.profile(fresh=fresh)

    @app.get("/v1/setup/recommendation", dependencies=[Depends(require_token)])
    def setup_recommendation() -> dict[str, Any]:
        return setup_service.recommendation()

    @app.get("/v1/setup/models", dependencies=[Depends(require_token)])
    def setup_models() -> dict[str, Any]:
        return {**setup_service.models(), "source": runtime.config.model_source}

    @app.post("/v1/setup/benchmark", dependencies=[Depends(require_token)])
    def setup_benchmark(body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        return setup_service.benchmark(body.get("model_key"), body.get("num_ctx"))

    # ── 컨텍스트 상한 — 이 PC 에서 올려 보고 잰다 (2026-09-23) ─────────────────────
    # 마법사(처음 적용할 때)와 제품 화면(모델 고르개)이 같은 문을 쓴다. 재는 데 몇 분 걸려 뒤에서 돌고,
    # 칸마다 `setup_context_probe` 이벤트로 알린다. 끝나면 `setup_context_measured`.
    from .model_setup import read_ceilings

    context_probe: dict[str, Any] = {"thread": None}

    def _busy() -> bool:
        # 재는 동안 모델을 내렸다 올린다 — 도는 일이 있으면 그 일이 죽는다.
        return any(runtime.store.list_job_summaries(20, status) for status in ("running", "queued"))

    # ── 컨텍스트 감시 (2026-09-23 제품 요청) — 30분마다 **보기만** 한다(nvidia-smi 한 번, 모델은 안 건드림).
    #    모델 카드에 붙은 프로그램이 잴 때와 달라지면 `context_watch` 이벤트 → 화면이 모델 칩에 작은 점을 찍는다.
    from .context_watch import assess as _watch_assess

    context_watch_state: dict[str, Any] = {"last": None}
    context_watch_gate = threading.Lock()

    def _watch_first() -> dict[str, Any]:
        """감시 루프가 아직 한 번도 안 돌았을 때의 첫 값 — **한 번만** 재서 둔다.

        ★ 2026-10-07: 루프는 30분 뒤에야 처음 돈다. 그 전에는 `/v1/setup/context` 가 불릴 때마다 `nvidia-smi` 를 두 번씩 돌렸고
          (결과를 두지 않았다), 마법사는 컨텍스트 상한을 재는 동안 이 주소를 **1초마다** 부른다. 카드가 바쁘면 `nvidia-smi` 가
          느려져 호출이 겹쳐 쌓인다. 이미 재는 호출이 있으면 기다리지 않고 「모름」을 준다 — 다음 물음이 둔 값을 받는다.
        """
        if not context_watch_gate.acquire(blocking=False):
            return {"state": "unknown"}
        try:
            if context_watch_state["last"] is None:
                context_watch_state["last"] = _watch_now()
            return context_watch_state["last"]
        finally:
            context_watch_gate.release()

    def _watch_now() -> dict[str, Any]:
        record = read_ceilings(Path(runtime.config.data_dir)).get(runtime.config.model_for("chat")) or {}
        try:
            return _watch_assess(record, setup_service.gpu_snapshot())
        except Exception:  # noqa: BLE001 — 못 보면 「모름」이다. 판을 죽이지 않는다
            return {"state": "unknown"}

    def _watch_loop() -> None:
        interval = max(60, int(getattr(runtime.config, "context_watch_interval_sec", 1800) or 1800))
        while True:
            time.sleep(interval)
            seen = _watch_now()
            before = context_watch_state["last"] or {}
            context_watch_state["last"] = seen
            # 바뀐 순간에만 알린다 — 같은 말을 30분마다 반복하면 아무도 안 본다.
            if (seen.get("state"), seen.get("left"), seen.get("joined")) != (
                    before.get("state"), before.get("left"), before.get("joined")):
                runtime.events.publish("context_watch", seen)

    threading.Thread(target=_watch_loop, name="ontelic-context-watch", daemon=True).start()

    @app.get("/v1/setup/context", dependencies=[Depends(require_token)])
    def setup_context() -> dict[str, Any]:
        from .ollama_install import _read_owned, _read_user_context_length

        thread = context_probe["thread"]
        owned = _read_owned(Path(runtime.config.data_dir) / "ollama_env_owned.json")
        current_global = _read_user_context_length()
        watch = context_watch_state["last"] or _watch_first()
        return {
            "watch": watch,
            "chat_model": runtime.config.model_for("chat"),
            "num_ctx": runtime.config.ollama_num_ctx,
            "ceilings": read_ceilings(Path(runtime.config.data_dir)),
            "measuring": bool(thread is not None and thread.is_alive()),
            "live": setup_service.context_live,
            "global": {"value": current_global,
                       "ours": bool(current_global) and current_global == owned.get("OLLAMA_CONTEXT_LENGTH")},
        }

    @app.post("/v1/setup/context/measure", dependencies=[Depends(require_token)])
    def setup_context_measure(body: dict[str, Any] | None = None) -> dict[str, Any]:
        tag = str((body or {}).get("model") or "") or None
        thread = context_probe["thread"]
        if thread is not None and thread.is_alive():
            return {"ok": False, "error": "already_measuring"}
        if _busy():
            return {"ok": False, "error": "busy"}
        def _measure_then_rewatch() -> None:
            setup_service.measure_context_ceiling(tag, busy=_busy)
            context_watch_state["last"] = None  # 새 기준점이 생겼다 — 옛 「바뀌었다」를 들고 있지 않는다

        worker = threading.Thread(
            target=_measure_then_rewatch,
            name="ontelic-context-ceiling", daemon=True,
        )
        context_probe["thread"] = worker
        worker.start()
        return {"ok": True, "started": True}

    @app.post("/v1/setup/context/apply", dependencies=[Depends(require_token)])
    def setup_context_apply(body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        applied = setup_service.apply_context_ceiling(str(body.get("model") or "") or None,
                                                      int(body.get("num_ctx") or 0) or None)
        # ★ 2026-09-30 대표 스크린샷: 104K 를 적용했는데 머리 칩은 「32K」 — 칩이 맞았다. 올라가 있던 32K 러너가 설정보다
        #   작으면 그 크기를 그대로 쓰는 규칙(`_options`, 09-28 남의 앱 러너를 안 뺏으려고)이 **사람이 방금 고른 값**까지
        #   눌렀다. 패널은 「다음 요청에서 다시 올립니다」라고 약속했는데 영원히 32K 였다. 도는 일이 없으면 지금 새 크기로
        #   다시 올린다(창 크기가 다르면 Ollama 가 러너를 갈아 끼운다). 도는 일이 있으면 그 일을 끊지 않는다.
        if applied.get("ok") and not _busy():
            import threading as _threading

            _threading.Thread(target=setup_service._rewarm, args=(str(applied["model"]),),
                              name="setup-context-reload", daemon=True).start()
            applied = {**applied, "reloading": True}
        if not applied.get("ok") or not body.get("also_global"):
            return applied
        # 「다른 프로그램도 이 값으로」 — 사람이 체크했을 때만. Ollama 를 다시 켜므로 도는 일이 있으면 미룬다.
        if _busy():
            return {**applied, "global": {"ok": False, "error": "busy"}}
        done = runtime.ollama_installer.set_default_context(
            int(applied["num_ctx"]), owned_path=Path(runtime.config.data_dir) / "ollama_env_owned.json")
        if done.get("ok") and done.get("restarted") not in (None, "unchanged", "not_running"):
            # 다시 켠 Ollama 는 비어 있다 — 상한으로 한 번 올려 둔다(다음 대화가 기다리지 않게).
            setup_service.benchmark(None, int(applied["num_ctx"]))
        return {**applied, "global": done}

    @app.post("/v1/setup/models/pull", dependencies=[Depends(require_token)])
    def setup_pull(body: dict[str, Any]) -> dict[str, Any]:
        return setup_service.start_pull(str(body.get("model_key") or ""), int(body.get("apply_ctx") or 0))

    # ── 첫 실행 판정 (W2) — 앱이 이 파일이 없으면 마법사 창을 연다 ───────────────
    from . import setup_state

    @app.get("/v1/setup/state", dependencies=[Depends(require_token)])
    def setup_state_read() -> dict[str, Any]:
        return setup_state.read(runtime.config.data_dir)

    @app.post("/v1/setup/state", dependencies=[Depends(require_token)])
    def setup_state_write(body: dict[str, Any]) -> dict[str, Any]:
        steps = body.get("steps")
        return setup_state.write(runtime.config.data_dir,
                                 steps=[str(s) for s in steps] if isinstance(steps, list) else [],
                                 completed=bool(body.get("completed")))

    @app.post("/v1/setup/state/reset", dependencies=[Depends(require_token)])
    def setup_state_reset() -> dict[str, Any]:
        return setup_state.reset(runtime.config.data_dir)

    # ── Ollama 한 번 설치 (W2) ─────────────────────────────────────────────
    @app.get("/v1/setup/ollama", dependencies=[Depends(require_token)])
    def setup_ollama_status() -> dict[str, Any]:
        return runtime.ollama_installer.status()

    @app.post("/v1/setup/ollama/install", dependencies=[Depends(require_token)])
    def setup_ollama_install() -> dict[str, Any]:
        return runtime.ollama_installer.start_install()

    # 모델을 카드에 올리는 동안의 실측 진행률(2026-10-01, 헤르메스 비교에서 배움). 화면은 콜드 적재 중일 때만 2초마다 부른다 —
    # `/health` 에 넣지 않은 것은 워치독·점검 줄이 자주 부르는 곳에 nvidia-smi 를 매번 얹지 않기 위해서다.
    from .load_progress import LoadWatch

    load_watch = LoadWatch(Path(runtime.config.data_dir))

    @app.get("/v1/model/loading", dependencies=[Depends(require_token)])
    def model_loading() -> dict[str, Any]:
        health = runtime.ollama.health()
        if not health.get("ok"):
            return {"ok": False, "loading": False}
        return {"ok": True, "model": health.get("model"), **load_watch.observe(
            model=str(health.get("model") or ""), num_ctx=int(runtime.config.num_ctx_for("chat")),
            resident=bool(health.get("resident")), model_bytes=int(health.get("model_bytes") or 0),
        )}

    # 켤 때 돈 자가 점검의 결과 — 화면이 고장일 때만 한 줄 띄운다(2026-09-18). `run=1` 이면 지금 다시 본다.
    @app.get("/v1/self-check", dependencies=[Depends(require_token)])
    def self_check_status(run: int = 0) -> dict[str, Any]:
        if run:
            return runtime.self_care.boot_check(include_model=True, wait=False)
        return runtime.self_check_latest() or {"pending": True}

    # 화면의 「고치기」. 정해진 버튼만 누른다 — 고장일 때만, 고친 뒤 다시 읽는다(SelfCare.heal 규칙 그대로).
    @app.post("/v1/self-check/heal", dependencies=[Depends(require_token)])
    def self_check_heal(body: dict[str, Any]) -> dict[str, Any]:
        result = runtime.self_care.heal({"action": str(body.get("action") or "")})
        runtime.self_care.boot_check(include_model=True)
        return result

    @app.post("/v1/setup/ollama/repair", dependencies=[Depends(require_token)])
    def setup_ollama_repair() -> dict[str, Any]:
        """고장난 **우리** Ollama 를 끄고 새 자리로 옮겨 켠다(2026-09-18 노트북). 사람이 깐 Ollama 는 안 건드린다."""
        return runtime.ollama_installer.repair()

    @app.post("/v1/setup/ollama/gpu-only", dependencies=[Depends(require_token)])
    def setup_ollama_gpu_only() -> dict[str, Any]:
        """마법사가 모델을 받기·올리기 **전에** 부른다 — Ollama 가 NVIDIA 카드만 쓰게 맞춘다(권고 `fixes`)."""
        return runtime.ollama_installer.fix_gpu_selection()

    @app.post("/v1/setup/models/apply", dependencies=[Depends(require_token)])
    def setup_apply(body: dict[str, Any]) -> dict[str, Any]:
        # `eyes: false` — 그림 부속을 뺀 「글만 읽기」로 올린다. 안 주면 예전 그대로다.
        eyes = body.get("eyes")
        return setup_service.apply(str(body.get("model_key") or ""), int(body.get("num_ctx") or 0),
                                   eyes=eyes if isinstance(eyes, bool) else None)

    # ── 목록 밖 모델 (M3) — 이미 받은 모델 · 직접 입력 ─────────────────────────────
    @app.get("/v1/setup/models/installed", dependencies=[Depends(require_token)])
    def setup_installed_models() -> dict[str, Any]:
        return setup_service.installed_models()

    @app.post("/v1/setup/models/pull-tag", dependencies=[Depends(require_token)])
    def setup_pull_tag(body: dict[str, Any]) -> dict[str, Any]:
        # `eyes: false` — 다 받은 뒤 「글만 읽기」로 적용한다(목록 밖 모델도). 안 주면 예전 그대로다.
        eyes = body.get("eyes")
        return setup_service.start_pull_tag(str(body.get("tag") or ""), int(body.get("apply_ctx") or 0),
                                            "code" if body.get("role") == "code" else "chat",
                                            eyes=eyes if isinstance(eyes, bool) else None)

    # ── 허깅페이스에서 직접 고르기 (2026-10-01 밤) — 이 카드에 들어가는 GGUF·양자화를 사람이 고른다 ──────
    from .hf_catalog import HfCatalog

    # 이 PC 에서 잰 기록을 같이 넘긴다 — 화면이 「추천」 대신 「이 PC 실측」을 사실로 적게(2026-10-03).
    hf_catalog = HfCatalog(measured=lambda: read_ceilings(Path(runtime.config.data_dir)))

    def _usable(raw: Any) -> float:
        try:
            return max(0.0, min(float(raw or 0), 512.0))
        except (TypeError, ValueError):
            return 0.0

    @app.get("/v1/setup/hf/search", dependencies=[Depends(require_token)])
    def setup_hf_search(q: str = "", usable_gb: float = 0.0, sort: str = "downloads") -> dict[str, Any]:
        return hf_catalog.search(q, _usable(usable_gb), sort=sort)

    @app.get("/v1/setup/hf/files", dependencies=[Depends(require_token)])
    def setup_hf_files(repo: str = "", usable_gb: float = 0.0, ctx: int = 32768) -> dict[str, Any]:
        return hf_catalog.files(repo, _usable(usable_gb), ctx)

    @app.post("/v1/setup/models/apply-tag", dependencies=[Depends(require_token)])
    def setup_apply_tag(body: dict[str, Any]) -> dict[str, Any]:
        eyes = body.get("eyes")
        return setup_service.apply_tag(str(body.get("tag") or ""), int(body.get("num_ctx") or 32768),
                                       eyes=eyes if isinstance(eyes, bool) else None)

    # ── 머리의 모델 이름을 눌렀을 때 (2026-09-21) ──────────────────────────────
    # 카탈로그와 이 PC 의 Ollama 를 **한 번에** 합쳐서 준다. 역할(chat·code)마다 따로.
    # ── 권한 모드 (2026-09-21) — 토글 아홉 개 말고 손잡이 하나 ────────────────
    # 사장님: 「계속 눌러야 되는 게 귀찮네」. 모드는 **새 관문이 아니라** 기존 설정값을
    # 정하는 한 곳이다 — 관문이 둘이면 언젠가 갈리고 낮은 쪽만 일한다.
    from .permissions import change_mode, public_modes

    @app.get("/v1/permissions/mode", dependencies=[Depends(require_token)])
    def permission_mode() -> dict[str, Any]:
        return public_modes(runtime.config)

    @app.post("/v1/permissions/mode", dependencies=[Depends(require_token)])
    def set_permission_mode(body: dict[str, Any]) -> dict[str, Any]:
        # 저장과 적용은 다른 일이다 — 적용됐는지 읽어 보고 안 됐으면 `ok: False` 로 돌려준다.
        return change_mode(runtime.settings, runtime.config, str(body.get("mode") or ""))

    @app.get("/v1/setup/models/picker", dependencies=[Depends(require_token)])
    def setup_model_picker(role: str = "chat") -> dict[str, Any]:
        return setup_service.picker(role)

    @app.post("/v1/setup/models/select", dependencies=[Depends(require_token)])
    def setup_model_select(body: dict[str, Any]) -> dict[str, Any]:
        return setup_service.select(
            str(body.get("tag") or ""),
            str(body.get("role") or "chat"),
            int(body.get("num_ctx") or 0),
        )

    # ── 첫 실행: 다른 도구의 지침 가져오기 (전략안 §43, P4) ─────────────────────────
    # ★ 미리보기·넣기는 **경로가 아니라 후보 id** 만 받는다. 경로를 받으면 이 문이 곧
    #   「아무 파일이나 읽어 주는 API」가 된다. 후보는 `candidate_paths` 한 곳에서만 나온다.
    from .instruction_import import InstructionImportService

    import_service = InstructionImportService(runtime.config.database_path, publish=runtime.events.publish)

    def _str_list(value: Any) -> list[str]:
        return [str(v) for v in value] if isinstance(value, list) else []

    def _paste(value: Any) -> dict[str, Any] | None:
        return value if isinstance(value, dict) else None

    @app.get("/v1/setup/import/scan", dependencies=[Depends(require_token)])
    def setup_import_scan(project: str = "") -> dict[str, Any]:
        return import_service.scan(project)

    @app.post("/v1/setup/import/preview", dependencies=[Depends(require_token)])
    def setup_import_preview(body: dict[str, Any]) -> dict[str, Any]:
        return import_service.preview(
            str(body.get("project") or ""), _str_list(body.get("ids")), _paste(body.get("paste")),
            redact_contacts=bool(body.get("redact_contacts")),
        )

    @app.post("/v1/setup/import/commit", dependencies=[Depends(require_token)])
    def setup_import_commit(body: dict[str, Any]) -> dict[str, Any]:
        items = [i for i in body.get("items") or [] if isinstance(i, dict)]
        return import_service.commit(
            str(body.get("project") or ""), items, _paste(body.get("paste")),
            redact_contacts=bool(body.get("redact_contacts")),
        )

    @app.get("/v1/setup/import/list", dependencies=[Depends(require_token)])
    def setup_import_list() -> dict[str, Any]:
        return import_service.list()

    @app.post("/v1/setup/import/remove", dependencies=[Depends(require_token)])
    def setup_import_remove(body: dict[str, Any]) -> dict[str, Any]:
        try:
            import_id = int(body.get("import_id") or 0)
        except (TypeError, ValueError):
            import_id = 0
        return import_service.remove(import_id)

    # ── 「나에 대한 지침」 (2026-10-18) ───────────────────────────────────────────
    # ★ 매 턴 실리는 프로필 파일(`JARVIS_PROFILE.md`)은 있었는데 화면이 없었고, 지침 가져오기는 화면만 있고 아무 데도 안
    #   쓰였다(막다른 길). 둘을 이 파일 하나로 모은다 — 설명은 `about_me.py` 머리말. 경로는 받지 않는다(파일은 설정의 한 자리뿐).
    from .about_me import AboutMe

    about_me = AboutMe(runtime.config, runtime.profile, settings=runtime.settings, imports=import_service)

    def _lang(body: dict[str, Any]) -> str:
        return "en" if str(body.get("lang") or "") == "en" else "ko"

    @app.get("/v1/about-me", dependencies=[Depends(require_token)])
    def about_me_view() -> dict[str, Any]:
        return about_me.view()

    @app.put("/v1/about-me", dependencies=[Depends(require_token)])
    def about_me_save(body: dict[str, Any]) -> dict[str, Any]:
        content = body.get("content")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail="expected_content")
        return about_me.save(content)

    @app.post("/v1/about-me/card/preview", dependencies=[Depends(require_token)])
    def about_me_card_preview(body: dict[str, Any]) -> dict[str, Any]:
        return about_me.preview_card(body.get("answers"), _lang(body))

    @app.post("/v1/about-me/card", dependencies=[Depends(require_token)])
    def about_me_card_save(body: dict[str, Any]) -> dict[str, Any]:
        return about_me.save_card(body.get("answers"), _lang(body))

    @app.get("/v1/about-me/import-lines", dependencies=[Depends(require_token)])
    def about_me_import_lines(import_id: int) -> dict[str, Any]:
        return about_me.import_lines(import_id)

    @app.post("/v1/about-me/import-lines", dependencies=[Depends(require_token)])
    def about_me_append_import(body: dict[str, Any]) -> dict[str, Any]:
        try:
            import_id = int(body.get("import_id") or 0)
        except (TypeError, ValueError):
            import_id = 0
        return about_me.append_import(import_id, body.get("lines"))

    @app.post("/v1/about-me/open", dependencies=[Depends(require_token)])
    def about_me_open(request: Request) -> dict[str, Any]:
        """설정의 파일 **하나만** 연다(경로를 받지 않는다). 연결된 편집기가 없으면 메모장으로(`file_open`)."""
        import os

        client = request.client.host if request.client else ""
        if client not in {"127.0.0.1", "::1", "localhost"}:
            return {"ok": False, "error": "not_this_pc"}
        path = about_me.ensure_file()
        from .msix import external_path

        real = external_path(path)
        if os.name != "nt":
            return {"ok": False, "error": "not_windows", "path": str(real)}
        from .file_open import open_file

        open_file(real)
        return {"ok": True, "path": str(real)}

    # ── 첫 실행: 클로드·코덱스·커서에 잇기 (전략안 §43 P5) ─────────────────────────
    # ★ 다른 프로그램의 영구 설정을 바꾸는 문이다. 화면에서 사람이 눌러야 불린다.
    from .mcp_connect import ConnectService

    connect_service = ConnectService(runtime.config, exported_tools=lambda: _exported_tools(),
                                     pack_guides=lambda: _pack_guides(), guide_lang=ui_i18n.lang)
    # 지난번에 누른 「Claude Desktop 잇기」가 재부팅·재시작으로 끊겼으면 이어서 기다린다(mcp_connect.resume_pending).
    try:
        connect_service.resume_pending()
    except Exception:  # noqa: BLE001 — 연결 대기가 앱 기동을 막으면 안 된다
        pass

    @app.get("/v1/setup/connect/scan", dependencies=[Depends(require_token)])
    def setup_connect_scan() -> dict[str, Any]:
        return connect_service.scan()

    @app.post("/v1/setup/connect/apply", dependencies=[Depends(require_token)])
    def setup_connect_apply(body: dict[str, Any]) -> dict[str, Any]:
        return connect_service.apply(str(body.get("client") or ""))

    @app.post("/v1/setup/connect/restart-desktop", dependencies=[Depends(require_token)])
    def setup_connect_restart_desktop() -> dict[str, Any]:
        # 사람이 「다시 켤까요?」에 누른 뒤에만 화면이 부른다 — Claude Desktop 을 닫고 → 잇고 → 다시 켠다.
        return connect_service.restart_desktop()

    @app.post("/v1/setup/connect/remove", dependencies=[Depends(require_token)])
    def setup_connect_remove(body: dict[str, Any]) -> dict[str, Any]:
        return connect_service.remove(str(body.get("client") or ""))

    @app.post("/v1/setup/connect/verify", dependencies=[Depends(require_token)])
    def setup_connect_verify() -> dict[str, Any]:
        return connect_service.verify()

    @app.post("/v1/setup/connect/hook", dependencies=[Depends(require_token)])
    def setup_connect_hook(body: dict[str, Any]) -> dict[str, Any]:
        return connect_service.set_hook(bool(body.get("enabled")))

    # ── 가이드 스킬 (인수인계 H1-b) ─────────────────────────────────────────
    # 도구 표는 MCP 로 **실제 내보내는** 목록에서 뽑는다 — 같은 거름망·같은 위임 문.
    from .delegation import DELEGATION_TOOLS, GUIDE_TOOL
    from .guide_skill import GuideSkillService
    from .mcp_server import ToolFilter, lean_toolset

    def _pack_guides() -> list[dict[str, Any]]:
        # 켜진 팩 중 바깥 AI 용 사용서가 있는 것. 부를 때마다 읽는다 — 켜고 끄는 것이 곧바로 반영되게.
        rows: list[dict[str, Any]] = []
        for pack in runtime.packs.enabled():
            path = pack.guide_path
            if path is not None:
                rows.append({"id": pack.id, "name": pack.name, "text": path.read_text(encoding="utf-8")})
        return rows

    # 가이드 본문은 화면 언어를 따른다(2026-10-19) — 영어 화면이면 클로드·코덱스도 영어 가이드를 읽고 영어로 맡긴다.
    guide_skill = GuideSkillService(pack_guides=_pack_guides, lang=ui_i18n.lang)

    def _refresh_pack_guides() -> None:
        # ★ 게임 팩을 켜면 이미 이어 둔 클로드·코덱스의 지침에 「게임 일이면 이 사용서」가 저절로 들어간다(끄면 빠진다).
        #   잇지 않은 클라이언트에는 아무것도 새로 만들지 않는다 — 다른 프로그램의 설정은 사람이 잇기를 눌렀을 때만.
        guide_skill.refresh_packs(_exported_tools())

    runtime.packs.on_change(_refresh_pack_guides)

    def _exported_tools() -> list[dict[str, Any]]:
        # 가이드 스킬에 적는 도구 = MCP 가 실제로 내보내는 도구. 기본(맡기기 전용)이면 맡기기 문과 가이드만.
        if lean_toolset():
            return [dict(tool) for tool in DELEGATION_TOOLS] + [dict(GUIDE_TOOL)]
        return [dict(tool) for tool in DELEGATION_TOOLS] + ToolFilter.from_env().apply(runtime.gateway.list_tools())

    # 업데이트로 가이드 문구가 바뀌었으면 이미 이어 둔 클로드·코덱스의 가이드도 맞춘다(guide_skill.refresh_installed).
    try:
        guide_skill.refresh_installed(_exported_tools())
    except Exception:  # noqa: BLE001 — 가이드를 못 고쳐도 앱은 뜬다(옛 문구가 남을 뿐이다)
        pass

    # ── 「문제 보내기」 (2026-09-29) — 보여 주고, 동의받고, 보여 준 그대로 보낸다(problem_report.py). ──
    from . import __version__ as _app_version
    from .context_watch import gpu_snapshot as _gpu_snapshot
    from . import msix as _msix
    from .problem_report import ProblemReporter, build_report, first_run_trace

    problem_reporter = ProblemReporter(url=runtime.config.problem_report_url)

    @app.get("/v1/report/preview", dependencies=[Depends(require_token)])
    def report_preview(job_id: str = "") -> dict[str, Any]:
        try:
            gpu = _gpu_snapshot()
        except Exception:  # noqa: BLE001 — GPU 를 못 읽어도 보고는 만든다
            gpu = {"gpus": []}
        # 첫 실행 자취 — 하나를 못 읽어도 나머지는 싣는다. 판이 없는 사람의 제보가 비어 오지 않게(2026-10-06).
        seen: dict[str, Any] = {}
        for name, read in (("setup", lambda: setup_state.read(runtime.config.data_dir)),
                           ("ollama", runtime.ollama_installer.status),
                           ("pulls", setup_service.pulls),
                           ("runners", runtime.ollama_installer._list_runners)):
            try:
                seen[name] = read()
            except Exception:  # noqa: BLE001 — 못 읽은 칸은 빈 채로 간다
                seen[name] = None
        # 판 번호는 스토어·채널에 올린 **패키지 번호**다. 파이썬 패키지 번호(0.1.0)는 어느 판인지 못 가린다.
        report = build_report(health=runtime.health(), jobs=runtime.store.list_jobs(40), gpu=gpu,
                              home=Path.home(), job_id=job_id,
                              app_version=_msix.package_version() or _app_version,
                              first_run=first_run_trace(**seen))
        return problem_reporter.preview(report)

    @app.post("/v1/report/send", dependencies=[Depends(require_token)])
    def report_send(body: dict[str, Any]) -> dict[str, Any]:
        return problem_reporter.send(str(body.get("id") or ""), consent=body.get("consent") is True,
                                     note=str(body.get("note") or ""), home=Path.home())

    @app.get("/v1/setup/guide-skill", dependencies=[Depends(require_token)])
    def setup_guide_skill_status() -> dict[str, Any]:
        return guide_skill.status()

    @app.post("/v1/setup/guide-skill", dependencies=[Depends(require_token)])
    def setup_guide_skill(body: dict[str, Any]) -> dict[str, Any]:
        action = str(body.get("action") or "")
        if action == "install_claude_code":
            return guide_skill.install_claude_code(_exported_tools())
        if action == "remove_claude_code":
            return guide_skill.remove_claude_code()
        if action == "build_zip":
            return guide_skill.build_zip(_exported_tools())
        # ★ 전역 지침 한 줄 (2026-09-16): 연결만 해 두면 안 부른다 — Codex 는 온텔릭을 0번 부르고 자기 브라우저로 했다.
        if action == "install_note":
            return guide_skill.install_note(str(body.get("client") or ""), _exported_tools())
        if action == "remove_note":
            return guide_skill.remove_note(str(body.get("client") or ""))
        if action == "manual_note":
            return {"ok": True, "text": guide_skill.manual_note()}
        raise HTTPException(status_code=400, detail="unknown_action")

    # ── 설정 화면 (W3) ──────────────────────────────────────────────────
    # 허용 목록 안의 칸만. 비밀은 이 문으로 안 받는다(`settings.SETTINGS` 에 없다).
    @app.get("/v1/settings", dependencies=[Depends(require_token)])
    def settings_view() -> dict[str, Any]:
        return runtime.settings.view()

    @app.patch("/v1/settings", dependencies=[Depends(require_token)])
    def settings_patch(body: dict[str, Any]) -> dict[str, Any]:
        result = runtime.settings.patch(body.get("values") if isinstance(body.get("values"), dict) else body)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result

    @app.post("/v1/settings/reset", dependencies=[Depends(require_token)])
    def settings_reset(body: dict[str, Any] | None = None) -> dict[str, Any]:
        keys = (body or {}).get("keys")
        return runtime.settings.reset([str(k) for k in keys] if isinstance(keys, list) else None)

    # ── 디스코드 연결 (2026-10-18) ──────────────────────────────────────
    # 명령 창 마법사(`python -m alture_jarvis.messaging setup`)의 단계를 화면이 하나씩 부른다. 봇 토큰은 이 문들로
    # **들어오지도 나가지도 않는다** — 본체가 클립보드를 직접 읽고 자격 증명 관리자에만 둔다(`messaging/service.py`).
    # 실패도 200 + {"ok": false, "error": 코드, "message": 사람 말} 로 돌려준다 — 화면이 status 모양 하나로 그린다.
    @app.get("/v1/discord/status", dependencies=[Depends(require_token)])
    def discord_status() -> dict[str, Any]:
        return runtime.discord.status()

    @app.post("/v1/discord/token/from-clipboard", dependencies=[Depends(require_token)])
    def discord_token_from_clipboard() -> dict[str, Any]:
        return runtime.discord.token_from_clipboard()

    @app.post("/v1/discord/recheck", dependencies=[Depends(require_token)])
    def discord_recheck() -> dict[str, Any]:
        return runtime.discord.recheck()

    @app.post("/v1/discord/finish", dependencies=[Depends(require_token)])
    def discord_finish() -> dict[str, Any]:
        return runtime.discord.finish()

    @app.post("/v1/discord/disconnect", dependencies=[Depends(require_token)])
    def discord_disconnect() -> dict[str, Any]:
        return runtime.discord.disconnect()

    # 허용 요청(가족 · 동료 추가 카드). 주인 말고 다른 사람이 들어오는 문은 allow 하나뿐이다.
    @app.get("/v1/discord/requests", dependencies=[Depends(require_token)])
    def discord_requests() -> dict[str, Any]:
        return runtime.discord.access_requests()

    @app.post("/v1/discord/requests", dependencies=[Depends(require_token)])
    def discord_request_record(body: dict[str, Any]) -> dict[str, Any]:
        """다리(본체 안 · 따로 띄운 것)가 부른다 — 허용 목록 밖 사람이 봇에게 말을 걸었다."""
        return runtime.discord.record_access_request(body if isinstance(body, dict) else {})

    @app.post("/v1/discord/requests/{user_id}/allow", dependencies=[Depends(require_token)])
    def discord_request_allow(user_id: str) -> dict[str, Any]:
        return runtime.discord.allow_request(user_id)

    @app.post("/v1/discord/requests/{user_id}/ignore", dependencies=[Depends(require_token)])
    def discord_request_ignore(user_id: str) -> dict[str, Any]:
        return runtime.discord.ignore_request(user_id)

    @app.put("/v1/discord/settings", dependencies=[Depends(require_token)])
    def discord_settings(body: dict[str, Any]) -> dict[str, Any]:
        """디스코드 쪽 비밀 아닌 설정 — 지금은 기본 모델 별명(`default_model_alias`, 빈 값 = PC 와 같음)만."""
        return runtime.discord.update_settings(body if isinstance(body, dict) else {})

    # ── 모델 별명 표 (2026-10-18) ───────────────────────────────────────
    # 「똑똑한」 · 「빠른」 같은 짧은 이름 → Ollama 태그. 표가 없으면 깔린 모델에서 둘쯤 채운다(읽기만 — 모델을 올리지 않는다).
    @app.get("/v1/models/aliases", dependencies=[Depends(require_token)])
    def model_aliases_view() -> dict[str, Any]:
        return runtime.model_aliases.view()

    @app.put("/v1/models/aliases", dependencies=[Depends(require_token)])
    def model_aliases_replace(body: dict[str, Any]) -> dict[str, Any]:
        from .model_aliases import clean_items

        try:
            clean_items(body.get("aliases") if isinstance(body, dict) else None)
            runtime.model_aliases.replace(body.get("aliases"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
        return {"ok": True, **runtime.model_aliases.view()}

    # ── 아껴 준 양 영수증 (2026-10-19) ─────────────────────────────────
    # 바깥 AI 가 맡긴 판에서 손자리가 대신 읽은 본문의 **하한** 토큰을 기간으로 모은다. 읽기 전용 — DB 를 `mode=ro` 로 연다.
    # 어떤 판을 세는지 · 왜 하한만 말하는지는 `savings_receipt` 머리말.
    @app.get("/v1/savings", dependencies=[Depends(require_token)])
    def savings_view(days: int = 7) -> dict[str, Any]:
        from .savings_receipt import collect

        return collect(runtime.store.path, days=days)

    @app.post("/v1/ollama/prime-front", dependencies=[Depends(require_token)])
    def ollama_prime_front() -> dict[str, Any]:
        """고정 앞부분을 지금 한 번 데운다(`ollama.prime_front`). 평소에는 한가할 때 스스로 한다 — 재 볼 때와 진단용."""
        return runtime.ollama.prime_front("asked")

    @app.get("/v1/settings/granted-paths", dependencies=[Depends(require_token)])
    def granted_paths_view() -> dict[str, list[str]]:
        return runtime.local_computer.granted_paths()

    @app.post("/v1/settings/granted-paths/revoke", dependencies=[Depends(require_token)])
    def granted_paths_revoke(body: dict[str, Any]) -> dict[str, Any]:
        path = body.get("path")
        mode = body.get("mode")
        if not isinstance(path, str) or not path.strip() or mode not in ("read", "write"):
            raise HTTPException(status_code=400, detail="path_and_mode_required")
        removed = runtime.local_computer.revoke_path_access(path, mode)
        return {"ok": removed, "granted_paths": runtime.local_computer.granted_paths()}

    # ── 스킬 온보딩 (W4) — 「주로 무엇에 쓰시나요」 ─────────────────────────
    @app.get("/v1/skills/domains", dependencies=[Depends(require_token)])
    def skills_domains() -> dict[str, Any]:
        from .skill_domains import catalog

        view = catalog(runtime.skills, tuple(runtime.config.skills_domains))
        view["route_enabled"] = bool(runtime.config.skills_route_enabled)
        return view

    @app.post("/v1/skills/domains", dependencies=[Depends(require_token)])
    def skills_domains_apply(body: dict[str, Any]) -> dict[str, Any]:
        """고른 분야를 저장하고, 비어 있지 않으면 스킬 붙이기를 켠다(분야를 골랐는데 꺼져 있으면 누른 척이다)."""
        from .skill_domains import BY_ID, catalog

        picked = [str(item) for item in (body.get("domains") or []) if str(item) in BY_ID]
        changes: dict[str, Any] = {"skills_domains": picked}
        if picked:
            changes["skills_route_enabled"] = True
        result = runtime.settings.patch(changes)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        view = catalog(runtime.skills, tuple(runtime.config.skills_domains))
        view["route_enabled"] = bool(runtime.config.skills_route_enabled)
        return {"ok": True, **view}

    @app.post("/v1/diagnostics/export", dependencies=[Depends(require_token)])
    def diagnostics_export() -> dict[str, Any]:
        from .diagnostics import export_bundle

        return export_bundle(runtime)

    # 이 프로세스가 무엇을 쥐고 있나(손잡이 · 메모리 · 살아 있는 물건의 종류별 수) — 새는 것을 안에서 센다. 읽기만 한다.
    @app.get("/v1/diagnostics/census", dependencies=[Depends(require_token)])
    def diagnostics_census(top: int = 40, who: str = "", samples: int = 3, depth: int = 6, roots: bool = False) -> dict[str, Any]:
        from .process_census import census

        out = census(top=top, who=who, samples=samples, depth=depth, roots=roots)
        if who == "stale_browser_connections":
            # 연결을 갈아 끼운 뒤 옛 연결을 브라우저 일꾼의 어느 칸이 쥐고 있나(2026-10-14 · 재연결이 메모리를 못 풀던 것).
            from .process_census import stale_holders

            worker = runtime.browser
            current = getattr(getattr(getattr(worker, "_context", None), "_impl_obj", None), "_connection", None)
            out["stale_browser_connections"] = stale_holders(worker, current)
        return out

    @app.post("/v1/desktop/open-folder", dependencies=[Depends(require_token)])
    def desktop_open_folder(body: dict[str, Any]) -> dict[str, Any]:
        """데이터·백업·진단·가이드 스킬 zip·스킬팩 폴더 **다섯 중 하나만** 연다. 경로를 받지 않는다 — 받으면 아무 폴더나 여는 문이 된다."""
        import os

        which = str(body.get("which") or "")
        folders = {
            "data": runtime.config.data_dir,
            "backup": runtime.config.memory_backup_dir,
            "diagnostics": runtime.config.output_dir / "diagnostics",
            "guide_skill": guide_skill.documents,
            # 「내 스킬팩 넣기」 — 받은 폴더를 끌어다 놓을 자리(문서 폴더 안이라 가상화 밖이다).
            "skillpacks": runtime.config.skillpacks_dir,
        }
        folder = folders.get(which)
        if folder is None:
            return {"ok": False, "error": "unknown_folder"}
        folder.mkdir(parents=True, exist_ok=True)
        # ★ 스토어판이면 우리 프로세스가 보는 AppData 경로는 가상화된 보기다. 탐색기(패키지 밖)는 그 경로에서
        #   빈 폴더를 연다 — 밖의 앱이 여는 실제 경로로 바꿔 연다(2026-09-15 PC 의존성 정리).
        from .msix import external_path

        real = external_path(folder)
        if os.name == "nt":
            os.startfile(str(real))  # noqa: S606 — 고정된 폴더만
        return {"ok": True, "path": str(real)}

    # ── 기억 복제 폴더 (W1-3) ────────────────────────────────────────────────
    # 앱을 지워도 대화·배운 사실이 남는다. 첫 실행 마법사가 세대를 보고 「이전 기억을 가져올까요?」를
    # 묻고, 설정 > 데이터가 「지금 백업」·「백업까지 지우기」를 부른다.
    @app.get("/v1/backup", dependencies=[Depends(require_token)])
    def backup_status() -> dict[str, Any]:
        return runtime.backup.status()

    @app.post("/v1/backup/now", dependencies=[Depends(require_token)])
    def backup_now() -> dict[str, Any]:
        return runtime.backup.create("manual")

    @app.post("/v1/backup/restore", dependencies=[Depends(require_token)])
    def backup_restore(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.backup.restore(str(body.get("generation") or ""))

    @app.post("/v1/backup/delete", dependencies=[Depends(require_token)])
    def backup_delete(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.backup.delete_all(str(body.get("confirmation") or ""))

    # ── 이어받기 (전략안 §44) ──────────────────────────────────────────────────
    @app.get("/v1/takeover/sessions", dependencies=[Depends(require_token)])
    def takeover_sessions(hours: float = 12.0) -> dict[str, Any]:
        return runtime.takeover.scan(hours=max(1.0, min(hours, 168.0)))

    @app.get("/v1/takeover", dependencies=[Depends(require_token)])
    def takeover_list(status: str = "") -> dict[str, Any]:
        return runtime.takeover.list(status=status)

    @app.post("/v1/takeover/pick", dependencies=[Depends(require_token)])
    def takeover_pick(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.takeover.record_card(str(body.get("session_path") or ""))

    @app.get("/v1/takeover/review-context", dependencies=[Depends(require_token)])
    def takeover_review_context(cwd: str = "") -> dict[str, Any]:
        return {"context": runtime.takeover.review_context(cwd)}

    @app.post("/v1/takeover/{takeover_id}/accept", dependencies=[Depends(require_token)])
    def takeover_accept(takeover_id: int) -> dict[str, Any]:
        return runtime.takeover.accept(takeover_id)

    @app.post("/v1/takeover/{takeover_id}/cowork", dependencies=[Depends(require_token)])
    def takeover_cowork(takeover_id: int, body: dict[str, Any]) -> dict[str, Any]:
        return runtime.takeover.prepare_cowork(
            takeover_id,
            direction=str(body.get("direction") or "continue"),
            custom=str(body.get("custom") or ""),
        )

    @app.post("/v1/takeover/{takeover_id}/dismiss", dependencies=[Depends(require_token)])
    def takeover_dismiss(takeover_id: int) -> dict[str, Any]:
        return runtime.takeover.dismiss(takeover_id)

    @app.post("/v1/takeover/{takeover_id}/discard", dependencies=[Depends(require_token)])
    def takeover_discard(takeover_id: int) -> dict[str, Any]:
        return runtime.takeover.discard(takeover_id)

    @app.get("/v1/capabilities")
    def capabilities() -> dict[str, Any]:
        tools = runtime.gateway.list_tools()
        by_risk: dict[str, int] = {}
        for tool in tools:
            level = str(tool.get("risk_level") or "L0")
            by_risk[level] = by_risk.get(level, 0) + 1
        recipes = runtime.site_recipes.list_actions() if runtime.site_recipes else {"sites": []}
        return {
            "tools": tools,
            "tool_count": len(tools),
            "by_risk": by_risk,
            # 사이트 레시피 — 사람이 한 번 뚫으면 다음부터 안 막히는, 자율이 저절로
            # 늘어나는 유일한 축이다. 그런데 지금 몇 개인지 아무 데도 안 보였다.
            "recipes": recipes.get("sites", []),
            "sites": runtime.agent.atlas.known(),
        }

    @app.post("/v1/tools/execute", dependencies=[Depends(require_token)])
    def execute_tool(request: ToolRequest) -> dict[str, Any]:
        result = runtime.gateway.execute(request.name, request.arguments)
        return result.to_dict()

    @app.get("/v1/approvals", dependencies=[Depends(require_token)])
    def approvals(limit: int = 50, status: str = "") -> list[dict[str, Any]]:
        # 저장은 인자만 한다 — 사람이 읽을 칸(실제 경로·자리)은 보여 줄 때 붙인다.
        return [runtime.gateway.describe_approval(item) for item in runtime.store.list_approvals(limit, status)]

    @app.post("/v1/approvals/{nonce}", dependencies=[Depends(require_token)])
    def decide_approval(nonce: str, request: ApprovalDecision) -> dict[str, Any]:
        decision = runtime.decide_approval(nonce, request.approve, request.answer)
        if decision is None:
            raise HTTPException(status_code=404, detail="approval_not_found")
        return decision

    @app.get("/v1/external-actions/{action_id}", dependencies=[Depends(require_token)])
    def external_action_preview(action_id: str) -> dict[str, Any]:
        preview = runtime.external_actions.public_preview(action_id)
        if preview is None:
            raise HTTPException(status_code=404, detail="external_action_not_found")
        return preview

    # ── people the camera knows ──────────────────────────────────────────────
    # These bypass the L2 approval that guards the model's equivalent tool, and
    # that is the intent: the gate exists so the model cannot write a
    # colleague's face to disk off a spoken sentence. A person pressing the
    # button in the app, holding the control token, *is* the human decision the
    # gate was asking for -- making them approve their own click twice would
    # only teach them to dismiss approval cards.
    @app.get("/v1/people", dependencies=[Depends(require_token)])
    def list_people() -> dict[str, Any]:
        if runtime.face_identity is None:
            return {"enabled": False, "registered": [], "ready": False}
        report = runtime.face_identity.available()
        return {"enabled": True, **report}

    @app.post("/v1/people/discover", dependencies=[Depends(require_token)])
    def discover_person(request: NewPersonRequest) -> dict[str, Any]:
        """Sweep the room and register whoever is not on file yet."""
        try:
            return runtime.person_tools.register_new_person({"name": request.name})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/v1/people/{name}", dependencies=[Depends(require_token)])
    def forget_person(name: str) -> dict[str, Any]:
        if runtime.face_identity is None:
            raise HTTPException(status_code=409, detail="face_recognition_disabled")
        return runtime.face_identity.forget(name)

    @app.post("/v1/agents/{job_id}/continue", dependencies=[Depends(require_token)])
    def continue_agent(job_id: str, request: ContinuationDecision) -> dict[str, Any]:
        try:
            return runtime.agent.continue_job(job_id, request.action)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.websocket("/v1/ws")
    async def websocket_events(websocket: WebSocket) -> None:
        # ★ HTTP 미들웨어는 여기 안 걸린다 (2026-08-24).
        #
        # `@app.middleware("http")` 는 이름 그대로 HTTP 만 본다. 소켓은 통째로
        # 비켜 간다 — 문지기를 달아 놓고 **정작 실시간 이벤트 통로가 열려 있는**
        # 상태가 될 뻔했다. 토큰이 막아 주긴 하지만, 여는 범위는 여기서도 같아야
        # 한다. 한 곳만 좁히면 좁힌 줄 알고 넘어가게 된다.
        client = websocket.client.host if websocket.client else ""
        if not peer_guard.is_allowed(client, extra_allowed):
            await websocket.close(code=4403)
            return
        protocols = [
            item.strip()
            for item in websocket.headers.get("sec-websocket-protocol", "").split(",")
            if item.strip()
        ]
        protocol_token = protocols[1] if len(protocols) >= 2 and protocols[0] == "jarvis" else ""
        legacy_query_token = websocket.query_params.get("token", "")
        supplied_token = protocol_token or legacy_query_token
        if supplied_token != runtime.config.control_token:
            await websocket.close(code=4401)
            return
        await websocket.accept(subprotocol="jarvis" if protocol_token else None)
        cursor = runtime.events.sequence
        await websocket.send_json({"event": "connected", "sequence": cursor})
        # HUD가 꺼진 동안 승인 요청이 생기면 이벤트는 이미 지나가 있다. 새 소켓은
        # 현재 sequence부터 듣기 때문에 그 카드를 영원히 못 받고, 백엔드만
        # waiting_approval에 남는다. 연결 직후 아직 유효한 최신 승인 하나를 해당
        # 클라이언트에만 재생한다. 이벤트 버스에 다시 publish하지 않으므로 다른
        # 화면에 중복 카드를 만들지 않는다(잡 러너가 직렬이라 live pending은 하나다).
        pending = runtime.store.list_approvals(limit=1, status="pending")
        if pending:
            await websocket.send_json(
                {
                    "event": "approval_requested",
                    "sequence": cursor,
                    "timestamp": time.time(),
                    "payload": ui_i18n.translate_payload(pending[0]),
                    "replayed": True,
                }
            )
        try:
            while True:
                records = await asyncio.to_thread(runtime.events.wait_since, cursor, 15.0)
                if not records:
                    await websocket.send_json({"event": "heartbeat", "sequence": cursor})
                    continue
                for record in records:
                    await websocket.send_json(ui_i18n.translate_payload(record.to_dict()))
                    cursor = record.seq
        except WebSocketDisconnect:
            return

    return app


def __getattr__(name: str) -> Any:
    """`alture_jarvis.api:app` 은 **쓰일 때** 만든다 (2026-10-09).

    여기에 `app = create_app()` 가 있었다. 그러면 이 모듈을 **불러오기만 해도** 기본 설정으로 런타임이 통째로 만들어지고,
    기본 뿌리(사용자의 앱 데이터 폴더)의 DB 가 열린다. `create_app` 만 가져다 쓰려는 시험 수십 개가 그 문을 지났다 —
    손자리를 깔아 둔 PC 에서 시험을 돌리면 수집 단계에서 **진짜 설치본의 DB** 를 여는 것이다. 시험 쪽에
    「임시 폴더 밖의 DB 는 거절」을 넣고서야 드러났다(그 문은 수집이 끝난 뒤에 서서, 이 불러오기는 그 전에 지나갔다).

    서버를 띄우는 쪽(`__main__` 의 `uvicorn.run("alture_jarvis.api:app")`)은 이름으로 `app` 을 찾으니 그대로 된다.
    """
    if name == "app":
        instance = create_app()
        globals()["app"] = instance
        return instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
