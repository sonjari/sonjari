"""「문제 보내기」 — 보낼 내용을 **먼저 보여 주고, 동의를 받은 뒤, 보여 준 그대로** 보낸다 (2026-09-29, 베타 전 필수).

받는 곳은 손자리 개발팀 서버 `POST /sonjari/reports`(2026-09-29 결정). 받는 쪽은 저장만 한다(`nas_server/app/routes/sonjari_reports.py`).

무엇을 싣나
- 앱 버전·빌드 · 윈도우 판 · 모델 이름과 창 크기 · GPU(이름 없이 메모리 수치만)
- 최근 문제 작업 몇 개: 상태 · 요청 제목 · 걸음별 도구 이름과 오류 앞머리 · 멈춘 이유
- 사용자가 적은 한 줄

지키는 것
- **보여 준 것과 보내는 것이 같다.** 미리보기가 번호를 받고, 전송은 그 번호의 내용만 보낸다(그사이 새로 모으지 않는다).
- 가린다: 사용자 폴더 경로 → `~` · 메일 → `<메일>` · 전화번호 → `<전화>` · 긴 토큰류(24자 이상 영숫자) → `<숨김>`.
  완벽하지 않다 — 그래서 **보여 주고 묻는다.** 가림은 실수를 줄이는 것이지 동의를 대신하지 않는다.
- 크기: 200KB 를 넘으면 오래된 작업부터 뺀다(받는 쪽 한도 256KB).
"""

from __future__ import annotations

import json
import platform
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

MAX_BYTES = 200 * 1024
PREVIEW_TTL_SEC = 30 * 60
DEFAULT_URL = "https://api.robometafit.com/sonjari/reports"
#: 문제로 보는 작업 상태 — 끝났어도 덜 채운 판(partial)은 결과 안에서 본다.
_PROBLEM_STATUSES = {"failed", "cancelled", "waiting_continuation", "needs_review"}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
#: 국내(0 으로 시작)·국제(+82)·괄호 형식. 0/+82 로 시작하지 않는 숫자(시각·크기)는 건드리지 않는다.
_PHONE = re.compile(r"(?<![\d+])(?:\+82[- .]?\(?0?|\(?0)\d{1,2}\)?[- .]?\(?\d{3,4}\)?[- .]?\d{4}(?!\d)")
_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_\-]{24,}(?![A-Za-z0-9])")
#: 어느 사용자 폴더든 — 구분자가 섞여도(`C:/Users\name`) 이름까지 가린다.
_USER_DIR = re.compile(r"(?i)\b[a-z]:[\\/]+users[\\/]+[^\\/\s\"'<>|]+")
#: `password=…`·`아이디: …` 처럼 이름 붙은 값. 이름은 두고 값만 가린다(무엇이 있었는지는 알아야 진단한다).
_LABELED = re.compile(
    r"(?i)\b(password|passwd|pwd|pass|secret|token|api[_-]?key|user(?:name)?|login|userid|user_id)"
    r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
    r"|(비밀번호|암호|아이디)(\s*[:=]\s*)([^\s,;&]+)"
)


def _mask_labeled(match: re.Match[str]) -> str:
    if match.group(1):
        return f"{match.group(1)}{match.group(2)}<숨김>"
    return f"{match.group(4)}{match.group(5)}<숨김>"


#: 우리 코드가 적는 오류·이벤트 이름(`pull_reported_success_but_model_missing`)은 비밀이 아니다. 소문자 낱말을 밑줄로
#: 이은 긴 이름이 「토큰」으로 가려져, 정작 무슨 오류였는지가 제보에서 지워졌다. 숫자·대문자·붙임표가 하나라도
#: 끼면 예전처럼 가린다.
_OUR_CODE = re.compile(r"[a-z]+(?:_[a-z]+){2,}")


def _mask_token(match: re.Match[str]) -> str:
    text = match.group(0)
    return text if _OUR_CODE.fullmatch(text) else "<숨김>"


def scrub(text: str, home: Path | None = None) -> str:
    """보내기 전에 가린다. 순서: 경로 → 이름 붙은 값 → 메일 → 전화 → 토큰(메일 속 긴 이름이 토큰으로 먼저 먹히지 않게).

    ★ 2026-09-29 코덱스 교차 검사로 넓혔다: 구분자 섞인 경로(`C:/Users\\name`), `+82-10-…`, `010 (1234) 5678`,
      `username=… password=…`(짧은 비밀번호는 긴 토큰 규칙에 안 걸린다)가 그대로 나갔다.
    """
    out = str(text or "")
    if home is not None:
        parts = [re.escape(part) for part in re.split(r"[\\/]+", str(home)) if part]
        if parts:
            out = re.sub(r"[\\/]+".join(parts), "~", out, flags=re.IGNORECASE)
    out = _USER_DIR.sub("~", out)
    out = _LABELED.sub(_mask_labeled, out)
    out = _EMAIL.sub("<메일>", out)
    out = _PHONE.sub("<전화>", out)
    return _TOKEN.sub(_mask_token, out)


def _scrub_tree(value: Any, home: Path | None) -> Any:
    if isinstance(value, str):
        return scrub(value, home)
    if isinstance(value, dict):
        return {key: _scrub_tree(item, home) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_tree(item, home) for item in value]
    return value


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    trace = result.get("agent_trace") if isinstance(result.get("agent_trace"), dict) else {}
    steps = [step for step in trace.get("steps") or [] if isinstance(step, dict)]
    return {
        "status": str(job.get("status") or ""),
        "title": str(job.get("title") or "")[:120],
        "error": str(job.get("error") or "")[:300],
        "stop_reason": str((result.get("verification") or {}).get("stop_reason") or trace.get("stop_reason") or ""),
        "continuation": str((result.get("continuation") or {}).get("reason") or ""),
        "steps": [
            {"tool": str(step.get("tool") or ""), "ok": bool(step.get("ok")),
             **({"error": str(step.get("error") or "")[:200]} if not step.get("ok") else {})}
            for step in steps[-15:]
        ],
    }


def _is_problem(job: dict[str, Any]) -> bool:
    if str(job.get("status") or "") in _PROBLEM_STATUSES:
        return True
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    return str(result.get("status") or "") in {"partial", "needs_review"}


def first_run_trace(*, setup: Any = None, ollama: Any = None, pulls: Any = None,
                    runners: Any = None) -> dict[str, Any]:
    """첫 실행이 어디까지 갔나 — **한 일이 하나도 없는 사람**의 제보에도 실리는 칸.

    ★ 2026-10-06 스토어판 첫 제보(6GB 노트북): 마법사 마지막 단추가 안 먹어 「문제 보내기」를 눌렀는데 제보에는
      「최근 판 0개」뿐이었다. 그날 나온 세 건(Ollama 설치 실패 · 설치 중 받기 · 시작 단추)이 전부 **판을 하나도
      못 돌린 자리**였다 — 정작 필요한 순간에 빈 제보가 온다.

    싣는 것은 단계 이름·오류 글·개수뿐이다. 설정 파일·엔진 폴더·실행기의 **경로는 싣지 않는다**(사용자 이름이 든다).
    오류 글에 낀 경로는 `build_report` 의 가림이 지운다.
    """
    setup = setup if isinstance(setup, dict) else {}
    ollama = ollama if isinstance(ollama, dict) else {}
    install = ollama.get("install") if isinstance(ollama.get("install"), dict) else {}
    rows = [row for row in (pulls.values() if isinstance(pulls, dict) else pulls or []) if isinstance(row, dict)]
    trace: dict[str, Any] = {
        "setup": {"completed": bool(setup.get("completed")),
                  "steps": [str(step)[:40] for step in (setup.get("steps") or [])][:8]},
        "ollama": {"running": bool(ollama.get("running")), "version": str(ollama.get("version") or "")[:40],
                   "managed": bool(ollama.get("managed")), "runner_missing": bool(ollama.get("runner_missing")),
                   "can_install": bool(ollama.get("can_install")),
                   "install_phase": str(install.get("phase") or "")[:40],
                   "install_error": str(install.get("error") or "")[:300]},
        "pulls": [{"model": str(row.get("model_key") or "")[:80], "status": str(row.get("status") or "")[:40],
                   "phase": str(row.get("phase") or "")[:40], "reason": str(row.get("reason") or "")[:60],
                   "detail": str(row.get("detail") or "")[:200]} for row in rows[-5:]],
    }
    if runners is not None:
        live = [row for row in runners if isinstance(row, dict)]
        # 실행기가 몇 개 떠 있고, 그중 부모 Ollama 가 죽은 것이 몇인가 — 경로는 안 싣는다.
        trace["runners"] = {"count": len(live), "parent_dead": sum(1 for row in live if not row.get("parent_alive"))}
    return trace


def build_report(*, health: dict[str, Any], jobs: list[dict[str, Any]], gpu: dict[str, Any] | None,
                 home: Path | None, job_id: str = "", limit: int = 5, app_version: str = "",
                 first_run: dict[str, Any] | None = None) -> dict[str, Any]:
    """보낼 내용을 만든다(가림까지). 아직 보내지 않는다."""
    ollama = health.get("ollama") if isinstance(health.get("ollama"), dict) else {}
    picked = [job for job in jobs if job_id and str(job.get("id")) == job_id]
    picked += [job for job in jobs if _is_problem(job) and job not in picked]
    report: dict[str, Any] = {
        "schema": 1,
        "app_version": str(app_version or health.get("version") or ""),
        "build": str(health.get("build") or ""),
        "os": platform.platform(),
        "python": platform.python_version(),
        "model": {"name": str(ollama.get("model") or ""), "context": ollama.get("context_length"),
                  "resident": ollama.get("resident"), "size_vram": ollama.get("size_vram")},
        # 카드에 붙은 프로그램 이름(`apps`)은 싣지 않는다 — 사용자가 무엇을 켜 두었는지는 우리가 알 일이 아니다.
        "gpu": [{"used_gb": g.get("used_gb"), "total_gb": g.get("total_gb")}
                for g in (gpu or {}).get("gpus") or [] if isinstance(g, dict)],
        "jobs": [_job_summary(job) for job in picked[:limit]],
    }
    if first_run:
        report["first_run"] = first_run
    report = _scrub_tree(report, home)
    while len(json.dumps(report, ensure_ascii=False).encode("utf-8")) > MAX_BYTES and report["jobs"]:
        report["jobs"].pop()
    return report


class ProblemReporter:
    """미리보기를 잠깐 기억해 두고, 동의가 오면 **그 내용 그대로** 보낸다."""

    def __init__(self, *, url: str = DEFAULT_URL, post: Callable[..., Any] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.url = url or DEFAULT_URL
        self._post = post or (lambda url, payload: httpx.post(url, json=payload, timeout=20.0))
        self._clock = clock
        self._previews: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def preview(self, report: dict[str, Any]) -> dict[str, Any]:
        preview_id = secrets.token_hex(8)
        now = self._clock()
        with self._lock:
            self._previews = {k: v for k, v in self._previews.items() if now - v[0] < PREVIEW_TTL_SEC}
            self._previews[preview_id] = (now, report)
        return {"id": preview_id, "report": report, "text": json.dumps(report, ensure_ascii=False, indent=2),
                "to": self.url}

    def send(self, preview_id: str, *, consent: bool, note: str = "", home: Path | None = None) -> dict[str, Any]:
        if consent is not True:
            return {"ok": False, "error": "consent_required"}
        with self._lock:
            held = self._previews.pop(str(preview_id), None)
        if held is None or self._clock() - held[0] >= PREVIEW_TTL_SEC:
            return {"ok": False, "error": "preview_expired"}
        payload = {**held[1], "consent": True, "note": scrub(str(note or "")[:2000], home)}
        try:
            response = self._post(self.url, payload)
        except httpx.HTTPError as exc:
            with self._lock:  # 못 보냈으면 다시 누를 수 있게 돌려놓는다
                self._previews[str(preview_id)] = held
            return {"ok": False, "error": f"network: {type(exc).__name__}"}
        status = int(getattr(response, "status_code", 0) or 0)
        if status != 200:
            with self._lock:
                self._previews[str(preview_id)] = held
            return {"ok": False, "error": f"http_{status}"}
        try:
            report_id = str(response.json().get("id") or "")
        except Exception:  # noqa: BLE001 — 받았는데 번호를 못 읽은 것은 실패가 아니다
            report_id = ""
        return {"ok": True, "id": report_id}


__all__ = ["DEFAULT_URL", "ProblemReporter", "build_report", "scrub"]
