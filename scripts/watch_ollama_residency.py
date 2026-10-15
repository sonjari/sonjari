"""Ollama 가 무엇을 언제 올리고 내렸는지 남기는 녹음기.

## 왜 필요한가 (2026-08-31)

모델 호출이 굳는 고장을 현장에서 잡았다 — `py-spy` 가 `_receive_response_headers`
에 멈춰 있었고, 3090 은 0%, 슬롯은 idle, 모델은 상주였다. 즉 **Ollama 가 요청을
받고 생성을 시작조차 안 했다.**

그런데 **왜** 그랬는지는 되짚을 수가 없었다. Ollama 의 기본 로그는 적재·해제를
안 남긴다 — `server.log` 4.2MB 에 `level=INFO` 가 117줄뿐이고, 나머지는 전부 GIN
접속 기록이다. `starting llama server` · `offload` · `unload` 같은 줄은 0건이었다.

**사후에 알 방법이 없으면, 미리 녹음하는 수밖에 없다.**

## 무엇을 남기나

- `/api/ps` — 어느 모델이 상주하고 언제 만료되는가 (본 서버와 정찰기 둘 다)
- `llama-server.exe` PID — 러너가 태어나고 죽는 순간
- GPU 메모리·사용률 — 그 순간 카드가 일하고 있었는가

## 규율

- **변한 것만 적는다.** 5초마다 같은 줄을 쌓으면 아무도 안 읽는다.
- **살아 있다는 것도 적는다.** 조용한 것이 「아무 일 없음」인지 「녹음기가 죽음」인지
  구별이 안 되면 그 기록은 못 믿는다(빈 값 하나가 두 사실을 뜻하면 조용히 고장난다).
  그래서 `HEARTBEAT_SEC` 마다 한 줄은 반드시 남긴다.
- **아무것도 건드리지 않는다.** 읽기만 한다. 프로브를 쏘면 그 프로브가 모델을
  올려 버려서, 재는 행위가 재려는 것을 바꾼다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

#: 얼마나 자주 볼까. 굳는 사건은 분 단위라 5초면 충분히 촘촘하다.
POLL_SEC = 5.0

#: 아무 변화가 없어도 이만큼마다 한 줄은 남긴다 — 녹음기가 살아 있었다는 증거.
HEARTBEAT_SEC = 300.0

#: 본 모델과 정찰기. 둘은 **별개 Ollama 서버**다(2026-08-31 확인: :11434 pid 25172,
#: :11435 pid 22732). 그래서 한쪽 슬롯이 다른 쪽을 뺏지는 않는다 — 그래도 둘 다
#: 본다. 정찰기가 죽어 있으면 사고 번역과 정찰이 조용히 멈춘다.
ENDPOINTS = {"main": "http://127.0.0.1:11434", "scout": "http://127.0.0.1:11435"}


def _identity(rows: list[tuple[str, float, str]] | None) -> tuple[tuple[str, float], ...]:
    """무엇이 올라와 있는가. 만료 시각은 뺀다 — 쓸 때마다 갱신돼 사건이 아니다."""
    return tuple((name, size) for name, size, _ in rows or [])


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def residency() -> dict[str, list[tuple[str, float, str]]]:
    """어느 서버에 무엇이 올라와 있나. 못 물어보면 빈 목록이 아니라 표시를 남긴다."""
    out: dict[str, list[tuple[str, float, str]]] = {}
    for name, base in ENDPOINTS.items():
        try:
            with httpx.Client(timeout=3.0) as client:
                payload = client.get(f"{base}/api/ps").json()
            out[name] = sorted(
                (
                    str(m.get("name") or ""),
                    round(float(m.get("size") or 0) / 1e9, 1),
                    str(m.get("expires_at") or "")[:19],
                )
                for m in payload.get("models") or []
            )
        except Exception as exc:  # 서버가 죽은 것과 빈 것은 다른 사실이다
            out[name] = [("<unreachable>", 0.0, type(exc).__name__)]
    return out


def runners() -> dict[int, str]:
    """살아 있는 llama-server 프로세스. 러너가 새로 나면 그게 재적재다."""
    try:
        raw = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | "
                "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CreationDate.ToString('HH:mm:ss') }",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except Exception:
        return {}
    found: dict[int, str] = {}
    for line in raw.splitlines():
        if "|" in line:
            pid, _, born = line.strip().partition("|")
            if pid.strip().isdigit():
                found[int(pid)] = born.strip()
    return found


def gpus() -> list[tuple[int, int]]:
    """(사용률 %, 쓰는 메모리 MiB). 굳은 순간 카드가 놀고 있었는지가 핵심 증거다."""
    try:
        raw = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except Exception:
        return []
    rows: list[tuple[int, int]] = []
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            rows.append((int(parts[0]), int(parts[1])))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=r"C:\RoboMetaFit\logs\ollama_residency.log",
        help="append-only 기록 파일",
    )
    args = parser.parse_args()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(kind: str, text: str) -> None:
        line = f"{_now()} [{kind}] {text}\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        print(line, end="", flush=True)

    prev_res = residency()
    prev_run = runners()
    write("START", f"residency={json.dumps(prev_res, ensure_ascii=False)} runners={sorted(prev_run)}")
    last_beat = time.monotonic()

    while True:
        time.sleep(POLL_SEC)
        res, run = residency(), runners()

        for server in ENDPOINTS:
            # ★ 만료 시각만 바뀐 것은 사건이 아니다 (2026-08-31 실측).
            #
            # `keep_alive` 는 쓸 때마다 갱신되므로 `expires_at` 이 계속 움직인다.
            # 그걸 변화로 세면 몇 분마다 한 줄씩 쌓여 **진짜 적재·해제가 묻힌다.**
            # 무엇이 올라와 있는가(이름·크기)만 비교한다.
            if _identity(res.get(server)) != _identity(prev_res.get(server)):
                write(
                    "RESIDENCY",
                    f"{server}: {json.dumps(prev_res.get(server), ensure_ascii=False)}"
                    f" -> {json.dumps(res.get(server), ensure_ascii=False)}"
                    f" gpu={gpus()}",
                )

        born = sorted(set(run) - set(prev_run))
        died = sorted(set(prev_run) - set(run))
        if born or died:
            # 러너가 새로 났다 = 재적재. 이게 「내려갔다 올라왔다」의 직접 증거다.
            write("RUNNER", f"born={born} died={died} alive={sorted(run)} gpu={gpus()}")

        prev_res, prev_run = res, run
        if time.monotonic() - last_beat >= HEARTBEAT_SEC:
            # 조용한 것과 죽은 것을 구별할 수 있어야 이 기록을 믿을 수 있다.
            last_beat = time.monotonic()
            write("ALIVE", f"residency={json.dumps(res, ensure_ascii=False)} gpu={gpus()}")


if __name__ == "__main__":
    sys.exit(main())
