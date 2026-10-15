"""산출물 요청이 **말이 아니라 파일**로 끝나는지 사다리로 잰다.

    요청만 -> 걸음 있음 -> 만들었다고 말함 -> 파일 실재 -> 열어서 내용 일치 -> 되돌릴 수 있음

분모는 실행 전에 먼저 정한다. 과제가 요구하는 도구가 현재 `/v1/tools` 에 없거나
꺼져 있으면 그 판은 0점이 아니라 ``not_possible`` 이다. 없는 손으로 하라고 해 놓고
실패율에 넣으면 제품이 아니라 눈금을 재게 된다.

파일은 답변에 적힌 경로를 믿지 않는다. 작업별 산출물 장부, 원 관찰, 그리고 그 작업이
돈 동안 실제로 새로 생긴 파일을 차례로 대조한다. 현재 sandbox 산출물은 작업별 장부에
아직 안 들어가므로 마지막 대조가 베이스라인에 필요하다.

사용:
    python scripts/bench_artifact_tasks.py --dry-run
    python scripts/bench_artifact_tasks.py --json docs/benchmarks/artifact_baseline.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8091"
RUNTIME_ROOT = Path(r"C:\RoboMetaFit\tools\alture-jarvis")
TOKEN_PATH = RUNTIME_ROOT / "data" / "control.token"
OUTPUT_ROOTS = (RUNTIME_ROOT / "outputs" / "sandbox", RUNTIME_ROOT / "outputs" / "workspace")
TERMINAL = {"completed", "failed", "cancelled"}
_CREATION_CLAIM = re.compile(r"(만들었|생성했|저장했|작성했|완료되었|완료했|파일\s*[:：])")


@dataclass(frozen=True)
class ArtifactTask:
    key: str
    prompt: str
    suffixes: tuple[str, ...]
    required_any: tuple[str, ...]
    possible_reason: str
    verify: Callable[[Path], tuple[bool, str]]


_STUDENTS = {"나래": 92, "가람": 88, "지훈": 75, "서연": 95, "민수": 61}
_RANKS = {"서연": 1, "나래": 2, "가람": 3, "지훈": 4, "민수": 5}


def _number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _verify_score_rows(rows: list[list[Any]], *, require_rank: bool) -> tuple[bool, str]:
    normalized = [[str(cell).strip() if cell is not None else "" for cell in row] for row in rows]
    missing: list[str] = []
    for name, score in _STUDENTS.items():
        matched = False
        for raw, text in zip(rows, normalized):
            if name not in text:
                continue
            numbers = [_number(value) for value in raw]
            has_score = any(value is not None and abs(value - score) < 0.001 for value in numbers)
            has_rank = any(value is not None and abs(value - _RANKS[name]) < 0.001 for value in numbers)
            if has_score and (has_rank or not require_rank):
                matched = True
                break
        if not matched:
            missing.append(name)
    flat_numbers = [_number(value) for row in rows for value in row]
    has_average = any(value is not None and abs(value - 82.2) < 0.001 for value in flat_numbers)
    ok = not missing and (has_average or not require_rank)
    details = []
    if missing:
        details.append("행 불일치=" + ",".join(missing))
    if require_rank and not has_average:
        details.append("평균 82.2 없음")
    return ok, "; ".join(details) or "학생·점수·등수·평균 일치"


def verify_xlsx(path: Path) -> tuple[bool, str]:
    try:
        # 벤치는 제품의 선택 의존성 상태와 무관하게 돌아야 한다. 편집용 E: venv에
        # openpyxl이 빠져 있던 날 눈금부터 죽었다. xlsx는 ZIP+XML 표준이므로 원시
        # 셀을 직접 읽으면 설치 상태를 분모와 섞지 않을 수 있다.
        with zipfile.ZipFile(path) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = ["".join(node.itertext()) for node in root]
            rows: list[list[Any]] = []
            for name in sorted(item for item in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", item)):
                root = ElementTree.fromstring(archive.read(name))
                for row_node in root.findall(".//{*}row"):
                    row: list[Any] = []
                    for cell in row_node.findall("{*}c"):
                        value = cell.find("{*}v")
                        inline = cell.find("{*}is")
                        raw = "" if value is None else (value.text or "")
                        if cell.get("t") == "s" and raw.isdigit() and int(raw) < len(shared):
                            row.append(shared[int(raw)])
                        elif inline is not None:
                            row.append("".join(inline.itertext()))
                        else:
                            row.append(raw)
                    rows.append(row)
        return _verify_score_rows(rows, require_rank=True)
    except Exception as exc:
        return False, f"xlsx를 열지 못함: {type(exc).__name__}: {exc}"


def verify_csv(path: Path) -> tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
        rows = [list(row) for row in csv.reader(text.splitlines())]
        return _verify_score_rows(rows, require_rank=False)
    except Exception as exc:
        return False, f"csv를 열지 못함: {type(exc).__name__}: {exc}"


def verify_docx(path: Path) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
            text = "\n".join(node.text or "" for node in root.findall(".//{*}t"))
    except Exception as exc:
        return False, f"docx를 열지 못함: {type(exc).__name__}: {exc}"
    wanted = ("자비스 산출물 점검", "파일은 말이 아니라 실재해야 한다", "2026-08-25")
    missing = [part for part in wanted if part not in text]
    return not missing, "문구 일치" if not missing else "문구 없음=" + ", ".join(missing)


def verify_workspace_text(path: Path) -> tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except Exception as exc:
        return False, f"텍스트를 열지 못함: {type(exc).__name__}: {exc}"
    wanted = ("workspace closed loop", "created by jarvis")
    missing = [part for part in wanted if part not in text]
    return not missing, "문구 일치" if not missing else "문구 없음=" + ", ".join(missing)


TASKS = (
    ArtifactTask(
        "xlsx",
        "학생 5명 점수로 엑셀 성적표 파일을 만들어줘. 나래 92, 가람 88, 지훈 75, "
        "서연 95, 민수 61. 이름·점수·등수와 전체 평균 82.2를 넣고 xlsx로 저장해줘.",
        (".xlsx",),
        ("sandbox_run",),
        "격리 상자가 openpyxl로 만들고 호스트 outputs로 자동 반출할 수 있다.",
        verify_xlsx,
    ),
    ArtifactTask(
        "csv",
        "나래 92, 가람 88, 지훈 75, 서연 95, 민수 61을 이름·점수 두 열의 UTF-8 CSV "
        "파일로 만들어 저장해줘.",
        (".csv",),
        ("sandbox_run",),
        "격리 상자가 표준 csv 모듈로 만들고 호스트 outputs로 자동 반출할 수 있다.",
        verify_csv,
    ),
    ArtifactTask(
        "docx",
        "제목은 '자비스 산출물 점검', 본문은 '파일은 말이 아니라 실재해야 한다', "
        "날짜는 '2026-08-25'인 워드 문서 파일을 docx로 만들어 저장해줘.",
        (".docx",),
        ("sandbox_run",),
        "격리 상자에 python-docx가 있어 문서를 만들고 호스트 outputs로 반출할 수 있다.",
        verify_docx,
    ),
    ArtifactTask(
        "workspace_text",
        "이번 작업 폴더에 loop.txt 파일을 만들고 첫 줄에 'workspace closed loop', "
        "둘째 줄에 'created by jarvis'를 저장해줘.",
        (".txt",),
        ("local_write_file",),
        "작업별 workspace에 직접 쓰는 도구가 있어야 한다.",
        verify_workspace_text,
    ),
)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8-sig").strip()


#: 자비스가 재기동하는 동안 기다릴 시간. 실측(2026-08-28) 재기동은 20~40초다.
CALL_RETRIES = 12
CALL_RETRY_SLEEP = 5.0


def _never_delivered(error: Exception) -> bool:
    """요청이 **서버에 닿지도 못했나.**

    TCP 연결 자체가 거부/끊김이면 서버는 그 요청을 본 적이 없다. 그때만
    POST 를 다시 보내도 안전하다. 보낸 뒤의 읽기 타임아웃은 서버가 이미
    받았을 수 있으므로 **재시도하면 잡이 두 개 생긴다.**
    """
    reason = getattr(error, "reason", error)
    return isinstance(
        reason, (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError)
    )


def call(
    path: str,
    method: str = "GET",
    body: dict | None = None,
    tok: str = "",
    *,
    retries: int = CALL_RETRIES,
) -> Any:
    """자비스 API 한 번. 서버가 잠깐 없어져도 기다렸다가 이어 간다.

    ## 왜 필요했나 (2026-08-28)

    13:37 에 GPU 드라이버가 뻗어(LiveKernelEvent 193) 자비스가 죽었다.
    자비스는 재기동 후 잡을 스스로 복구했는데(`recovered_after_restart`),
    **벤치는 ConnectionRefusedError 로 통째로 죽었다.** 한 판이 아니라
    실행 전체가 날아갔다 — 재는 쪽이 재어지는 쪽보다 약했다.

    ## 재시도해도 되는 것만 재시도한다

    GET 은 몇 번을 불러도 같다. POST 는 **연결이 거부돼 서버에 닿지도 못한
    경우에만** 다시 보낸다. 그 구분을 안 하면 잡이 두 개 생긴다.
    """
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    idempotent = method.upper() in {"GET", "HEAD"}
    last: Exception | None = None
    for attempt in range(max(1, retries)):
        request = urllib.request.Request(BASE + path, data=data, method=method)
        request.add_header("Content-Type", "application/json; charset=utf-8")
        if tok:
            request.add_header("X-JARVIS-TOKEN", tok)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError:
            # 서버가 답한 것이다 — 재시도가 아니라 호출부가 볼 일이다.
            raise
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if not (idempotent or _never_delivered(exc)):
                raise
            if attempt + 1 >= max(1, retries):
                break
            # 조용히 기다리지 않는다. 몇 초를 어디서 기다렸는지 남긴다.
            print(
                f"  [call] {method} {path} 실패 ({type(exc).__name__}) — "
                f"{CALL_RETRY_SLEEP:.0f}초 뒤 재시도 {attempt + 1}/{retries}",
                flush=True,
            )
            time.sleep(CALL_RETRY_SLEEP)
    raise last if last else RuntimeError("call_failed")


def enabled_tools(tok: str) -> set[str]:
    rows = call("/v1/tools", tok=tok)
    return {str(row.get("name")) for row in rows if row.get("enabled") is not False}


def snapshot_outputs() -> dict[str, int]:
    found: dict[str, int] = {}
    for root in OUTPUT_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    found[str(path.resolve())] = path.stat().st_mtime_ns
                except OSError:
                    pass
    return found


def _path_strings(value: Any, *, key: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            found.extend(_path_strings(child, key=str(child_key)))
    elif isinstance(value, list):
        for child in value:
            found.extend(_path_strings(child, key=key))
    elif isinstance(value, str) and key in {"path", "saved_to", "output_path"}:
        found.append(value)
    return found


def output_candidates(job_id: str, tok: str, before: dict[str, int], suffixes: tuple[str, ...]) -> list[dict]:
    candidates: dict[str, str] = {}
    try:
        ledger = call(f"/v1/outputs?job_id={job_id}", tok=tok)
        for item in ledger.get("items") or []:
            raw = str(item.get("path") or "")
            if raw:
                candidates[raw] = "job_ledger"
    except Exception:
        pass
    try:
        observations = call(f"/v1/jobs/{job_id}/steps", tok=tok)
        for raw in _path_strings(observations):
            candidates.setdefault(raw, "observation")
    except Exception:
        pass

    after = snapshot_outputs()
    for raw, stamp in after.items():
        if raw not in before or before[raw] != stamp:
            candidates.setdefault(raw, "filesystem_delta")

    rows = []
    wanted = {suffix.lower() for suffix in suffixes}
    for raw, source in candidates.items():
        path = Path(raw)
        if path.suffix.lower() not in wanted:
            continue
        exists = path.is_file()
        rows.append({
            "path": str(path), "source": source, "exists": exists,
            "bytes": path.stat().st_size if exists else 0,
        })
    return sorted(rows, key=lambda row: (not row["exists"], row["path"]))


def run_one(task: ArtifactTask, tok: str, *, budget_sec: int) -> dict:
    before = snapshot_outputs()
    posted = time.time()
    job = call(
        "/v1/chat", "POST",
        {"prompt": task.prompt, "session_id": f"artifact-bench-{task.key}-{int(posted * 1000)}", "open_results": False},
        tok,
    )
    job_id = str(job.get("id") or "")
    detail: dict[str, Any] = {}
    continued = 0
    while True:
        time.sleep(3)
        detail = call(f"/v1/jobs/{job_id}", tok=tok)
        status = str(detail.get("status") or "")
        started_at = float(detail.get("started_at") or 0)
        working = time.time() - started_at if started_at else 0
        if status == "waiting_continuation":
            call(f"/v1/agents/{job_id}/continue", "POST", {"action": "continue_task"}, tok)
            continued += 1
            continue
        if status in TERMINAL or status == "waiting_approval":
            break
        if started_at and working > budget_sec:
            detail["timed_out"] = True
            break
        if not started_at and time.time() - posted > budget_sec * 3:
            detail["never_started"] = True
            break

    detail = call(f"/v1/jobs/{job_id}", tok=tok)
    result = detail.get("result") or {}
    trace = result.get("agent_trace") or {}
    steps = trace.get("steps") or []
    answer = str(result.get("answer") or "")
    files = output_candidates(job_id, tok, before, task.suffixes)
    verified_path = ""
    verify_detail = "대상 파일 없음"
    content_ok = False
    for item in files:
        if not item["exists"]:
            continue
        content_ok, verify_detail = task.verify(Path(item["path"]))
        if content_ok:
            verified_path = item["path"]
            break
    try:
        undoable = any(str(row.get("job_id") or "") == job_id for row in (call("/v1/undo", tok=tok).get("items") or []))
    except Exception:
        undoable = False
    started_at = float(detail.get("started_at") or posted)
    finished_at = float(detail.get("finished_at") or time.time())
    return {
        "key": task.key,
        "prompt": task.prompt,
        "possible": True,
        "possible_reason": task.possible_reason,
        "job_id": job_id,
        "status": detail.get("status"),
        "requested": True,
        "stepped": bool(steps),
        "claimed_created": bool(_CREATION_CLAIM.search(answer)),
        "file_exists": any(item["exists"] and item["bytes"] > 0 for item in files),
        "content_ok": content_ok,
        "undoable": undoable,
        "steps": len(steps),
        "tools": [str(step.get("tool") or "") for step in steps],
        "files": files,
        "verified_path": verified_path,
        "verify_detail": verify_detail,
        "queued_sec": round(max(0.0, started_at - posted), 1),
        "working_sec": round(max(0.0, finished_at - started_at), 1),
        "continued": continued,
        "answer_head": answer[:300],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="과제 키(xlsx/csv/docx/workspace_text)")
    parser.add_argument("--budget-sec", type=int, default=420)
    parser.add_argument("--json", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tok = token()
    tools = enabled_tools(tok)
    tasks = [task for task in TASKS if not args.only or task.key == args.only]
    rows: list[dict] = []
    print("분모 — 지금 코드로 가능한가")
    for task in tasks:
        possible = any(name in tools for name in task.required_any)
        names = "/".join(task.required_any)
        print(f"  [{task.key}] {'가능' if possible else '불가능'} · {names} · {task.possible_reason}")
        if not possible:
            rows.append({
                "key": task.key, "prompt": task.prompt, "possible": False,
                "possible_reason": task.possible_reason, "required_any": list(task.required_any),
                "reached": "분모 밖",
            })
    if args.dry_run:
        return 0

    for index, task in enumerate(tasks, 1):
        if not any(name in tools for name in task.required_any):
            continue
        print(f"[{index}/{len(tasks)}] ({task.key}) {task.prompt[:58]}", flush=True)
        row = run_one(task, tok, budget_sec=args.budget_sec)
        rows.append(row)
        ladder = [row[name] for name in ("requested", "stepped", "claimed_created", "file_exists", "content_ok", "undoable")]
        reached = sum(1 for value in ladder if value)
        print(f"    사다리 {reached}/6 · 파일 {row['file_exists']} · 내용 {row['content_ok']} · "
              f"일한 {row['working_sec']}초 (큐 {row['queued_sec']}초)", flush=True)

    judged = [row for row in rows if row.get("possible")]
    print("\n" + "─" * 68)
    print(f"  가능한 분모          {len(judged)}/{len(rows)}")
    labels = (
        ("stepped", "걸음 있음"), ("claimed_created", "생성 주장"),
        ("file_exists", "★ 파일 실재"), ("content_ok", "열어서 내용 일치"),
        ("undoable", "되돌릴 길"),
    )
    for key, label in labels:
        print(f"  {label:<18} {sum(1 for row in judged if row.get(key))}/{len(judged)}")
    if len(judged) < 10:
        print("  ⚠ 표본이 적다 — 비율 말고 개수로 본다")
    print("─" * 68)

    payload = {
        "measured_at": time.time(),
        "tool_count": len(tools),
        "possible_denominator": len(judged),
        "total_tasks": len(rows),
        "rows": rows,
    }
    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  기록: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
