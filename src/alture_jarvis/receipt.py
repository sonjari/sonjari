"""영수증 — 이번 주 손자리가 대신 한 일 (2026-10-21 대표).

## 왜

간판은 「클로드 한도 덜기 + 검사」다(10-19 결론). 그런데 사용자는 손자리가 클로드 대신 얼마나 읽었는지 볼 곳이 없었다 —
판마다 `sonjari_task_status` 의 `cost` 에만 있고, 그건 클로드가 읽는 칸이다. 그래서 한 주를 모아 사람이 보는 한 장으로 만든다.

## 무엇을 세나 (전부 센 값 · 부풀리지 않는다)

- 맡긴 일: 바깥 AI(클로드 코드 · 코덱스 · 커서)가 MCP 로 맡겨 **끝난** 판 수.
- 대신 읽은 페이지: 그 판들에서 손자리가 이 PC 에서 성공한 읽기 걸음 수(`delegation.host_context_kept_out` 의 `reads`).
- 클로드에 안 실은 본문: 그 읽기의 글자 수 ÷ 4.5 의 **하한**(같은 함수). 한글은 토큰당 약 1.7자라 실제는 더 크다.
- 근거 없는 숫자 표시: 클로드에게 돌려줄 때 「도구가 준 적 없는 숫자」가 붙은 판 수(`delegation.summarize_job` — 클로드가 받은 것과 같은 셈).
- 직접 시킨 일: 사람이 손자리에게 바로 시킨 판(화면 · 음성 · 디스코드)과 거기서 읽은 페이지(클로드를 안 쓰는 사람도 볼 것이 있게).

**측정 판은 뺀다** — 요청에 `measurement` 표시가 있거나 대화방 이름이 `measure` · `bench` 로 시작하는 판. 예전 벤치 판은 표시가 없어
이 거르개로 다 빠지지 않을 수 있다(우리 PC 숫자를 밖에 낼 때는 따로 확인). 달러로 바꾸지 않는다 — 요금이 모델 · 요금제마다 달라 부풀리기 쉽다.
"""

from __future__ import annotations

import time
from typing import Any

from .delegation import host_context_kept_out, summarize_job

#: 측정 · 벤치 판의 대화방 이름 머리.
MEASURE_SESSIONS = ("measure", "bench")
#: 바깥 AI 가 맡긴 판의 origin.
DELEGATED_ORIGINS = frozenset({"mcp"})
#: 같은 MCP 입구로 들어오지만 **사람이 직접** 시킨 것 — 디스코드 다리는 폰에서 사람이 보낸 말이다(10-21 첫 셈에서 29건이 섞였다).
HUMAN_CALLERS = frozenset({"discord"})


def is_measurement(payload: dict[str, Any]) -> bool:
    if payload.get("measurement"):
        return True
    session = str(payload.get("session_id") or "").casefold()
    return session.startswith(MEASURE_SESSIONS)


def weekly(store: Any, *, days: int = 7, now: float | None = None) -> dict[str, Any]:
    """최근 `days` 일의 영수증. 화면 카드 · MCP 안내가 같이 쓴다(숫자가 갈리지 않게 한 곳)."""
    now = time.time() if now is None else float(now)
    days = max(1, min(int(days or 7), 90))
    since = now - days * 86400
    delegated = {"jobs": 0, "pages": 0, "tokens_at_least": 0, "chars": 0, "flagged_numbers_jobs": 0}
    direct = {"jobs": 0, "pages": 0}
    callers: dict[str, int] = {}
    skipped = 0
    for job in store.finished_jobs_since(since):
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        if is_measurement(payload):
            skipped += 1
            continue
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        trace = result.get("agent_trace") if isinstance(result.get("agent_trace"), dict) else {}
        steps = [step for step in trace.get("steps") or [] if isinstance(step, dict)]
        kept = host_context_kept_out(steps) if steps else None
        caller_name = str(payload.get("caller") or "").strip()
        if str(payload.get("origin") or "") in DELEGATED_ORIGINS and caller_name.casefold() not in HUMAN_CALLERS:
            delegated["jobs"] += 1
            caller = caller_name or "바깥 AI"
            callers[caller] = callers.get(caller, 0) + 1
            if kept:
                delegated["pages"] += int(kept.get("reads") or 0)
                delegated["tokens_at_least"] += int(kept.get("tokens_at_least") or 0)
                delegated["chars"] += int(kept.get("text_chars") or 0)
            try:
                if summarize_job(job).get("unsupported_numbers"):
                    delegated["flagged_numbers_jobs"] += 1
            except Exception:  # noqa: BLE001 — 한 판의 기록이 이상해도 영수증 전체를 버리지 않는다
                pass
        else:
            direct["jobs"] += 1
            if kept:
                direct["pages"] += int(kept.get("reads") or 0)
    return {
        "days": days,
        "since": since,
        "until": now,
        "delegated": delegated,
        "direct": direct,
        "callers": dict(sorted(callers.items(), key=lambda item: -item[1])),
        "measurement_jobs_skipped": skipped,
        "basis": "센 글자 수 ÷ 4.5 의 하한입니다. 한글은 토큰당 약 1.7자라 실제는 더 큽니다. 측정 판은 뺐습니다.",
    }


def one_line(receipt: dict[str, Any], lang: str = "ko") -> str:
    """클로드가 읽는 한 줄(MCP 안내 끝). 맡긴 일이 없으면 빈 글. 영어 연결이면 영어로(같은 숫자)."""
    delegated = receipt.get("delegated") or {}
    if not delegated.get("jobs"):
        return ""
    if lang == "en":
        return (f"Receipt for the last {receipt.get('days', 7)} days: {delegated['jobs']} jobs handed over · "
                f"{delegated['pages']} pages Sonjari read instead · at least {delegated['tokens_at_least']:,} tokens of page text "
                f"kept out of Claude (counted characters ÷ 4.5, a floor) · {delegated['flagged_numbers_jobs']} jobs flagged "
                "for numbers no tool gave.")
    return (f"이번 {receipt.get('days', 7)}일 영수증: 맡긴 일 {delegated['jobs']}건 · 손자리가 대신 읽은 페이지 {delegated['pages']}개 · "
            f"클로드에 안 실은 본문 최소 {delegated['tokens_at_least']:,}토큰(센 글자 ÷ 4.5 의 하한) · "
            f"근거 없는 숫자가 표시된 판 {delegated['flagged_numbers_jobs']}건.")


#: 영수증 그림이 가는 자리 — 결과물 폴더(`문서\Sonjari`) 안의 고정 칸. 경로를 받지 않는다(받으면 아무 데나 쓰는 문이 된다).
IMAGE_DIR_NAME = "receipts"
#: 1080×1080 PNG 한 장은 수백 KB 다. 이보다 크면 우리 화면이 그린 그림이 아니다.
IMAGE_MAX_BYTES = 4 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def save_image(documents_dir: Any, data: bytes, *, now: float | None = None) -> dict[str, Any]:
    """화면이 그린 공유용 영수증 PNG 를 `문서\Sonjari\receipts` 에 저장한다(2026-10-21).

    ★ 왜 백엔드가 쓰나: 데스크톱 앱(WebView2)에서 `<a download>` 는 반응이 없거나 어디로 갔는지 안 보일 수 있다
      (`open_job_output` 머리말 · 09-17). 결과물 폴더는 사람이 이미 아는 자리라 거기에 둔다.
    PNG 머리 · 크기만 보고 받는다. 파일 이름은 날짜로 우리가 정한다 — 같은 날 또 저장하면 -2, -3 을 붙인다(덮어쓰지 않는다).
    """
    from pathlib import Path

    if not isinstance(data, (bytes, bytearray)) or not data.startswith(_PNG_SIGNATURE):
        return {"ok": False, "error": "not_png"}
    if len(data) > IMAGE_MAX_BYTES:
        return {"ok": False, "error": "too_large"}
    folder = Path(documents_dir) / IMAGE_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else float(now)))
    stem = f"sonjari-receipt-{day}"
    target = folder / f"{stem}.png"
    n = 2
    while target.exists():
        target = folder / f"{stem}-{n}.png"
        n += 1
    target.write_bytes(bytes(data))
    return {
        "ok": True,
        "path": str(target),
        "name": target.name,
        # 화면에 짧게 보일 자리 — 사람 이름이 든 집 경로를 빼고 결과물 폴더부터.
        "short": "\\".join((Path(documents_dir).name, IMAGE_DIR_NAME, target.name)),
        "bytes": len(data),
    }
